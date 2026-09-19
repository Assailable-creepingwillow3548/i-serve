# Runsheet — MI300X run 3: the router arm, and what a fleet costs on one card

`router/` routes on cache locality and has been watched doing it on `kind`, and
not one number from that day says the seat count moves: the routing property and
the seat effect are different measurements, and the second one needs a card and a
prediction written before it (`router/README.md` §8). **This sheet is that
prediction.** It asks one question — *what does sending a request to the replica
that already holds its prefix buy, and what does having two replicas cost in the
first place?* — and it asks it in the regime where the answer is not obviously
"nothing": a card where capacity binds.

**Status: written 2026-09-19, before any card exists and before run 1 has been
taken. Not reviewed** — `docs/adding-a-run.md` §1 says a sheet is reviewed and
committed before renting, and neither has happened for this one.

**Runs are numbered per card**, so "run 3" is this one and the L40S's third run
is named with its card wherever both appear below. **There is no
`mi300x-run-2.md`**: run 2 is the FP8 KV run, named as a destination by run 1's
sheet and never written. If the credit window closes with only two runs in it,
this one is taken second and keeps its number — a gap in the numbering is
cheaper than a sheet whose name stops matching the run that faced it.

**Run order: after MI300X run 1, and independent of run 2.** Run 1 fits
`eff_mem` and `mfu` on this card and reads the prefill interference; this sheet
spends both. It does not depend on run 2's FP8 KV, and either order works —
§6 of `docs/SLO.md` shows FP8 cancels out of the ratio this run is about.

**Every predicted figure below comes from `bench/predictions.py` table 11**,
added 2026-09-19; re-run it if the module has changed since. Where this sheet
disagrees with a measured number, `docs/benchmarks/` wins.

**The instrument is `bench/harness.py`**, not `vllm bench sweep`: a controlled
prefix cache hit rate is the one thing the sweep cannot be asked for
(`bench/predictions.py`, module docstring), and `h` is this run's dependent
variable. Prefix caching is **on** in both arms, which run 3 measured to be free
when it buys nothing (+0.027 % on the decode step, `docs/SLO.md` §6).

**Cost, flagged up front.** AMD Developer Cloud, 1 × MI300X at **$1.99/h**
assumed (the console price at droplet creation wins and is written here when
read). Expected clock **≈ 2 h**, session budget **≤ 3 h ≈ $6**, hard stop. The
credits expire **2026-10-18** and the window is shared with runs 1 and 2, so
this run is third in the queue and first to be cut if the window closes.

---

## What this run is not

- **Not a routing-correctness run.** Which replica a prompt lands on, how evenly
  the ring spreads, what a stale fleet costs: measured on `kind` on 2026-09-19,
  `deploy/router/README.md`. Nothing here re-measures it.
- **Not the replica question.** Two engines *on one card* is not two cards. What
  it can and cannot settle is §3.
- **Not a second model, and not FP8.** One model, BF16, `docs/adding-a-run.md`
  §7 and run 2 respectively.

## What earlier work established, and which of it transfers

| From | Status here |
|---|---|
| Run 3 (L40S): `h` = 0.8 is worth 12.5 → 37.8 seats | One prefix shared by **every** request — the ceiling of what `h` is worth. This run prices a *distribution* of prefixes, which is the open item `docs/SLO.md` §10 holds, and the first thing that can make `h` fall below its nominal value |
| Run 3: the `h` = 0 overhead of prefix caching is +0.027 % | Transfers as a decision, not a number: both arms serve with the cache on, so the arms differ in the routing policy alone |
| `kind`, 2026-09-19: the router routes, and a stale fleet costs 29 % of requests | Routing behaviour only. It says nothing about TTFT or seats, which is why this sheet exists (`router/README.md` §8) |
| MI300X `eff_mem`, `mfu`, and the prefill interference | **Run 1's**, fitted on the card this run uses. Quote them with the run that produced them, never the L40S's (`docs/SLO.md` §9) |
| §6: which limit binds is a property of the card | The MI300X is capacity-bound by 8 %, and a second engine does not change that (asserted in `bench/tests/test_roofline.py`). It is the reason this run is on this card: on the L40S the seats a fleet frees are idle capacity already |

---

## 0 · Before the card (no credits spent)

Writing this sheet found three defects that would each have let the run spend
credits and measure nothing **without erroring**. They are prerequisites, not
risks, and the first one was verified rather than argued. **All four boxes below
were closed on 2026-09-19**, in the commit that follows this one — the sheet is
left showing what it found, because a runsheet that quietly matches the code it
fixed cannot be judged.

- [x] **The router cannot read the prompts the harness sends.** `bench/loadgen.py`
      sends `"prompt": [151, 2934, …]` — an array of token ids — and
      `router/key.go`'s `writeStringOrArray` unmarshals a string or an array of
      *strings*, so the body parses, no key is built, and every request takes the
      `no-prompt` fallback to `round_robin`. Both arms would be the control.
      Verified 2026-09-19 against `cacheKey` itself, not by reading it. The fix
      is to teach the key the number-array shape, with a test: for this harness
      token ids are the *better* key, since the BPE boundary approximation of
      `router/README.md` §2 disappears when the ids are what is hashed.
      **Done**: `writeStringOrArray` reads `[]json.Number`, three tests in
      `router/key_test.go`.
- [x] **A gate that makes the above impossible to miss again.** The harness
      records `X-Router-Policy` per request, and a level is invalid unless every
      response on the prefix arm carries `prefix` and every response on the
      control carries `round_robin` — the shape `check_hit_rate` already has.
      **Done**: `--expect-policy`, which invalidates the level rather than
      warning it, and `Record.policy` carrying the header into the
      per-request artefacts.
- [x] **There is no control arm yet.** `round_robin` is a fallback in this
      router, not a policy that can be asked for (`router/README.md` §1), and a
      control that reaches the engines by a different door differs in hops
      rather than in policy. Add `-policy prefix|round_robin`. **Done**, and
      the control still reads the body and computes the key before discarding
      it, so the arms differ in the decision and not in the work.
- [x] **Metrics through the router are one replica's, picked by the fallback.**
      `bench/harness.py` scrapes `/metrics` at the same `host:port` it loads,
      which behind the router is an unkeyed path and therefore a round-robin
      choice. Add a repeatable `--metrics-endpoint`, scraped directly from each
      engine and summed, so `hit_rate()` reads the fleet and not a sample of it.
      **Done**: `--metrics-endpoint`, `scrape_fleet()` and `delta_fleet()`,
      which sum the counters before taking the ratio — an average of two
      engines' ratios would give an idle engine an equal vote.
- [ ] Three scenarios in `bench/scenarios/`: `router-arm`, five levels at
      `num_prefixes` 32 / 64 / 128 / 256 / 512, `prompt_tokens` 4 000,
      `prefix_tokens` 3 200, `concurrency` 64, `num_prompts` = 4 × N and never
      below 256; and `fleet-bill` / `fleet-bill-half`, one level each of unique
      prompts at concurrency 64 and 32 for block A.
- [ ] `python3 bench/predictions.py` — table 11 open beside the terminal.
- [ ] Run 1 taken, its `mi300x-run1` entry in `ACCELERATORS` and its fit in
      `INTERFERENCE_FITS`. Without them §5's seat line stays *not derivable*, and
      that is a correct answer rather than a missing one.
- [ ] `bench/harness.py --dry-run --scenario router-arm --accelerator mi300x`
      exits 0 off-card.
- [ ] The router image built **on the droplet** (`docker build -t
      prefix-router:dev router`): a Mac builds arm64 and the droplet is amd64.
- [ ] Read the hourly price off the console and write it into the header above.

---

## 1 · Droplet up, and the single engine first (~25 min, mostly download)

Same droplet as run 1 — one card, not eight; destroy, never stop; everything
under `/workspace` and copied off before the destroy (`mi300x-run-1.md` §1). The
container is the same image with the same device flags, plus `--network host` so
the router can reach the engines, and the repository's `bench/` and `router/`
copied in by `scp`.

```
docker run -it --rm --name run3 --network host \
  --device /dev/kfd --device /dev/dri --group-add video \
  --cap-add SYS_PTRACE --security-opt seccomp=unconfined --ipc host \
  -v /workspace:/workspace -v /workspace/hf:/root/.cache/huggingface \
  --entrypoint bash vllm/vllm-openai-rocm:v0.27.1
```

**The single engine runs first**, because block A's control has to be measured
and not derived:

```
vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --dtype auto \
  --gpu-memory-utilization 0.90 --max-model-len 9000 \
  --max-num-batched-tokens 2048 2>&1 | tee /workspace/run3/engine-solo.log
```

No `--enable-prefix-caching`: it is the V1 default, and the log line is the
proof rather than the flag.

---

## 2 · Checkpoint A — three startup logs against the arithmetic

Read the solo log now and the pair's two logs after §3 relaunches; the gates are
the same and the comparison between them is the whole of block A's first row.

```
grep -E 'GPU KV cache size|Maximum concurrency|prefix_caching|max_num_batched_tokens|block_size|backend|dtype|non-torch|activation' \
  /workspace/run3/engine-*.log
```

| Log line | Predicted | Source | On a miss |
|---|---|---|---|
| `GPU KV cache size`, solo at 0.90 | **1 060 655** tokens derived, **~986 000** with the 7 % shortfall | table 11 | Either figure within 3 % is a pass and the other is the finding — run 1's argument for 3 % over §9's 5 % applies unchanged. Run 1 read this same line and it outranks both |
| `GPU KV cache size`, each engine of the pair at 0.45 | **474 718** derived, **~441 000** corrected | table 11 | Same rule |
| The pair's two pools summed | **949 436** against the solo engine's own figure | table 11 | The difference, **111 219 tokens**, *is* the second copy of the weights. A sum that does not show it means the flag was not obeyed and §3 has nothing to measure |
| `prefix_caching` | **True** everywhere | V1 default | If false, relaunch: every level in §4 asks for a hit rate |
| `max_num_batched_tokens` | **2 048** everywhere | the launch line | A different value moves the interference and makes run 1's fit inapplicable |
| attention backend, `block_size`, dtype | whatever run 1 recorded | run 1 | Not gates, except the backend: one that differs from run 1's invalidates the borrowed fit, and that is a stop rather than a note |

---

## 3 · Block A — the fleet's bill (~15 min)

The one block that needs no router: the same load against **one** engine at
`0.90` and against **two** at `0.45` each, unique prompts, `h` = 0.

```
# against the solo engine
python3 bench/harness.py --scenario fleet-bill --accelerator mi300x \
  --host 127.0.0.1 --port 8000 --startup-log /workspace/run3/engine-solo.log \
  --out /workspace/run3/results/solo
```

Then stop it and bring the pair up **serially — the second only once the first
has logged its KV pool**:

```
vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --dtype auto \
  --gpu-memory-utilization 0.45 --max-model-len 9000 \
  --max-num-batched-tokens 2048 2>&1 | tee /workspace/run3/engine-8000.log &
# wait for "GPU KV cache size" in that log, then the same at --port 8001
```

The ordering is load-bearing, and checkpoint A is what tests it: vLLM sizes its
pool from the memory it finds free at start-up, so two engines racing each other
through that measurement is a way to get two pools that do not add up to the
card. Read both logs rather than assuming the flag was obeyed. Then the same
level against the pair, half its concurrency to each engine:

```
python3 bench/harness.py --scenario fleet-bill-half --accelerator mi300x \
  --port 8000 --startup-log /workspace/run3/engine-8000.log \
  --out /workspace/run3/results/pair-8000 &
python3 bench/harness.py --scenario fleet-bill-half --accelerator mi300x \
  --port 8001 --startup-log /workspace/run3/engine-8001.log \
  --out /workspace/run3/results/pair-8001 &
```

Predicted (table 11), against the uncalibrated 0.70 until run 1 replaces it:

| Quantity | One engine | Two engines | Difference |
|---|---|---|---|
| KV pool, tokens | 1 060 655 | 949 436 | **−111 219 (−10.5 %)** |
| Seats at a 4 200-token seat, capacity | 252 | 226 | **−26** |
| Seats at 50 ms, latency, 4 000 tokens | 286 | 258 | **−28** |
| Decode step at 64 seats fleet-wide | 14.60 ms | 19.02 ms | **+4.42 ms (+30 %)** |

One sentence holds all four rows: **both limits have the form
`(X − weights) / (context × kv_per_token)`, so a second copy of the weights costs
the same seats in each, and a second weights read costs the step
`weights / (bandwidth × eff_mem)`.**

**What this cannot settle.** Two engines on one card time-slice that card, so the
measured rise in the decode step is the duplicated read **plus** whatever running
two processes on one accelerator costs. A rise larger than 4.42 ms is therefore
not evidence against the arithmetic, and this run cannot split the two. The open
item as originally posed — replicas duplicating the weights read — is about two
*cards* and stays open (`mi300x-run-1.md`, *Not in this run*). What this block
does settle is what a single-card fleet actually pays, which is the arrangement
§4 routes over.

---

## 4 · Block B — the hit rate each policy can hold (~50 min)

Five working sets × two policies, at 64 seats across the fleet, 32 per engine,
prompts of 4 000 tokens behind a shared prefix of 3 200 — the construction that
measured `h` = 0.800 on every cached level of run 3.

The model, from table 11: a replica retains about **96** prefixes after the
shortfall and the live sequences. Under `round_robin` a replica sees all N
prefixes; under affinity it sees N/R. So the same pool holds twice the working
set, and what that is worth depends on where N falls:

| Prefixes N | Retained, rr / prefix | `h` rr | `h` prefix | Seats recovered |
|---|---|---|---|---|
| 32 | 32 / 16 | 0.800 | 0.800 | 24.4 |
| 64 | 64 / 32 | 0.800 | 0.800 | 48.8 |
| 128 | 96 / 64 | 0.600 | 0.800 | 48.7 |
| 256 | 96 / 96 | 0.300 | 0.600 | 0.0 |
| 512 | 96 / 96 | 0.150 | 0.300 | 0.0 |

The router goes in front of the pair, and the arm is the flag on it:

```
docker build -t prefix-router:dev router      # on the droplet: it is amd64
docker run -d --name router --network host prefix-router:dev \
  -listen :8080 -upstreams http://127.0.0.1:8000,http://127.0.0.1:8001 \
  -policy prefix -dial-timeout 250ms
```

```
python3 bench/harness.py --scenario router-arm --accelerator mi300x \
  --port 8080 --expect-policy prefix \
  --metrics-endpoint 127.0.0.1:8000 --metrics-endpoint 127.0.0.1:8001 \
  --startup-log /workspace/run3/engine-8000.log \
  --out /workspace/run3/results/prefix
```

Then `docker rm -f router`, relaunch it with `-policy round_robin`, and send the
same scenario with `--expect-policy round_robin` to `--out …/round-robin`. The load goes to `:8080` both times and
the counters are read from the engines directly — which is the point of
`--metrics-endpoint`, since `/metrics` through the router is an unkeyed path and
therefore one replica chosen by the fallback.

**Two regimes, and locating the boundary is the point.** While both policies
retain everything, affinity's saving is *space* — it buys seats, at 0.76 each
per prefix, and it has to clear block A's 26-seat bill before the arrangement is
worth anything at all: **below N ≈ 35, two engines on one card are a loss no
routing policy recovers.** Once `round_robin` is evicting, both policies hold the
same 96 prefixes, there is no space left to differ over, and the whole difference
moves into `h`.

**The order the prefixes are asked for is a decision, and it is made here.** The
`h` columns above assume any prefix is as likely to be asked for next as any
other. The harness draws them in strict rotation, which is LRU's worst case: a
prefix comes round again only after every other one has evicted it, so the hit
rate does not fall to a share, it falls to **zero** — `round_robin` past N = 96
and affinity past N = 192. Both cliffs assume vLLM evicts least-recently-used
blocks, which this repository has *not* read at the pinned tag
(`vllm/v1/core/block_pool.py`): it is the one input to this block that is
neither measured nor derived, and reading it costs nothing and no credits. That is the grid this run sends, unchanged, and it
means the measured spread between the arms is the **friendliest case for the
router**, not a general figure. Real traffic is neither: it is Zipf-shaped, and
sits between the two models. Both predictions are written down; the run faces the
rotation one.

**Alternate the arm order across the working sets** — prefix first at 32, 128 and
512, `round_robin` first at 64 and 256. Each level warms its own prefixes, but
the arm that runs second starts against a cache the first arm shaped, and
alternating is what keeps that bias from lining up with the policy.

**Read per level:** measured `h` summed over both engines; the
`X-Router-Policy` counts; the split of requests between the two engines. If one
engine takes more than 60 % of a level, bounded loads engaged — affinity was
traded for balance, by design (`router/README.md` §4), and `h` is not the only
thing that moved.

**Stop condition.** If the prefix arm at N = 32 does not measure `h` ≈ 0.8, stop
and fix the instrument: at that working set everything is retained under either
policy and the number is not about the card.

---

## 5 · Block C — what the hit rate buys (no extra card time)

Read off block B's levels; nothing new is sent.

**TTFT.** Prefix caching removes prefill work outright, so the prefill component
of TTFT falls by `(1 − h)` — the one knob that moves TTFT and TPOT the same way
(`docs/SLO.md` §6). At 4 000 tokens the MI300X prefill floor is **94.5 ms**
(table 10), so the predicted difference between the arms is `94.5 × (h_prefix −
h_rr)` ms per request: **28.4 ms** at N = 256 under the uniform model, **75.6 ms**
at N = 128 under the rotation the run actually sends. Compared arm against arm at
the same load, never against the floor: queueing sits on top of it and is the
larger term (`docs/SLO.md` §4).

**Seats: not derivable on this card until run 1 says otherwise.**
`INTERFERENCE_FITS` has no MI300X entry on purpose — lending the L40S's line to a
different memory system and a different attention backend would print a seat
count with no run behind any part of it. Once run 1 has fitted it:

```
python3 bench/predictions.py --what-if --accelerator mi300x-run1 --hit-rate <measured h>
```

once per arm, and the difference between the two is the seat effect of the
routing policy. Those numbers belong in the report, never back into this sheet.

---

## 6 · Budget, drop order, and what "done" means

| | |
|---|---|
| Expected clock | ≈ 2 h — 25 min up, 15 min block A, 50 min block B, the rest harvest and destroy |
| Hard stop | **3 h ≈ $6** of the credit balance |
| Drop order | N = 512 first (it only halves an already-broken hit rate), then N = 32 (it predicts no difference), then N = 64. **Never N = 128 or 256** — those two are what separate the two order models |
| Done | both logged pools read against table 11; block A's four rows faced; the arm pair at N = 128 and N = 256 measured with `h` per engine and the policy header counted |
| Not done | anything where `X-Router-Policy` was not checked. A level without it is a level that may have run the control twice |

Everything lands in `docs/benchmarks/raw/mi300x-<date>/` with its README, read
once for a credential before staging, and the file count checked across
`git add` (`docs/adding-a-run.md` §2).

---

## 7 · Not in this run, and where each goes

- **The real replica question** — weights duplicated across two *cards*, not two
  processes. Needs the 8-card droplet at $15.92/h; its own decision.
- **The Pod watch, and the retry to a different replica** — both priced on
  `kind` on 2026-09-19 and deliberately not taken (`router/README.md` §8). This
  run pins its fleet, so neither is on the path.
- **`-key-bytes`** — 512 bytes is a guess with a shape. Fitting it needs prompts
  that share a prefix of *varying* length, which is a different scenario.
- **Zipf-distributed prefix popularity** — the model between this sheet's two,
  and the one real traffic sits at. A generator change, and worth its own arm
  once the two bounds are measured.
- **FP8 KV** — run 2. It halves `kv_per_token`, which divides both limits and
  cancels out of their ratio (`docs/SLO.md` §6), so it moves every number here
  and none of the conclusions.

---

## 8 · If it goes sideways

| Symptom | First move |
|---|---|
| Both arms measure the same `h` | The key defect is back. `X-Router-Policy` on any response says which of the five ran; `no-prompt` means the body shape, not the router |
| The second engine's pool is far below the first's | The launch race. Kill both, relaunch strictly serially, and re-read checkpoint A — every figure in §3 is against the pair, so one wrong pool invalidates the block |
| OOM at launch | `--gpu-memory-utilization 0.42` each, note it, and re-derive §2 and §3 at the new share before continuing; the seat figures are not comparable across shares |
| One engine takes almost everything | Bounded loads at 1.25, or a ring imbalance. Read the request split before the hit rate: a policy that concentrated the load is not the policy the table predicts |
| `h` on the prefix arm sits below nominal at every N | The warmup is not warm, or the counter window includes it. Run 3 hit exactly this and the fix was the per-level seed offset (`bench/scenarios/prefix_sweep.py`) |
| The router returns 502s | An engine died, and the fleet is a flag: nothing re-reads it. Check both engines before blaming the router (`deploy/router/README.md` §1) |
| The clock passes 2.5 h | Harvest what exists and destroy the droplet. A partial block B with its `h` values is a result; an over-run is a credit the window does not have |
