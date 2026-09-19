"""Load generation against an OpenAI-compatible server: arrivals, SSE, timings.

The I/O half of the load harness. It
knows how to put requests on a socket and how to timestamp what comes back; it
knows nothing about what the numbers mean. Aggregation is bench/stats.py, the
engine's own counters are bench/vllm_metrics.py, and what to run is
bench/scenarios/. Four files because they change for four different reasons --
the same split roofline.py and predictions.py already use.

Three decisions worth stating, because each one is a trade this module made and
a later reader would otherwise have to re-derive.

**Standard library only.** No aiohttp, no httpx, no numpy: the harness has to run
inside the vllm/vllm-openai image on a rented pod, where adding a dependency
costs GPU-minutes and can pull a different version of something the server
depends on. The cost is the ~60 lines of HTTP/1.1 and chunked-transfer parsing
below, which is a fair price for "it runs wherever python does".

**Prompts are sent as token IDs, not text.** /v1/completions accepts a list of
ints for `prompt`, and that removes the tokenizer from the measurement entirely:
prompt length is exact rather than approximate, and a shared prefix is shared
*by construction* rather than by hoping two strings tokenise the same way. Since
the whole point of run 3 is a controlled prefix cache hit rate, an approximate
prefix would be an approximate independent variable.

**No retries.** A load generator that retries measures its own retry policy. A
failed request is recorded as a failure and counted; it never becomes a second
arrival, because that would deform the arrival process the run is built on.

    python3 bench/loadgen.py --help   # a smoke test against a live server
"""

import asyncio
import json
import random
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Endpoint:
    """Where the server is, and how patient the client is with it.

    timeout is per request and deliberately large: a request that is queued
    behind 40 others is *late*, which is a measurement, not an error. Cutting it
    off early would turn the tail this run exists to see into a missing value.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/v1/completions"
    model: str = "Qwen/Qwen3-8B"
    api_key: str | None = None
    timeout: float = 600.0


@dataclass(frozen=True)
class Request:
    """One prompt, already tokenised, with the shape that produced it.

    prefix_tokens is carried alongside the ids because the harness has to be able
    to state the *nominal* hit rate without re-inspecting the prompt: it is the
    number the measured h from the engine's counters is scored against.
    """

    index: int
    prompt_ids: tuple[int, ...]
    max_tokens: int
    prefix_tokens: int

    @property
    def prompt_tokens(self) -> int:
        return len(self.prompt_ids)


@dataclass
class Record:
    """One request's timings, as the client saw them.

    Times are seconds from a monotonic clock (time.perf_counter), converted for
    display only -- this repository keeps SI base units, and that applies to a
    measurement as much as to a derivation.

    `sent` is the instant the bytes reached the socket, and every latency below
    is measured from it. The connection is opened *before* that instant on
    purpose: TCP setup against a pod on the same host is under a millisecond, but
    it is not the service's latency, and TTFT here has to stay comparable to
    what `vllm bench serve` reports.

    `scheduled - sent` is the harness's own lateness. It is recorded rather than
    asserted away: an open-loop generator that cannot keep up with its own
    arrival process silently becomes a closed loop, which is precisely the defect
    docs/GLOSSARY.md warns about, and the only way to notice is to measure it.
    """

    index: int
    prompt_tokens: int
    scheduled: float
    sent: float = 0.0
    ttft: float | None = None
    itls: list[float] = field(default_factory=list)
    latency: float | None = None
    output_tokens: int = 0
    usage_output_tokens: int | None = None
    error: str | None = None
    # X-Router-Policy, when something in front of the engine set it. None means
    # nothing did, which is the ordinary case of loading an engine directly --
    # not a failed read. What it is for: a request routed by prefix and a
    # request that fell back look identical in every other field here.
    policy: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.ttft is not None

    @property
    def lateness(self) -> float:
        return self.sent - self.scheduled

    @property
    def tpot(self) -> float | None:
        """Mean ITL of this request -- the SLO quantity (docs/GLOSSARY.md).

        Undefined for a single-token response: with one token there is no gap to
        average, and returning 0 or the TTFT would both be a lie that percentiles
        would then smooth into plausibility.
        """
        if not self.ok or self.latency is None or self.output_tokens < 2:
            return None
        return (self.latency - self.ttft) / (self.output_tokens - 1)


class _ProtocolError(Exception):
    """The server said something that is not HTTP/1.1 + SSE as expected."""


async def _read_headers(reader: asyncio.StreamReader) -> tuple[int, dict[str, str]]:
    status_line = await reader.readline()
    if not status_line:
        raise _ProtocolError("connection closed before a status line")
    parts = status_line.decode("latin-1").split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise _ProtocolError(f"bad status line: {status_line!r}")
    status = int(parts[1])

    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        name, _, value = line.decode("latin-1").partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers


async def _iter_body(reader: asyncio.StreamReader, headers: dict[str, str]):
    """Yield raw body bytes as they arrive, unwrapping chunked framing.

    vLLM streams SSE with Transfer-Encoding: chunked, so the chunk sizes have to
    be consumed or every event arrives with a hex length glued to its front. The
    non-chunked branch exists for the test server and for error responses, which
    come back with a Content-Length and no stream at all.
    """
    if headers.get("transfer-encoding", "").lower() == "chunked":
        while True:
            size_line = await reader.readline()
            if not size_line:
                raise _ProtocolError("connection closed mid-chunk")
            size = int(size_line.strip().split(b";")[0] or b"0", 16)
            if size == 0:
                await reader.readline()          # the trailing CRLF
                return
            yield await reader.readexactly(size)
            await reader.readexactly(2)          # the CRLF after the chunk
    elif "content-length" in headers:
        remaining = int(headers["content-length"])
        while remaining > 0:
            data = await reader.read(min(65536, remaining))
            if not data:
                return
            remaining -= len(data)
            yield data
    else:
        while True:
            data = await reader.read(65536)
            if not data:
                return
            yield data


def _build_http_request(ep: Endpoint, req: Request) -> bytes:
    """The wire format, assembled by hand because there is no client library.

    ignore_eos is the load-testing flag that makes output length an *input*:
    without it the model stops where it likes and every level measures a
    different number of decode steps. temperature 0 for the same reason -- a run
    that is comparing configurations should not also be sampling.
    """
    body = json.dumps({
        "model": ep.model,
        "prompt": list(req.prompt_ids),
        "max_tokens": req.max_tokens,
        "min_tokens": req.max_tokens,
        "ignore_eos": True,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()

    lines = [
        f"POST {ep.path} HTTP/1.1",
        f"Host: {ep.host}:{ep.port}",
        "Content-Type: application/json",
        "Accept: text/event-stream",
        # One connection per request, closed by the server when the stream ends.
        # Keep-alive would save a handshake and cost the ability to reason about
        # a stalled socket, which is the failure this harness has to survive.
        "Connection: close",
        f"Content-Length: {len(body)}",
    ]
    if ep.api_key:
        lines.append(f"Authorization: Bearer {ep.api_key}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode()
    return head + body


async def send_one(ep: Endpoint, req: Request, scheduled: float) -> Record:
    """Send one request, timestamping every token event that comes back.

    An SSE chunk can carry more than one event when the server batches its
    writes; the events in it then share a timestamp and one of the ITLs reads
    zero. That is a property of any streaming client, `vllm bench serve`
    included -- it is why the *median* ITL is the decode-step proxy and the mean
    is not (docs/GLOSSARY.md).
    """
    rec = Record(index=req.index, prompt_tokens=req.prompt_tokens, scheduled=scheduled)
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ep.host, ep.port), timeout=ep.timeout)

        rec.sent = time.perf_counter()
        writer.write(_build_http_request(ep, req))
        await writer.drain()

        status, headers = await asyncio.wait_for(_read_headers(reader), ep.timeout)
        rec.policy = headers.get("x-router-policy")
        if status != 200:
            detail = b"".join([c async for c in _iter_body(reader, headers)])
            rec.error = f"HTTP {status}: {detail[:200].decode('utf-8', 'replace')}"
            return rec

        last = rec.sent
        buffer = b""
        async for chunk in _iter_body(reader, headers):
            now = time.perf_counter()
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                payload = line[len(b"data:"):].strip()
                if payload == b"[DONE]":
                    continue
                event = json.loads(payload)

                usage = event.get("usage")
                if usage:
                    rec.usage_output_tokens = usage.get("completion_tokens")

                choices = event.get("choices") or []
                if not choices or not choices[0].get("text"):
                    # A usage-only frame, or a finish frame with no text: it is
                    # not a token, so it must not become an ITL sample.
                    continue

                if rec.ttft is None:
                    rec.ttft = now - rec.sent
                else:
                    rec.itls.append(now - last)
                last = now
                rec.output_tokens += 1

        if rec.ttft is None:
            rec.error = "stream ended before any token"
        else:
            rec.latency = last - rec.sent
        return rec

    except asyncio.TimeoutError:
        rec.error = f"timeout after {ep.timeout:.0f} s"
        return rec
    except (OSError, _ProtocolError, json.JSONDecodeError) as exc:
        rec.error = f"{type(exc).__name__}: {exc}"
        return rec
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def poisson_offsets(rate: float, count: int, seed: int) -> list[float]:
    """Arrival offsets in seconds for a Poisson process of the given rate.

    Exponential gaps, which is what makes the process Poisson and what makes the
    tail worth measuring: a constant-interval generator at the same mean rate
    never produces the coincident arrivals that build a queue, and run 2 found
    the TTFT p99 breaking at a third of the rate the steady-state arithmetic
    predicted (docs/benchmarks/l40s-run2.md section 3).

    Seeded, because a run that cannot be repeated cannot be re-faced with a
    changed configuration -- the same reason coefficients are pinned to a run.
    """
    if rate <= 0:
        raise ValueError("a Poisson arrival rate must be positive")
    rng = random.Random(seed)
    offsets, t = [], 0.0
    for _ in range(count):
        offsets.append(t)
        t += rng.expovariate(rate)
    return offsets


async def run_open_loop(
        ep: Endpoint, requests: list[Request], rate: float,
        seed: int = 0, max_in_flight: int | None = None) -> tuple[list[Record], float]:
    """Fire requests at wall-clock arrival times, regardless of what is finished.

    This is the mode in which TTFT means anything: the queue that forms is the
    *service's*, so the number can be compared with a target. The closed-loop
    sibling below cannot answer that question at all (docs/SLO.md section 9).

    max_in_flight is a safety valve, not a load parameter. If it ever engages the
    generator has stopped being open-loop, so it is reported rather than
    absorbed: the caller sees the deferred count and treats the level's TTFT the
    way it treats a closed loop's.
    """
    offsets = poisson_offsets(rate, len(requests), seed)
    gate = asyncio.Semaphore(max_in_flight) if max_in_flight else None
    records: list[Record] = []
    start = time.perf_counter()

    async def one(req: Request, offset: float) -> None:
        scheduled = start + offset
        delay = scheduled - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        if gate is not None:
            async with gate:
                records.append(await send_one(ep, req, scheduled))
        else:
            records.append(await send_one(ep, req, scheduled))

    await asyncio.gather(*(one(r, o) for r, o in zip(requests, offsets)))
    duration = time.perf_counter() - start
    records.sort(key=lambda r: r.index)
    return records, duration


async def run_closed_loop(
        ep: Endpoint, requests: list[Request],
        concurrency: int) -> tuple[list[Record], float]:
    """Hold exactly `concurrency` requests in flight until the list is exhausted.

    The mode that measures the *engine*: a fixed batch size is the independent
    variable of every decode-step and seat-count question, which is what run 1
    and the concurrency sweeps of run 2 needed. Its TTFT is the generator's own
    backlog and is not a service metric -- bench/stats.py carries that flag
    forward so a table cannot quietly print it against a 300 ms target.
    """
    if concurrency < 1:
        raise ValueError("closed-loop concurrency must be at least 1")
    queue: asyncio.Queue[Request] = asyncio.Queue()
    for req in requests:
        queue.put_nowait(req)
    records: list[Record] = []
    start = time.perf_counter()

    async def worker() -> None:
        while True:
            try:
                req = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            # scheduled == sent by definition here: in a closed loop the arrival
            # *is* the completion of the previous request on this worker.
            records.append(await send_one(ep, req, time.perf_counter()))

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    duration = time.perf_counter() - start
    records.sort(key=lambda r: r.index)
    return records, duration
