# Raw evidence — L40S run 1, 2026-08-18

Verbatim capture, no interpretation. The analysis lives in
`docs/benchmarks/l40s-baseline.md`; the checklist the run followed is
`docs/benchmarks/runsheets/l40s-first-run-card.md`.

| File | What it is |
|---|---|
| `pod-console.log` | RunPod Logs tab, full download. Boot, engine config, periodic `Engine 000:` lines |
| `concurrency/cNN.txt` | `vllm bench serve` stdout per concurrency level, input 4 000, output 200 |
| `concurrency/c45-metrics-maxima.txt` | the four maxima extracted in-pod at c=45 |
| `prompt-length/lenNNNN.txt` | same, concurrency fixed at 4, input 2 000 / 4 000 / 8 000 |
| `sweep-json-and-c45-metrics.txt` | terminal dump of all 12 `sweep-*.json` plus the c=45 sampler, as pasted |
| `results.jsonl` | the 12 JSON objects, one per line, sorted by concurrency then input length |
| `c45-metrics.tsv` | the c=45 sampler as `time running waiting kv_usage preemptions`, 162 samples at 2 s |

## Provenance notes

- **`pod-console.log` has a hole from 12:28:10 to 12:51:20** — the levels c=16
  through c=45. RunPod's Logs tab returned 46 `Engine 000:` lines for a 75-minute
  run and dropped that window; two separate downloads produced the same hole. The
  in-pod metrics sampler covers c=45 instead, which is why `c45-metrics.tsv`
  exists. A provider's log viewer is not a record.
- Environment: image `vllm/vllm-openai:v0.27.1`, `vllm --version` 0.27.1,
  fingerprint `vllm-0.27.1-d58650c8`, driver 580.159.04 / CUDA 13.0, one L40S
  reporting 46 068 MiB, FlashAttention 2 backend, pod `4vtd8ye7ae3en3`.
- Server flags: `--dtype auto` (resolved BF16), `--gpu-memory-utilization 0.90`,
  `--max-model-len 9000`, `--no-enable-prefix-caching`, `--host 127.0.0.1`.
- All levels: `--random-range-ratio 0` (fixed length), `--ignore-eos`,
  `--request-rate inf`, zero failed requests.
- `vllm bench serve` no longer forces `temperature=0`; sampling was server-default
  throughout. It does not affect timing under fixed input and output lengths, but
  the generated text is not reproducible.
