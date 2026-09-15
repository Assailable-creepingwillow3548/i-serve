# Runsheet — run 2: the scheduler, the arrival rate, and FP8 KV

Run 1 (2026-08-18) calibrated the card. It did not measure the service. This run
is scoped by that distinction and by nothing else: three blocks, each aimed at one
line of `docs/SLO.md` §10 that run 1 left open.

Written before any card is rented, which is the point — a prediction is only a
prediction if it exists before the measurement. Where this sheet and the card
(`docs/benchmarks/runsheets/l40s-run-2-card.md`) disagree, **this file wins**; the card is
execution only and carries no reasoning. Where either disagrees with a measured
number, `docs/benchmarks/` wins (`docs/SLO.md` §9).

**Every predicted figure below comes from `bench/roofline.py` at `L40S_RUN1`** —
`eff_mem = 0.83`, `mfu = 0.439`, the coefficients run 1 fitted. That is
deliberate: the whole value of this run is that those two numbers face a
measurement they did not produce.

**Cost.** Budget **2.5 h ≈ $2.50** at $0.99/h, hard stop, expected spend
$1.30–1.60. Plus a 25 GB network volume, ~$3.5/month, **kept after this run**
(justification in §1). Run 1 spent $1.45 of $2.50.

---

## What run 1 established, and which of it is load-bearing here

Every figure in this section is measured, from `docs/benchmarks/l40s-baseline.md`.
Nothing below is re-derived; run 2's predictions are built on top of it.

| Fact | Value |
|---|---|
| KV pool, logged | **168 985 tokens** (`kv cache memory in use` 23.23 GiB) |
| Capacity at 4 100 ctx | 41 seats — confirmed under load, `num_requests_running` max 41 |
| `eff_mem`, median-ITL fit, twelve levels | **0.83** ± 0.02 |
| `mfu`, one uncontended prefill | **0.439** |
| Pure decode step, c=13, ctx 4 100 | 33.80 ms measured / 33.83 ms predicted |
| TPOT p99 ≤ 50 ms holds until | **c ≈ 12** |
| Decode step crosses 50 ms at | c ≈ 31 |
| TPOT p50 ÷ median ITL | 1.00 / 1.10 / 1.28 / **1.44** / 1.53 / 1.72 / **1.91** / 2.06 at c = 1 / 4 / 8 / 13 / 16 / 23 / 32 / 45 |
| Peak throughput | 314.9 output tok/s at c=32 → **1.57 req/s** at 200 output tokens |
| Median TTFT, c=4 | 391.7 / 674.8 / 1 313.2 ms at 2 000 / 4 000 / 8 000 input |
| Server defaults observed | `max_num_batched_tokens` 2 048, `max_num_seqs` 256, `block_size` 16, FlashAttention 2 |

The one sentence run 2 exists to attack: **the calibrated model is right about
the hardware and wrong about the service by 2.6×, and the residual is a
scheduler.**

---

## Why these three blocks, and why in this order

`docs/SLO.md` §10 has six open items. Three are answerable on one rented card in
under an hour, and they happen to be the three that decide what an operator can
promise:

**A — a finite `--request-rate`.** Run 1 was a closed loop, so every TTFT after
the first wave contains the load generator's own backlog and none of them can be
compared to a 300 ms target. Until this is fixed, half of `docs/SLO.md` §2 is
untested. This block also produces the first **goodput** curve this repository
has, and therefore the first measured collapse point.

**B — `max_num_batched_tokens`.** The 2.6× gap is charged to this knob by
argument, not by measurement. Block B prices it, and — see below — is built so
that the *invariant* is what gets tested, not a number.

**C — FP8 KV.** What this phase owes is a report comparing
**two configurations**, BF16 KV against FP8 KV, and run 1 compared none. Without
this block the phase cannot meet its own Done criterion, whatever else the run
measures.

**The order is forced by what each block disturbs.** A runs on the default
configuration and needs no restart. B changes exactly one flag per restart. C may
silently change the *attention backend* (§5), which is why it goes last: nothing
measured before it can be contaminated by it.

---

## 1 · The structural change from run 1: vLLM is not PID 1

Run 1 launched vLLM as the container's start command. That was right for one
configuration and is wrong for five: the start command is fixed at deploy on
RunPod, so changing `max_num_batched_tokens` would mean a redeploy per level —
four redeploys, four weight loads, and the console log as the only place the
startup lines exist.

**Run 2 deploys the pod idle and launches vLLM by hand**, using the JSON start
command run 1 wrote down as a fallback and never needed:

```
{"entrypoint": ["bash", "-lc"], "cmd": ["sleep infinity"]}
```

Four consequences, all improvements:

1. **Five server configurations cost five `vllm serve` invocations**, not five
   pods. Weights load from the network volume each time — expect 2–3 min, against
   ~12 min for the first download.
2. **The startup log becomes a file** on `/workspace` instead of console
   scrollback that vanishes with the pod. Checkpoint A stops being a copy-paste
   race. This alone removes run 1's most fragile step.
3. **No API key at all.** The pod exposes no HTTP port and the server binds to
   `127.0.0.1`; the only way in is SSH. Run 1's 401 dance existed because the
   image sets `VLLM_API_KEY` from the pod id, which sits in a public URL — with
   nothing published there is nothing to authenticate. Stated so it is a decision
   and not an omission: **this is safe only because no port is exposed.** If a
   port is ever published, the key comes back.
4. **`nvidia-smi` between runs becomes the gate.** A relaunch onto a card that
   still holds the previous process's memory is the failure mode this
   introduces, so every relaunch checks the card is empty first.

**Network volume: 25 GB, attached at deploy** (it cannot be added later), and
**kept when the pod is terminated.** Run 1 deleted it and paid ~10 min of GPU
time re-downloading 16.4 GB. At ~$3.5/month the volume costs about $0.12 a day,
which is a quarter of the GPU-minute it saves; it is deleted when weeks 2–3 close,
not at the end of this run.

---

## 2 · Checkpoint A′ — the reproducibility read

Same read as run 1's checkpoint A, on the first configuration, from
`/workspace/serve-bf16-2048.log`. It is not a formality: it is the gate on
everything that follows.

| Log line | Predicted (from run 1's measurement) | Why it matters |
|---|---|---|
| `GPU KV cache size` | **168 985 ± 500 tokens** | different → not the same card/build, and no comparison to run 1 is legal |
| `kv cache memory in use` | 23.23 GiB | the same fact in the other unit |
| `Maximum concurrency for 9,000 tokens` | 18.8× | 168 985 / 9 000 |
| `max_num_batched_tokens` | **2 048**, now passed explicitly | confirms the flag lands where the default did |
| `max_num_seqs` | 256 (default, untouched) | run 1's server behaviour, deliberately unchanged |
| attention backend | **FlashAttention 2** | the baseline for block C's confounder check |
| `enable_prefix_caching` | False | run 2 still measures the uncached path |

**Gate.** The pure decode step at config 1, c=13, must land within ±10% of
**33.80 ms**. This is the cheapest possible re-facing of `eff_mem = 0.83`: same
geometry, fresh pod, a coefficient that was fitted to a *different* pod's
measurement. If it misses by more than 10%, stop and re-read the log before
believing any later number — the fit was pod-specific, which is a finding, not a
malfunction.

---

## 3 · Block A — finite `--request-rate`

### Why 1 500-token prompts and not run 1's 4 000

Because at 4 000 tokens the question is already settled by arithmetic and the
measurement would be theatre: the prefill floor is 349.8 ms against a 300 ms TTFT
budget, so goodput against the interactive SLO is **zero at every arrival rate**,
including zero. Run 1 established that (`l40s-baseline.md` §6) and inverted it —
3 516 tokens spends the entire budget on computation.

1 500 tokens is chosen so the question is live:

```
prefill floor, 1 500 tokens = 131.2 ms
300 ms budget − 131.2 ms     = 168.8 ms of queue the SLO can afford
```

A second reason, worth as much: **1 500 < 2 048**, so a prompt is one prefill
chunk under the default `max_num_batched_tokens`. Block A therefore measures
queueing without chunking interacting with it — and block B changes chunking with
the prompt length held at 4 000. One variable each.

### Why open loop, and the one thing it costs

`--request-rate` finite with **`--max-concurrency` omitted**. The omission is the
whole point and it is not a style choice: `vllm bench serve` wraps each request in
`asyncio.Semaphore(max_concurrency)` when that flag is set, which re-imposes a
closed loop on top of the arrival process and reproduces exactly the defect run 1
is trying to leave behind. `--burstiness 1.0` (the default) gives Poisson
arrivals.

What it costs: **concurrency is no longer a controlled variable.** In a closed
loop `n` is the flag; here `n` is a response, fluctuating within a level. So
block A gives a weaker `eff_mem` fit than run 1 did — implied `eff_mem` has to be
computed against a *mean* `n` read from `/metrics`, not against a number typed
into a command. That is why blocks B and C, not A, carry the coefficient work, and
why a metrics sampler runs for the whole session (card, step 3).

### Predictions

The operating point of an open loop is where the card's completion rate equals
the arrival rate. With `step(n)` from `tpot_floor` at ctx 1 600 and a 131.2 ms
prefill charged per request, utilisation reaches 1 when

```
R = n / (200 × step(n) + n × 0.1312 s)
```

solved for `n` at each rate. Batching makes `step(n)/n` fall as `n` rises, so the
server self-stabilises at the `n` that matches the offered rate — until the pool
runs out of seats.

| Rate, req/s | Predicted `n` | Predicted decode step | Step × 1.9 (run 1's TPOT ratio at high load) | Predicted verdict |
|---|---|---|---|---|
| 0.5 | 2.5 | 23.70 ms | 45.0 ms | inside everything |
| 1.0 | 5.7 | 24.74 ms | 47.0 ms | inside everything |
| **1.5** | 9.7 | 26.07 ms | 49.5 ms | **the TPOT knee** |
| **2.0** | 15.1 | 27.84 ms | 52.9 ms | TPOT p99 breaches |
| 2.5 | 22.5 | 30.28 ms | 57.5 ms | breached |
| 3.0 | 33.5 | 33.91 ms | 64.4 ms | breached |
| 4.0 | 86.3 | 51.25 ms | 97.4 ms | **at the 105-seat pool ceiling** |

Seats at ctx 1 600: **105 by capacity** (measured pool ÷ 1 600), **82 by TPOT
50 ms** at `eff_mem` 0.83 — so at this prompt length latency and capacity are only
1.28× apart, against 3.4× at 4 000 tokens. Worth noticing before the run: the
card's two limits move relative to each other with prompt length, which is the
same shelf-and-legs distinction in a third guise.

**Stated predictions, in falsifiable form:**

1. **TPOT p99 crosses 50 ms between 1.5 and 2.0 req/s.** The uncertainty is
   deliberate: the 1.9 multiplier is borrowed from run 1 at 4 000-token prompts,
   where each request injects 350 ms of prefill; at 1 500 tokens it injects
   131 ms, so the multiplier should be **smaller** and the crossing **later**.
   Direction stated in advance, as `docs/SLO.md` §9 requires.
2. **TTFT p99 crosses 300 ms between 1.5 and 2.5 req/s** — and, unlike run 1's,
   these TTFT numbers are legal to compare against the target.
3. **Goodput peaks at 1.2–1.6 req/s and collapses before 3.0.** Measured
   natively: `--goodput ttft:300 tpot:50` reports it in req/s, so goodput stops
   being a concept in the glossary and becomes a column.
4. **Throughput keeps rising after goodput collapses.** This is the shape
   `docs/SLO.md` §5 predicts and the reason goodput exists; run 1 saw the
   reversal in throughput but had no SLO-filtered number beside it.
5. At R = 4.0 the pool ceiling is reached and **preemptions appear**
   (`num_preemptions_total` > 0), as at run 1's c=45.

### Stop conditions

- Any TTFT p50 **below 131 ms** → prefix caching is on, or the prompts are not
  1 500 tokens. Check the log, do not sweep further.
- Goodput non-zero at R = 4.0 → the SLO parse is wrong (`--goodput` values are
  **milliseconds**); re-read the flag before believing the curve.

---

## 4 · Block B — `max_num_batched_tokens`, and the invariant that makes it a test

### The argument the block has to break

Run 1 named this knob from the ratio table: with a 2 048-token chunk budget,
every arriving request injects prefill chunks into the decode stream and each
injection stretches that step for every sequence in the batch. Smaller chunks
stretch a step less. Therefore smaller chunks should fix the 2.6×.

**That argument has a hole, and finding it before the run is the reason to write
the sheet.** Total prefill work is set by the load, not by the chunk size: at
c=13 and ~1.22 req/s, 350 ms of prefill compute arrives per request whatever
`max_num_batched_tokens` is. Chunking **redistributes** that work; it cannot
remove it. So the *mean* inflation — which is what TPOT is — should be roughly
invariant, and only the *tail* should move.

| MNBT | Chunks per 4 000-token prompt | Prefill tokens per step | Chunk compute at `mfu` 0.439 | Worst step, upper bound | TTFT ≥ |
|---|---|---|---|---|---|
| 512 | 9 | 499 | 43.6 ms | 77.5 ms | 697 ms |
| 1 024 | 4 | 1 011 | 88.4 ms | 122.2 ms | 489 ms |
| **2 048** (default, run 1) | 2 | 2 035 | 178.0 ms | 211.8 ms | 424 ms |
| 4 096 | 1 | 4 083 | 357.1 ms | 390.9 ms | 391 ms |

("Prefill tokens per step" is the budget minus the 13 decode tokens that share
it. "Worst step" adds the chunk's compute to the 33.83 ms decode step, which
over-counts because a step overlaps the two — run 1's measurement sits about 20%
under this bound. It is an upper bound on purpose: the *ordering* is the
prediction, not the values.)

**Predictions:**

1. **TPOT p50 is invariant across the four levels, within ±15%.** This is the
   sharp one, and it is the opposite of what the naive reading of run 1 expects.
2. **ITL p99 falls monotonically with MNBT**, roughly in the ratio 77 : 122 :
   212 : 391.
3. **TPOT p99 improves as MNBT falls**, and *how much* is the block's answer:
   - improves from 12 seats to ~31 (the decode-step answer) → the 2.6× was pure
     redistribution and `max_num_batched_tokens` **is** the fix;
   - improves to ~18–22 and stalls → part of the gap is prefill work that no
     chunk size removes, and the fix is elsewhere: prefix caching, shorter
     prompts, or a separate prefill pool;
   - does not move → the gap was never chunking, and run 1's attribution was
     wrong. Least likely, most valuable.
4. **TTFT p50 rises as MNBT falls**, ordered 512 > 1 024 > 2 048 > 4 096. This is
   the TTFT-for-TPOT trade getting a price on
   both sides for the first time.

Every level is closed loop at **c=13 and c=32, 4 000-token prompts** — run 1's
exact geometry, so the MNBT 2 048 rows double as the reproducibility check of §2
and as the control for the other three configurations.

`long_prefill_token_threshold` sits beside this knob and is **not** planned:
confirm it exists with `--help` on the pod and note it, but a second scheduler
knob in the same run makes neither attributable.

---

## 5 · Block C — FP8 KV

`--kv-cache-dtype fp8`, one byte per K/V value instead of two, with the weights
left at BF16. Everything else held at config 1.

### Predictions

| Quantity | BF16 KV (measured, run 1) | FP8 KV (predicted) |
|---|---|---|
| KV bytes per token | 147 456 | **73 728** |
| `GPU KV cache size` | 168 985 | **~338 300 tokens (2.00×)** |
| Capacity at 4 100 ctx | 41 seats | **82 seats** |
| Seats by TPOT 50 ms, `eff_mem` 0.83 | 32 | **64** |
| Decode step at n=13 | 33.80 ms | 28.35 ms |
| Decode step at **n=26** | — | **33.83 ms** |
| Decode step at n=64 | — | 49.85 ms (= BF16 at n=32) |
| TTFT, 4 000-token prompt | 674.8 ms at c=4 | **unchanged, within 3%** |

**The claim in `docs/SLO.md` §10 — "FP8 KV doubles concurrency at constant TPOT" —
is exactly true in the model, and the reason is worth stating before it is
measured.** The weights term of `decode_step_bytes` is untouched by the KV dtype;
only the KV term halves. So doubling `n` with halved bytes per token reproduces
the same total, at *any* `n`. That is why the c=26 level is the one that must not
be dropped: **FP8 at n=26 predicted 33.83 ms against BF16 at n=13 measured
33.80 ms** is a one-line test of the whole claim.

**And the claim is predicted to be worth almost nothing to the interactive
class.** FP8 KV does not touch prefill — `prefill_bytes` moves 16.99 → 16.69 GB
and prefill is compute-bound by an order of magnitude either way — so the
scheduler-driven TPOT p99 limit stays near 12. Predicted operator conclusion:
**FP8 KV buys capacity for the batch class and nothing for the latency class.**
If TPOT p99 *does* double, the 2.6× was capacity pressure after all and block B's
attribution is wrong.

### The confounder, and how it is detected rather than assumed

vLLM's FlashAttention-2 backend has historically refused FP8 KV cache and fallen
back to another backend; per-head FP8 quantisation is Flash-Attention-only, and
FA3 is Hopper-class, which an L40S is not. Run 1 ran FlashAttention 2. **So this
block may change two things at once: the KV dtype and the attention backend.**

Two defences, both cheap:

1. **Read the backend line from the startup log** and record it beside the pool
   figure. If it is still FlashAttention 2, there is no confounder.
2. **TTFT is the detector.** FP8 KV is predicted not to move TTFT at all, because
   prefill is compute-bound and its bytes barely change. A TTFT shift greater
   than 10% therefore means the *kernel* changed, not the cache. If that fires,
   one conditional relaunch — BF16 KV forced onto the same backend via
   `VLLM_ATTENTION_BACKEND`, one level at c=13 — separates the two causes for
   ~4 minutes of card time.

### What this block does not measure, stated so it is not implied

**Accuracy.** Uncalibrated FP8 KV uses default scales of 1.0; calibrated scales
come from a separate `llm-compressor` pass. No eval is run here, so the only
honest claim afterwards is about *capacity and latency at unchanged
configuration*. A production decision to ship FP8 KV needs a quality measurement
this run does not produce, and the write-up must say so rather than let the
throughput number imply it.

**A second coefficient, not an edit.** If the implied `eff_mem` under FP8 differs
from 0.83 — plausible, since paged FP8 access adds a dequantisation step per
access — it is recorded as a *separate* coefficient beside it, following the
`L40S_RUN1` precedent in `bench/roofline.py`. A coefficient belongs to a card, a
build **and a cache dtype**.

---

## 6 · Budget, drop order, and what "done" means

**Expected clock:** deploy and first weight download 12 min · checkpoint A′ 5 min
· block A 14 min · block B 17 min · block C 10 min · harvest 8 min ≈ **70 min**.
Hard stop at 2.5 h.

**Drop order, decided now so it is not decided under time pressure:**

1. Block B's MNBT 4 096 configuration — its prediction is the least surprising
   end of a monotone ordering.
2. Block A's R = 0.5 and R = 3.0 levels.
3. Block B's c=32 levels; keep c=13, which is where the SLO binds.
4. Block C's conditional backend-control relaunch.

**Never dropped:** checkpoint A′ and its ±10% gate · block A at R = 1.5 and 2.0 ·
block B's MNBT 512 at c=13 · block C's checkpoint and its **c=26** level · the
harvest step.

**Done for run 2** — three sentences that can be written afterwards with a number
in each:

- the arrival rate at which goodput collapses, and the SLO that broke first;
- what a smaller `max_num_batched_tokens` costs in TTFT and buys in TPOT p99,
  and therefore whether the 2.6× is a knob or a workload;
- what FP8 KV changes and, more usefully, what it does not.

---

## What run 2 still cannot answer

Written now so the write-up does not overclaim later.

- **Prefix caching.** Off again, deliberately: two runs of the uncached path make
  a baseline, and the cached path deserves its own run with a dataset that has
  shared prefixes — `--dataset-name random` has none by construction.
- **FP8 accuracy.** Above.
- **Decode MFU.** Still assumed at the prefill value. Harmless, still unvalidated.
- **Replicas duplicating the weights read** — the open question from week 1. Needs two
  replicas, which is weeks 4–6.
- **MI300X.** No coefficient measured here transfers to it, and after two runs
  that will be two cards' worth of L40S evidence and zero for AMD.
- **Reasoning-length context.** `max_model_len` stays 9 000; `docs/SLO.md` §8 is
  untouched.

---

## Postscript — what this sheet got wrong about the method (added 2026-08-23)

Written after the run, and kept here rather than in `docs/benchmarks/l40s-run2.md`
because these are defects of the *instrument* this file specified, not findings
about the card. The next runsheet is written from this list. Measured results and
their argument stay in the write-up; nothing below is repeated there.

1. **The checkpoint gate of ±500 tokens (§2) is indefensible.** The same
   configuration relaunched on the same pod logged 169 833 / 176 994 / 169 833
   tokens — 4.2% spread, driven by whether the `torch.compile` cache was warm when
   the memory-profiling pass ran. A ±0.3% gate fires on noise. Gate on `kv cache
   memory in use`, or on ±5%.
2. **The FP8 confounder detector (§5) had no statistical power.** It watched TTFT
   at c=13 with a 10% trigger; that quantity spans 32% across three identical
   launches. What did work, immediately and for free, was the attention-backend
   line in the startup log. Detect a kernel change by reading the log, never by
   inferring it from a latency.
3. **`VLLM_ATTENTION_BACKEND` does not work in vLLM 0.27.1.** It is accepted and
   ignored — the conditional in the card silently measured FLASH_ATTN a second
   time. The flag is `--attention-backend`, and when it is used vLLM logs
   `Using AttentionBackendEnum.X backend.` instead of the usual
   `out of potential backends` line, so the obvious grep returns nothing.
4. **`vllm serve --help` and `vllm bench serve --help` no longer list flags.**
   0.27.1 prints argument *groups*; `--help=all` prints the flags. The card's flag
   checks both came back empty and looked like a missing feature.
5. **The 4 096 row of §4's table charged 4 083 prefill tokens to a 4 000-token
   prompt.** The bound should be 383.6 ms, not 390.9, and the over-count against
   the measurement is +5.1% rather than +7.1%. Cap the chunk at the prompt.
6. **A hosted template's environment can carry an unresolvable reference.** The
   RunPod deploy form rejected `env[2]` with
   `String cannot represent a non string value: { name: "MISSING" }` — the
   template's `VLLM_API_KEY` row was a reference, not a literal, and the row could
   not be deleted. Renaming the key and typing a literal cleared it. Budget a few
   minutes for the deploy form itself, and check `env` on the pod afterwards.
7. **Start the metrics sampler exactly once, and reduce it before terminating.**
   Two samplers were launched into the same file with `>`, interleaving their
   output; the file was truncated and one restarted. And the trace was reduced only
   to session-wide maxima, so per-level mean concurrency — the thing that would
   have made block A a clean `eff_mem` fit rather than a compound one — was never
   extracted. Reduce per level, on the pod, as part of the harvest.
8. **The transfer path off the pod was never exercised** — answered on 2026-08-26
   on a $0.10 CPU-class pod while emptying the volume, and it changes what a
   runsheet has to specify **at deploy time**. The RunPod proxy
   (`ssh <pod>-<hash>@ssh.runpod.io`) refuses a non-interactive command outright:
   `Error: Your SSH client doesn't support PTY`, and with `-tt` it opens a
   terminal that never returns — so no `tar` through a pipe and no `scp`. The
   direct endpoint does it in one command, but it exists **only if TCP 22 was
   published when the pod was created**, and ports cannot be added afterwards.
   Second trap on top: the console prints `-i ~/.ssh/id_ed25519` for both
   endpoints and it is wrong for the direct one, which accepted only
   `~/.ssh/id_ed25519_runpod`. **Every future runsheet publishes TCP 22 in its
   deploy step and names the key**, or the harvest has no path off the pod.

What the sheet got right and should be repeated: predictions written before the
rental, in falsifiable form, with the *direction* of an expected error stated;
`sleep infinity` with the servers launched by hand, which turned four scheduler
settings into one pod; the drop order, which was never needed but cost nothing;
and putting block C last, since it did change the attention backend.
