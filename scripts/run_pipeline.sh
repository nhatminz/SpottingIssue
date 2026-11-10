#!/usr/bin/env bash
set -euo pipefail

# Chỉnh trực tiếp các default hoặc đặt biến môi trường trước khi chạy.
# Đường dẫn model local thuộc server; client dùng GEN_MODEL/JUDGE_MODEL là ID API.
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="${PROJECT_ROOT:-$SCRIPT_ROOT}"
export PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"

# Input/output: không sửa input. LIMIT=0 là toàn bộ; START_INDEX bắt đầu từ 0.
export INPUT_PATH="${INPUT_PATH:-$PROJECT_ROOT/input/judgment_with_situation.jsonl}"
export OUTPUT_PATH="${OUTPUT_PATH:-$PROJECT_ROOT/output/judgment_with_issues.jsonl}"
# File riêng cho vụ bị loại; mặc định nằm cạnh OUTPUT_PATH, không trộn vào labels.
export REJECTED_PATH="${REJECTED_PATH:-$(dirname -- "$OUTPUT_PATH")/rejected_cases.jsonl}"
export AUDIT_DIR="${AUDIT_DIR:-$PROJECT_ROOT/output/audit}"
export LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/output/logs}"
export CHECKPOINT_DIR="${CHECKPOINT_DIR:-$PROJECT_ROOT/output/checkpoints}"
export PROMPT_DIR="${PROMPT_DIR:-$PROJECT_ROOT/prompts}"
export RESUME="${RESUME:-true}"
export OVERWRITE_OUTPUT="${OVERWRITE_OUTPUT:-false}"

# GPU/runtime: CUDA ở client không đổi GPU của server đã chạy.
# MAX_WORKERS: số vụ đồng thời; MAX_CONCURRENT_REQUESTS: tổng request đang bay.
# BATCH_SIZE: số vụ tối đa được giữ trong mỗi đợt, không phải batch token của GPU.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export MAX_WORKERS="${MAX_WORKERS:-1}"
export MAX_CONCURRENT_REQUESTS="${MAX_CONCURRENT_REQUESTS:-1}"
export BATCH_SIZE="${BATCH_SIZE:-8}"
export START_INDEX="${START_INDEX:-0}"
export LIMIT="${LIMIT:-0}"
export RANDOM_SEED="${RANDOM_SEED:-42}"

# Generator: endpoint/API model ID riêng. Secret file chỉ dùng khi API_KEY rỗng.
# null = không gửi sampling parameter. extra_high -> max; medium -> high ở DeepSeek.
export GEN_API_BASE="${GEN_API_BASE:-http://127.0.0.1:8000/v1}"
export GEN_API_KEY="${GEN_API_KEY:-}"
export GEN_API_KEY_FILE="${GEN_API_KEY_FILE:-}"
export GEN_MODEL="${GEN_MODEL:-deepseek-flash}"
export GEN_BACKEND="${GEN_BACKEND:-deepseek}"
export GEN_THINKING_ENABLED="${GEN_THINKING_ENABLED:-true}"
export GEN_THINKING_EFFORT="${GEN_THINKING_EFFORT:-extra_high}"
export GEN_MAX_OUTPUT_TOKENS="${GEN_MAX_OUTPUT_TOKENS:-16384}"
export GEN_TEMPERATURE="${GEN_TEMPERATURE:-null}"
export GEN_TOP_P="${GEN_TOP_P:-null}"
export GEN_SEED="${GEN_SEED:-null}"
export GEN_TIMEOUT="${GEN_TIMEOUT:-null}"
export GEN_MAX_RETRIES="${GEN_MAX_RETRIES:-3}"
export GEN_GENERIC_THINKING_STYLE="${GEN_GENERIC_THINKING_STYLE:-qwen}"
export GEN_SUPPORTED_EFFORTS="${GEN_SUPPORTED_EFFORTS:-[\"low\",\"high\",\"max\"]}"
export GEN_FALLBACK_EFFORT="${GEN_FALLBACK_EFFORT:-high}"
export GEN_STRUCTURED_OUTPUT_MODE="${GEN_STRUCTURED_OUTPUT_MODE:-json_object}"
export GEN_STOP="${GEN_STOP:-[]}"
export GEN_EXTRA_BODY="${GEN_EXTRA_BODY:-}"
if [[ -z "$GEN_EXTRA_BODY" ]]; then export GEN_EXTRA_BODY='{}'; fi

# Judge: có client/system prompt/context/inference riêng, dù dùng chung endpoint.
export JUDGE_API_BASE="${JUDGE_API_BASE:-http://127.0.0.1:8000/v1}"
export JUDGE_API_KEY="${JUDGE_API_KEY:-}"
export JUDGE_API_KEY_FILE="${JUDGE_API_KEY_FILE:-}"
export JUDGE_MODEL="${JUDGE_MODEL:-deepseek-flash}"
export JUDGE_BACKEND="${JUDGE_BACKEND:-deepseek}"
export JUDGE_THINKING_ENABLED="${JUDGE_THINKING_ENABLED:-true}"
export JUDGE_THINKING_EFFORT="${JUDGE_THINKING_EFFORT:-extra_high}"
export JUDGE_MAX_OUTPUT_TOKENS="${JUDGE_MAX_OUTPUT_TOKENS:-16384}"
export JUDGE_TEMPERATURE="${JUDGE_TEMPERATURE:-null}"
export JUDGE_TOP_P="${JUDGE_TOP_P:-null}"
export JUDGE_SEED="${JUDGE_SEED:-null}"
export JUDGE_TIMEOUT="${JUDGE_TIMEOUT:-null}"
export JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-3}"
export JUDGE_GENERIC_THINKING_STYLE="${JUDGE_GENERIC_THINKING_STYLE:-qwen}"
export JUDGE_SUPPORTED_EFFORTS="${JUDGE_SUPPORTED_EFFORTS:-[\"low\",\"high\",\"max\"]}"
export JUDGE_FALLBACK_EFFORT="${JUDGE_FALLBACK_EFFORT:-high}"
export JUDGE_STRUCTURED_OUTPUT_MODE="${JUDGE_STRUCTURED_OUTPUT_MODE:-json_object}"
export JUDGE_STOP="${JUDGE_STOP:-[]}"
export JUDGE_EXTRA_BODY="${JUDGE_EXTRA_BODY:-}"
if [[ -z "$JUDGE_EXTRA_BODY" ]]; then export JUDGE_EXTRA_BODY='{}'; fi

# Debate: N cycles Judge -> Generator, luôn thêm final Judge sau lần sửa cuối.
# MAX_DEBATE_ROUNDS mặc định 8; production có thể chỉnh 5–10.
# FINALIZE_POLICY chỉ chọn candidate trong private audit, không quyết định output.
# UNRESOLVED_POLICY=reject: bỏ vụ không đạt, lưu riêng, tiếp tục vụ kế tiếp.
# Giá trị cũ stop/continue được chuyển thành reject có warning.
export MAX_DEBATE_ROUNDS="${MAX_DEBATE_ROUNDS:-8}"
export ENABLE_EARLY_STOP="${ENABLE_EARLY_STOP:-true}"
export ENABLE_GENERATOR_REBUTTAL="${ENABLE_GENERATOR_REBUTTAL:-true}"
export ENABLE_JUDGE_RECONSIDERATION="${ENABLE_JUDGE_RECONSIDERATION:-true}"
export ENABLE_BLIND_JUDGE_DISCOVERY="${ENABLE_BLIND_JUDGE_DISCOVERY:-false}"
export STOP_ON_STAGNATION="${STOP_ON_STAGNATION:-true}"
export MAX_STAGNANT_ROUNDS="${MAX_STAGNANT_ROUNDS:-2}"
export FINALIZE_POLICY="${FINALIZE_POLICY:-best_valid}"
export UNRESOLVED_POLICY="${UNRESOLVED_POLICY:-reject}"

# Validation: tắt kiểm tra cốt lõi không đủ điều kiện xuất nhãn (REJECTED).
# SITUATION_ERROR_POLICY: material_missing hoặc material_missing_or_contradiction.
export STRICT_FORMAT="${STRICT_FORMAT:-true}"
export ENABLE_EVIDENCE_VALIDATION="${ENABLE_EVIDENCE_VALIDATION:-true}"
export ENABLE_DEDUPLICATION="${ENABLE_DEDUPLICATION:-true}"
export ENABLE_COVERAGE_CHECK="${ENABLE_COVERAGE_CHECK:-true}"
export ENABLE_SITUATION_AUDIT="${ENABLE_SITUATION_AUDIT:-true}"
export SITUATION_ERROR_POLICY="${SITUATION_ERROR_POLICY:-material_missing}"
export MAX_JSON_REPAIR_RETRIES="${MAX_JSON_REPAIR_RETRIES:-2}"
export REQUIRE_STRUCTURED_OUTPUT="${REQUIRE_STRUCTURED_OUTPUT:-true}"

# Context/request: vượt context thì dừng, không cắt bản án để kết luận sai audit.
# TOKENIZER_PATH tuỳ chọn local tokenizer để đếm chính xác; rỗng dùng byte upper bound.
# API_EXTRA_BODY JSON chung; *_EXTRA_BODY ghi đè có log, không cho ghi đè messages/model.
export MAX_CONTEXT_TOKENS="${MAX_CONTEXT_TOKENS:-131072}"
export MAX_INPUT_TOKENS="${MAX_INPUT_TOKENS:-100000}"
export TRUNCATION_POLICY="${TRUNCATION_POLICY:-error}"
export TOKENIZER_PATH="${TOKENIZER_PATH:-}"
export API_REQUEST_TIMEOUT="${API_REQUEST_TIMEOUT:-300}"
export RETRY_BACKOFF="${RETRY_BACKOFF:-1}"
export RETRY_JITTER="${RETRY_JITTER:-0.25}"
export API_EXTRA_BODY="${API_EXTRA_BODY:-}"
if [[ -z "$API_EXTRA_BODY" ]]; then export API_EXTRA_BODY='{}'; fi
export THINKING_UNSUPPORTED_POLICY="${THINKING_UNSUPPORTED_POLICY:-fail}"

# Logging/debug: raw chỉ lưu final content, tuyệt đối không reasoning_content/API keys.
# DRY_RUN chỉ kiểm tra input/config/prompt, không gọi model, không ghi output/checkpoint.
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export SAVE_DEBATE_HISTORY="${SAVE_DEBATE_HISTORY:-true}"
export SAVE_RAW_RESPONSES="${SAVE_RAW_RESPONSES:-false}"
export SAVE_TOKEN_USAGE="${SAVE_TOKEN_USAGE:-true}"
export DRY_RUN="${DRY_RUN:-false}"
export FAIL_ON_RECORD_ERROR="${FAIL_ON_RECORD_ERROR:-true}"

[[ -f "$INPUT_PATH" ]] || { echo "Không tìm thấy INPUT_PATH: $INPUT_PATH" >&2; exit 2; }
[[ -d "$PROMPT_DIR" ]] || { echo "Không tìm thấy PROMPT_DIR: $PROMPT_DIR" >&2; exit 2; }
[[ -x "$PYTHON_BIN" ]] || { echo "Không tìm thấy Python >=3.10: $PYTHON_BIN; xem README.md" >&2; exit 2; }
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m legal_issue_pipeline.cli "${1:-run}"
