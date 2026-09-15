# Card — L40S run 2

Execution only. Every *why* is in `l40s-run-2.md`, which wins on any conflict.
Budget **2.5 h, ~$2.50**, expected $1.30–1.60. **Terminate** the pod at 2.5 h or
when step 8 is done. **Do not delete the network volume** — it is kept for run 3.

**Where each block runs.**

| Tag | Where | What lives there |
|---|---|---|
| `[laptop]` | local terminal, in this repo | step 0; every paste of results |
| `[console]` | RunPod web UI | deploy form, Terminate |
| `[pod]` | SSH session on the pod | everything else — vLLM is **not** PID 1 this time |

Unlike run 1, the startup log is a **file on `/workspace/run2`**, not console
scrollback. There is nothing to copy out of the console under time pressure.

---

## 0 · Off the clock

**`[laptop]`**

```
python3 bench/tests/test_roofline.py      # must print 42/42 passed
```

- [ ] Long sheet open at §2 (checkpoint gate), §3 (rate table), §4 (MNBT table),
      §5 (FP8 table). Those four tables are the run.
- [ ] `[console]` Balance ≥ 1 h of the config; L40S On-Demand visible in a
      **North American** DC; a **25 GB network volume** creatable there.
- [ ] Drop order memorised: **MNBT 4096 → A's R=0.5 and R=3.0 → B's c=32 →
      C's conditional relaunch.** Never: checkpoint, A at 1.5/2.0, B's 512 at
      c=13, C's c=26, the harvest.

## 1 · Deploy the pod idle (~10 min)

**`[console]`** — Template **vLLM Latest**, **GPU count 1**.

| Field | Value |
|---|---|
| Image | **`vllm/vllm-openai:v0.27.1`** — override the template's `:latest` |
| Network volume | **25 GB → `/workspace`**, NA DC. **Attach at deploy** — it cannot be added later |
| Container disk | template default |
| Exposed HTTP ports | **none** — nothing is published, which is why there is no API key |
| `HF_HOME` | `/workspace/.huggingface` |
| `VLLM_CACHE_ROOT` | `/workspace/.vllm` |

**Container Start Command — the JSON form, so vLLM is not PID 1:**

```
{"entrypoint": ["bash", "-lc"], "cmd": ["sleep infinity"]}
```

- [ ] `[pod]` **Gate — open a shell**: `ssh <pod-id>-<hash>@ssh.runpod.io`, type
      `echo ok`. **No `-i`** — `~/.ssh/config` pins the key; drop the
      `-i ~/.ssh/id_ed25519` the Connect dialog appends.
- [ ] `[pod]` `nvidia-smi` shows one L40S, ~0 MiB used. Record the driver line.
      **No GPU visible → terminate and redeploy, do not wait.**
- [ ] `[pod]` `vllm --version` → expect **0.27.1**.

## 2 · Define the shell (~3 min, off the meter in effect)

**`[pod]`** — one session for the whole run. Paste all of it at once.

```
export HF_HOME=/workspace/.huggingface
export VLLM_CACHE_ROOT=/workspace/.vllm
export OPENAI_API_KEY=EMPTY
mkdir -p "$HF_HOME" "$VLLM_CACHE_ROOT" /workspace/run2

L() {  # L <mnbt> <kv-dtype> <tag>   launch a server
  nohup vllm serve Qwen/Qwen3-8B \
    --host 127.0.0.1 --port 8000 --dtype auto \
    --gpu-memory-utilization 0.90 --max-model-len 9000 \
    --no-enable-prefix-caching \
    --max-num-batched-tokens "$1" --kv-cache-dtype "$2" \
    > "/workspace/run2/serve-$3.log" 2>&1 &
  echo "launched $3 pid $!"; }

W() { until curl -sf 127.0.0.1:8000/health >/dev/null 2>&1; do sleep 5; done
      echo READY; }

K() { pkill -f 'vllm serve'; sleep 20
      nvidia-smi --query-gpu=memory.used --format=csv,noheader; }

OA() { # OA <rate> <num-prompts> <tag>   open loop, 1500-token prompts
  vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
    --endpoint /v1/completions --model Qwen/Qwen3-8B \
    --dataset-name random --random-input-len 1500 --random-output-len 200 \
    --random-range-ratio 0 --ignore-eos \
    --request-rate "$1" --burstiness 1.0 --num-prompts "$2" \
    --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,90,99 \
    --goodput ttft:300 tpot:50 \
    --save-result --result-dir /workspace/run2 --result-filename "A-$3.json" \
    2>&1 | tee "/workspace/run2/A-$3.txt"; }

CL() { # CL <config-tag> <concurrency> <num-prompts>   closed loop, 4000-token
  vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
    --endpoint /v1/completions --model Qwen/Qwen3-8B \
    --dataset-name random --random-input-len 4000 --random-output-len 200 \
    --random-range-ratio 0 --ignore-eos \
    --request-rate inf --max-concurrency "$2" --num-prompts "$3" \
    --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,90,99 \
    --save-result --result-dir /workspace/run2 --result-filename "$1-c$2.json" \
    2>&1 | tee "/workspace/run2/$1-c$2.txt"; }
```

- [ ] `vllm bench serve --help | grep -E "goodput|burstiness|request-rate|max-concurrency|percentile-metrics|random-range-ratio|save-result"`
      — **seven** flags must come back. `grep`, never `less`: no pager in this
      image. A rejected flag is dropped from the function and noted.
- [ ] `vllm serve --help | grep -E "kv-cache-dtype|max-num-batched-tokens|long-prefill"`
      — first two must exist. `long_prefill_token_threshold` is **recorded, not
      used**.

## 3 · Config 1 and checkpoint A′ (~15 min, first launch downloads 16.4 GB)

```
L 2048 auto bf16-2048 ; W
```

Then start the sampler, once, for the whole run:

```
nohup bash -c 'while true; do
  printf "%s " "$(date +%s)"
  curl -s 127.0.0.1:8000/metrics 2>/dev/null \
    | grep -E "^vllm:(num_requests_running|num_requests_waiting|num_preemptions_total|kv_cache_usage_perc)\{" \
    | sed -E "s/^vllm:([a-z_]+)\{[^}]*\} /\1=/" | tr "\n" " "
  echo; sleep 1; done' > /workspace/run2/metrics.log 2>&1 &
echo $! > /workspace/run2/sampler.pid
```

- [ ] `head -3 /workspace/run2/metrics.log` shows named values, not blanks.

**Checkpoint A′ — from the file, not the console:**

```
grep -E 'KV cache size|kv cache memory in use|Maximum concurrency|max_num_batched_tokens|max_num_seqs|block_size|backend|prefix_caching|Graph capturing|non-torch|activation' /workspace/run2/serve-bf16-2048.log
```

| Line | Predicted | Measured |
|---|---|---|
| `GPU KV cache size` | **168 985 ± 500** tokens | |
| `kv cache memory in use` | 23.23 GiB | |
| `Maximum concurrency for 9,000 tokens` | 18.8× | |
| `max_num_batched_tokens` | **2 048** | |
| `max_num_seqs` | 256 | |
| attention backend | **FlashAttention 2** | |
| `enable_prefix_caching` | False | |

- [ ] Smoke test:
      `curl -s 127.0.0.1:8000/v1/models` returns the model id — **copy it
      exactly**, it is already in the functions as `Qwen/Qwen3-8B`.
- [ ] **Pool off by >500 tokens → stop and read the log before anything else.**

## 4 · Block A — open loop, 1 500-token prompts (~14 min)

**No `--max-concurrency` in `OA`. That omission is the block.**

```
OA 1.0  20 warm     # discarded
OA 0.5  60 r0.5
OA 1.0 120 r1.0
OA 1.5 180 r1.5
OA 2.0 240 r2.0
OA 2.5 240 r2.5
OA 3.0 300 r3.0
OA 4.0 300 r4.0
```

| Rate | Predicted `n` | Predicted step | Predicted verdict | TTFT p99 | TPOT p99 | Goodput |
|---|---|---|---|---|---|---|
| 0.5 | 2.5 | 23.70 ms | inside | | | |
| 1.0 | 5.7 | 24.74 ms | inside | | | |
| **1.5** | 9.7 | 26.07 ms | **TPOT knee** | | | |
| **2.0** | 15.1 | 27.84 ms | TPOT p99 breaches | | | |
| 2.5 | 22.5 | 30.28 ms | breached | | | |
| 3.0 | 33.5 | 33.91 ms | breached | | | |
| 4.0 | 86.3 | 51.25 ms | **pool ceiling, preemptions** | | | |

- [ ] Goodput column is `--goodput`'s own req/s figure, **not** computed by hand.
- [ ] Predicted: goodput peaks at **1.2–1.6 req/s** and is ~0 by 3.0, while raw
      throughput keeps climbing. Record both.
- [ ] Predicted: TPOT p99 crosses 50 ms **between 1.5 and 2.0**, and *later* than
      that if anything — the 1.9× ratio is borrowed from 4 000-token prompts.
- [ ] **STOP** if any TTFT p50 is below **131 ms** — prefix caching on, or the
      prompts are not 1 500 tokens.

## 5 · Block B — `max_num_batched_tokens` (~17 min)

Config 1 is still up; it is the control.

```
CL bf16-2048 13  52
CL bf16-2048 32 128
K ; L 512  auto bf16-512  ; W ; CL bf16-512  13  52 ; CL bf16-512  32 128
K ; L 1024 auto bf16-1024 ; W ; CL bf16-1024 13  52 ; CL bf16-1024 32 128
K ; L 4096 auto bf16-4096 ; W ; CL bf16-4096 13  52 ; CL bf16-4096 32 128
```

- [ ] After every `K`, `nvidia-smi` must read **near 0 MiB** before `L`. If not:
      `pkill -9 -f vllm`, wait, re-check. Never launch onto an occupied card.
- [ ] After every `L`, `grep max_num_batched_tokens /workspace/run2/serve-*.log`
      confirms the flag landed.

| MNBT | Chunks | Worst step (upper bound) | TTFT ≥ | TPOT p50 | ITL p99 | TPOT p99 |
|---|---|---|---|---|---|---|
| 512 | 9 | 77.5 ms | 697 ms | | | |
| 1 024 | 4 | 122.2 ms | 489 ms | | | |
| **2 048** | 2 | 211.8 ms | 424 ms | | | |
| 4 096 | 1 | 390.9 ms | 391 ms | | | |

- [ ] **Gate on the control row:** median ITL at `bf16-2048`, c=13 must be
      **33.80 ms ± 10%** (run 1). That row is the re-facing of `eff_mem = 0.83`.
- [ ] Predicted: **TPOT p50 invariant ±15%** across the four; **ITL p99
      monotone** in MNBT; **TTFT p50 ordered 512 > 1024 > 2048 > 4096**.
- [ ] The answer to record: how far TPOT p99's seat count moves from **12** at
      MNBT 512 — toward 31 (pure redistribution, the knob is the fix), to ~18–22
      (partly workload), or not at all (run 1's attribution was wrong).

## 6 · Block C — FP8 KV (~10 min)

```
K ; L 2048 fp8 fp8-2048 ; W
grep -E 'KV cache size|kv cache memory in use|Maximum concurrency|backend|scale' /workspace/run2/serve-fp8-2048.log
CL fp8-2048 13  52
CL fp8-2048 26 104
CL fp8-2048 32 128
```

| Quantity | Predicted | Measured |
|---|---|---|
| `GPU KV cache size` | **~338 300 tokens (2.00×)** | |
| Capacity at 4 100 ctx | 82 seats | |
| attention backend | **may change — read it** | |
| Decode step, n=13 | 28.35 ms | |
| **Decode step, n=26** | **33.83 ms = BF16 at n=13** | |
| Decode step, n=32 | 36.36 ms | |
| TTFT, c=13 | **unchanged within 3%** | |
| TPOT p99 seat count | **still ~12** | |

- [ ] **c=26 is the level that tests the claim.** Do not drop it.
- [ ] **TTFT is the confounder detector.** A shift >10% means the *kernel*
      changed, not the cache. If it fires and time allows:

      ```
      K ; VLLM_ATTENTION_BACKEND=<backend from the fp8 log> L 2048 auto bf16-ctl ; W
      CL bf16-ctl 13 52
      ```
- [ ] Record the backend line verbatim in both logs. Accuracy is **not** measured
      here — uncalibrated FP8 scales default to 1.0.

## 7 · Harvest, while the container still exists (~8 min)

```
kill "$(cat /workspace/run2/sampler.pid)"
ls -la /workspace/run2/
wc -l /workspace/run2/metrics.log
tail -n 45 /workspace/run2/A-*.txt
tail -n 45 /workspace/run2/bf16-*.txt /workspace/run2/fp8-*.txt
grep -E 'KV cache size|kv cache memory in use|Maximum concurrency|max_num_batched_tokens|max_num_seqs|backend|prefix_caching|Graph capturing|non-torch|activation' /workspace/run2/serve-*.log
```

Getting it off the pod, in order of preference:

1. `[laptop]` `ssh <user>@ssh.runpod.io "tar cz -C /workspace run2" > run2.tgz`
   — one command, everything, if the proxy runs non-interactive commands.
2. Paste the `tail`/`grep` blocks **verbatim** into the scratch file, as run 1
   did. `metrics.log` is the one file too large to paste: reduce it first —
   `awk` per level to min / mean / max of `num_requests_running` and
   `num_requests_waiting`, and paste that.

- [ ] Every level has a `.json` and a `.txt`. Expected: 8 A-levels (the warm-up
      makes a file too, and it is discarded, not deleted) + 8 B-levels +
      3 C-levels = **19** pairs (+1 if the conditional ran).
- [ ] Five `serve-*.log` files (+1).
- [ ] `[console]` **Terminate the pod. Do NOT delete the network volume.**
- [ ] Record actual $ spent against $2.50.

## 8 · Off the clock

What the run owes once the pod is gone: `docs/benchmarks/l40s-run2.md`; new
assertions in `bench/tests/test_roofline.py`; `docs/SLO.md` §9 and §10; and glossary
entries for anything the run introduced — `--burstiness`, `--goodput`,
`long_prefill_token_threshold`, and whichever attention backend appeared.

---

## If it breaks

| Symptom | Do |
|---|---|
| SSH `Permission denied (publickey)` | Wrong key, not a dead pod. Re-run without `-i`; `ssh -v` must offer `id_ed25519_runpod` |
| Pod comes up with no GPU | Terminate and redeploy — that machine has no free L40S |
| `sleep infinity` pod has no shell | Redeploy; if the JSON form is rejected, fall back to run 1's shape (vLLM as PID 1) and accept **one** configuration — take blocks A and C's checkpoint only, drop B |
| `vllm serve` exits at once | Read `/workspace/run2/serve-*.log`; model name first and bare, no verb |
| CUDA OOM at launch | `--gpu-memory-utilization 0.85`, note it, and the run is no longer comparable to run 1's pool |
| `nvidia-smi` still shows memory after `K` | `pkill -9 -f vllm`, wait 30 s, re-check. Never launch onto an occupied card |
| MNBT 512 rejected | `max_num_batched_tokens` must be ≥ `max_num_seqs` (256). 512 is legal; if it is refused, read the error and try 1 024 |
| FP8 refused on this card | Record the message verbatim — that *is* the finding — and spend the remaining time on block B's dropped level |
| Goodput reads 0 everywhere | `--goodput` values are **milliseconds**; check the parse before believing the curve |
| Measured TTFT far below floor | Prefix caching on. Check the log, re-run the level |
| A number off by >2× | Stop sweeping. Re-read the startup log |
| Anything eats >20 min | Terminate the pod, write down where it died |
