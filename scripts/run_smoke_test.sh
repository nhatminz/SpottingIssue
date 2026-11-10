#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
export PROJECT_ROOT
# Mọi artifact smoke tách khỏi production. SMOKE_ROOT mới cho cấu hình mới.
export SMOKE_ROOT="${SMOKE_ROOT:-$PROJECT_ROOT/output/smoke}"
export OUTPUT_PATH="${OUTPUT_PATH:-$SMOKE_ROOT/judgment_with_issues.jsonl}"
export REJECTED_PATH="${REJECTED_PATH:-$SMOKE_ROOT/rejected_cases.jsonl}"
export AUDIT_DIR="${AUDIT_DIR:-$SMOKE_ROOT/audit}"
export LOG_DIR="${LOG_DIR:-$SMOKE_ROOT/logs}"
export CHECKPOINT_DIR="${CHECKPOINT_DIR:-$SMOKE_ROOT/checkpoints}"
export GEN_API_BASE="${GEN_API_BASE:-http://127.0.0.1:8001/v1}"
export JUDGE_API_BASE="${JUDGE_API_BASE:-$GEN_API_BASE}"
export GEN_MODEL="${GEN_MODEL:-qwen3-4b}"
export JUDGE_MODEL="${JUDGE_MODEL:-$GEN_MODEL}"
export GEN_BACKEND=generic JUDGE_BACKEND=generic
export GEN_THINKING_ENABLED="${GEN_THINKING_ENABLED:-false}"
export JUDGE_THINKING_ENABLED="${JUDGE_THINKING_ENABLED:-false}"
export GEN_THINKING_EFFORT="${GEN_THINKING_EFFORT:-none}"
export JUDGE_THINKING_EFFORT="${JUDGE_THINKING_EFFORT:-none}"
export GEN_STRUCTURED_OUTPUT_MODE="${GEN_STRUCTURED_OUTPUT_MODE:-json_schema}"
export JUDGE_STRUCTURED_OUTPUT_MODE="${JUDGE_STRUCTURED_OUTPUT_MODE:-json_schema}"
export GEN_TEMPERATURE="${GEN_TEMPERATURE:-0.7}"
export JUDGE_TEMPERATURE="${JUDGE_TEMPERATURE:-0.7}"
export GEN_TOP_P="${GEN_TOP_P:-0.8}"
export JUDGE_TOP_P="${JUDGE_TOP_P:-0.8}"
export GEN_SEED="${GEN_SEED:-42}"
export JUDGE_SEED="${JUDGE_SEED:-42}"
export GEN_EXTRA_BODY="${GEN_EXTRA_BODY:-}"
export JUDGE_EXTRA_BODY="${JUDGE_EXTRA_BODY:-}"
if [[ -z "$GEN_EXTRA_BODY" ]]; then export GEN_EXTRA_BODY='{"repetition_penalty":1.05}'; fi
if [[ -z "$JUDGE_EXTRA_BODY" ]]; then export JUDGE_EXTRA_BODY='{"repetition_penalty":1.05}'; fi
export GEN_MAX_OUTPUT_TOKENS="${GEN_MAX_OUTPUT_TOKENS:-4096}"
export JUDGE_MAX_OUTPUT_TOKENS="${JUDGE_MAX_OUTPUT_TOKENS:-8192}"
export MAX_CONTEXT_TOKENS="${MAX_CONTEXT_TOKENS:-32768}"
export MAX_INPUT_TOKENS="${MAX_INPUT_TOKENS:-24000}"
export TOKENIZER_PATH="${TOKENIZER_PATH:-/mnt/hdd/nhatminh/SpecDecode/models/Qwen3-4B}"
export LIMIT="${LIMIT:-2}"
export MAX_DEBATE_ROUNDS="${MAX_DEBATE_ROUNDS:-2}"
# Chỉ PASS vào output; vụ không đạt lưu REJECTED, lỗi kỹ thuật giữ FAILED.
export UNRESOLVED_POLICY="${UNRESOLVED_POLICY:-reject}"
export GEN_TIMEOUT="${GEN_TIMEOUT:-600}"
export JUDGE_TIMEOUT="${JUDGE_TIMEOUT:-600}"
bash "$PROJECT_ROOT/scripts/run_pipeline.sh" "${1:-run}"
if [[ "${1:-run}" == run && "${DRY_RUN:-false}" != true ]]; then
  bash "$PROJECT_ROOT/scripts/run_pipeline.sh" validate
fi
