# i-serve

A slice of an LLM inference operator's platform — Qwen3-8B on Kubernetes —
answering the three questions an operator has, in the order they arrive:
[**1. Speed**: are we inside SLO](#1-speed-are-we-inside-slo),
[**2. Cost**: what does a million tokens cost](#2-cost-what-does-a-million-tokens-cost), and
[**3. Trouble**: what happens on a traffic spike](#3-trouble-what-happens-on-a-traffic-spike).

**[Open the page →](https://alexgitspace.github.io/i-serve/)** All three, draggable, in a browser with
nothing installed. The rest of this file is the stack behind them.

![Measured divided by predicted, for every prediction L40S runs 1-3 made](docs/benchmarks/predicted-vs-measured.svg)

One row per prediction that named a two-sided value — a range is drawn at its
midpoint and a one-sided bound is left out, so this is a selection of the three
§9 tables rather than all of them. The counts, the misses and the hollow marks
are on the picture and are not repeated here; what a drawing cannot show is what
a miss cost. Run 3's seat count under prefix caching came out **56 % low**
against the predicted range, 64 % against its midpoint, and rewriting
[docs/SLO.md](docs/SLO.md) §6 is the bill. Row by row, with the coefficient each
one used: §9 of every report in [docs/benchmarks/](docs/benchmarks/).

## 1. Speed: are we inside SLO?

**Measured: the interactive class fits an L40S at 12 seats with a cold cache and
32 at an 80 % prefix-cache hit rate**, TPOT p99 ≤ 50 ms, 4 000-token prompts
([docs/benchmarks/](docs/benchmarks/)). The floor behind it says 31 seats before
arriving prompts are priced in, and names which limit set them — *time*, the
decode step growing with every seat, or *room*, the KV pool running out.

The SLO is yours to set, and nothing here chooses it for you; what this
repository refuses is letting you pick it by feel. Both presets are *derived*
([docs/SLO.md §2](docs/SLO.md#2-targets)), and they are two obligations rather
than two numbers: interactive is a latency promise, batch a throughput-and-deadline
commitment whose per-token threshold is only a stall guard
([§1](docs/SLO.md#1-workload-classes)).

- **On the page**, step 1: the seats the hardware allows, the seats a service can
  safely promise, the first-word wait, and runs 1 and 3 drawn only where your
  sliders sit inside their geometry.
- **In docs**: the floors in [§4](docs/SLO.md#4-floors), the ceiling in
  [§6](docs/SLO.md#6-concurrency-ceiling). Before a card, the same arithmetic in a
  terminal:

      python3 bench/predictions.py --what-if --tpot-ms 50 --ttft-ms 300 --accelerator l40s-run1

  The line to watch is `max_num_seqs` — the seats a target permits, and which
  limit set them.

**The honest limit.** On a card the question is row 1 of the `vllm-slo` dashboard,
read in the order [docs/runbook.md](docs/runbook.md) *Morning triage* gives. On
`kind` that row is *No data* by construction: the stub exports no histogram, so
nothing there can say whether an SLO was met.

## 2. Cost: what does a million tokens cost?

**$0.39 per 1M output tokens that met the SLO** — L40S at $0.99/h, Qwen3-8B BF16,
4 000-token prompts at an 80 % prefix-cache hit rate, 32 seats, TPOT p99 ≤ 50 ms.
With no cache hits the same card and the same gate hold 12 seats instead of 32,
and the figure is **$1.18**.

The denominator is the whole argument: pushed past the goodput peak, run 2's cost
per output token *fell* 35 % while its cost per token that met the target *rose*
15×, so the figure above counts only tokens a customer could use. All three
denominators, and what is still not priced: [docs/SLO.md §7](docs/SLO.md).

- **On the page**, step 2: the price at your promise, the hardware floor beside it,
  and the one move that changes the figure most — more cache hits while they are
  below 80 %, the other card once they are not — with the price of the promise
  drawn as a curve over the target.
- **In docs**: [§7](docs/SLO.md) for the formula and its three denominators;
  [docs/benchmarks/](docs/benchmarks/) for the runs the coefficients came from.

**The honest limit.** Every figure is a floor scaled by coefficients measured on
one card. On the MI300X they are a prior until a run.

## 3. Trouble: what happens on a traffic spike?

This is the one of the three `kind` can demonstrate. The stub serves a real FIFO
queue and streams SSE, so it can be saturated: twenty-four streamed completions
opened in the same second against sixteen seats take one replica to four and the
queue alert to pending and then firing, and both unwind once the clients are
killed — second by second in `deploy/observability/README.md`, the loop itself
under *Pushing load at it* below.

![The dashboard mid-breach, with QueueBeyondTTFTBudget firing](deploy/observability/breach-alert-firing.jpg)

From the alert the runbook hands off to
[docs/symptom-map.md](docs/symptom-map.md): seven symptoms, each with the number
to read first, the branches it splits into and the traps that make a right number
read wrong, every node carrying its evidence and its home.

- **On the page**, step 3: the map as four questions about your dashboard — are
  people queuing up, is every seat taken, is the first word late, are the words
  slow — each with *don't know* as a real answer and each judged against the
  floors of your own operating point. Back comes one symptom's branch, the number
  to read next and the knobs it points at; *let me type them* runs the same rules
  over readings typed by hand.
- **In docs**: [docs/runbook.md](docs/runbook.md) for the alert to the map,
  [docs/symptom-map.md](docs/symptom-map.md) for the 64 nodes.

**The honest limit.** Nothing here shortens the control loop — scrape, KEDA poll,
HPA window and a 69 s cold start are minutes, and a burst shorter than that is
answered only by seats that already exist ([docs/SLO.md §4](docs/SLO.md#4-floors)).
And nothing here reads a metric: on `kind` the stub exports the two queue gauges
and no histogram, so two of the four questions have nothing there but *don't know*.

## Pick a route

| You have | Start at | What you get |
|---|---|---|
| **Thirty seconds**, a browser | [the page](https://alexgitspace.github.io/i-serve/) | your situation as one sentence you edit, and the three questions above as three steps under it: how fast each word may appear and how many people that seats, what a million tokens then costs, and where to look when it slows down — it reads no metric, so it can price your SLO and cannot tell you whether you are meeting it |
| **Five minutes**, nothing installed | the command under *Five minutes* below | the performance model's answer for two different cards, in one command |
| **An evening**, a laptop | `./up.sh` | the whole stack on `kind` — edge, queue-depth autoscaler, Prometheus, Grafana — against a stub, no accelerator |
| **Deeper** | [docs/SLO.md](docs/SLO.md), then [docs/benchmarks/](docs/benchmarks/) | every number, how it was derived, and the seven predictions run 3 got wrong |

The page is those three questions made draggable, in plain words. Your
situation is **one sentence** at the top — the model, the card and its hourly
rate, the prompt and answer lengths, and how much of each prompt the cache
already holds — and every value in it opens the control that changes it. The
card carries the same **measured**/**prior** badge the command under *Five
minutes* prints, and the second model is marked *predicted only*: it is priced,
never served and never measured here
([docs/audience.md](docs/audience.md#changing-the-model)). Under the sentence,
three steps, each answering in three numbers: *Speed* gives the seats the
hardware allows, the seats a service can safely promise, and the first-word
wait; *Cost* gives the price per million tokens that kept the promise, the
hardware floor beside it, and the one move that changes the figure most; *Trouble*
is the symptom map as four questions about your dashboard. KV dtype,
`gpu_memory_utilization` and the first-token target sit behind *More
assumptions*. The whole operating point lives in the URL hash, so a point you
reached is a link you can send, and *Keep this to compare* holds one while you
move to another. Dotted words explain themselves on hover, each one registered in
[docs/GLOSSARY.md](docs/GLOSSARY.md) by a test. There is no build step and no
server to run: `open site/index.html` works from `file://` with its fonts
vendored under `site/fonts/`, and `site/README.md` is the rest.

## What is real here

Three kinds of number live in this repository, and they are never mixed:

- **measured** — produced by a run on a rented card, raw evidence committed under
  [docs/benchmarks/raw/](docs/benchmarks/raw/). Three L40S runs so far; two
  coefficients fitted on run 1 and survived runs 2 and 3.
- **derived** — the floors, the concurrency ceiling and the cost formula in
  [docs/SLO.md](docs/SLO.md). Every one is a prediction until measured, and
  vLLM's own startup log outranks all of them ([§9](docs/SLO.md)).
- **prior** — spec-sheet coefficients for a card no run has faced. The MI300X is
  one: its runsheet is written and reviewed, the run not yet made.

The Kubernetes half — edge, queue-depth autoscaler, per-pod metrics, alerts,
dashboard — comes up on `kind` against a stub that carries vLLM's API and metric
contract and serves no model. It shows what the system *does*, never what the
numbers *are*, and no number produced on `kind` appears anywhere in
[docs/benchmarks/](docs/benchmarks/). The newest parts, the symptom map and the
page, have been walked against three runs and one `kind` breach and never yet
against a reader. Who this is for, what is real on `kind` and what is fixture,
and the four limits this repository owes you: [docs/audience.md](docs/audience.md).

## Five minutes: ask the model, install nothing

No cluster, no card, no dependencies — `bench/` is standard library only,
Python 3.10+.

    python3 bench/harness.py --dry-run --scenario seats-cached --accelerator l40s-run1
    python3 bench/harness.py --dry-run --scenario seats-cached --accelerator mi300x

Same workload, two cards. The prefill floor per level moves from **70.0 ms** to
**18.9 ms**, and the second line of the header is the one to read first:

    accelerator: NVIDIA L40S (run 1 coefficients)
    coefficients: eff_mem 0.83, mfu 0.439 -- measured (run 1, 2026-08-18); survived runs 2-3

    accelerator: AMD Instinct MI300X
    coefficients: eff_mem 0.7, mfu 0.45 -- prior, unvalidated; no run on this card

One of those floors is built on coefficients a rented card produced and two later
runs failed to break; the other is built on spec-sheet assumptions and is a
prediction waiting to be embarrassed. The repository will not let you mistake one
for the other — that distinction is what [docs/SLO.md §9](docs/SLO.md) is about,
and changing `--accelerator` is the cheapest way to see it. The third header line
names the SLO the plan is judged against, and `--slo-tpot-ms` moves the last
column.

## Model

The default is **`Qwen/Qwen3-8B`** (Apache 2.0), chosen so that `git clone` and
one command work for anyone — no account, no token, no approval step. Swapping it
is not a string substitution: three strings name the model and six numbers are
derived from it. The checklist, the gated-weights alternative and what it costs
whoever runs the stack: [docs/audience.md](docs/audience.md#changing-the-model).

## Running it on kind

The evening route: the whole stack on a laptop, no accelerator, nothing to pay
for. One paragraph comes before the commands rather than after them, because a
reader who curls first and reads second draws the wrong conclusion.

**What comes up is not vLLM.** The container the `kind` overlay runs is a stub
carrying the engine's API and metric contract with no model behind it: it answers
`/v1/models` with `Qwen/Qwen3-8B` because the contract says that is what the
field holds, and it has never loaded a weight. That is the rule that split
`deploy/manifests/` into two layers. What `kind` does give you is the control
plane being right: the edge routing, the queue-depth autoscaler moving on a
threshold derived in [docs/SLO.md](docs/SLO.md) §4, the alert going pending and
then firing, and the dashboard lighting the panels a stub can fill. Which parts
are real and which are fixture: *What is real here* above, and
[docs/audience.md](docs/audience.md).

### Prerequisites

`kind`, `kubectl`, `docker` and `curl` on `PATH`, and a Docker daemon actually
running — `up.sh` checks all four before it touches anything, because a missing
tool halfway through a bring-up is a partial cluster. Versions this was last
brought up with, 2026-09-11:

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
both ends: [`.github/workflows/bench.yml`](.github/workflows/bench.yml) executes
the test files on 3.10 and on 3.14 at every push, and installs nothing before it
does — a `pip install` that ever became necessary is what that workflow fails
on. The only thing that wants installing is `pytest`, and only because it is a
nicer runner than the one each test file carries for a rented pod. The Pages
site is the one place a second language appears: its JavaScript is a port of
`bench/roofline.py`, held equal to the Python by a golden grid the Python writes
and `node` — already on the runner, nothing installed — re-checks in the same
workflow.

### Bringing it up

    ./up.sh          # brings it up
    ./down.sh        # deletes the cluster and everything on it

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

**The two `rollout status` lines are load-bearing, and they are load-bearing for
different reasons** — both prerequisites install an admission webhook, and the
two webhooks disagree about what to do when they are not yet serving.

ingress-nginx sets `failurePolicy: Fail`, so the Ingress in the manifests overlay
is rejected outright. Measured by removing the wait:

    Error from server (InternalError): failed calling webhook
    "validate.nginx.ingress.kubernetes.io": ... connect: connection refused

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

### Pushing load at it

The stub serves a real FIFO queue and streams SSE, so it can be saturated — and
saturating it is how the autoscaler and the queue alert were watched. The
documented way is a shell loop:

    for i in $(seq 24); do
      curl -sN -o /dev/null -X POST localhost:8080/v1/completions \
        -H 'Content-Type: application/json' \
        -d '{"model":"Qwen/Qwen3-8B","prompt":"x","max_tokens":12000,"stream":true}' &
    done

What that produced, second by second, is in `deploy/observability/README.md`;
the picture of the moment the rule fires is under *What happens on a traffic
spike* above.

**`bench/harness.py` will not do this, and the reason is worth knowing before you
try.** It counts a generated token by the arrival of a non-empty text field, and
the stub leaves that field empty on purpose. Run it against the stub and it stops
on its own warm-up request:

    RuntimeError: smoke-c2-h50: warmup request failed (stream ended before any
    token); a cold prefix would make every h below meaningless

Forced past that with `--no-warmup` it sends the requests and reports `0/4`, with
every figure `nan`. Each half is right on its own and the seam between them is
invisible from either side, because the stub was validated against the platform
and the harness against a card, never against each other. The harness is for a
card. The loop above is for `kind`.

### Looking at it rather than curling it

    kubectl -n monitoring port-forward svc/grafana 3000:3000
    open http://localhost:3000/d/vllm-slo

One dashboard, no login. On `kind` most of it says *No data*, and that is the
stub keeping the promise made above, not a fault — which panels light here and
which wait for a card is the table in `deploy/observability/README.md`, and the
dashboard's own top panel carries the same contract. The reading order — and why
on `kind` it runs row 3 first rather than top to bottom — is
[docs/runbook.md](docs/runbook.md), "Morning triage".

## Contributing

The unit of contribution is one run: a runsheet with its predictions written
before, raw results after, two fitted coefficients, and one row per prediction in
a §9 table. Why runs are what accumulate here, and the checklist:
[docs/adding-a-run.md](docs/adding-a-run.md). Ground rules:
[CONTRIBUTING.md](CONTRIBUTING.md). Another model is out of scope, and
[docs/audience.md](docs/audience.md#changing-the-model) says why.

## Layout

**Not a route** — the routes are at the top of this file, and the reading orders
are in [docs/audience.md](docs/audience.md). This is the map: one row per
component of the stack, with what it is and how far it actually got. `docs/`
explains the stack, the rest implements it.

| Path | What | State |
|---|---|---|
| `up.sh`, `down.sh` | The eleven commands of *Running it on kind* as one entry point, with a preflight | brings the stack up on `kind` and tears it down; runs no command the section below does not list, and skips cluster creation when one already exists |
| `CONTRIBUTING.md` | What a contribution is here, what it is not, and how to send one | written 2026-09-13 |
| `docs/SLO.md` | Service level objectives, floors, concurrency ceiling, and how each was derived | ✅ |
| `docs/GLOSSARY.md` | Vocabulary and notation used across the repo | ✅ |
| `docs/model-anatomy.md` | The served model at five zoom levels: where the bytes counted in `SLO.md` come from | ✅ |
| `docs/accelerator-landscape.md` | The accelerator market: which term of the decode equation each vendor attacks, and what it trades away | ✅ snapshot, dated 2026-08-23 |
| `docs/architecture.md` | Request path from ingress to GPU, and where each SLO is won or lost along it | ✅ drawn from the running objects; every timing in it taken on `kind`, none on a GPU |
| `docs/runbook.md` | Canary rollout, SLO-breach tree, morning triage, OOM | canary rollout and roll-back run once on `kind`; morning triage written 2026-09-07; the SLO-breach tree continues into `docs/symptom-map.md`; the OOM procedure not written |
| `docs/symptom-map.md`, `docs/symptom-map.json` | The operator's decision tree — seven symptoms, the number to read first, the branches, the traps — and the checked subset the site's advisor evaluates as rules | 64 nodes, each with its evidence and its home; the JSON's 37 nodes held equal to the markdown by a test |
| `docs/adding-a-run.md` | Why runs are what accumulate here, and the checklist for adding one — or a card | written 2026-09-13; the MI300X run is its first user |
| `docs/benchmarks/` | Load test reports, cost-per-1M-tokens figures, and the predicted-vs-measured chart on the front page | runs 1–3 (L40S) written up, raw evidence committed |
| `docs/benchmarks/runsheets/` | The sheet written **before** each run: its commands, its predicted numbers, its stop conditions and its budget | five sheets for runs 1–3, never revised against the results they predicted; one written and reviewed for a MI300X run not yet made |
| `docs/instrument-vllm-bench-sweep.md` | What `vllm bench sweep` does at `v0.27.1`, and where it belongs in a run | verified off-card against the source of that tag and the CPU image |
| `bench/` | Load harness, workload scenarios, `roofline.py` performance model, the generator for that chart, and the export the site is built from; tests in `bench/tests/`, runnable with `pytest` or directly, since a rented pod has neither | performance model complete and calibrated; harness ran run 3 on a card and invalidated three levels on its own gates; `--what-if --hit-rate --json` and a dry run that reads the SLO flags since 2026-09-13 |
| `site/` | The calculator and the advisor as one static page for GitHub Pages — one situation and three steps, one per question at the top of this file: `bench/roofline.py` ported to JavaScript and held equal to it by a golden grid, two pictures, `docs/symptom-map.json` walked as rules over four dashboard questions, the operating point kept in the URL hash so it can be sent as a link, and three OFL fonts vendored so `file://` looks like Pages | works from `file://`, `python3 -m http.server` and Pages; parity 211/211 rows; deployed by `.github/workflows/pages.yml` once the repository's Pages source is set to Actions |
| `.github/workflows/` | CI: the test files on Python 3.10 and 3.14, the quick-start commands, a redraw of the front-page chart, a regeneration of `site/data/` and the JavaScript parity check; a Pages deploy that refuses a page whose arithmetic disagrees with Python | installs nothing, which is the claim it exists to test |
| `.githooks/` | A pre-commit hook that redraws the chart, regenerates `site/data/` and stages both, so neither can lag the data it is drawn from | opt-in per clone: `git config core.hooksPath .githooks` |
| `deploy/kind/` | Local CPU-only cluster for logic debugging | control plane + two workers, reproducible from `cluster.yaml` |
| `deploy/manifests/` | vLLM as Deployment, Service and Ingress; a `kind` overlay swaps the container for a stub | base is the GPU artefact; the stub serves a real FIFO queue, streamed SSE and `/metrics`; a canary overlay splits `/v1` by weight at the edge |
| `deploy/ingress/` | ingress-nginx overlay: the edge in front of the Service | route live on `kind`; edge timeout derived from `--max-model-len` x TPOT and measured |
| `deploy/helm/vllm/` | vLLM chart (OpenAI-compatible API) | empty |
| `deploy/keda/` | Queue-depth autoscaling on `vllm:num_requests_waiting` | ScaledObject written, threshold derived, loop watched scaling 1→4→1 on `kind`; reads the stable track only after scaling on a canary's queue |
| `deploy/observability/` | Prometheus rules, Grafana dashboards as code | Prometheus scrapes vLLM per pod; two alerting rules on the TTFT objective, the queue one watched firing on `kind`; one provisioned Grafana dashboard, read top-to-bottom as the triage order — its `kind`-visible panels watched during the same breach, the histogram panels dark until a card |
| `deploy/terraform/` | GPU node provisioning | one MI300X droplet on the AMD Developer Cloud, with a first-boot image pull; validated, never applied — the plan and image slugs are read from the API on the run morning |
| `controllers/modelwarmup/` | Go operator: warm a model before it joins routing | architecture note only, and it argues against the code |
