# The prefix router, on `kind`

What the router *is* — the ring, the key, the bounded load, the five policies —
is [`../../router/README.md`](../../router/README.md), and none of it is
restated here. This directory is the other half: what it takes to put that
binary in front of the engine Pods of a running cluster, and what the missing
half of it costs, measured.

**Where it sits.** `edge → router → Pod address`, on the host
`router.localhost` only. The engine's own route is untouched: `/v1` with no
host still goes `edge → Service → round_robin over Pods`
([`../manifests/base/ingress.yaml`](../manifests/base/ingress.yaml)). Two doors
onto one set of Pods, differing in the policy and in nothing else — that is the
comparison, and repointing the existing route would have thrown it away along
with the canary overlay that splits the same path by weight.

**What it is not.** There is no `base/` here, and the omission is the point: the
replica set is a start-up flag, and a flag is not a production shape. A base
would be a claim that this can be deployed somewhere that matters, which the
next section is the argument against.

---

## 1. The flag's bill, measured on `kind` (2026-09-19)

The router is told its fleet once, at start-up. Nothing in the cluster tells it
again. Both halves of what that costs were watched on a three-replica stub
fleet, pinned with `paused-replicas` so KEDA was not competing:

| Event | What the router did | Cost |
|---|---|---|
| fleet 3 → 4 | kept routing over the three addresses it was given | **24 of 24 requests to the old three; the new replica took none.** Silent — no error anywhere, the capacity is simply not used |
| fleet 3 → 2 | kept sending the departed replica's share of the key space to an address that no longer exists | **7 of 24 requests (29 %) returned 502**, and did so forever, not transiently |

The second is the sharper one, and it stays sharp after the fix below: the
router is *confident*. A replica that is gone is not a replica it avoids; it is
a third of the ring.

Neither is a defect in the router. Both are the absence of the thing that calls
`setUpstreams`, which is already safe to call while requests are in flight —
that is what the ring was built for. The placeholder shaped exactly like the
hole is [`upstreams.sh`](upstreams.sh).

## 2. What a departed replica costs per request

A Pod address removed from the cluster network does not refuse connections, it
blackholes them. With Go's default transport that is a **30 s** dial before the
502 — measured 30.006 s against 0.026 s to a live replica, **100× the whole
300 ms TTFT budget** ([`../../docs/SLO.md`](../../docs/SLO.md) §1), spent
producing an error.

`-dial-timeout` (250 ms) is the fix, and it is a policy number rather than a
detail: it does not make the request succeed — there is no retry — it makes the
failure arrive inside the budget instead of a hundred budgets later. Re-measured
after the change: **0.256 s**. The argument for the value, including what a
timeout under one second gives up, is in `newTransport`
([`../../router/router.go`](../../router/router.go)).

This is the defect the session was for. It was not visible by reading: every
test in `router/` dials a `httptest` server on loopback, where a dead address
refuses instantly and the dial timeout never runs.

## 3. Running it

The stack first — [`../../docs/running-on-kind.md`](../../docs/running-on-kind.md),
or `./up.sh`. Then four commands, and the first two are the price of a compiled
component: unlike the Python stub, a Go binary cannot ride a ConfigMap.

    docker build -t prefix-router:dev router
    kind load docker-image prefix-router:dev --name i-serve
    kubectl apply -k deploy/router/kind
    ./deploy/router/upstreams.sh

Between the third and the fourth the router is in `CrashLoopBackOff` with
`-upstreams is required` in its log. That is not a race to wait out: it is the
Pod saying it does not know what the fleet is, which is the honest state of a
router whose fleet is a flag.

`up.sh` does **not** do any of this, deliberately. Adding it would make a Docker
build a prerequisite of the whole stack, and the eleven commands
`docs/running-on-kind.md` documents are worth more than the convenience.

### Seeing the property

A fleet of one cannot show routing, and KEDA owns the replica count. Pin it:

    kubectl -n llm annotate scaledobject/vllm \
        autoscaling.keda.sh/paused-replicas=3 --overwrite
    kubectl -n llm rollout status deployment/vllm
    ./deploy/router/upstreams.sh

Then the two loops from [`../../router/README.md`](../../router/README.md) §7,
with the host header doing the work the port did off-cluster:

    # one prompt, four times -- one replica
    for i in 1 2 3 4; do
      curl -s -D - -o /dev/null -X POST http://router.localhost:8080/v1/completions \
        -H 'content-type: application/json' \
        -d '{"model":"Qwen/Qwen3-8B","prompt":"you are a careful assistant. summarise.","max_tokens":2}' \
      | grep -i '^x-router'
    done

    # twelve prompts, all different -- the fleet
    for i in $(seq 1 12); do
      curl -s -D - -o /dev/null -X POST http://router.localhost:8080/v1/completions \
        -H 'content-type: application/json' \
        -d "{\"model\":\"Qwen/Qwen3-8B\",\"prompt\":\"unrelated question $i\",\"max_tokens\":2}" \
      | grep -i '^x-router-upstream'
    done | sort | uniq -c

Observed 2026-09-19, twice, over two different three-replica fleets: `prefix`
four times on one address both times, then 2 / 6 / 4 over the three in the
first run and 4 / 4 / 4 in the second. **Read the policy and the spread, not
the address, and not the split** — the Pod IPs differ between fleets, so they
land on a different ring. The property is that the first loop uses one address
and the second uses all three. One address out of the second loop is the
clustering defect of `../../router/README.md` §3 come back.

Release the pin with
`kubectl -n llm annotate scaledobject/vllm autoscaling.keda.sh/paused-replicas-`,
and run `upstreams.sh` again afterwards, for the reason §1 gives.

## 4. Two things this arrangement leaves behind

- **The restart window.** `upstreams.sh` updates an env-sourced ConfigMap,
  which a running Pod never re-reads, so it restarts the router. For a few
  seconds the old Pod is draining and still in the EndpointSlice: one request
  out of 24 was served by it, with the stale fleet, after the refill. Seen
  twice on 2026-09-19, and the second time the signature was unmistakable — a
  502 naming an upstream the ConfigMap no longer contained, followed by clean
  200s a few seconds later. A watch would have no such window, because nothing
  would restart.
- **One router Pod.** Each replica bounds load by its own in-flight count, so a
  second router would compute a fleet mean from half the traffic. Two is a
  second thing to reason about before the first has been measured at all.
