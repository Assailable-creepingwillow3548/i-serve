# The edge

One hop in front of the Service, and the first place in this stack where a knob
belonging to a proxy can break an SLO the engine is meeting. What is routed and
why is [`../manifests/base/ingress.yaml`](../manifests/base/ingress.yaml); the
numbers in it are derived in [`../../docs/SLO.md`](../../docs/SLO.md). This file
covers only the controller.

| Path | What it is |
|---|---|
| `overlays/kind/` | The upstream kind manifest as a pinned remote resource, with the one patch it needs on `deploy/kind/cluster.yaml`. |

    kubectl apply -k deploy/ingress/overlays/kind
    kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller

The wait is required, not tidiness. The manifest installs an admission webhook
with `failurePolicy: Fail`, so an Ingress applied before it serves is rejected —
`connect: connection refused` from the API server, after the rest of the overlay
has already been created. Where this sits in the full bring-up is
[`../../docs/running-on-kind.md`](../../docs/running-on-kind.md), which holds the
only copy of that order.

The controller is a prerequisite and is not vendored, the same call made for KEDA
(`../keda/README.md`): 700 lines copied in would only become a second thing to
keep current. It is taken at a release tag and never `main` — an unpinned proxy
changes under numbers already measured through it, exactly as `latest` would
change the engine.

## Why the patch exists

`deploy/kind/cluster.yaml` labels the control-plane node `ingress-ready=true` and
maps its ports 80/443 out to `localhost:8080/8443`, on the documented assumption
that the kind provider manifest selects that label. **By `controller-v1.15.1` it
no longer does** — upstream kept the `hostPort: 80/443` and the control-plane
tolerations but reduced `nodeSelector` to `kubernetes.io/os: linux`. The Pod is
then free to land on a worker, bind port 80 there, and be unreachable from
outside the cluster.

The failure is quiet and worth recognising by its signature: `curl
localhost:8080` returns **curl exit 52, empty reply** — not connection refused.
`extraPortMappings` is a docker-level publish on the node container, so the TCP
connect is accepted whether or not anything inside that node is listening.
Refused would mean no mapping; an empty reply means a mapping with nothing behind
it.

The overlay restores the selector. Note what it does not do: nothing here makes
the edge highly available. `hostPort` is exclusive per node, so the controller is
one Pod on one node by construction, and a second replica would need a second
labelled node with its own mappings.

## Observed: the edge under autoscaling

12 concurrent streamed completions driven through `localhost:8080`, sampled every
8 s, on a cluster built from scratch so the HPA carried no history (4 seats per
replica, `maxReplicaCount` 4):

    t=1s     ready 1    edge endpoints 1
    t=17s    ready 4    edge endpoints 2     <- edge behind
    t=25s    ready 4    edge endpoints 4
    t=66s    ready 4    edge endpoints 3     <- edge ahead
    t=74s    ready 2    edge endpoints 2
    t=99s    ready 1    edge endpoints 1

**The two sets converge; they are not equal at any given instant.** Two of
fifteen samples disagreed, and in both directions — the edge lagging on
scale-out, and the edge dropping a replica before the Deployment's status caught
up on scale-in. An earlier run against a warm HPA agreed at every sample and was
read as equality; that was a sampling artefact, and the cold run is the one to
trust. The same pair shows why the timings here are observations and not
reproducible numbers: warm, the fleet reached four replicas at t=28 s and stepped
down 4 -> 3 -> 2; cold, t=17 s and 4 -> 2 -> 1.

What is structural rather than timing-dependent is that **no nginx reload is
involved**: the backends live in a Lua shared dict fed by an endpoints watch,
which is why a scale-out costs the edge nothing.

The lag has a direction, and the two directions are not equally harmless. On
scale-out, capacity Kubernetes already counts as ready is not yet receiving
traffic, so the queue keeps draining at the old rate for a moment after the
replicas exist — negligible against a real card, where weight loading dominates
that delay by orders of magnitude and is what `controllers/modelwarmup/` exists
to remove. On scale-in it is the safe direction: the edge stops using a replica
before the fleet's status reflects it.

The list follows *ready* replicas, so the readiness gate is the lever that takes
a replica off the edge — the same gate the drain in `../manifests/README.md`
fails first on SIGTERM, before the listener closes. Withdrawing readiness and
withdrawing traffic are one action.

## Where this goes next

Ingress is frozen at v1 and Gateway API is its successor, which matters here
more than it does for an ordinary web service: the LLM-serving gateways
(llm-d, AIBrix, vLLM production-stack) build on Gateway API's Inference
Extension, whose whole point is routing decisions this hop cannot make.

That gap is visible already, and it was checked rather than asserted: read the
controller's own backend list at `localhost:10246/configuration/backends` and the
endpoints it holds for this route are **Pod** addresses, not the Service's
ClusterIP, with the choice between them made by `balancer_by_lua_file` inside
nginx, whose `DEFAULT_LB_ALG` is `round_robin`. The observed values, and what
follows for the request path, are `../../docs/architecture.md` §1.

So **the edge load-balances, not kube-proxy** — and it does so by a policy close
to the worst available for LLM traffic. Request cost here varies by orders of
magnitude, and sending a request to the replica that already holds its prefix is
worth more than any balance: run 3 measured 12.5 seats at a prefix-cache hit rate
of 0 against 37.8 at 0.8 (`docs/SLO.md` §6). Naming the policy is enough for now;
changing it is a Gateway API step, not an annotation.
