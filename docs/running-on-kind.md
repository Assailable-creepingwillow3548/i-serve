# Running it on kind

The evening route: the whole stack on a laptop, no accelerator, nothing to pay
for. One paragraph comes before the commands rather than after them, because a
reader who curls first and reads second draws the wrong conclusion.

**What comes up is not vLLM.** The container the `kind` overlay runs is a stub
carrying the engine's API and metric contract with no model behind it: it answers
`/v1/models` with `Qwen/Qwen3-8B` because the contract says that is what the
field holds, and it has never loaded a weight. That is the rule that split
`deploy/manifests/` into two layers. What `kind` does give you is the control
plane being right: the edge routing, the queue-depth autoscaler moving on a
threshold derived in [SLO.md](SLO.md) §4, the alert going pending and
then firing, and the dashboard lighting the panels a stub can fill. Which parts
are real and which are fixture: *What is real here* in the repository
[README](../README.md), and [audience.md](audience.md).

**Nothing is downloaded either, and that is also a decision rather than a side
effect.** The base carries a Job that fills a volume with the weights before any
server starts; the `kind` overlay deletes it
(`deploy/manifests/overlays/kind/patch-no-fetch.yaml`), because **16.4 GB** would
otherwise arrive on a laptop to satisfy a container that never reads a byte of
it. The PVC is kept, because volume binding and scheduling are real here. What
the cluster does pull is four ordinary container images and the two pinned
manifests named below.

## Prerequisites

`kind`, `kubectl`, `docker` and `curl` on `PATH`, and a Docker daemon actually
running — `up.sh` checks all four before it touches anything, because a missing
tool halfway through a bring-up is a partial cluster. Nothing else installs:
there is no Go toolchain here even for the router, which builds inside its own
image, and no `kustomize` binary, which `kubectl` has carried since v1.14.

**A reachable network is the fifth prerequisite, and the preflight does not
check it.** The node image, ingress-nginx at `controller-v1.15.1` and KEDA at
`v2.20.2` are all fetched when they are applied, not vendored, so a blocked
GitHub fails on the second or third command with the cluster already created —
the same partial bring-up the preflight exists to prevent, arriving by the one
door it does not watch.

Versions this was last brought up with, 2026-09-11:

| | Version |
|---|---|
| kind | v0.32.0 |
| node image | `kindest/node:v1.36.1`, pinned in `deploy/kind/cluster.yaml` |
| kubectl | v1.36.3, kustomize v5.8.1 |
| Docker | 24.0.2 |
| KEDA | v2.20.2, pinned in the command below |

**There is no `requirements.txt`, and its absence is a feature rather than an
omission.** `bench/` imports nothing outside the standard library — every
import checked against the interpreter's own list of standard modules — and
needs Python 3.10 or newer. The floor used to be a
reading of the grammar and the modules used; since 2026-09-11 it is a run, on
both ends: [`.github/workflows/bench.yml`](../.github/workflows/bench.yml) executes
the test files on 3.10 and on 3.14 at every push, and installs nothing before it
does — a `pip install` that ever became necessary is what that workflow fails
on. The only thing that wants installing is `pytest`, and only because it is a
nicer runner than the one each test file carries for a rented pod. The Pages
site is the one place a second language appears: its JavaScript is a port of
`bench/roofline.py`, held equal to the Python by a golden grid the Python writes
and `node` — already on the runner, nothing installed — re-checks in the same
workflow.

## Bringing it up

```bash
./up.sh          # brings it up
./down.sh        # deletes the cluster and everything on it
```

`up.sh` is a wrapper, not a replacement for what follows: it runs the eleven
commands below, in this order, and differs in three ways. It adds a preflight, so
a missing `kind`, `kubectl`, `docker` or `curl` fails on the first line with a
sentence instead of halfway through a bring-up. It passes an explicit
`--context`, so an `apply` cannot land on whatever cluster `kubectl` was pointing
at. And it **skips** the first command when a cluster of that name already
exists, so a half-finished bring-up can be resumed — which also means a stale
cluster built from an older `deploy/kind/cluster.yaml` is reused rather than
rebuilt; `./down.sh` first if that is a risk. If the last step never serves, it
reports the status code and what that code means rather than exiting on `curl`'s
number alone.

The commands are kept here because **the waits between them are the content**,
and a script that hides them teaches nothing. This is the one place the full
order is written down; the READMEs under `deploy/` cover their own component and
point back here.

```bash
kind create cluster --config deploy/kind/cluster.yaml

kubectl apply -k deploy/ingress/overlays/kind
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller

kubectl apply --server-side -f \
  https://github.com/kedacore/keda/releases/download/v2.20.2/keda-2.20.2.yaml
kubectl -n keda rollout status deployment/keda-operator

kubectl apply -k deploy/observability/prometheus
kubectl apply -k deploy/observability/grafana
kubectl apply -k deploy/manifests/overlays/kind
kubectl apply -k deploy/keda/overlays/kind

kubectl -n llm rollout status deployment/vllm
curl -sS --fail --retry 5 --retry-delay 1 localhost:8080/v1/models
```

**The two `rollout status` lines are load-bearing, and they are load-bearing for
different reasons** — both prerequisites install an admission webhook, and the
two webhooks disagree about what to do when they are not yet serving.

ingress-nginx sets `failurePolicy: Fail`, so the Ingress in the manifests overlay
is rejected outright. Measured by removing the wait:

```text
Error from server (InternalError): failed calling webhook
"validate.nginx.ingress.kubernetes.io": ... connect: connection refused
```

Note what the same apply did before that line: namespace, ConfigMap, Service, PVC
and Deployment were all created. The result is not a failed bring-up but a
**partial** one — a stack that looks up and has no edge, until something curls it.

KEDA sets `failurePolicy: Ignore` on all six of its webhooks, so nothing is
rejected; the ScaledObject is admitted **unvalidated**. That is the quieter
failure of the two, and it is not hypothetical: KEDA's webhook is what rejects a
`pollingInterval` above a zero floor as irrelevant (`deploy/keda/README.md`), and
inside this window that rejection simply does not happen. The wait buys
validation, not admission.

**So is `--retry` on the last line.** `rollout status` returns when the
Deployment's pod is ready, which is not when the edge routes to it: the controller
keeps its own endpoint set, updated by a watch, and there is a gap between the two
spent answering **503**. Measured twice, because it is not a fixed number — ~544
ms re-applying the overlay onto a running cluster, and around 2–3 s on a
cold bring-up where the controller is also still settling. One or two
`curl: (22) ... 503` lines before the JSON are that window, not a fault; `--fail`
is there so the retries print those instead of six HTML error pages.

The status code names which side is behind, and is worth reading rather than
retrying blindly: **503** is a route with no live endpoint, **404** is no route at
all, and an **empty reply** (curl exit 52) is no controller on the mapped node
(`deploy/ingress/README.md`).

## Pushing load at it

The stub serves a real FIFO queue and streams SSE, so it can be saturated — and
saturating it is how the autoscaler and the queue alert were watched. The
documented way is a shell loop:

```bash
for i in $(seq 24); do
  curl -sN -o /dev/null -X POST localhost:8080/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"Qwen/Qwen3-8B","prompt":"x","max_tokens":12000,"stream":true}' &
done
```

What that produced, second by second, and the pictures of the moment the rule
fires: [`deploy/observability/README.md`](../deploy/observability/README.md).

**`bench/harness.py` will not do this, and the reason is worth knowing before you
try.** It counts a generated token by the arrival of a non-empty text field, and
the stub leaves that field empty on purpose. Run it against the stub and it stops
on its own warm-up request:

```text
RuntimeError: smoke-c2-h50: warmup request failed (stream ended before any
token); a cold prefix would make every h below meaningless
```

Forced past that with `--no-warmup` it sends the requests and reports `0/4`, with
every figure `nan`. Each half is right on its own and the seam between them is
invisible from either side, because the stub was validated against the platform
and the harness against a card, never against each other. The harness is for a
card. The loop above is for `kind`.

## Looking at it rather than curling it

```bash
kubectl -n monitoring port-forward svc/grafana 3000:3000
open http://localhost:3000/d/vllm-slo
```

One dashboard, no login. On `kind` most of it says *No data*, and that is the
stub keeping the promise made above, not a fault — which panels light here and
which wait for a card is the table in `deploy/observability/README.md`, and the
dashboard's own top panel carries the same contract. The reading order — and why
on `kind` it runs row 3 first rather than top to bottom — is
[runbook.md](runbook.md), "Morning triage".

## The router, which is not part of the bring-up

`up.sh` leaves the edge balancing `round_robin` over the stub Pods, and that is
the whole stack. The prefix router is a separate, optional four commands on top
— `deploy/router/README.md` §3 has them and this file does not repeat them —
and it is separate on purpose: the router is a compiled binary, so bringing it
up needs a Docker build and a `kind load`, and making those a prerequisite of
the stack would cost every reader a build for a component most of them are not
here for.

What it adds when it is up is one more host on the same edge,
`router.localhost`, in front of the same Pods. The default route is untouched,
which is the point: two doors, one fleet, and the only difference is the policy.
