"""A stand-in for vLLM's OpenAI-compatible server, for CPU-only clusters.

It answers the endpoints the platform depends on, not the ones a client uses to
get text: this exists so Deployment, Service, probes and autoscaling can be
debugged where no GPU is rented. It serves no model and computes nothing.

What it does model is the one thing autoscaling reads: a bounded set of
`max_num_seqs` seats, and a queue in front of it. Requests over the ceiling wait
— they are not rejected — because in vLLM back-pressure is latency, not a 429.

Env:
  MODEL_NAME     the id reported by /v1/models and carried as a metric label
  MAX_NUM_SEQS   seats in the running batch (vLLM's default is 256)
  SIM_DECODE_MS  fake milliseconds per generated token; occupies a seat
  PORT           listen port (8000, as vLLM's default)
"""

import collections
import json
import os
import signal
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen3-8B")
MAX_NUM_SEQS = int(os.environ.get("MAX_NUM_SEQS", "256"))
SIM_DECODE_MS = float(os.environ.get("SIM_DECODE_MS", "20"))
# On SIGTERM: keep accepting for this long while /health already fails, so the
# endpoint is withdrawn before the socket closes. 15 s is the readiness probe's
# own arithmetic — failureThreshold 3 x periodSeconds 5 in the base Deployment.
DRAIN_DELAY_S = float(os.environ.get("DRAIN_DELAY_S", "15"))
# Then wait this long for seats to empty. Below terminationGracePeriodSeconds,
# or the kernel resolves the drain with SIGKILL instead.
DRAIN_TIMEOUT_S = float(os.environ.get("DRAIN_TIMEOUT_S", "90"))
PORT = int(os.environ.get("PORT", "8000"))


class Seats:
    """The scheduler's two queues, and nothing else about the scheduler.

    `running` is clipped at capacity by construction; `waiting` is unbounded.
    That asymmetry is the whole reason autoscaling reads waiting: a gauge
    sitting at its ceiling cannot tell "exactly full" from "ten times over".
    """

    def __init__(self, capacity):
        self.capacity = capacity
        # One lock guards both counters and doubles as the wait/notify channel.
        self._cv = threading.Condition()
        self._running = 0
        # A deque, not a counter: vLLM's waiting queue is FIFO, and a queue that
        # serves in arbitrary order has a different tail latency at the same
        # depth. Its length is the waiting gauge.
        self._queue = collections.deque()

    @contextmanager
    def occupy(self):
        ticket = object()
        with self._cv:
            # Enqueued before the ceiling is tested, so a request is never
            # invisible: in vLLM too, admission takes at least one scheduler
            # step even when a seat is free.
            self._queue.append(ticket)
            while self._running >= self.capacity or self._queue[0] is not ticket:
                self._cv.wait()
            self._queue.popleft()
            self._running += 1
        try:
            yield
        finally:
            with self._cv:
                self._running -= 1
                # notify_all, not notify: the predicate now depends on *which*
                # thread is asking, so waking one arbitrary waiter can wake a
                # thread that is not at the head, which sleeps again while the
                # head is never woken at all.
                self._cv.notify_all()

    def read(self):
        # Both counters under one lock: a scrape must not see a request that
        # has left waiting but not yet entered running.
        with self._cv:
            return self._running, len(self._queue)


SEATS = Seats(MAX_NUM_SEQS)
DRAINING = threading.Event()

# Name and label set are copied from a real capture of the pinned engine —
# docs/benchmarks/raw/l40s-2026-08-18/concurrency/c32.txt — not from memory. The
# `engine="0"` label is part of it, and a scaler's query selects on these labels,
# so a version that renames one silently breaks autoscaling rather than the
# dashboard. (vLLM main has since added a `reason` label to waiting; v0.27.1,
# the tag base/ pins, has not.)
LABELS = f'{{engine="0",model_name="{MODEL_NAME}"}}'

# Two gauges, and the omissions are deliberate: gpu_cache_usage_perc,
# preemptions and the latency histograms describe an engine that is executing a
# model. The stub is not, and a zero there would be a fabricated measurement,
# where an absent series is merely an absent series.
METRICS = (
    ("vllm:num_requests_running", "Number of requests in model execution batches."),
    ("vllm:num_requests_waiting", "Number of requests waiting to be processed."),
)


def render_metrics():
    values = dict(zip((m[0] for m in METRICS), SEATS.read()))
    out = []
    for name, help_text in METRICS:
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} gauge")
        out.append(f"{name}{LABELS} {float(values[name])}")
    return ("\n".join(out) + "\n").encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, payload=b"", content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _chunk(self, payload):
        """One chunk of a chunked body. False means the client is gone.

        A streamed response learns about a departed client at its next write.
        The buffered path cannot: it writes once, at the end, so it holds a seat
        through a generation whose reader left — measured through the edge as
        10 s of a 70 s completion produced for nobody.
        """
        try:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return False

    def _stream(self, max_tokens):
        """Server-sent events, the shape vLLM streams in.

        This is the only shape in which TTFT is observable: a non-streaming
        completion has exactly one arrival, at the end, so a client measuring it
        reads TTFT and total latency as the same number. The platform contract
        the stub exists to reproduce therefore includes SSE, or the first metric
        in docs/SLO.md cannot be observed on this cluster at any hop.

        Chunked encoding is written out by hand: the length is unknown in
        advance and `protocol_version` is HTTP/1.1, where a body with neither a
        Content-Length nor `chunked` has no declared end.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        with SEATS.occupy():
            for i in range(max_tokens):
                time.sleep(SIM_DECODE_MS / 1000.0)
                # `text` stays empty, as on the non-streaming path: the stub
                # computes nothing and inventing tokens would be a fabricated
                # measurement. The observable here is the arrival time of each
                # event, not its content.
                event = {
                    "object": "text_completion",
                    "model": MODEL_NAME,
                    "choices": [{
                        "index": 0,
                        "text": "",
                        "finish_reason": "length" if i == max_tokens - 1 else None,
                    }],
                }
                if not self._chunk(f"data: {json.dumps(event)}\n\n".encode()):
                    return
        self._chunk(b"data: [DONE]\n\n")
        self._chunk(b"")

    def _read_json(self):
        # No Content-Length means no body worth parsing; the stub does not
        # implement chunked uploads.
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        if self.path == "/health":
            if DRAINING.is_set():
                # Shutdown is readiness-first: fail the probe while still
                # serving, so the Service withdraws this pod before the socket
                # goes away. Closing the port first is the ordinary way a
                # rollout drops requests that were already routed here.
                self._send(503, b'{"error":"draining"}')
            else:
                # vLLM answers 200 with an empty body; the readiness probe reads
                # only the status code.
                self._send(200)
        elif self.path == "/metrics":
            # The exposition format is text, and Prometheus reads the version
            # off the Content-Type; JSON here scrapes as zero series.
            self._send(200, render_metrics(),
                       "text/plain; version=0.0.4; charset=utf-8")
        elif self.path == "/v1/models":
            body = {
                "object": "list",
                "data": [{
                    "id": MODEL_NAME,
                    "object": "model",
                    "owned_by": "vllm",
                    "root": MODEL_NAME,
                }],
            }
            self._send(200, json.dumps(body).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path != "/v1/completions":
            self._send(404, b'{"error":"not found"}')
            return

        if DRAINING.is_set():
            # Stop admitting, finish what is running — the same order vLLM
            # drains in, and the reason terminationGracePeriodSeconds is 120.
            self._send(503, b'{"error":"draining"}')
            return

        body = self._read_json()
        max_tokens = int(body.get("max_tokens") or 16)

        if body.get("stream"):
            self._stream(max_tokens)
            return

        with SEATS.occupy():
            # The seat is held for the length of the generation, which is what
            # makes the queue behind it fill. The sleep is fake time and is
            # never a latency measurement — see deploy/manifests/README.md.
            time.sleep(max_tokens * SIM_DECODE_MS / 1000.0)

        payload = {
            "object": "text_completion",
            "model": MODEL_NAME,
            "choices": [{"index": 0, "text": "", "finish_reason": "length"}],
            "usage": {"completion_tokens": max_tokens},
        }
        self._send(200, json.dumps(payload).encode())

    def log_message(self, fmt, *args):
        # One line per request on stdout, so kubectl logs shows probe traffic.
        print(f"{self.address_string()} {fmt % args}", flush=True)


def on_sigterm(signum, frame):
    """Without this the process ignores SIGTERM outright.

    A container's entrypoint is PID 1, and the kernel does not apply default
    signal dispositions to PID 1: a signal with no installed handler is
    discarded. So an unhandled SIGTERM means every rollout waits out
    terminationGracePeriodSeconds in full and ends in SIGKILL — 120 s of
    downtime per deploy, and in-flight requests killed rather than drained.
    """
    if DRAINING.is_set():
        return
    DRAINING.set()
    print("SIGTERM: readiness now fails, still accepting", flush=True)
    threading.Thread(target=stop_accepting, daemon=True).start()


def stop_accepting():
    time.sleep(DRAIN_DELAY_S)
    print("closing the listener, draining in-flight", flush=True)
    HTTPD.shutdown()      # returns once serve_forever has left its loop


if __name__ == "__main__":
    print(
        f"stub serving {MODEL_NAME} on :{PORT} "
        f"({MAX_NUM_SEQS} seats, {SIM_DECODE_MS:g} ms/token simulated)",
        flush=True,
    )
    HTTPD = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    signal.signal(signal.SIGTERM, on_sigterm)
    HTTPD.serve_forever()

    deadline = time.monotonic() + DRAIN_TIMEOUT_S
    while SEATS.read()[0] and time.monotonic() < deadline:
        time.sleep(0.2)
    left = SEATS.read()[0]
    print(f"exit with {left} request(s) still in flight", flush=True)
    HTTPD.server_close()
