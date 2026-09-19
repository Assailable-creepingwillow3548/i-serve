# i-serve

A slice of an LLM inference operator's platform — Qwen3-8B on Kubernetes. It
answers the three questions an operator has, in the order they arrive:
[**1. Speed**](#1-speed--how-fast-should-each-word-appear),
[**2. Cost**](#2-cost--what-does-a-million-tokens-cost-at-that-speed),
[**3. Trouble**](#3-trouble--it-got-slow-where-do-you-look-first).

[![The page: describe your situation in one sentence, and it works out the trade between speed, seats and money — shot 2026-09-16](docs/page.jpg)](https://alexgitspace.github.io/i-serve/)

**[Open the page →](https://alexgitspace.github.io/i-serve/)** All three,
draggable, in a browser with nothing installed. The rest of this file is the
stack behind them.

## 1. Speed — how fast should each word appear?

People reading a chat notice anything slower than about 50 ms per word. At that
promise an L40S seats **12 people with a cold cache and 32 when 80 % of each
prompt repeats** — measured, TPOT p99 ≤ 50 ms, 4 000-token prompts
([docs/benchmarks/](docs/benchmarks/)).

The arithmetic behind it says 31 seats before arriving prompts are priced in, and
names which limit set them: *time*, the decode step growing with every seat, or
*room*, the KV pool running out.

The target is yours to set. What this repository refuses is letting you pick it
by feel — both presets are derived ([docs/SLO.md §2](docs/SLO.md#2-targets)), and
they are two different obligations, not two numbers
([§1](docs/SLO.md#1-workload-classes)).

- **On the page**, step 1 gives the seats the hardware allows, the seats you can
  safely promise, and the first-word wait.
- **In docs**: the floors in [§4](docs/SLO.md#4-floors), the ceiling in
  [§6](docs/SLO.md#6-concurrency-ceiling). Before a card, the same arithmetic in
  a terminal:

```bash
python3 bench/predictions.py --what-if --tpot-ms 50 --ttft-ms 300 --accelerator l40s-run1
```

**The honest limit.** On `kind` nothing here can tell you whether you are meeting
a target: the stub exports no histogram, so row 1 of the dashboard is *No data*
by construction.

## 2. Cost — what does a million tokens cost at that speed?

**$0.39 per 1M output tokens that met the SLO** — L40S at $0.99/h, Qwen3-8B
BF16, 4 000-token prompts, 80 % hit rate, 32 seats, TPOT p99 ≤ 50 ms. With no
cache hits the same card and the same gate hold 12 seats instead of 32, and the
figure is **$1.18**.

The denominator is the whole argument. Pushed past the goodput peak, run 2's cost
per output token *fell* 35 % while its cost per token that met the target *rose*
15× — so the figure above counts only tokens a customer could use. All three
denominators, and what is still not priced:
[docs/SLO.md §7](docs/SLO.md).

- **On the page**, step 2 gives the price at your promise, the hardware floor
  beside it, and the one move that changes the figure most.
- **In docs**: [§7](docs/SLO.md) for the formula;
  [docs/benchmarks/](docs/benchmarks/) for the runs the coefficients came from.

**The honest limit.** Every figure is a floor scaled by coefficients measured on
one card. On the MI300X they are a prior until a run.

## 3. Trouble — it got slow. Where do you look first?

This is the one of the three `kind` can demonstrate. The stub serves a real FIFO
queue and streams SSE, so it can be saturated: twenty-four streamed completions
opened in the same second against sixteen seats take one replica to four and the
queue alert to pending and then firing, and both unwind once the clients are
killed.

![Queue per replica during the breach: one pod at 20 waiting, three new pods at 0, the alert threshold at 1, and the shaded band the alert firing](deploy/observability/breach-queue-per-replica.jpg)

From the alert the runbook hands off to
[docs/symptom-map.md](docs/symptom-map.md): seven symptoms, each with the number
to read first, the branches it splits into, and the traps that make a right
number read wrong.

- **On the page**, step 3 asks four questions about your dashboard, each with
  *don't know* as a real answer, and hands back one symptom's branch and the
  knobs it points at.
- **In docs**: [docs/runbook.md](docs/runbook.md) for the alert to the map,
  [docs/symptom-map.md](docs/symptom-map.md) for the 69 nodes.

**The honest limit.** Nothing here shortens the control loop — scrape, KEDA poll,
HPA window and a 69 s cold start are minutes, and a burst shorter than that is
answered only by seats that already exist
([docs/SLO.md §4](docs/SLO.md#4-floors)). And nothing here reads a metric: on
`kind` two of the page's four questions have nothing but *don't know*.

## The proof

![Measured divided by predicted, for every prediction L40S runs 1-3 made](docs/benchmarks/predicted-vs-measured.svg)

One row per prediction that named a two-sided value. What a drawing cannot show
is what a miss cost. Run 3's seat count under prefix caching came out **56 %
higher** than the §6 row predicts, and 64 % above the midpoint of the 22–24 range
the runsheet named; rewriting [docs/SLO.md](docs/SLO.md) §6 is the bill.

Row by row, with the coefficient each used: §9 of every report in
[docs/benchmarks/](docs/benchmarks/).

## Pick a route

| You have | Start at | What you get |
|---|---|---|
| **Thirty seconds** | [the page](https://alexgitspace.github.io/i-serve/) | your situation as one sentence you edit, and the three questions above as three steps under it |
| **Five minutes** | *Five minutes*, below | the performance model's answer for two cards, in one command |
| **An evening** | `./up.sh` | the whole stack on `kind`, against a stub, no accelerator |
| **Deeper** | [docs/SLO.md](docs/SLO.md) | every number and how it was derived |

Each route in full, and who this is for: [docs/audience.md](docs/audience.md).

## What is real here

Three kinds of number live here, and they are never mixed:

- **measured** — produced by a run on a rented card, raw evidence under
  [docs/benchmarks/raw/](docs/benchmarks/raw/). Three L40S runs so far; two
  coefficients fitted on run 1 and survived runs 2 and 3.
- **derived** — the floors, the ceiling and the cost formula in
  [docs/SLO.md](docs/SLO.md). Every one is a prediction until measured, and
  vLLM's own startup log outranks all of them ([§9](docs/SLO.md)).
- **prior** — spec-sheet coefficients for a card no run has faced. The MI300X is
  one: its runsheet is written and reviewed, the run not yet made.

The Kubernetes half comes up on `kind` against a stub that carries vLLM's API and
metric contract and serves no model. It shows what the system *does*, never what
the numbers *are*, and no number produced on `kind` appears in
[docs/benchmarks/](docs/benchmarks/). What is real on `kind` and what is fixture:
[docs/audience.md](docs/audience.md).

## Five minutes: ask the model, install nothing

No cluster, no card, no dependencies — `bench/` is standard library only,
Python 3.10+.

```bash
python3 bench/harness.py --dry-run --scenario seats-cached --accelerator l40s-run1
python3 bench/harness.py --dry-run --scenario seats-cached --accelerator mi300x
```

Same workload, two cards. The prefill floor per level moves from **70.0 ms** to
**18.9 ms**, and the second line of the header is the one to read first:

```text
accelerator: NVIDIA L40S (run 1 coefficients)
coefficients: eff_mem 0.83, mfu 0.439 -- measured (run 1, 2026-08-18); survived runs 2-3

accelerator: AMD Instinct MI300X
coefficients: eff_mem 0.7, mfu 0.45 -- prior, unvalidated; no run on this card
```

One floor is built on coefficients a rented card produced and two later runs
failed to break; the other on spec-sheet assumptions, and it is a prediction
waiting to be embarrassed. Changing `--accelerator` is the cheapest way to see
the difference that [docs/SLO.md §9](docs/SLO.md) is about.

## An evening: the whole stack on kind

```bash
./up.sh          # brings it up
./down.sh        # deletes the cluster and everything on it
```

The eleven commands `up.sh` wraps, the two waits that are load-bearing for
different reasons, and why what comes up is not vLLM:
[docs/running-on-kind.md](docs/running-on-kind.md).

## Model

The default is **`Qwen/Qwen3-8B`** (Apache 2.0), chosen so that `git clone` and
one command work for anyone — no account, no token, no approval step. Swapping it
is not a string substitution: three strings name the model and six numbers are
derived from it. The checklist and the gated-weights alternative:
[docs/audience.md](docs/audience.md#changing-the-model).

## Contributing

The unit of contribution is one run: a runsheet with its predictions written
before, raw results after, two fitted coefficients, and one row per prediction in
a §9 table. Why runs are what accumulate here, and the checklist:
[docs/adding-a-run.md](docs/adding-a-run.md). Ground rules:
[CONTRIBUTING.md](CONTRIBUTING.md). Another model is out of scope, and
[docs/audience.md](docs/audience.md#changing-the-model) says why.

## Layout

**Not a route** — the routes are above. This is the map: one row per component,
with what it is and how far it got.

| Path | What | State |
|---|---|---|
| `up.sh`, `down.sh` | The eleven commands of [docs/running-on-kind.md](docs/running-on-kind.md) as one entry point | brings the stack up and tears it down |
| `docs/SLO.md` | Targets, floors, concurrency ceiling, and how each was derived | ✅ |
| `docs/GLOSSARY.md` | Vocabulary and notation | ✅ |
| `docs/model-anatomy.md` | The served model at five zoom levels | ✅ |
| `docs/accelerator-landscape.md` | Which term of the decode equation each vendor attacks | ✅ snapshot, dated 2026-08-23 |
| `docs/architecture.md` | Request path from ingress to GPU | ✅ drawn from the running objects |
| `docs/runbook.md` | Canary rollout, SLO-breach tree, morning triage, OOM | canary run once on `kind`; the OOM procedure not written |
| `docs/symptom-map.md`, `.json` | The operator's decision tree, and the checked subset the site evaluates | 69 nodes; the JSON's 37 nodes held equal by a test |
| `docs/running-on-kind.md` | The eleven commands, the two load-bearing waits, the stub contract | ✅ |
| `docs/adding-a-run.md` | Why runs are what accumulate here, and the checklist | the MI300X run is its first user |
| `docs/benchmarks/` | Load test reports, cost figures, and the chart above | runs 1–3 written up, raw evidence committed |
| `docs/benchmarks/runsheets/` | The sheet written **before** each run | five sheets for runs 1–3; one for a MI300X run not yet made |
| `docs/instrument-vllm-bench-sweep.md` | What `vllm bench sweep` does at `v0.27.1` | verified off-card against that tag |
| `bench/` | Load harness, `roofline.py`, the chart generator, the site export; tests in `bench/tests/` | model calibrated; the harness ran run 3 on a card |
| `site/` | The calculator and the advisor as one static page for Pages | live; parity 211/211 rows |
| `.github/workflows/` | Tests on Python 3.10 and 3.14, the quick-start commands, the chart, the parity check | installs nothing, which is the claim it tests |
| `.githooks/` | A pre-commit hook that regenerates the chart and `site/data/`, and three refusals — a status glyph on the map, non-English content, a credential in any file | opt-in: `git config core.hooksPath .githooks`; CI runs the three on a branch no hook saw |
| `deploy/kind/` | Local CPU-only cluster for logic debugging | control plane + two workers |
| `deploy/manifests/` | vLLM as Deployment, Service and Ingress; a `kind` overlay swaps in a stub | base is the GPU artefact; a canary overlay splits `/v1` by weight |
| `deploy/ingress/` | ingress-nginx overlay: the edge in front of the Service | route live on `kind`; edge timeout derived and measured |
| `deploy/helm/vllm/` | vLLM chart | empty |
| `deploy/keda/` | Queue-depth autoscaling on `vllm:num_requests_waiting` | watched scaling 1→4→1 on `kind` |
| `deploy/observability/` | Prometheus rules, Grafana dashboards as code | queue alert watched firing; histogram panels dark until a card |
| `deploy/router/` | The router on `kind`: manifests, the fleet-filling script, and what the flag costs | routing watched over three replicas; the staleness priced |
| `deploy/terraform/` | GPU node provisioning | one MI300X droplet; validated, never applied |
| `router/` | Go: a prefix-aware router, choosing the replica that already holds the prompt | binary and tests; on `kind` it serves a second host in front of the stub Pods |
| `controllers/modelwarmup/` | Go operator: warm a model before it joins routing | architecture note only, and it argues against the code |
