#!/usr/bin/env bash
# Validate the sweep parameter files without a GPU: `vllm bench sweep serve
# --dry-run` only expands and prints the commands, and the vLLM CPU image
# carries the same CLI as the GPU build, so this runs on a laptop.
#
# Usage:  bench/sweep/dry-run.sh            (defaults to serve-params.json / bench-params.json)
#         bench/sweep/dry-run.sh <serve-params.json> <bench-params.json>
set -euo pipefail

VLLM_TAG="${VLLM_TAG:-v0.27.1}"          # the tag runs 1-3 used; MI300X may pin another
HERE="$(cd "$(dirname "$0")" && pwd)"
ARCH="$(uname -m)"; [ "$ARCH" = "aarch64" ] && ARCH=arm64   # image tags: -arm64 / -x86_64
SERVE_PARAMS="${1:-serve-params.json}"
BENCH_PARAMS="${2:-bench-params.json}"

# The base commands. Every knob the sweep varies must appear here exactly once
# (so an override replaces it) or not at all (so it is appended) -- a boolean
# knob spelled as --no-X in the base command and X: true in the params yields
# both flags on one line, and only argparse's last-wins order saves it.
SERVE_CMD="vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --dtype auto \
  --gpu-memory-utilization 0.90 --max-model-len 9000 --no-enable-prefix-caching \
  --max-num-batched-tokens 2048 --kv-cache-dtype auto"
BENCH_CMD="vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --request-rate inf \
  --max-concurrency 8 --num-prompts 48 --metric-percentiles 50,90,99"

# --percentile-metrics, --save-result, --result-dir and --result-filename are
# appended by the sweep itself, so they are deliberately absent from BENCH_CMD.
docker run --rm -v "$HERE":/sweep:ro --entrypoint vllm \
  "vllm/vllm-openai-cpu:${VLLM_TAG}-${ARCH}" \
  bench sweep serve \
    --serve-cmd "$SERVE_CMD" --bench-cmd "$BENCH_CMD" \
    --serve-params "/sweep/$SERVE_PARAMS" --bench-params "/sweep/$BENCH_PARAMS" \
    --num-runs 3 -o /tmp/results -e dry-run --dry-run \
  | grep -v '^INFO'
