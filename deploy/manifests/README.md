# Manifests

Two layers, and the split exists to keep one rule enforceable: **nothing that
runs without a GPU may be reported as a measurement of vLLM.**

| Path | What it is |
|---|---|
| `base/` | The stack as it runs on a GPU node: `vllm/vllm-openai:v0.27.1`, one accelerator per Pod, the flags run 3 measured. This is the artefact — the thing to defend and to draw from memory. Applied on its own it needs a real accelerator. |
| `overlays/kind/` | The same objects with the container swapped for `stub/server.py`, so Deployment, Service, probes and autoscaling can be debugged on `deploy/kind/cluster.yaml` for free. |
| `overlays/kind-canary/` | The stub overlay again, suffixed `-canary`, with its own Service and an Ingress that ingress-nginx treats as a weighted alternative for the same `/v1` rule. `patch-version.yaml` is the version under test. The procedure is `docs/runbook.md`, "Canary rollout"; what happened when it was run is at the end of this file. |

    kubectl apply -k deploy/manifests/overlays/kind
    kubectl -n llm rollout status deployment/vllm

Those two lines are this component only. The full bring-up — the cluster, the
edge, the metrics and the autoscaler, in the order the admission webhooks
require — is in the repository `README.md`, and it is the only copy.

## What the stub is and is not

It answers `/health`, `/v1/models`, `/v1/completions` — non-streaming and, on
`"stream": true`, as chunked SSE — and `/metrics`, and it serves no model and
computes nothing. Streaming is part of the contract and not a convenience: a
non-streaming completion has exactly one arrival, so TTFT and total latency are
the same number at the client and the first metric in `docs/SLO.md` is not
observable on this cluster at any hop without it. The events carry empty `text`,
because the arrival times are the observable and invented tokens would be a
fabricated measurement. Its purpose is the platform's contract, not
text: a Service selector, a readiness gate and a queue-depth metric are all
testable without weights, and none of them is cheaper to test on a rented card.
Latency, throughput and seat counts are not testable here at all — those live in
`docs/benchmarks/`, measured.

What it does reproduce is the shape autoscaling reads: `MAX_NUM_SEQS` seats, a
FIFO queue in front of them, and requests over the ceiling that **wait rather
than fail** — in vLLM back-pressure is latency, not a 429. A completion holds a
seat for `max_tokens × SIM_DECODE_MS` of fake time.

`/metrics` carries two gauges, `vllm:num_requests_running` and
`vllm:num_requests_waiting`, with the name and label set (`engine`, `model_name`)
copied from a real capture of the pinned engine, not from memory:
`docs/benchmarks/raw/l40s-2026-08-18/concurrency/c32.txt`. Everything else the
real server exports is deliberately absent — a `gpu_cache_usage_perc` of zero
would be a fabricated measurement, where a missing series is only missing.

**The two env values in the overlay are fixtures and may not be quoted.**
`MAX_NUM_SEQS: "4"` is a ceiling a laptop can push a queue over; the real seat
count is derived per card and target (`docs/SLO.md` §4), and run 3 used the
engine default of 256. `SIM_DECODE_MS: "20"` measures nothing at all.

Observed on the cluster, 12 concurrent requests against 4 seats: `running`
pinned at 4 for the whole run while `waiting` stepped 8 → 4 → 0. That is the
argument for scaling on waiting — `running` is clipped at the ceiling, so three
levels of overload look identical through it.

## Graceful shutdown, and the bug that made it visible

A rollout on `kind` took the full 120 s of `terminationGracePeriodSeconds` for a
stub with nothing to drain, and the cause is not vLLM-specific: **a container's
entrypoint is PID 1, and the kernel does not apply default signal dispositions to
PID 1**, so a SIGTERM with no installed handler is discarded. Isolated outside
Kubernetes: `docker stop -t 10` on `python -c "time.sleep(300)"` takes 10.2 s and
ends in SIGKILL.

The consequence is a deploy that is guaranteed downtime rather than a drain, and
with `Recreate` (the strategy a fixed accelerator pool forces) the new Pod cannot
start until the old one is killed. The stub now installs the handler, in the
production order:

1. SIGTERM arrives — `/health` starts answering 503 while the process keeps
   serving. The Service withdraws the endpoint first, so nothing new is routed to
   a socket that is about to close.
2. After 15 s — `failureThreshold` 3 x `periodSeconds` 5, the readiness probe's
   own arithmetic — the listener closes.
3. In-flight requests finish, bounded well below the grace period.

Measured after the fix: 17.9 s to delete a Pod, against 120 s before.

## The edge, and the two ways it wastes a card

Four things measured on `kind` against the stub, with fixture Ingresses carrying
the defaults so both sides of each knob were live at once. The controller itself
is `deploy/ingress/`; the annotations and their derivations are
`base/ingress.yaml`.

**1. The edge timeout is derived from the engine's flags, and the default is too
short.** `proxy-read-timeout` is the gap allowed between two reads from upstream,
so a streamed response resets it every decode step and the 60 s default never
fires. A non-streaming request is the opposite: nothing is readable until
generation ends, and `--max-model-len 9000` x the 50 ms TPOT target is 450 s of
silence. Against a 70 s completion: **504 at 60.004 s** on the default, **200 at
70.010 s** at 480 s.

**2. A cut at the edge does not cancel the work, and nothing server-side says
so.** Sampling the engine across that same 504: the seat was still occupied at
t = 62 s and t = 67 s, and freed at t = 71 s — the full generation ran. Ten
seconds of a seventy-second request, 14% of its work, was produced for a client
that had left. That is the definition of a goodput loss, and it is invisible from
inside: `/metrics` reports `running = 1`, the HPA sees occupied capacity, and no
series separates those ten seconds from useful ones. A short edge timeout under
overload does not shed load — it converts capacity into waste silently.

**3. Streaming is how the platform learns the work became worthless.** The same
test on the streamed path: client killed at t = 4 s of a 60 s generation, seat
free by t = 9 s. `proxy_ignore_client_abort` defaults to off, so nginx closes the
upstream connection, and the stub finds out at its next write — a buffered
response, writing once at the end, cannot find out at all. So `"stream": true`
is not only a TTFT feature; it is the only channel by which an abandoned
generation stops being paid for.

**4. A prediction that measurement refuted.** `proxy-buffering: "off"` was set on
the belief that buffering delivers a stream in one arrival at the end. It does
not: a fixture Ingress at `"on"` produced the same 101 SSE events ~20 ms apart,
with identical arrival times, and `off` is already ingress-nginx's own default
(vanilla nginx defaults to `on`). Buffering decouples the rate nginx reads
upstream from the rate it writes to the client; it does not withhold the body.
The annotation stays as a pinned guarantee rather than a change — and the first
instrument used to test it was wrong too: curl's `time_starttransfer` counts
headers, which pass promptly in both modes, so TTFB cannot see buffering by
construction. Per-event arrival times can.

**Reproduced.** All four were first taken on a cluster left running from an
earlier session, which is not a controlled instrument: live objects can have
drifted from the files, and a warm HPA carries history. So they were re-taken on
a cluster built from scratch — 504 at 60.004 s against 200 at 70.006 s, the seat
still held five seconds after its client's 504, the streamed abort freeing a seat
at t=10 s of a 60 s generation, and 101 SSE events ~20 ms apart identically in
both buffering modes. What did *not* survive the rebuild was a claim about
autoscaling, corrected in `../ingress/README.md`: the edge's endpoint set follows
`readyReplicas` by convergence, not by equality at every instant, and the warm run
that appeared to show equality was sampling luck.

## What changes on the way to a real card

- **AMD.** MI300X is `amd.com/gpu` in `limits` and a `rocm/vllm` image: two
  fields, one more overlay. The weeks 9–11 instrument decision is
  `docs/instrument-vllm-bench-sweep.md`.
- **Weights.** Decided, and it is `base/pvc.yaml`: one RWO volume, populated
  once by the `fetch-weights` Job and mounted read-only by every replica. The
  argument against the two alternatives — a shared network volume, a baked
  image — is in that file. On a multi-node accelerator pool the answer changes
  to the baked image.
- **Placement, which the volume now decides.** Watched on `kind` at four
  replicas: the PersistentVolume carries a node affinity to the node that first
  bound it, and all four Pods were scheduled there while the other worker sat
  empty. This is correct on a single-accelerator-node pool and a trap anywhere
  else — replicas cannot spread past the volume, so free GPUs on other nodes are
  unreachable and the surplus Pods stay Pending. The volume is a placement
  constraint, not only a storage choice.

## Canary, observed on kind — 2026-09-03

The runbook's canary procedure, run once, on the roll-back branch by design:
the version in `overlays/kind-canary/patch-version.yaml` has one seat and a
1000 ms step, so it cannot hold a tenth of the traffic and the rule has to say
so. Fixtures throughout — none of the numbers below is a performance number,
and the timings are timings of `kind`, Prometheus and ingress-nginx, not of an
engine.

Stable: 1 replica, 4 seats, 20 ms/token. Canary: 1 replica, weight 10. Load:
one streamed completion per second for 300 s, `max_tokens` 50 — a hold of 1 s on
stable, 50 s on the canary. `t` counts from the first request.

    t=0        canary applied 33 s earlier; startup log reads "1 seats, 1000 ms/token"
    t=+15 s    canary waiting 5           stable 1 replica, waiting 0    QueueBeyondTTFTBudget{pod=vllm-canary-…} pending
    t=+30 s    canary waiting 6           stable 3 replicas, all waiting 0
    t=+91 s    canary waiting 9           stable 4 replicas, all waiting 0
    t=+138 s   canary waiting 10          stable 4 replicas               firing
    t=+154 s   kubectl delete -k overlays/kind-canary
    t=+157 s   last "no alternative balancer" line in the edge log; those 3 requests went to stable with 200
    t=+168 s   canary series gone from the query                            still firing (one evaluation)
    t=+184 s                                                                no alert
    t=+188 s   one 503 from a stable Pod draining for scale-in
    t=+199 s   stable 1 replica
    t=+262 s   canary Pod exits; the edge logs 9 upstreams closed prematurely

Every one of the 298 requests is in the edge's access log: 14 reached the canary
and 284 the stable track. Over the 154 s the canary existed that is 14 of 153,
9.2 % against a weight of 10. Of the 14, five completed — one per 50 s, the last
two *after* the roll-back, served out of the queue during the drain — and nine
were cut when the Pod exited: eight had never left the queue (0 bytes of body),
one was mid-stream.

**What the run says, in the order it matters at 03:00.**

*The rule named the track.* `max by (pod)` put the canary Pod's name in the
alert, and the stable Pods never entered it. That is the whole promote-or-roll-
back signal, and it is why the `service` label exists in
`../observability/prometheus/prometheus.yml`: an unscraped canary would have
queued in silence.

*The scaler spent capacity on a queue it could not reach.* Three stable
replicas added for a canary queue, all idle. The query was fleet-wide and the
fleet had two tracks; the fix and its reasoning are in `../keda/README.md`.

*Roll-back is one delete, and it costs what is in the queue.* The Ingress left
first: for three seconds the edge still drew requests for the canary, found no
backend and sent them to stable — no client saw that. The alert cleared when
the Service left discovery, thirty seconds after the delete, not when the Pod
did. The Pod took 108 s — the stub's 15 s readiness withdrawal plus its 90 s
drain — and left with nine requests inside, because a queue of 50 s holds on
one seat cannot drain in 90 s. On a card the same arithmetic is
`terminationGracePeriodSeconds` against the queue depth times the hold, and a
roll-back with a deep queue is a roll-back that fails those requests; the way
to fail fewer is to roll back at `pending`, not at `firing`.

*The 503 was not the canary's.* It came from a stable Pod that had just
received SIGTERM for scale-in: the stub fails readiness and refuses new
completions with 503 for the 15 s it stays on the endpoint list, and the edge
does not retry a 503 (`base/ingress.yaml`, deliberately). One request in 298 —
and a scale-in cost the canary run made visible without causing it.

**Not measured here.** The promotion branch — weight to 100, the stable
rollout, the canary deleted — has not been run; its capacity gap is derived in
the runbook. Whether the per-track split of the histogram rule is needed on a
card (a canary at 10 % burning at 100 % is a fleet burn rate of 10, under the
14.4 threshold) — needs the histogram. Whether a real engine's drain behaves
like the stub's 15 + 90 s.
