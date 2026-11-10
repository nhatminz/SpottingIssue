#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export QWEN_MODEL_PATH="${QWEN_MODEL_PATH:-/mnt/hdd/nhatminh/SpecDecode/models/Qwen3-4B}"
export QWEN_SERVED_MODEL="${QWEN_SERVED_MODEL:-qwen3-4b}"
export QWEN_HOST="${QWEN_HOST:-127.0.0.1}"
export QWEN_PORT="${QWEN_PORT:-8001}"
export QWEN_MAX_MODEL_LEN="${QWEN_MAX_MODEL_LEN:-32768}"
export QWEN_DTYPE="${QWEN_DTYPE:-bfloat16}"
export QWEN_CPU_THREADS="${QWEN_CPU_THREADS:-4}"
export QWEN_SERVER_BACKEND="${QWEN_SERVER_BACKEND:-transformers}"
export QWEN_TENSOR_PARALLEL_SIZE="${QWEN_TENSOR_PARALLEL_SIZE:-1}"
export QWEN_GPU_MEMORY_UTILIZATION="${QWEN_GPU_MEMORY_UTILIZATION:-0.85}"
[[ -d "$QWEN_MODEL_PATH" ]] || { echo "Thiếu model: $QWEN_MODEL_PATH" >&2; exit 2; }
[[ -x "$PYTHON_BIN" ]] || { echo "Thiếu Python: $PYTHON_BIN" >&2; exit 2; }
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ "$QWEN_SERVER_BACKEND" == vllm ]]; then
  exec "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
    --model "$QWEN_MODEL_PATH" --served-model-name "$QWEN_SERVED_MODEL" \
    --host "$QWEN_HOST" --port "$QWEN_PORT" --dtype "$QWEN_DTYPE" \
    --max-model-len "$QWEN_MAX_MODEL_LEN" --tensor-parallel-size "$QWEN_TENSOR_PARALLEL_SIZE" \
    --gpu-memory-utilization "$QWEN_GPU_MEMORY_UTILIZATION" --reasoning-parser qwen3
elif [[ "$QWEN_SERVER_BACKEND" == transformers ]]; then
  exec "$PYTHON_BIN" -m legal_issue_pipeline.local_server
else
  echo "QWEN_SERVER_BACKEND phải là transformers hoặc vllm" >&2; exit 2
fi
