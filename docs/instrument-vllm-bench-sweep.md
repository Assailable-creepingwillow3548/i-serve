# Instrument note — `vllm bench sweep`, and where it belongs on MI300X

Not a runsheet: no card is rented and no number is predicted here. This note
exists because runs 1–3 drove the load by hand — `S() { vllm bench serve ... }`
in `l40s-first-run-card.md` §4 and `l40s-run-2-card.md`, then
`bench/harness.py` — and the `vllm bench sweep` subcommand family was never
considered. The miss was found by reading the engine's own documentation, not
this repository. Checking an instrument against its own documentation before
committing a run to it is the step that was skipped when runs 1–3 were planned. The MI300X
credit window is 30 days from activation and its rule is that hours go into runs
rather than into debugging, so the instrument decision is made here, before the
credits are activated.

Written 2026-08-31 against the documentation for **`v0.27.1`**, the tag runs 1–3
used; verified off-card 2026-09-04 against the source of that tag and against
`vllm/vllm-openai-cpu:v0.27.1-arm64`, whose `vllm bench sweep` is the same code
without a card behind it. The pinned tag for MI300X may differ; if it does, this
whole note is a hypothesis again and `--help=all` on the pod settles it.

## What the tool is, in `v0.27.1`

Five subcommands: `serve` (benchmark under multiple settings), `serve_workload`
(explore the latency–throughput tradeoff over workload levels), `startup`
(startup time over parameter combinations), `plot`, `plot_pareto` (tokens/s/user
against tokens/s/GPU). **There is no `serve_sla`** — it is documented only for
older releases, so no SLA-driven search exists here.

`sweep serve` takes `--serve-cmd` and `--bench-cmd` as strings and sweeps the
Cartesian product of `--serve-params` and `--bench-params`, both JSON files of
parameter dicts. `--num-runs` defaults to **3**, `--output-dir` to `results`
(results land under `output_dir/experiment_name`), and `--resume` continues an
interrupted sweep. `--dry-run` prints the commands without running them, and it
**runs on a machine with no GPU** — 14 s in the CPU image, all of it the import
(`bench/sweep/dry-run.sh`). It creates nothing on disk, which has a consequence:
the "cannot overwrite existing experiment" guard never fires under `--dry-run`,
so the same `-e` name can be dry-run any number of times and is protected only
from the first real run onward.

Seven mechanics decide every question below:

1. **The server starts once per `--serve-params` entry** and is kept up across
   `--bench-params`. A server-side grid therefore costs one model load per row,
   not one per level.
2. **Between benchmark runs the tool calls every `/reset_*_cache` endpoint** to
   give the next run a clean slate — `/reset_prefix_cache`, `/reset_mm_cache`,
   `/reset_encoder_cache`, in that order, and it sets `VLLM_SERVER_DEV_MODE=1`
   on the server it spawns so that they exist. **Unless `--after-bench-cmd` is
   given: that command *replaces* the reset rather than following it.**
3. **`serve_workload` picks its own levels**: serial inference, then batch
   inference, then the remaining `--workload-iters` (default 10) spread
   uniformly between them.
4. `--after-bench-cmd` is the only hook, and it runs *after* a benchmark — in
   place of the cache reset (mechanic 2), so a hook that reads `/metrics` must
   also do the reset itself, or the next run starts warm.
5. **`--link-vars a=b` filters the Cartesian product** to the rows where serve
   key `a` equals bench key `b`: `max_num_seqs=max_concurrency` turns a 2 × 2
   grid into its diagonal. Verified in the dry-run.
6. **An override is applied by replacing the flag if the base command has it,
   else by appending.** A boolean knob is the trap: `--no-enable-prefix-caching`
   in the base command and `enable_prefix_caching: true` in the params yields
   *both* flags on one line, and it works only because vLLM's parser takes the
   last one (verified: no-then-yes → `True`, yes-then-no → `False`). Rule for the
   harness: a knob the sweep varies appears in the base command exactly once,
   spelled as a value, or not at all. Param files may be a dict keyed by row
   name; the name becomes the results directory (`SERVE--fp8-kv-BENCH--c16`),
   where the list form produces `max_num_batched_tokens=2048-kv_cache_dtype=fp8`.
7. **Without `--show-stdout` the server's stdout goes to `/dev/null`, and vLLM
   logs to stdout** (verified in the CPU image: every `INFO` line is on stdout,
   none on stderr). So the default swallows the startup log — the `GPU KV cache
   size` and `Maximum concurrency` lines that `docs/SLO.md` §9 puts above every
   derivation. **`--show-stdout` is mandatory, with the whole sweep piped through
   `tee`** into a file on a mounted volume; the server log, the benchmark
   summaries and the sweep's own `[BEGIN …]` markers then interleave in one file,
   and the startup lines are distinctive enough to `grep` back out.

## Use it for

- **The server-side grid.** `max_num_seqs` × `max_num_batched_tokens` as
  `--serve-params`, where run 2 restarted the server by hand.
- **Repetition.** `--num-runs 3` is free here, and reproducibility across
  identical launches was a whole block of run 2 (§6).
- **Machine-shaped output and `--resume`.** Run 2's numbers were transcribed into
  a `levels.tsv` by hand (`bench/measured_run3.py`); inside a 30-day window with
  a hard budget, a resumable sweep that writes its own JSON is worth more than
  the transcription discipline it replaces.
- **`plot_pareto`.** Tokens/s/user against tokens/s/GPU is the seats-against-
  latency frontier this repository has been drawing by hand.

## Do not use it for

- **Anything needing a warm prefix.** Mechanic 2 wipes the prefix cache before
  every run, so a controlled `h` is not merely unavailable — the tool actively
  destroys the state the measurement needs. `--after-bench-cmd true` would keep
  the cache alive (mechanic 4), but a cache that is merely *not wiped* is still
  not a cache at a known `h`; the exclusion stands on control, not on the wipe. Prefix-cache work stays on
  `bench/harness.py`, which sends token IDs and reads
  `vllm:prefix_cache_hits` / `vllm:prefix_cache_queries` itself.
- **Hunting a predicted threshold.** Mechanic 3 spreads levels uniformly, and
  the interesting levels are adjacent pairs around a prediction — run 1 ran
  c = 23 and c = 24 for that reason, and run 2 knows TTFT p99 crosses 300 ms
  between 0.5 and 1.0 req/s. Broad curve: `sweep`. Threshold: a hand ladder.
- **Levels whose gates read `/metrics` on both edges.** Mechanic 4 gives one
  post-benchmark hook, where runs 1–2 read `num_preemptions_total` and
  `num_requests_waiting` before *and* after each level.
- **A seat count under a latency target.** With no `serve_sla`, the search for
  the largest concurrency meeting TPOT p99 ≤ 50 ms stays our own logic in
  `bench/harness.py`.

## Before it is used on a card

- [ ] `vllm bench sweep --help` and `vllm bench sweep serve --help=all` on the
      pod. **The help output wins over this note**, as `l40s-first-run-card.md`
      §7 already rules for `vllm bench serve`. Plain `--help` on the subcommand
      prints an empty "Config Groups" stub in `v0.27.1`; `=all` is the one that
      lists the flags.
- [x] Confirm `/reset_prefix_cache` is among the endpoints the sweep resets, and
      record it — the exclusion above rests on it. Done 2026-09-04 from the
      `v0.27.1` source (`vllm/benchmarks/sweep/server.py`); mechanic 2.
- [ ] Price the sweep before launching it: rows × levels × `--num-runs`, plus one
      model load per `--serve-params` row. Three repeats turn seven levels into
      twenty-one runs.
- [x] Validate the JSON parameter files with `--dry-run` off the card. Done
      2026-09-04: `bench/sweep/dry-run.sh` against `bench/sweep/*.json`, 27
      benchmark commands and 3 server launches printed, exit 0. The values in
      those files are run 2's geometry, a skeleton — the MI300X grid is set by
      the runsheet that predicts it, and this check is re-run when it changes.
