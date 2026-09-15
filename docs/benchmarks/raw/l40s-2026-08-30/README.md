# Raw evidence — L40S run 3, 2026-08-30

Verbatim capture, no interpretation. The analysis lives in
`docs/benchmarks/l40s-run3.md`; the arithmetic that reads these files is
`bench/measured_run3.py`; the reasoning and the before-the-fact predictions are
`docs/benchmarks/runsheets/l40s-run-3.md`.

| Path | What it is |
|---|---|
| `results/<run>/run.json` | one per harness invocation: scenario, argv, startup-log facts, the pool gate, the seat verdict, and the levels it contains |
| `results/<run>/<level>.json` | one per level: every latency percentile, the harness's own fields (`harness_*`) including measured `h`, preemptions, generator lateness and the gates that fired |
| `results/<run>/<level>-metrics.json` | the Prometheus counter deltas taken across that level's window |
| `run3/serve-cache-off.log` | config 1's full startup log — `--no-enable-prefix-caching` |
| `run3/serve-cache-on.log` | config 2's full startup log — prefix caching on |
| `run3/*.out` | the console output of each sweep, as the operator saw it |

**This directory is a capture, not a transcription**, which is the first
difference from runs 1 and 2: `bench/harness.py` wrote every file here on the pod
and `scp` moved them off before Terminate. There is no hand-typed derivative to
verify against, and `bench/measured_run3.py` reads these files directly.

## What each results directory is

| Directory | Block | What it holds |
|---|---|---|
| `20260830-094744-smoke` | A″ | the smoke level against config 1 — refused, correctly: a cached scenario against a caching-off server |
| `20260830-095022-smoke` | A″ | the smoke level against config 2 — `h` = 0.500 on a 128/256 prefix, which is what proved the counters count tokens |
| `run3-c-control` | C | c = 13, `h` = 0, caching **off** — also the reproducibility read against runs 1 and 2 |
| `run3-a-h00` | A | **the contaminated uncached sweep**, kept deliberately (see below) |
| `run3-a-h00-clean` | A | the uncached sweep as measured, per-level seeds |
| `run3-a-h80` | A | the cached sweep, c = 8…28 |
| `run3-a-h80-ext` | A | the conditional extension, c = 32…56, decided in the runsheet before the run |
| `run3-b-h80` | B | Poisson arrivals, 1.5…7 req/s |
| `run3-b-h80-ext` | B | the conditional extension, 9/11/13 req/s |
| `run3-c-treatment` | C | c = 13, `h` = 0, caching **on** — the same level as the control |

## The one directory that is evidence of a defect

`run3-a-h00` is kept because it is the clearest thing in here. Its levels at
c = 12, 14 and 16 report a measured `h` of 0.664 / 0.854 / 0.872 with a nominal
`h` of **zero**, and the harness flagged all three `INVALID` on its own gate.
`Workload.seed` was a single constant across levels, so each level's prompts were
a byte-identical prefix of the next level's — harmless with prefix caching off,
which is how runs 1 and 2 never met it, and a total cache hit with it on. The
numbers are exactly 24/36, 36/42 and 42/48.

`run3-a-h00-clean` is the same sweep after `SEED + concurrency`. Compare the two
directories to see a gate doing the job it was written for; the write-up's §3 is
the argument.

## Provenance, and what is missing

- Pod `ff6689f28bec` (RunPod `tlm7f7mjyzi3ot`), L40S, driver 580.126.20, image
  `vllm/vllm-openai:v0.27.1`, no network volume. Terminated after the harvest.
- **An earlier pod was rented and thrown away**: driver 570.124.06 (CUDA 12.8),
  on which vLLM 0.27.1's torch refused to initialise. No data from it exists, and
  the failure is described in the write-up §1.
- **No metrics trace at 1 Hz.** Run 2 sampled the whole session into one file;
  run 3's harness samples per level instead and writes the deltas beside each
  level, which is what run 2's postscript asked for. The session-wide trace is
  therefore absent by design, not lost.
- **No `levels.tsv`.** There is nothing to transcribe.
- **The startup logs do not carry `max_num_batched_tokens` or `max_num_seqs`** on
  this build. Both were left at defaults and neither was passed, so the claim that
  the geometry matches runs 1 and 2 rests on the c = 13 decode step and not on a
  log line.
