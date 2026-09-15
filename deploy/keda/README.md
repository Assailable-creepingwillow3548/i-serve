# Autoscaling

One `ScaledObject` on one metric: `sum(vllm:num_requests_waiting{service="vllm"})`.
Why queue depth and not GPU utilisation is `docs/SLO.md` §4 — utilisation
saturates long before latency degrades, and 42% of the interactive TTFT budget on
the measurement card is queue. The threshold is derived in the same section and
is not restated here. The `service` selector is the stable track: the scaler
reads the queue of the Deployment it scales and nothing else, for the reason at
the end of this file.

| Path | What it is |
|---|---|
| `base/` | The ScaledObject as it runs against a real deployment: `threshold: "1"`, a 300 s scale-down window, `maxReplicaCount` capped at the accelerator count. |
| `overlays/kind/` | The same object with fixture numbers, so the loop can be watched inside a session on `deploy/kind/cluster.yaml`. |

KEDA itself is a prerequisite and is deliberately not vendored here:

    kubectl apply --server-side -f \
      https://github.com/kedacore/keda/releases/download/v2.20.2/keda-2.20.2.yaml
    kubectl -n keda rollout status deployment/keda-operator
    kubectl apply -k deploy/keda/overlays/kind

The `rollout status` line buys validation, not admission, and the distinction was
measured rather than assumed: all six KEDA webhooks carry
`failurePolicy: Ignore`, so a ScaledObject applied before the operator serves is
**accepted unvalidated** — no error, no rejection. Since this webhook is exactly
what catches a `pollingInterval` that KEDA will not honour (below), skipping it
is the quiet kind of mistake. ingress-nginx makes the opposite choice, `Fail`, and
is discussed in `../ingress/README.md`.

What else has to be running before this works — the metrics it reads, the
Deployment it scales — is in the repository `README.md`, which holds the only
copy of the full order.

## What the loop actually is

KEDA is not a controller that scales anything here. With `minReplicaCount` above
zero it registers an external metric and creates an HPA; the HPA runs the loop at
the controller manager's sync period, and KEDA answers its queries by asking
Prometheus. `pollingInterval` is therefore absent from the manifest — KEDA's own
admission webhook rejects it as irrelevant unless the floor is zero.

The HPA reports the metric as an *average per replica*: `1250m` at four replicas
is five queued requests across the fleet, and the desired count is
`ceil(sum / threshold)`.

## Observed on kind — including the failure

12 concurrent requests, 4 seats per replica, `threshold: "2"`, a 30 s scale-down
window, over a 90 s load:

    t=20s   1 replica    sum 0      steady
    t=25s   4 replicas   sum 8      ceil(8/2) = 4, capped at maxReplicaCount
    t=50s   4 replicas   sum 0      16 seats absorb the 12 in flight
    t=65s   1 replica    sum 0.25   scaled in after the 30 s window
    t=80s   4 replicas   sum 8      ...and the same load re-queues immediately
    t=110s  3 replicas   sum 5      ceil(5/2) = 3
    t=125s  1 replica    sum 0      load over

**It oscillated, and the oscillation is the lesson.** The trigger metric is
destroyed by the response to it: replicas are added because the queue is deep,
the queue empties because the replicas were added, and scaling in restores
exactly the state that triggered the scale-out. Nothing in the metric can
distinguish "the load went away" from "the load is being served by capacity that
is about to be removed".

The fix is not a bigger threshold — that only moves the oscillation to a higher
load. It is the scale-down window, which is why `base/` sets 300 s against the
fixture's 30 s, and why the two directions are deliberately asymmetric: adding a
replica costs a weight load, and removing one throws that load away. The 30 s
here is a fixture that buys an observable scale-in inside a session, and it buys
the flapping with it.

**The fixture numbers may not be quoted.** `threshold: "2"` belongs to a stub
with 4 fake seats; the derived value is `"1"` and lives in `docs/SLO.md` §4.

## Observed beside a canary — the scaler reading the wrong track

2026-09-03, with the canary of `../manifests/overlays/kind-canary` taking 10 %
of `/v1` and unable to serve it (one seat, a 50 s hold per request): the queue
formed on the canary Pod, the stable Pods held `waiting 0` throughout, and the
query as it then stood — `sum(vllm:num_requests_waiting)` with no selector —
summed the canary's queue in. The HPA did the arithmetic it is built for,
`ceil(sum / 2)`, and the stable track went 1 → 3 at t+30 s and 4 by t+91 s,
every added replica at `running 0, waiting 0`. A request already routed to the
canary cannot be taken by a stable replica, so the response reached nothing the
metric described. The timeline is in `../manifests/README.md`; the scaler's
share of it is this paragraph.

The fix is the `{service="vllm"}` selector in both manifests, and it is a
selector rather than a `by (service)` because the ScaledObject scales exactly
one Deployment: it should read exactly that Deployment's queue. Re-run the same
day with the same canary beside it: the canary's queue reached 13, the alert
fired and the stable track stayed at one replica throughout.
