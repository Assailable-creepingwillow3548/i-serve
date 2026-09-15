# Runsheet — run 3: the seat count against a known prefix cache hit rate

Run 1 (2026-08-18) calibrated the card. Run 2 (2026-08-23) measured the service
and eliminated `max_num_batched_tokens` as the fix for the seat gap. This run
measures the one candidate `docs/SLO.md` §6 answered on paper and nothing else:
**prefix caching, priced in seats.** Three blocks, each aimed at one of the three
open items §10 opened on 2026-08-26.

Written before any card is rented, which is the point — a prediction is only a
prediction if it exists before the measurement. **No card was written**: the run
was driven live over SSH with every threshold already in `bench/harness.py`, and
the postscript records what a card would still have been for. Where this sheet
disagrees with a measured number, `docs/benchmarks/` wins (`docs/SLO.md` §9).

**Every predicted figure below comes from `bench/roofline.py` at `L40S_RUN1`** —
`eff_mem = 0.83`, `mfu = 0.439` — plus the prefill-interference fit in
`bench/predictions.py`. The coefficients have now faced one run they did not
produce (§9); the *interference model* has faced none, and this run is its first.

**What is new about this run's instrument.** Runs 1 and 2 drove `vllm bench
serve`. Run 3 drives `bench/harness.py`, written 2026-08-29, because a controlled
cache hit rate is not a flag that tool has. Every gate that run 2 wrote into prose
and read at 09:00 on a rented card is now code that fires on its own row. **This
sheet therefore carries predictions and configuration, and exactly one threshold**
(§3.4, the decode-step reproducibility read, which needs a cross-run reference the
harness does not hold). Every other threshold lives in `bench/harness.py` and
`bench/vllm_metrics.py`, which is where run 2's postscript said they belong.

**Cost.** Budget **2.5 h ≈ $2.48** at $0.99/h, hard stop, expected spend
$1.10–1.40. **No network volume** (§1). Run 1 spent $1.45, run 2 $1.44.

---

## What runs 1 and 2 established, and which of it is load-bearing here

Every figure measured, from `docs/benchmarks/`. Nothing below is re-derived.

| Fact | Value | Source |
|---|---|---|
| KV pool, logged | 168 985 · **169 833** · 176 994 · 169 833 tokens | run 1, run 2 ×3 |
| `eff_mem`, median-ITL fit, twelve levels | **0.83** ± 0.02, re-faced to 0.01 % at c = 13 | run 1, run 2 §9 |
| `mfu`, one uncontended prefill | **0.439** | run 1 |
| **Decode step, c = 13, ctx 4 100, MNBT 2 048** | **33.79 / 33.71 / 33.80 ms** | run 1, run 2 §6 |
| Decode step reproducibility, identical launches | **0.24 %** | run 2 §6 |
| TTFT p50 reproducibility, identical launches | **32 %** | run 2 §6 |
| Logged pool reproducibility, identical launches | **4.2 %** | run 2 §6 |
| Seat count, 4 000 tok, TPOT p99 ≤ 50 ms | **12** (MNBT 2 048), 14 (MNBT 512) | run 1, run 2 §4 |
| Seats the decode step alone permits, ctx 4 100 | **31** | run 1 |
| c = 13, MNBT 2 048, 4 000 tok: TTFT p50 / TPOT p50 / **TPOT p99** / med ITL / ITL p99 | 745.6 / 49.44 / **51.83** / 33.79 / 198.18 ms | run 2 §4 |
| Worst step = decode step + chunk compute at `mfu` | high by **5–10 %**, flat over 8× of chunk size | run 2 §4 |
| Goodput peak, 1 500 tok, Poisson | **1.87 req/s** at an offered 2.5; 0.90 at 3.0; 0.12 at 4.0 | run 2 §3 |
| TTFT p99 crosses 300 ms, 1 500 tok | between **0.5 and 1.0 req/s** | run 2 §3 |
| Capacity, 1 500 tok, three counters agreeing | **106 seats** | run 2 §3 |
| Server defaults observed | `block_size` 16, `max_num_seqs` 256, FlashAttention 2 (BF16 KV) | run 1, run 2 |

The one sentence run 3 exists to attack: **nineteen of the thirty-one seats the
hardware permits are lost to prefill work, and prefix caching is the only
candidate that removes that work rather than moving it.** §6 says the seat count
goes from 13/14 to **24 ± 2** at `h = 0.8`. That number has never met a card.

---

## 0 · The correction this sheet exists to make

`bench/scenarios/prefix_sweep.py` was written on 2026-08-29 with
`PROMPT_TOKENS = 1_500` for all three blocks, inherited from run 2's block A on
the argument that 1 500 is the only prompt length this card can serve inside the
interactive TTFT budget. **That argument is right for block B and wrong for
blocks A and C**, and the concurrency grid in the same file proves it: `SEATS =
(8, 12, 14, 16, 20, 22, 24, 26, 28)` is dense between 12 and 28 because that is
where 13/14 and 24 ± 2 sit — and those two numbers are §6's, derived at
**4 000**-token prompts.

At 1 500 tokens each request injects 131.2 ms of prefill instead of 349.8 ms, so
the interference term is 0.375× as large and both crossings move out of the grid:

| Prompt | Crossing at `h` = 0 | Crossing at `h` = 0.8 | Inside `SEATS`? |
|---|---|---|---|
| 4 000 tokens | **13.5** | **24.3** | both |
| 1 500 tokens | 31.3 | **61.1** | neither |

A cached sweep whose crossing is at 61 seats and whose top level is 28 returns
`seats: >= 28` — a true statement that answers nothing, on a card that costs a
dollar an hour. Three further reasons the seat blocks belong at 4 000 tokens:

1. **The interference model is used where it was fitted.** `I(n) = 1.640 n −
   6.36 ms` belongs to 4 000-token prompts at MNBT 2 048 (`bench/predictions.py`).
   At 4 000 tokens only `h` varies between the two sweeps; at 1 500 the run would
   test the model *and* an extrapolation of it, and a falsification would not say
   which failed.
2. **The control already exists.** c = 13, 4 000 tokens, MNBT 2 048 has been
   measured three times (33.79 / 33.71 / 33.80 ms). No closed-loop level at
   1 500 tokens has ever been run.
3. **The published prediction is at 4 000 tokens.** Scoring 24 ± 2 requires the
   geometry it was written for.

**Decision: blocks A and C at 4 000 tokens, block B at 1 500.** Block B's
question is goodput under arrivals, and its comparison is run 2's measured curve,
which is at 1 500 — the same reasoning, pointing the other way. `h = 0.8` of
4 000 is a 3 200-token prefix, 3 200 / 16 = 200 blocks exactly, so nominal `h` is
0.800 and not a rounded 0.798.

The edits this requires are listed in §7 and are owed **before** the card.

---

## 1 · Deploy, and the three things run 2 learned about it

Same structure as run 2 — **vLLM is not PID 1**; the pod sleeps and servers are
launched by hand — because run 3 needs two server configurations and the startup
log has to be a file on disk, not console scrollback.

```
{"entrypoint": ["bash", "-lc"], "cmd": ["sleep infinity"]}
```

Three deploy-time decisions that cannot be changed afterwards:

1. **Publish TCP 22.** Run 2's postscript item 8: the RunPod SSH proxy refuses a
   non-interactive command (`Your SSH client doesn't support PTY`), so `scp` and
   `tar` through a pipe both need the *direct* endpoint, which exists only if
   port 22 was published at creation. The key is `~/.ssh/id_ed25519_runpod`, not
   the `id_ed25519` the console prints. **Without this the run has no harvest
   path**, and the artefacts die with the pod.
2. **No network volume.** Run 2 kept one and it was deleted on 2026-08-26 with
   the phase's storage. Re-creating it costs $3.5/month to save ~10 min of the
   16.4 GB download *once*; run 3's second server launch reads the weights from
   the container's own HuggingFace cache, so the download is paid once either
   way. At $0.99/h those ten minutes are $0.17. **Download, do not rent.**
3. **No published HTTP port and therefore no API key.** The server binds
   `127.0.0.1`, the harness runs on the pod. Port 22 carries SSH only. Stated so
   it is a decision and not an omission: this is safe *because* nothing but SSH
   is exposed.

`nvidia-smi` between the two server launches is the gate on a relaunch landing
on a card that still holds the previous process's memory.

---

## 2 · Two server configurations, and why in this order

| | Config 1 | Config 2 |
|---|---|---|
| Flags | `--gpu-memory-utilization 0.90 --max-model-len 9000 --no-enable-prefix-caching` | the same, **without** `--no-enable-prefix-caching` |
| Log | `/workspace/run3/serve-cache-off.log` | `/workspace/run3/serve-cache-on.log` |
| Carries | checkpoint A″, block C's control | blocks A, B, and block C's treatment |

`max_num_batched_tokens` is left at the default 2 048 and `max_num_seqs` at 256 —
run 1's and run 2's geometry, unchanged, because this run varies `h` and nothing
else. **Prefix caching is ON by default in vLLM's V1 engine**, which is why runs 1
and 2 carried the negative flag and why config 2 carries no flag at all.

**Config 1 first**, for one reason that is worth the three minutes of relaunch:
block C's control and its treatment then differ in the *flag* and in nothing
else — same pod, same weights, same driver, same hour. Run 2 showed the logged
pool moves 4.2 % and TTFT p50 32 % between two launches of one identical
configuration; a cross-*run* comparison of prefix-caching overhead would be
comparing a 1 % effect against a 4 % instrument. Within one pod it is the decode
step, reproducible to 0.24 %, that carries the answer.

---

## 3 · Checkpoint A″ — the four things to learn before spending a level

Not a formality and not a gate typed by hand: three of the four are already code,
and this section says what to *read*, in what order, and what invalidates the run.

**1. The startup log parses at all.** `bench/vllm_metrics.py:read_startup_log`
returns only the keys whose regex matched, and `bench/harness.py` gates the pool
only `if "kv_cache_tokens" in facts`. **A wording change between vLLM versions
therefore disables a gate silently** — run 2 hit exactly this class of failure
twice (`VLLM_ATTENTION_BACKEND` accepted and ignored; `--help` no longer listing
flags). So the first command on the pod is:

```
python3 -c "import sys; sys.path.insert(0,'bench'); import vllm_metrics as v; \
            print(v.read_startup_log('/workspace/run3/serve-cache-off.log'))"
```

and the read is: **seven of the eight keys present, and `max_num_seqs` absent**.
That is not a prediction, it is the state as of 2026-08-30: writing the reporting
function (§7) immediately found that `max_num_seqs` appears in **no** harvested
startup log — run 2 reported it as "256 (default, untouched)" from its launch
command, which is a weaker claim than a log line and is now labelled as one.
Anything else missing is a code fix before the run continues, not a shrug;
`attention_backend` is the likeliest, since run 2 saw 0.27.1 print
`Using AttentionBackendEnum.X backend.` under `--attention-backend` while the
pattern expects `Using (\w+) attention`.

| Log line | Predicted | Why it matters |
|---|---|---|
| `GPU KV cache size` | **169 833 ± 5 %** | the ±5 % gate is code; run 2 measured 4.2 % of platform noise |
| `kv cache memory in use` | **23.34 GiB** | same fact, the other unit — and the one the ±5 % gate should prefer, being the figure the engine actually allocates |
| `enable_prefix_caching` | **False** on config 1, **True** on config 2 | a cached scenario against a caching-off server measures nothing, and the harness exits 2 on it |
| `kv_cache_dtype` | auto (BF16) | FP8 is not in this run; §8 |
| attention backend | **FlashAttention 2** | the cascade-attention question of §6 starts here |
| `max_num_batched_tokens` | 2 048 | run 1's and run 2's geometry; `max_num_seqs` is **not** a log fact on this build and is read from the launch command |

**2. Cascade attention, read rather than inferred.** `docs/SLO.md` §10 calls this
a startup-log question. It may not be answerable from the log at all — vLLM
decides the path per forward pass — in which case the answer comes from block A's
own detector (§5), which has far more power than any log line. Grep for
`cascade`, record what is there or that nothing is, and move on. **Do not spend
card time hunting for it.**

**3. The two facts about this build that no derivation can supply**, and the
smoke level that answers both in under a minute:

```
python3 bench/harness.py --scenario smoke --startup-log /workspace/run3/serve-cache-on.log
```

- **Does `/v1/completions` accept a list of token IDs as `prompt`?**
  `bench/loadgen.py` sends ints, deliberately, so a shared prefix is shared by
  construction rather than by hoping two strings tokenise alike. If this build
  rejects it, **the run's independent variable does not exist** and the whole
  sheet is void. This is the single highest-consequence unknown, it is free to
  test, and it is therefore first.
- **What does `vllm:prefix_cache_queries` count?** The smoke level is a
  128-token prefix over a 256-token prompt, so if the counter is in *tokens*
  the harness prints `h = 0.500`. A reading near 0.5 confirms the denominator; a
  reading of 0 or `--` with caching on means the counters mean something else and
  every `h` in this run is unscored.

**4. The reproducibility read**, on config 1 — block C's control level, which is
also run 1's and run 2's exact geometry:

```
python3 bench/harness.py --scenario overhead --out results/run3-c-control \
    --startup-log /workspace/run3/serve-cache-off.log --sample-gauges 1.0
```

Predicted median ITL **33.8 ms ± 10 %**, TPOT p99 **51.8 ms**, TTFT p50
somewhere in 700–1 100 ms (32 % spread; it decides nothing). A median ITL outside
±10 % stops the run and sends the operator back to the log — the fit would be
pod-specific, which is a finding, not a malfunction.

---

## 4 · Block A — the seat count against `h`

Two closed-loop sweeps on config 2 over the same nine concurrencies, 4 000-token
prompts, 200 output tokens, identical in one thing only: whether 3 200 of the
4 000 prompt tokens are shared.

```
python3 bench/harness.py --scenario seats-uncached --out results/run3-a-h00 \
    --startup-log /workspace/run3/serve-cache-on.log --sample-gauges 1.0
python3 bench/harness.py --scenario seats-cached   --out results/run3-a-h80 \
    --startup-log /workspace/run3/serve-cache-on.log --sample-gauges 1.0
```

### The model, and where its slope comes from

`docs/SLO.md` §6 scales the fitted interference by `(1 − h)`. That scaling is an
assertion about a *mechanism*, and it is worth stating why it is credible before
a card prices it. In steady state at `n` seats, the engine's timeline is decode
steps plus prefills, so a request's served step is

```
TPOT(n, h) = step(n) + n × prefill_compute(h) / output_tokens
step(n)    = (weights + n × ctx × kv_per_token) / (bandwidth × eff_mem)
           = 22.87 + 0.843 n   ms     (ctx 4 100, eff_mem 0.83)
```

The mechanistic slope is `349.8 ms / 200 tokens = 1.749 ms per seat`. The slope
run 1 *measured* is **1.640**. Two routes, 6 % apart, and the second route says
the interference term is prefill work per unit time — which is exactly the
quantity `h` removes. So `(1 − h)` is not a convenient factor; it is the same
arithmetic with less work in it.

**The scaling has one independent check already paid for.** Run 2's block A ran
1 500-token prompts, where the same rule predicts a slope 131.2/349.8 = 0.375×
smaller. Against its measured TPOT p50 minus median ITL:

| Implied `n` | 3.6 | 6.8 | 11.2 | 15.7 | 24.5 | 42.5 |
|---|---|---|---|---|---|---|
| Interference measured, ms | 1.23 | 2.19 | 4.46 | 7.27 | 10.16 | 17.35 |
| Model rescaled by prompt length, ms | −0.17 | 1.80 | 4.50 | 7.27 | 12.68 | 23.75 |

Within 0.4 ms up to `n ≈ 16`, then over-predicting — and it over-predicts from
exactly the rate at which run 2 showed the step model itself going 8 % low
(§3, past the goodput peak). The model is being used here at `n ≤ 28`, inside its
demonstrated range.

### Predictions, level by level

`med ITL` is the decode step and moves only with `n`; `TPOT p50` carries the
interference; TPOT p99 in a closed loop ran 2–5 % above p50 in run 2, so the
seat verdict sits one level below the p50 crossing.

| c | med ITL (both sweeps) | TPOT p50, `h` = 0 | TPOT p50, `h` = 0.8 | ITL p99, `h` = 0.8 |
|---|---|---|---|---|
| 8 | 29.61 | 36.37 | 30.97 | ~93 |
| 12 | 32.99 | 46.31 | 35.65 | ~96 |
| 14 | 34.67 | **51.27** | 37.99 | ~98 |
| 16 | 36.36 | 56.24 | 40.33 | ~99 |
| 20 | 39.73 | 66.17 | 45.02 | ~102 |
| 22 | 41.42 | 71.14 | 47.36 | ~104 |
| 24 | 43.10 | 76.10 | **49.70** | ~106 |
| 26 | 44.79 | 81.07 | 52.04 | ~107 |
| 28 | 46.47 | 86.03 | 54.39 | ~109 |

(ITL p99 uses run 2's calibrated bound — decode step plus the chunk's compute at
`mfu` 0.439, high by 5–10 %. At `h` = 0.8 the chunk is the 800 uncached tokens,
70.0 ms, against 178.0 ms uncached; run 2 measured ITL p99 198.18 ms at c = 13,
so this is a **halving of the worst step** as well as of the mean.)

**Stated predictions, in falsifiable form:**

1. **The harness prints `seats: between 12 and 14` for the uncached sweep and
   `seats: between 22 and 24` for the cached one.** That is §6's 13.5 → 24.3 as
   the instrument will actually report it, on TPOT p99 ≤ 50 ms.
2. **The decode step at equal `n` is identical between the two sweeps, to within
   1 %.** This is §6's channel 1 — a cache saves computing and writing KV, never
   reading it — and it is the run's sharpest single claim, because the quantity is
   reproducible to 0.24 %. See §5: it is also the cascade-attention detector.
3. **Measured `h` lands within 0.02 of 0.800 at every cached level**, and within
   0.05 or the harness invalidates the level. A drift *downward* across the sweep
   is the shared prefix being evicted as unique bodies churn the pool — a defect
   in the run, reportable, not a fact about the engine.
4. **TTFT p50 at c = 13–14 falls from run 2's 745.6 ms by roughly the cached
   share of its prefill component.** Weak by construction: TTFT p50 spans 32 %
   across identical launches, so only a fall of more than ~40 % says anything.
   Worth stating because the direction is what matters — prefix caching is the
   only knob in this repository that moves TTFT and TPOT the *same* way.
5. **No preemptions in either sweep.** Capacity at 4 200 tokens per seat is 40
   seats uncached; cached, the shared prefix is stored once and a seat costs
   1 000 tokens, so 167. The top level is 28. If `vllm:num_preemptions` moves,
   the pool is not being shared the way channel 2 says.

**What falsifies the whole §6 argument:** a cached seat count near 14. That would
mean the seats are not lost to prefill work at all, and the three candidates in
§6 are three answers to the wrong question.

### Stop conditions

- **Measured `h` = 0 on a cached level** → the server ignored the flag, or the
  prompts are not sharing. Read the log's `enable_prefix_caching`, do not sweep on.
- **TTFT p50 below 70 ms on a cached level** → the harness is measuring the cache
  and not the engine (whole prompts repeating, not a shared prefix). The gate is
  code and invalidates the level; the run stops rather than continuing.

---

## 5 · Cascade attention — the detector, and what it is worth

`docs/SLO.md` §6 names one unverified mechanism: vLLM's V1 engine has a path that
reads a prefix shared by the whole batch **once** per step instead of once per
sequence. If it engages, prefix caching also moves the *latency* limit and channel
1 of §6 is wrong.

Block A answers this for free, at nine concurrencies, with a margin no log line
could improve on. At `h` = 0.8 the two hypotheses predict different decode steps:

| c | med ITL if channel 1 holds | med ITL if cascade engages | fall |
|---|---|---|---|
| 8 | 29.61 | 25.01 | −15.6 % |
| 16 | 36.36 | 26.49 | −27.1 % |
| 24 | **43.10** | **27.97** | **−35.1 %** |
| 28 | 46.47 | 28.71 | −38.2 % |

Against an instrument that reproduces this quantity to 0.24 %. **The detector
cannot miss**, and it fires on the first cached level rather than at the end of
the sweep.

**If it fires**, the cached crossing moves from 24.3 to **54.1 seats** — outside
the grid, and the sweep would report `seats: >= 28` while every level sat inside
the SLO. The conditional response, decided now so it is not decided under time
pressure: extend the cached sweep with c = 32, 40, 48, 56 (`seats-cached-extended`,
§7) and drop block B's bridge levels to pay for it. Capacity at `h` = 0.8 is 167
seats, so the extension is physically available.

---

## 6 · Block B — goodput under arrivals, and block C — the cost of `h` = 0

### Block B: the same question a customer asks

1 500-token prompts, Poisson arrivals, `h` = 0.8 — run 2's block A geometry with
one thing changed, so its curve is the control:

| Offered rate | Operating `n`, `h` = 0.8 | Predicted step | Predicted TPOT p50 | Run 2 measured `n` at `h` = 0 |
|---|---|---|---|---|
| 2.5 | 14.9 | 27.76 | 29.11 | 24.5 |
| 3.0 | 19.0 | 29.11 | 30.96 | 42.5 |
| 4.0 | 29.0 | 32.40 | 35.48 | 100.0 |
| 5.0 | 42.4 | 36.81 | 41.54 | — |
| 6.0 | 61.3 | 43.03 | **50.09** | — |
| 7.0 | 90.0 | 52.48 | 63.07 | — |

**Predictions:**

1. **The goodput peak moves from 1.87 req/s to at least 3.5**, and the collapse
   from 3.0 to beyond 5.0. Run 2's collapse was the pool: 106 seats at 1 600
   tokens, three counters agreeing. At `h` = 0.8 a seat costs 500 tokens and the
   prefix is stored once — **337 seats** — so the pool cannot be the collapse
   mechanism at any rate in this sweep, and the SLOs have to break first.
2. **TPOT p50 crosses 50 ms between 5 and 6 req/s**, against between 2.5 and 3.0
   uncached.
3. **TTFT p99 crosses 300 ms between 2.5 and 4.0 req/s.** Run 2's crossing was at
   0.5–1.0, and its diagnosis was single decode steps displaced by 131 ms prefill
   chunks even on an idle card (ITL p99 122–144 ms at *every* rate). The chunk is
   now 26 ms. The direction is certain, the level is not — this is the run's
   softest prediction and it is the one an operator would care about most.
4. **The generator's lateness stays under one arrival interval at 7 req/s.**
   `bench/loadgen.py` measures it; an open loop that falls behind has become a
   closed one, and then no TTFT in the level means anything.

**Two bridge levels at `h` = 0** (2.5 and 4.0 req/s) run on the same pod, because
run 2's curve was measured on a different pod with the feature off. They cost
~5 min and turn a cross-run comparison into a same-pod one. First in the drop
order all the same: run 2's curve is the published control.

### Block C: what the feature costs when it buys nothing

One level, `overhead-c13-h00` at 4 000 tokens, run **twice** — on config 1 and on
config 2 — differing in the flag alone. Both earlier runs disabled prefix caching,
so the repository has no figure for hashing and block bookkeeping against a
workload that never repeats.

**Prediction: the decode step moves by less than 1 %** — under 0.34 ms on a
33.8 ms step — because hashing is a per-block CPU cost on the prefill path and the
decode step is a memory-bandwidth quantity. **The measurable cost, if any, is in
TTFT**, where a 4 000-token prompt is 250 block hashes on the critical path; and
TTFT p50 spans 32 %, so a TTFT effect below ~30 % is unmeasurable here and will be
reported as such rather than as zero.

Recorded either way: with caching on and `h` = 0, finished requests' blocks stay
in the pool until something evicts them. This level alone writes 39 x 4 200 =
164 k tokens into a 169 k pool, and block A's uncached sweep writes 353 k at
c = 28 — so eviction is running throughout both, and that is the honest cost of
leaving the feature on for traffic that never repeats.

---

## 7 · The five edits to `bench/` — **done 2026-08-30**

None was a new capability; all five follow from §0 and §5. Kept here as the
record of what the card may assume, with what each one turned up.

1. **`bench/scenarios/prefix_sweep.py`: split the prompt length.** 4 000 tokens
   for `SEATS_*` and `OVERHEAD`, 1 500 for `GOODPUT_*`. One constant becomes two,
   named for what decides each — the seat blocks answer §6 at its own geometry,
   the goodput block answers run 2 at its.
2. **Extend the rate grid.** The cached curve needs 5.0, 6.0 and 7.0 or it never
   reaches its own crossing; 0.5 and 1.0 can go. Add `goodput-bridge`: `h` = 0 at
   2.5 and 4.0.
3. **Add `seats-cached-extended`** — c = 32, 40, 48, 56 at `h` = 0.8 — the
   conditional set for a cascade-attention hit (§5). Written before the run so it
   is not written on a rented card.
4. **`read_startup_log` must report what it did *not* find.** Returning only
   matched keys means a renamed log line disables a gate silently. `vllm_metrics.
   unread_startup_facts` now names the misses and `bench/harness.py` prints them
   before the first level. This is run 2's postscript item 3 as a code change
   instead of a habit — **and it paid for itself immediately**: seven of eight
   patterns match the real log and `max_num_seqs` matches nothing, which nobody
   had noticed because a missing key looks exactly like a satisfied gate (§3).
5. **Re-run `--dry-run` on all scenarios** after 1–3 and check the printed
   nominal `h` and floors against this sheet's tables. The dry run *is* the
   check that the sheet and the instrument agree; nothing else asserts it.
   Done: seven scenarios, prefix 3 200 of 4 000, nominal `h` 0.800 exactly,
   uncached floor 70.0 ms — the figures §4 predicts against.

Tests: 32/32 in `bench/tests/test_harness.py` (two added — the prompt-length invariant
per block, and the unread-facts report), 62/62 in `bench/tests/test_roofline.py`.

---

## 8 · Budget, drop order, and what "done" means

**Expected clock:** deploy and the 16.4 GB download 14 min · config 1 launch and
checkpoint A″ 6 min · block C control 1 min · config 2 launch and the smoke/`h`
verification 5 min · block C treatment 1 min · block A uncached 7 min · block A
cached 6 min · block B cached 16 min · bridge 5 min · harvest 8 min ≈ **69 min**.
Hard stop at 2.5 h.

**Drop order, decided now so it is not decided under time pressure:**

1. Block B's two bridge levels — run 2's published curve stands in.
2. Block B at 2.5 and 3.0 req/s — the interesting half of that curve is above 4.0.
3. Block A uncached at 20, 22, 26, 28 — past the crossing; **8, 16 and 24 stay**,
   because the cascade detector needs the same `n` in both sweeps.
4. Block A cached at 8 and 12 — far inside the SLO.

**Never dropped:** checkpoint A″ in full, including the token-ID and counter
verification · block C's control/treatment pair · block A cached at 22, 24, 26 ·
block A uncached at 12 and 14 · block B cached at 4.0 and 6.0 · the harvest.

**Done for run 3** — four sentences that can be written afterwards with a number
in each:

- the seat count at `h` = 0.8 against `h` = 0 **on one pod**, and whether §6's
  24 ± 2 survived contact with the card;
- whether the decode step moved at equal concurrency, and therefore whether
  cascade attention engages on sm89 — which decides if §6's channel 1 is right;
- what the goodput peak becomes at `h` = 0.8, against run 2's 1.87 req/s, and
  which SLO breaks first now that the pool cannot;
- what prefix caching costs when it buys nothing, in decode-step milliseconds
  against the identical level with the feature off on the same pod.

If all four land, weeks 2–3 close on **six knobs measured of six**, and
`docs/SLO.md` §6's prefix-caching section stops being the only derived-and-
unmeasured argument in the document.

---

## What run 3 still cannot answer

Written now so the write-up does not overclaim later.

- **One prefix, not a distribution.** `num_prefixes = 1`: every request shares the
  same 3 200 tokens. Real traffic has many prefixes of many lengths, and the pool
  then holds several and evicts between them. This run measures the *ceiling* of
  what `h` is worth, not what a fleet sees.
- **`h` is still an input.** Nothing here measures the hit rate of a real
  workload, which is the number §6 says an operator cannot derive. That needs
  production traffic, not a card.
- **FP8 KV and prefix caching together.** Both are measured; their interaction is
  not. FP8 halves the bytes a seat costs, caching removes prefill work, and the
  two attack different terms — which is an argument, not a measurement.
- **Replicas duplicating the weights read**, still open. Two replicas,
  which is the Kubernetes phase.
- **The TTFT-tail open item** (run 2 §3): the queueing model predicts the step
  well and the tail badly. Block B constrains it but does not explain it.
- **MI300X.** After three runs this is three cards' worth of L40S evidence and
  zero for AMD; `eff_mem` and `mfu` there remain 0.70 and 0.45, unvalidated.
- **Reasoning lengths.** `max_model_len` stays 9 000; `docs/SLO.md` §8 untouched.

---

## Postscript — written 2026-08-30, after the run

What the run taught about the instrument and the procedure, not about the card;
the card's answers are `docs/benchmarks/l40s-run3.md`. Numbered so the next
runsheet can cite them the way this one cited run 2's.

1. **Pin the driver at deploy, not the image.** The first pod carried driver
   570.124.06 (CUDA 12.8) and vLLM 0.27.1's torch refused to initialise:
   `The NVIDIA driver on your system is too old (found version 12080)`. Lowering
   the image would have turned every cross-run comparison into a comparison of two
   builds, so the pod was thrown away — fifteen minutes, no data. **Every future
   deploy step filters on CUDA ≥ 12.9 and reads `nvidia-smi` before the weights
   download starts**, which is the cheapest possible place to lose a pod.
2. **A JSON entrypoint override also removes `sshd`.** §1.1 published TCP 22 and
   that was necessary but not sufficient: replacing the image's entrypoint with
   `bash -lc "sleep infinity"` replaces the script that starts the SSH daemon, so
   the direct endpoint refuses connections and the harvest path does not exist.
   The RunPod proxy still works and is how it gets fixed —
   `apt-get install -y openssh-server`, write `$PUBLIC_KEY` into
   `~/.ssh/authorized_keys`, `/usr/sbin/sshd`. Two minutes, once known.
3. **`/workspace` is not necessarily a local disk.** With no network volume
   attached it came up as RunPod's network filesystem (`mfs#…runpod.net`).
   Weights went to the container's own overlay instead; results and logs stayed on
   `/workspace` and were `scp`'d off before Terminate. Neither choice affects a
   measurement, and both affect how long the run takes to start.
4. **A single seed across levels is a defect the moment the server has memory.**
   `Workload.seed` was one constant, so each level's prompts were a byte-identical
   prefix of the next level's — invisible for two runs with prefix caching off,
   and a total cache hit with it on: `h` = 0.664 / 0.854 / 0.872 on levels whose
   nominal `h` was zero. The harness caught it, the sweep was re-run at $0.12, and
   the general rule is worth more than the fix (`SEED + concurrency`): **on a
   server that retains state between levels, sweep order is part of the
   measurement unless every level's input is its own.**
5. **`unread_startup_facts` earned its place on the first pod.** §7 added it
   because `max_num_seqs` matched nothing; the run then found
   `max_num_batched_tokens` missing too — six keys of eight, where the sheet
   predicted seven. A gate that reads a key the build stopped emitting does not
   fire and does not complain. **Next runsheet: pass the geometry flags
   explicitly even when the default is wanted**, so `argv` carries what the log
   no longer does.
6. **Both conditional extensions were used, and both paid.** §5's cascade
   extension (c = 32…56) was written before the card and ran within a minute of
   the cached sweep reporting `seats: >= 28`. Block B then hit the same wall the
   sheet had not anticipated — `goodput: never breached an SLO` at the top of its
   grid — and the extension to 9/11/13 req/s was written on the spot for the same
   reason. **A sweep that reports its own top level answers nothing**, and the
   fix costs three minutes of card when it is decided in advance and ten when it
   is not.
7. **Redirect Python with `-u`.** Levels wrote nothing to the `.out` file until
   the sweep finished, because stdout is block-buffered when redirected. Harmless
   here — the harness writes per-level JSON as it goes — but it makes a running
   sweep look hung, and a run watched by two people is a run where somebody
   reaches for the kill.
8. **The card was never written, and the run did not need one.** Execution ran
   from the laptop over SSH with an assistant driving, while every threshold sat
   in `bench/harness.py` where run 2's postscript put it. The gate that mattered
   most — three levels invalidated for lying about their own `h` — was code, not
   a checklist item, and no human read a number and decided. **A future run needs
   a card only for what cannot be code: the deploy form, the two server launches,
   the drop order, and Terminate.**
