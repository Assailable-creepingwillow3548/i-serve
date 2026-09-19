# Architecture

The request path from ingress to GPU, and where each SLO in [SLO.md](SLO.md) is
won or lost along it.

Three rules hold for everything below, and they are what make the document
defensible rather than decorative.

- **Nothing here was measured on a GPU node.** The objects are the ones in
  `deploy/`; every timing was taken on `kind` against a stub that carries the
  engine's API and metric contract and no model at all
  (`deploy/manifests/README.md`). Latency, throughput and seat counts live in
  [benchmarks/](benchmarks/), measured on a rented card, and the two are never
  mixed in one sentence.
- **No number is derived here.** Each one names the file that owns it — mostly
  [SLO.md](SLO.md) §4 and §6 — and is repeated only where the number *is* the
  point of the sentence.
- **The diagram is the deliverable.** It has to stay small enough to redraw on a
  whiteboard from memory; everything that cannot be drawn is prose underneath it,
  not a second diagram.

## 1. The path

    client
      |  one HTTP request; `"stream": true` decides much of what follows
      v
    +------------------------------------------+
    | edge - ingress-nginx                     |   route: /v1 and nothing else
    | one Pod, hostPort :80, one labelled node |   read timeout 480 s
    +------------------------------------------+   retry: connection errors only
      |  round_robin, straight to Pod addresses
      v
    +------------------------------------------+
    | vLLM Pod                                 |
    |                                          |
    |   HTTP server  - admits, never refuses   |
    |        |                                 |
    |        v                                 |
    |   waiting  - FIFO; over the ceiling      |  <- most of the TTFT budget
    |             requests wait, not fail      |
    |        |                                 |
    |        v                                 |
    |   running  - max_num_seqs seats          |  <- the ceiling that is derived
    |        |                                 |
    |        v                                 |
    |   GPU  - prefill once, then decode steps |  <- the floors
    +------------------------------------------+

    Service vllm (ClusterIP) is not a hop on that path. Its selector produces
    the endpoint list, and both consumers - the edge and Prometheus - resolve
    that list to Pod addresses and talk to Pods directly.

    control loop, one pass:

      each Pod /metrics --> Prometheus --> KEDA --> HPA --> Deployment replicas
                            per-Pod         external       ceil(sum / threshold)
                            discovery       metric

Five boxes on the data path, four on the control path, and one object off to the
side that everything depends on and nothing routes through. That last point is
the part of the picture most likely to be drawn wrong: a Service looks like a
load balancer in the middle of the path, and here it is a *membership list*.

**Checked, on a cluster built from scratch (2026-08-31).** The edge's own backend
list — `localhost:10246/configuration/backends` on the controller — carried one
backend for this route, `llm-vllm-http`, and its endpoint was the **Pod's**
address. The Service's ClusterIP appeared in that JSON only in an informational
`service` field, never as an upstream, and Prometheus's active target for the same
Pod was that Pod's address as well. The ClusterIP's DNS name occurs exactly once
in this repository — in a comment in `deploy/manifests/base/service.yaml`
explaining what it is for.

The addresses themselves are deliberately not quoted here: they belonged to a
cluster that no longer exists, and the check is reproducible on any cluster from
that same backend list.

The route's *omissions* were checked in the same pass, since an exposure surface
is worth measuring rather than intending: `/metrics`, `/health` and `/` all answer
**404 through the edge** and **200 at the Pod**. The internal state exists and is
reachable by the kubelet and by Prometheus over the Pod IP; it is simply not
published to whoever can reach the address.

Two consequences follow, and the first is measured while the second is derived:

- **kube-proxy is not in the request path, so the balancing decision belongs to
  the edge.** No policy is set anywhere here, so the controller's fallback
  applies — `balancer.lua` reads `backend["load-balance"] or DEFAULT_LB_ALG`, the
  backend's field is null and the ConfigMap is empty, and `DEFAULT_LB_ALG` is
  `round_robin`. Anything prefix-aware therefore has to be built at this hop or
  at its successor, never in the Service (§6, `deploy/ingress/README.md`).
- **A Service-level `sessionAffinity: ClientIP` would do nothing for external
  traffic**, since that field is enforced by kube-proxy on the path this traffic
  does not take. Derived from the above, not measured — the affinity fields on
  the observed backend were empty.

## 2. What each hop owns

Read this as: if this SLO is missed, which hop could have done it.

| Hop | What it owns | What it can break | Where the number lives |
|---|---|---|---|
| client | `"stream": true` or not | with one arrival there is no TTFT to measure, and an abandoned generation can never stop being paid for | `deploy/manifests/README.md` |
| edge | read timeout, buffering, retry policy, balancing policy | a 504 mid-generation while the seat keeps burning; `round_robin` spreads requests away from the replica holding their prefix | `deploy/manifests/base/ingress.yaml`, `deploy/ingress/README.md` |
| Service | the endpoint list, via one label selector | a selector typo yields a Service with no endpoints and no error; withdrawing readiness is how a replica leaves the edge | `deploy/manifests/base/service.yaml` |
| HTTP server | admission | nothing: back-pressure here is latency, not a 429, so overload arrives as a queue and not as an error rate | `deploy/manifests/README.md` |
| waiting | queue depth | the SLO, mostly — 84% of the interactive TTFT budget on the baseline card and 42% on the measurement card is queue, not computation | [SLO.md](SLO.md) §4 |
| running | how many sequences share the card | `max_num_seqs` too high trades TTFT for throughput; too low leaves seats unused | [SLO.md](SLO.md) §4, §6 |
| GPU | the floors | nothing above the floor is the model's fault; anything below it is a measurement error | [SLO.md](SLO.md) §4 |

Two of those rows are the same fact seen twice, and it is the fact that makes an
LLM platform different from a web platform: **the queue is inside the Pod, not in
front of it.** A web tier sheds load by refusing it, and its error rate is the
alarm. Here the engine admits everything and back-pressure appears only as
latency, so nothing on the path emits an error while the SLO is being missed. The
only series that moves is `vllm:num_requests_waiting`, which is why the
autoscaler reads that and not GPU utilisation ([SLO.md](SLO.md) §4).

## 3. Where each metric is observed

The same quantity has different values at different hops, and some quantities
exist at only one of them. Three classes, and knowing which class a metric is in
is what stops an operator from chasing a number that was never observable where
they were standing.

**Observable only from outside.** *Goodput* — work that arrived inside its SLO —
is a property of what the client received, so no series inside the Pod can carry
it. Measured on `kind`: a non-streaming request cut by the edge at 60 s ran to
the end of its 70 s generation, and 14% of its work was produced for a client
that had left. Throughout, `/metrics` reported `running = 1` and the HPA saw
occupied capacity; nothing separates those ten seconds from useful ones
(`deploy/manifests/README.md`). A short edge timeout under overload therefore
does not shed load — it converts capacity into waste, silently.

**Observable only from inside.** The prefix cache hit rate `h` and the KV pool
size are both invisible to a client. `h` has no gauge on the V1 engine at all,
only the counters `vllm:prefix_cache_queries` and `vllm:prefix_cache_hits`, whose
ratio *over a window* is the hit rate; the pool is not in `/metrics` at any point
and is logged once at startup, where [SLO.md](SLO.md) §9 puts it above every
derivation in this repository (`bench/vllm_metrics.py`).

**Observable from both, with different values.** These are the dangerous ones.

- **Queue depth** has three readings for one quantity. A per-Pod scrape gives
  that Pod's queue; a scrape of the ClusterIP gives *one arbitrary replica's*
  queue and looks like the fleet's, which is why discovery is per-endpoint rather
  than a static Service target (`deploy/observability/prometheus/prometheus.yml`);
  and the HPA reports an average per replica, so `1250m` at four replicas means
  five requests queued across the fleet (`deploy/keda/README.md`).
- **TPOT** measured as a decode step and TPOT as served are not the same number,
  and the gap is scheduling rather than bandwidth. On the measurement card the
  50 ms target is crossed at ~31 sequences if the question is put to the decode
  step and at 12 if it is put to TPOT p99, which is the metric the SLO actually
  names — 2.6× apart, with the residual being the engine's scheduler and not the
  memory bus ([benchmarks/l40s-baseline.md](benchmarks/l40s-baseline.md) §5,
  [SLO.md](SLO.md) §4). The proxy also expires: median ITL stops being a decode
  step once prefill lands in the *majority* of scheduler steps, and a ratio of
  TPOT to median ITL at or below 1 is the sign that it has
  ([benchmarks/l40s-run2.md](benchmarks/l40s-run2.md) §6).
- **TTFT** is only observable at all where the edge passes bytes through as they
  arrive, and only on a streamed response: with one arrival, TTFT and total
  latency are the same number at the client
  (`deploy/manifests/base/ingress.yaml`).

And the instrument itself can be blind by construction, which is the fourth
lesson and belongs here rather than in a runbook. `proxy-buffering` was tested
with curl's `time_starttransfer`, which counts headers — and headers pass
promptly in both modes, so TTFB cannot see buffering at all. Per-event arrival
times can, and they showed the prediction was wrong: 101 SSE events ~20 ms apart,
identical through both settings (`deploy/manifests/README.md`).

## 4. The control loop, and why it is minutes

The loop is: Prometheus scrapes each Pod, KEDA answers the HPA's query from
Prometheus, the HPA sets a replica count of `ceil(sum / threshold)`, and a new
Pod loads weights before it serves anything. KEDA scales nothing itself — with
`minReplicaCount` above zero it registers an external metric and creates the HPA,
which is what runs the loop (`deploy/keda/README.md`).

Its terms add up to minutes, and the largest one is not a controller: the scrape
interval, plus KEDA's 30 s default poll, plus the HPA's own sync period, plus a
Pod's start-up, measured at 69.16 s on the L40S. **A burst shorter than that loop
cannot be answered by scaling at all** — only by seats that already exist, which
is a cost decision and not a scaler setting ([SLO.md](SLO.md) §4).

That start-up term is the one that can be removed rather than tuned — but not by
moving the weights closer, which is what this section claimed before anyone
measured it. Fetching and loading 16.4 GB of weights is 19.1 s of the 69.16 s;
`torch.compile` alone is 34.95 s; and ~17 s is a floor no cache reaches
([benchmarks/l40s-run3.md](benchmarks/l40s-run3.md) §6). What is left for
`controllers/modelwarmup/` — and the case that it should stay empty — is
[../controllers/modelwarmup/README.md](../controllers/modelwarmup/README.md).

Three properties of the loop are worth holding in memory because each one
inverts an intuition.

1. **The trigger metric is destroyed by the response to it.** Replicas are added
   because the queue is deep, the queue empties because they were added, and
   scaling back in restores exactly the state that triggered the scale-out.
   Watched oscillating on `kind`, and the fix is not a larger threshold — that
   only moves the oscillation to a higher load — but an asymmetric scale-down
   window: adding a replica costs a weight load, and removing one throws that
   load away (`deploy/keda/README.md`).
2. **The threshold is a policy number, not a derived one.** The queue depth that
   preserves interactive TTFT works out below one request, so no positive integer
   threshold protects a queued request's latency. What autoscaling buys is a
   shorter overload — goodput — not a faster queued request ([SLO.md](SLO.md)
   §4).
3. **The edge's endpoint set and `readyReplicas` converge; they are not equal at
   an instant.** Two of fifteen samples disagreed on a cold cluster, in both
   directions. On scale-out that means ready capacity not yet receiving traffic;
   on scale-in it is the safe direction, the edge dropping a replica before the
   fleet's status reflects it. No nginx reload is involved either way — the
   backends live in a Lua shared dict fed by an endpoints watch
   (`deploy/ingress/README.md`).

## 5. When a replica goes away

**Planned — a rollout or a scale-in.** The order along the path is the whole of
it, and it runs backwards from the client: readiness is withdrawn first, so the
endpoint leaves the edge's list while the process is still serving; only then does
the listener close; only then do in-flight requests finish. **Withdrawing
readiness and withdrawing traffic are one action**, because the edge's list
follows *ready* Pods — the readiness gate is the only lever that takes a replica
off the edge (`deploy/ingress/README.md`).

That order is not free, and it is not the default. A container's entrypoint is
PID 1, which the kernel exempts from default signal dispositions, so an
unhandled SIGTERM is discarded and what looks like a drain is a wait for SIGKILL.
The handler, the probe arithmetic that sets each delay, and the measured cost of
getting it wrong are `deploy/manifests/README.md`.

What the order cannot buy on a fixed accelerator pool is a rollout without
downtime. `strategy: Recreate` is forced there — a surge Pod would need a free
accelerator, and there is none until the old Pod exits — so a deploy is a gap,
not an overlap. Zero-downtime is a canary with real spare capacity, not a
strategy field (`deploy/manifests/base/deployment.yaml`, [runbook.md](runbook.md)).

**Unplanned — a Pod or its accelerator lost.** Not measured; the following is
derived from the manifests and is flagged as such, per the rule that a derived
figure is never reported as a measurement ([SLO.md](SLO.md) §9).

- In-flight work on that Pod is gone. A request already streaming cannot be
  retried: `proxy-next-upstream` is set to connection errors only, deliberately,
  since a request that has burned accelerator time would otherwise be re-sent to
  burn it again — and once bytes have reached the client a streamed response is
  unretryable whatever the setting says
  (`deploy/manifests/base/ingress.yaml`). The tokens already produced are paid
  for and the failure lands on the client.
- A wedged engine is taken out of rotation before it is killed, because liveness
  is set to fire later than readiness. And a slow *start* is not a restart loop
  at all: until the startup probe passes it suspends the other two, so minutes of
  weight loading cost nothing. Three probes, three jobs, and the periods that
  order them are `deploy/manifests/base/deployment.yaml`.
- **The replacement may have nowhere to go**, and the cause is the weights
  volume. The PersistentVolume carries a node affinity to the node that first
  bound it — watched on `kind`, all four replicas scheduled onto that one node
  while the other worker sat empty. On a single-accelerator-node pool that is
  correct; anywhere else, a free GPU on another node is unreachable and the
  surplus Pods stay Pending. The volume is a placement constraint, not only a
  storage choice (`deploy/manifests/README.md`).

## 6. What this drawing does not contain

- **A GPU.** The whole path above has run only on `kind` against the stub. Every
  performance figure quoted here was measured on a rented L40S in a different
  setting, one server at a time and no Kubernetes involved.
- **Inference-aware routing — on the route drawn above.** The edge balances
  `round_robin` over Pod addresses, which for this traffic is close to the
  worst available policy: request cost varies by orders of magnitude, and
  sending a request to the replica that already holds its prefix is worth more
  than any balance — run 3 measured 12.5 seats against 37.8 at a hit rate of
  0.8 ([SLO.md](SLO.md) §6). Fixing it properly is a Gateway API step and not
  an annotation (`deploy/ingress/README.md`).

  Since 2026-09-19 there is a **second route** on `kind` that does route on
  cache locality: the host `router.localhost` goes edge → `prefix-router` →
  Pod address, over the same engine Pods (`router/`, `deploy/router/`). It is
  not in the drawing on purpose — the drawing is the default server's path and
  has to stay redrawable from memory — and it is not the default: the route
  above is still what an unadorned request gets, which is what makes the two
  comparable at all. What the second route has established is *routing*
  behaviour only. It has produced no TTFT and no seat number, and may not:
  those need a card and a prediction written first
  ([adding-a-run.md](adding-a-run.md)).
- **Fixture numbers, which may not be quoted.** The `kind` overlays carry
  `MAX_NUM_SEQS: "4"`, `SIM_DECODE_MS: "20"` and `threshold: "2"` so a laptop can
  push a queue over a ceiling inside a session. The derived values are in
  [SLO.md](SLO.md) §4 and the manifest bases.
- **Alert delivery.** The two alerting rules on the TTFT objective exist and
  the queue one has fired on `kind`; the dashboard shows a firing alert and
  Prometheus's `/alerts` lists it (`deploy/observability/README.md`), but
  nothing routes it to a person — there is no Alertmanager.
- **A second edge replica.** `hostPort` is exclusive per node, so the controller
  is one Pod on one node by construction (`deploy/ingress/README.md`).
- **The bring-up order.** It has exactly one copy, in the repository
  `README.md`, including which two waits are load-bearing and why the two
  admission webhooks fail differently.
