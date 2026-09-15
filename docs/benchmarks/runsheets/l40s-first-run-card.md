# Card — L40S first run

Execution only. Every *why* is in `l40s-first-run.md`, which wins on any conflict.
Budget: 2.5 h, ~$2.50. **Terminate** the pod at 2.5 h or when step 6 is done —
terminate, not stop: everything is on the network volume, a stop releases the GPU
anyway and keeps billing the disk.

**Where each block runs.** Three contexts all day, tagged before every command:

| Tag | Where | What lives there |
|---|---|---|
| `[laptop]` | local terminal, in this repo | step 0's two scripts; every paste of results |
| `[console]` | RunPod web UI | deploy form, Container Start Command, **Logs tab**, Terminate |
| `[pod]` | SSH session on the pod | everything else |
| `[pod-2]` | a second SSH session | only the metrics read during c=45 |

`[console]` work cannot be done over SSH and the reverse: the deploy form is read
once, as the pod starts, and vLLM is PID 1 — its stdout is the console log and
never a file on `/workspace`. SSH exists only while the pod runs; after Terminate
there is no container to connect to. **Expect no web terminal** on this image —
basic SSH is the shell.

---

## 0 · Off the clock

**`[laptop]`**

```
python3 bench/tests/test_roofline.py      # must print 32/32 passed
python3 bench/predictions.py        # keep tables 6 and 7 open
```

- [ ] `[console]` RunPod: balance loaded (deploy needs **≥ 1 h of the config** in
      credits), MFA on, L40S On-Demand visible in a **North American** data centre.
- [ ] `[console]` Off the deploy page, before renting: the template's own
      Container Start Command, the $/h against $0.99 Secure, and whether a
      **Community** NA data centre offers a network volume — that is the $0.79
      route.
- [ ] If time runs short, drop sweep levels in this order: **8, 16, 32.** Never
      1, 23, 24, 45, and never step 5.

## 1 · Deploy the pod (~10 min)

**`[console]`** — Template **vLLM Latest**, **GPU count 1**.

| Field | Value |
|---|---|
| Image | **`vllm/vllm-openai:v0.27.1`** — override the template's `:latest` |
| Network volume | **25 GB → `/workspace`**, North American DC. **Attach at deploy** — it cannot be added later |
| Container disk | leave at template default |
| `HF_HOME` | **set** `/workspace/.huggingface` — do not inspect, do not assume |
| `VLLM_CACHE_ROOT` | `/workspace/.vllm` |
| `VLLM_API_KEY` | the `sk-…` from the password manager — paste into the env var **at deploy**, it is read once at start |

**Container Start Command** — replace the template's line entirely. **This is the
only boot of the day**, so `9000` is on it from the first second:

```
Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --dtype auto --gpu-memory-utilization 0.90 --max-model-len 9000 --no-enable-prefix-caching
```

Deploy, then, in this order:

- [ ] `[pod]` **Gate — open a shell NOW**, while the weights download:
      `ssh <pod-id>-<hash>@ssh.runpod.io`. Type `echo ok`. No shell → stop, see
      "If it breaks". **No `-i`** — `~/.ssh/config` pins the key. Take
      `user@host` from the console's Connect dialog and **drop the
      `-i ~/.ssh/id_ed25519` it appends**: that is the wrong key, and the flag
      beats the config.
- [ ] `[console]` Record the image tag for the report.
- [ ] `[pod]` Record `vllm --version` (expect **0.27.1**; anything else and the
      log lines below are the first thing to re-check) and the `nvidia-smi`
      driver line.

## 2 · The boot → Checkpoint A (~20 min)

**`[console]`** — watch the **Logs tab**. Ready at `Application startup complete`
(~16.4 GB download first).

**Copy these out of the console NOW — RunPod keeps no logs once the pod is gone:**

| Log line | Predicted | Measured |
|---|---|---|
| `Model loading took … GiB memory` | ≈ 15.3 GiB | |
| `GPU KV cache size` (note: `181,749` with commas) | **≤ 181 749** tokens — expect **~160–170 k** | |
| `Maximum concurrency for 9,000 tokens…` | ≈ 20.2× at the bound → **expect ~17.8–18.9×** | |
| `Graph capturing finished … took … GiB` | 1–3 GiB — this is the gap | |
| `CUDA graph pool memory: … GiB (actual)` | same figure, restated | |
| `block_size` | 16 | |
| `max_num_batched_tokens` + chunked prefill | **predicted 2 048**, chunked prefill on (sub-70-GiB card) | |
| `max_num_seqs` | **expect 256** (same branch) | |
| `enable_prefix_caching` | **False** | |

`GPU KV cache size` and `Maximum concurrency` are **two separate lines** at
v0.27.1.

**`[pod]`** — smoke test (`127.0.0.1`, never `localhost`):

```
curl -s 127.0.0.1:8000/v1/models -H "Authorization: Bearer $VLLM_API_KEY"

curl -s 127.0.0.1:8000/v1/completions \
  -H "Authorization: Bearer $VLLM_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3-8B","prompt":"The capital of Finland is",
       "max_tokens":16,"temperature":0}'
```

- [ ] First returns the model id — **copy it exactly**, it goes to `--model`.
- [ ] Second returns a plausible continuation.
- [ ] 401? The shell lacks the variable, not the server:
      `[ -n "$VLLM_API_KEY" ] && echo present || echo MISSING`, then

      ```
      export $(tr '\0' '\n' < /proc/1/environ | grep '^VLLM_API_KEY=')
      ```

      `source /etc/rp_environment` is the *second* try, not the first — that file
      belongs to RunPod's base images, not to this one. Never a restart.

## 3 · Checkpoint B — on paper, no second boot (~2 min)

The second boot was cut: editing or redeploying to move `max_model_len` risks the
card for one observation. Full reasoning in the long sheet.

**`[laptop]`** — take the pool from checkpoint A and divide:

| | Predicted | Computed |
|---|---|---|
| pool ÷ 9 000 | ≈ 20.2× at bound / ~17.8–18.9× real | (from the log, step 2) |
| pool ÷ 4 096 | ≈ 44.4× at bound / ~39.1–41.5× real | |

- [ ] Recorded as **derived, never measured** (§9).

## 4 · Sweep 1 — concurrency (~40 min)

**`[pod]`** — everything in this step and the next, in one session.

Once:

```
vllm bench serve --help | grep -E "random-range-ratio|save-result|result-dir|result-filename"
export OPENAI_API_KEY="$VLLM_API_KEY"
```

`grep`, never `less` — no pager in this image. Four lines must come back:
`--random-range-ratio`, `--save-result`, `--result-dir`, `--result-filename`. All
four are in `S()` below (`0` = fixed length). If the release rejects one, drop it
from `S()` and note it.

Define once:

```
S() { vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B --dataset-name random \
  --random-output-len 200 --random-range-ratio 0 --ignore-eos --request-rate inf \
  --save-result --result-dir /workspace --result-filename "sweep-$4.json" \
  --random-input-len "$1" --max-concurrency "$2" --num-prompts "$3" \
  2>&1 | tee "/workspace/sweep-$4.txt"; }

M() { curl -s 127.0.0.1:8000/metrics \
  | grep -E '^vllm:(num_preemptions_total|num_requests_waiting|num_requests_running)\{'; }
```

**`S` and `M` live in this shell only.** Step 5 runs here too; the second
terminal at c=45 gets `M`'s `curl` written out in full, not `M`.

Run the levels **in this order**, reading `M` before and after each:

```
M; S 4000  1  20 c1;  M
M; S 4000  8  32 c8;  M
M; S 4000 16  64 c16; M
M; S 4000 23  92 c23; M
M; S 4000 24  96 c24; M
M; S 4000 32 128 c32; M
M; S 4000 45 180 c45; M
```

| c | TPOT p50 must be ≥ | Measured |
|---|---|---|
| 1 | 28.09 ms | |
| 8 | 34.92 ms | |
| 16 | 42.72 ms | |
| **23** | **49.55 ms** — inside 50 | |
| **24** | **50.52 ms** — breaches | |
| 32 | 58.32 ms | |
| 45 | 71.00 ms | |

- [ ] `[pod-2]` At c=45, **while the level runs**, in a second SSH session — `M`
      is not defined there, so the whole line:

      ```
      curl -s 127.0.0.1:8000/metrics \
        | grep -E '^vllm:(num_preemptions_total|num_requests_waiting|num_requests_running)\{'
      ```

      Record `num_requests_waiting` next to TTFT p99.
- [ ] Predicted: preemptions stay at 0 through c=32; at c=45 either preemptions
      move or waiting stays non-zero. Record which. **Which one to expect depends
      on the logged pool**: above 180 000 → pressure arrives late, preemption
      likely; below → prefills alone do not fit, sustained waiting likely.
- [ ] The 50 ms line: **23/24 is where the derivation crosses.** Where the
      *measurement* crosses is the day's answer, and the distance between them is
      the `eff_mem` calibration — not a failed prediction.
- [ ] **STOP the day if any p50 lands *below* its floor** — check
      `enable_prefix_caching` and the KV pool from checkpoint A first.

## 5 · Sweep 2 — prompt length (~25 min)

**`[pod]`** — same server, no restart, **same session as step 4**: `S` is defined
there. Concurrency fixed at 4.

```
S 2000 4 20 len2000
S 4000 4 20 len4000
S 8000 4 20 len8000
```

| Input | TTFT p50 ≥ | TPOT p50 ≥ | Measured |
|---|---|---|---|
| 2 000 | 170.6 ms | 29.07 ms | |
| 4 000 | 341.3 ms | 31.02 ms | |
| 8 000 | 682.5 ms | 34.92 ms | |

- [ ] TTFT must roughly **double** per doubling, **and the ratio to its floor must
      stay roughly constant (~4×)** — the floors assume one-step prefill, but
      `max_num_batched_tokens` is 2 048, so 4 000 takes two steps and 8 000 four.
      **If the ratio itself climbs steeply, stop here.**

## 6 · Close (~5 min on the clock)

**`[pod]`** — harvest first, while the container still exists:

```
ls -la /workspace/sweep-*.txt /workspace/sweep-*.json    # 20 files expected
tail -n 40 /workspace/sweep-*.txt
```

- [ ] `[laptop]` Ten summaries pasted into the scratch file, **verbatim**, each
      with a median TTFT and TPOT actually present.
- [ ] `[console]` From the **Logs tab**, one periodic line from inside the c=45
      level — it carries `Prefix cache hit rate`. `Preemptions:` appears only once
      the counter is > 0, and the whole line drops to DEBUG when idle — silence
      between levels is normal.
- [ ] Checkpoint A already pasted (step 2). Console logs are gone after the
      terminate; sweep files are recoverable from the volume.
- [ ] `[console]` **Terminate the pod.** Record actual $ spent against $2.50.

Off the clock: `docs/benchmarks/l40s-baseline.md` and the glossary entries for
whatever the run introduced — see the long sheet.

---

## If it breaks

| Symptom | Do |
|---|---|
| SSH: `Permission denied (publickey)` | Wrong key, not a dead pod. Re-run without `-i`; `ssh -v` must show `id_ed25519_runpod` offered |
| No web terminal, basic SSH refused | Redeploy, start command in JSON form: `{"entrypoint": ["bash", "-lc"], "cmd": ["sleep infinity"]}`, launch `vllm serve` by hand with the same flags. Then `nvidia-smi` must show the card empty between runs — long sheet |
| Pod comes up with **no GPU** | Zero-GPU pod: that machine has no free L40S. Terminate and deploy again — do not wait |
| A knob must move after all | `PATCH /pods/{id}` with `dockerStartCmd` → Edit Pod if the field exists → redeploy on the same volume. Terminate pod #1 first, checkpoint A out of its console first |
| `$VLLM_API_KEY` empty in the shell | `export $(tr '\0' '\n' < /proc/1/environ \| grep '^VLLM_API_KEY=')`. Not a restart |
| Pod exits in seconds, `unrecognized arguments` | Start command is malformed — model name first and bare, no verb |
| CUDA OOM at boot | `--gpu-memory-utilization 0.85` first; `--max-model-len` only second, and never below 8 200. Note which |
| Measured TTFT far below floor | Prefix caching is on. Check the log, re-run the level |
| Weights download on a later pod | `df -h`, `echo $HF_HOME`, `ls /root/.cache/huggingface` |
| `vllm bench serve` flag rejected | `--help` wins; fix the sheet afterwards |
| A number off by >2× | Stop sweeping. Re-read the startup log |
| Anything eats >20 min | Terminate the pod, write down where it died |
