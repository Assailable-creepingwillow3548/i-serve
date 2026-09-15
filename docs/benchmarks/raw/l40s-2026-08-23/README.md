# Raw evidence — L40S run 2, 2026-08-23

Verbatim capture, no interpretation. The analysis lives in
`docs/benchmarks/l40s-run2.md`; the checklist the run followed is
`docs/benchmarks/runsheets/l40s-run-2-card.md`, and its reasoning `docs/benchmarks/runsheets/l40s-run-2.md`.

| File | What it is |
|---|---|
| `levels.tsv` | the 22 benchmark levels, one row each, transcribed from the printed summary blocks |
| `startup-lines.txt` | the load-bearing lines of all eight `serve-*.log` files, plus the metrics maxima |
| `machine/` | the 54 machine-written files, fetched off the network volume on 2026-08-26 before it was deleted: 22 result JSONs, 22 tee'd stdout files, eight `serve-*.log`, the metrics trace, and the sampler's pid file — copied whole, nothing selected |

**A near-miss worth recording here rather than in a commit message:** the first
commit of `machine/` silently dropped all nine `.log` files — the eight server
logs and the metrics trace — to a `*.log` line in `.gitignore`, on the same day
the volume holding the only other copy was deleted. It was caught by counting
files against the directory, not by reading the diff. `.gitignore` now exempts
`docs/benchmarks/raw/**/*.log`, and the same rule recovered run 1's
`pod-console.log`, which had been untracked since 2026-08-20 for the same reason.

## Provenance, and what is missing

**This directory was a transcription for three days and is a capture now.** Until
2026-08-26 the machine-written artefacts sat under `/workspace/run2` on the 25 GB
network volume, deliberately not deleted at terminate, and `levels.tsv` was a
hand-typed derivative of the summary blocks they printed. On 2026-08-26 they were
fetched into `machine/` and the volume was deleted — it cost ~$3.5/month to save
a 16 GB weights download worth under $0.05 a run.

**The transcription was then checked against them, field by field: 22 levels ×
448 fields, zero mismatches** at the two decimals `levels.tsv` rounds to. That is
a stronger statement than either file alone makes — the derivative is exact where
it overlaps, and the capture adds the per-request arrays it drops.

Why it happened this way is itself a finding: run 1 lost its console scrollback to
the provider's log viewer, so run 2 wrote everything to a file on persistent
storage — and having done that, there was nothing left that terminating the pod
could destroy.

**The transfer path is no longer an open question, and the answer has a trap in
it.** RunPod offers two SSH endpoints, and only one of them can carry data:

- the **proxy**, `ssh <pod>-<hash>@ssh.runpod.io`, refuses a non-interactive
  command outright — `Error: Your SSH client doesn't support PTY` — and with
  `-tt` opens a terminal that never returns. No `tar` through a pipe, no `scp`;
  the console itself says "No support for SCP & SFTP";
- **SSH over exposed TCP**, a direct `root@<ip> -p <port>`, which exists only if
  **TCP 22 was published at deploy** (ports cannot be added later). There
  `ssh host "tar cz -C /workspace run2" > run2.tgz` works exactly as expected —
  3.3 MB, 158 kB compressed, one command.

The trap: the console prints `-i ~/.ssh/id_ed25519` for **both** endpoints, and
that is wrong for the second one. The proxy authenticated with the account's
default key; the pod's own sshd accepted only `~/.ssh/id_ed25519_runpod`, the key
registered with RunPod. A failed direct login with a working proxy login is that
mismatch, not a broken pod.

- Environment: image `vllm/vllm-openai:v0.27.1`, `vllm --version` 0.27.1, driver
  **550.127.05** / CUDA 13.0, one L40S reporting 46 068 MiB, pod `70700baa4cfa`,
  RunPod on-demand $0.99/h, North American DC.
- **The driver is not run 1's.** Run 1 had 580.159.04 on the same card model.
  Nothing in this run isolates a driver effect, and none is claimed.
- vLLM was **not PID 1**: the container ran `sleep infinity` and every server was
  launched by hand over SSH, which is what made eight configurations affordable
  in one pod. Start command, JSON form:
  `{"entrypoint": ["bash", "-lc"], "cmd": ["sleep infinity"]}`.
- Server flags common to every launch: `--dtype auto` (resolved BF16),
  `--gpu-memory-utilization 0.90`, `--max-model-len 9000`,
  `--no-enable-prefix-caching`, `--host 127.0.0.1`. `max_num_seqs` was left at the
  default 256 throughout, as in run 1.
- No HTTP port was exposed and the server bound to loopback, so no API key was
  set and `OPENAI_API_KEY=EMPTY` is correct rather than a workaround.
- Block A: `--random-input-len 1500`, finite `--request-rate`, `--burstiness 1.0`
  (Poisson), **no** `--max-concurrency`, `--goodput ttft:300 tpot:50`.
- Blocks B and C: `--random-input-len 4000`, `--request-rate inf` with
  `--max-concurrency`, i.e. run 1's geometry exactly.
- All levels: `--random-range-ratio 0` (fixed length), `--ignore-eos`, output 200
  tokens. **One** request failed in the entire run — level `A-r3.0`, 1 of 300,
  `aiohttp ServerDisconnectedError`.
- `vllm bench serve` does not force `temperature=0`; sampling was server-default,
  so timings reproduce and generated text does not.
- Spend: pod up 07:59, terminated after 09:26 — ~87 minutes of a 150-minute
  budget, ≈ $1.44 against $2.50.
