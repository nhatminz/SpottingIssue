#!/usr/bin/env bash
set -euo pipefail

# B200: client chỉ gọi HTTP tới DeepSeek đã serve, không load model/GPU local.
# Chỉnh default tại đây hoặc override bằng environment variables.
# Nếu chạy checkout ở nơi khác, đặt PROJECT_ROOT=/duong/dan/LegalDataset.
export PROJECT_ROOT="${PROJECT_ROOT:-/workspace/storage-shared/nlp/minhpn19/LegalDataset}"
export PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"

# Endpoint và model ID đã được cung cấp cho DeepSeek V4.1 Flash 1017.
# Đây là ID server expose qua /v1/models, không phải filesystem path tới weights.
# Đổi hai biến này để chuyển cả hai agent; GEN_/JUDGE_ vẫn override độc lập được.
export DEEPSEEK_API_BASE="${DEEPSEEK_API_BASE:-http://172.29.62.173:8000/v1}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-DeepSeek-V4.1-Flash-1017}"

# Input/output: không sửa input. LIMIT=0 là toàn bộ; START_INDEX bắt đầu từ 0.
export INPUT_PATH="${INPUT_PATH:-$PROJECT_ROOT/input/sample_input.jsonl}"
export FEWSHOT_PATH="${FEWSHOT_PATH:-$PROJECT_ROOT/input/fewshot.jsonl}"
export OUTPUT_PATH="${OUTPUT_PATH:-$PROJECT_ROOT/output/judgment_with_issues.jsonl}"
# File riêng cho vụ bị loại; mặc định nằm cạnh OUTPUT_PATH, không trộn vào labels.
export REJECTED_PATH="${REJECTED_PATH:-$(dirname -- "$OUTPUT_PATH")/rejected_cases.jsonl}"
export AUDIT_DIR="${AUDIT_DIR:-$PROJECT_ROOT/output/audit}"
export LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/output/logs}"
export CHECKPOINT_DIR="${CHECKPOINT_DIR:-$PROJECT_ROOT/output/checkpoints}"
export PROMPT_DIR="${PROMPT_DIR:-$PROJECT_ROOT/prompts}"
export RESUME="${RESUME:-true}"
export OVERWRITE_OUTPUT="${OVERWRITE_OUTPUT:-false}"

# Runtime phía client: không cần xin GPU. CUDA không đổi GPU của model server.
# Giữ biến caller đã đặt; mặc định rỗng. TOKENIZER_PATH rỗng => không cần Torch.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES-}"
# Số bản án được xử lý đồng thời; một worker giữ một vụ qua toàn bộ debate.
export MAX_WORKERS="${MAX_WORKERS:-40}"
# Tổng số HTTP inference requests đang chờ response, tính chung Generator/Judge.
export MAX_CONCURRENT_REQUESTS="${MAX_CONCURRENT_REQUESTS:-40}"
# Số bản án trong một đợt; xong cả đợt mới đưa đợt kế tiếp vào xử lý.
# Không phải batch GPU/token của server. Nên >= MAX_WORKERS để tận dụng workers.
# 100 vụ/đợt: tối đa 40 vụ chạy, các vụ còn lại chờ worker vừa xong.
export BATCH_SIZE="${BATCH_SIZE:-100}"
# Index bản ghi đầu tiên trong INPUT (0-based): 0=dòng 1; 100=dòng 101.
export START_INDEX="${START_INDEX:-0}"
# Số bản ghi INPUT được chọn từ START_INDEX; 0=đến cuối file.
# Đây không phải số vụ PASS cần thu được; REJECTED/FAILED vẫn thuộc phạm vi chọn.
export LIMIT="${LIMIT:-0}"
export RANDOM_SEED="${RANDOM_SEED:-42}"

# Generator: endpoint/API model ID riêng. Secret file chỉ dùng khi API_KEY rỗng.
# deepseek_vllm: chat_template_kwargs; low=25, high=50, xhigh=75, max=100.
# Có thể đặt số nguyên 1–100; đây là effort budget, không phải số token.
# medium/minimal không hợp lệ ở vLLM. extra_high là alias cũ của pipeline -> max.
# deepseek dành riêng cho hosted API với cách ánh xạ tier khác; generic cho Qwen.
# null = không gửi sampling parameter. THINKING_ENABLED=false hoặc EFFORT=none để tắt.
export GEN_API_BASE="${GEN_API_BASE:-$DEEPSEEK_API_BASE}"
export GEN_API_KEY="${GEN_API_KEY:-}"
export GEN_API_KEY_FILE="${GEN_API_KEY_FILE:-}"
export GEN_MODEL="${GEN_MODEL:-$DEEPSEEK_MODEL}"
export GEN_BACKEND="${GEN_BACKEND:-deepseek_vllm}"
export GEN_THINKING_ENABLED="${GEN_THINKING_ENABLED:-true}"
export GEN_THINKING_EFFORT="${GEN_THINKING_EFFORT:-high}"
# Trần token SINH MỚI của MỖI request Generator, gửi thành max_tokens tới API.
# Thinking + final JSON dùng budget này theo cách tính của backend.
# Mỗi lượt có budget 131073 riêng; không trừ token đã dùng ở lượt trước.
export GEN_MAX_OUTPUT_TOKENS="${GEN_MAX_OUTPUT_TOKENS:-131073}"
export GEN_TEMPERATURE="${GEN_TEMPERATURE:-null}"
export GEN_TOP_P="${GEN_TOP_P:-null}"
export GEN_SEED="${GEN_SEED:-null}"
export GEN_TIMEOUT="${GEN_TIMEOUT:-null}"
export GEN_MAX_RETRIES="${GEN_MAX_RETRIES:-3}"
export GEN_GENERIC_THINKING_STYLE="${GEN_GENERIC_THINKING_STYLE:-qwen}"
export GEN_SUPPORTED_EFFORTS="${GEN_SUPPORTED_EFFORTS:-[\"low\",\"high\",\"xhigh\",\"max\"]}"
export GEN_FALLBACK_EFFORT="${GEN_FALLBACK_EFFORT:-high}"
export GEN_STRUCTURED_OUTPUT_MODE="${GEN_STRUCTURED_OUTPUT_MODE:-json_object}"
export GEN_STOP="${GEN_STOP:-[]}"
export GEN_EXTRA_BODY="${GEN_EXTRA_BODY:-}"
if [[ -z "$GEN_EXTRA_BODY" ]]; then export GEN_EXTRA_BODY='{}'; fi

# Judge: có client/system prompt/context/inference riêng, dù dùng chung endpoint.
export JUDGE_API_BASE="${JUDGE_API_BASE:-$DEEPSEEK_API_BASE}"
export JUDGE_API_KEY="${JUDGE_API_KEY:-}"
export JUDGE_API_KEY_FILE="${JUDGE_API_KEY_FILE:-}"
export JUDGE_MODEL="${JUDGE_MODEL:-$DEEPSEEK_MODEL}"
export JUDGE_BACKEND="${JUDGE_BACKEND:-deepseek_vllm}"
export JUDGE_THINKING_ENABLED="${JUDGE_THINKING_ENABLED:-true}"
export JUDGE_THINKING_EFFORT="${JUDGE_THINKING_EFFORT:-high}"
# Trần token SINH MỚI của MỖI request Judge; độc lập với budget của Generator.
# Mỗi lượt có budget 131073 riêng; không chia sẻ với Generator hoặc các vòng khác.
export JUDGE_MAX_OUTPUT_TOKENS="${JUDGE_MAX_OUTPUT_TOKENS:-131073}"
export JUDGE_TEMPERATURE="${JUDGE_TEMPERATURE:-null}"
export JUDGE_TOP_P="${JUDGE_TOP_P:-null}"
export JUDGE_SEED="${JUDGE_SEED:-null}"
export JUDGE_TIMEOUT="${JUDGE_TIMEOUT:-null}"
export JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-3}"
export JUDGE_GENERIC_THINKING_STYLE="${JUDGE_GENERIC_THINKING_STYLE:-qwen}"
export JUDGE_SUPPORTED_EFFORTS="${JUDGE_SUPPORTED_EFFORTS:-[\"low\",\"high\",\"xhigh\",\"max\"]}"
export JUDGE_FALLBACK_EFFORT="${JUDGE_FALLBACK_EFFORT:-high}"
export JUDGE_STRUCTURED_OUTPUT_MODE="${JUDGE_STRUCTURED_OUTPUT_MODE:-json_object}"
export JUDGE_STOP="${JUDGE_STOP:-[]}"
export JUDGE_EXTRA_BODY="${JUDGE_EXTRA_BODY:-}"
if [[ -z "$JUDGE_EXTRA_BODY" ]]; then export JUDGE_EXTRA_BODY='{}'; fi

# Debate: N cycles Judge -> Generator, luôn thêm final Judge sau lần sửa cuối.
# Tối đa 6 lượt Judge -> Generator, rồi final Judge; không có lần sửa thứ 7.
# FINALIZE_POLICY chỉ chọn candidate trong private audit, không quyết định output.
# UNRESOLVED_POLICY=reject: bỏ vụ không đạt, lưu riêng, tiếp tục vụ kế tiếp.
# Giá trị cũ stop/continue được chuyển thành reject có warning.
export MAX_DEBATE_ROUNDS="${MAX_DEBATE_ROUNDS:-6}"
export ENABLE_EARLY_STOP="${ENABLE_EARLY_STOP:-true}"
export ENABLE_GENERATOR_REBUTTAL="${ENABLE_GENERATOR_REBUTTAL:-true}"
export ENABLE_JUDGE_RECONSIDERATION="${ENABLE_JUDGE_RECONSIDERATION:-true}"
# Optional discovery và mọi Judge request chỉ dùng facts_clean, không nhận bản án.
export ENABLE_BLIND_JUDGE_DISCOVERY="${ENABLE_BLIND_JUDGE_DISCOVERY:-true}"
export STOP_ON_STAGNATION="${STOP_ON_STAGNATION:-true}"
export MAX_STAGNANT_ROUNDS="${MAX_STAGNANT_ROUNDS:-2}"
export FINALIZE_POLICY="${FINALIZE_POLICY:-best_valid}"
export UNRESOLVED_POLICY="${UNRESOLVED_POLICY:-reject}"

# Validation: tắt kiểm tra cốt lõi không đủ điều kiện xuất nhãn (REJECTED).
export STRICT_FORMAT="${STRICT_FORMAT:-true}"
export ENABLE_EVIDENCE_VALIDATION="${ENABLE_EVIDENCE_VALIDATION:-true}"
export ENABLE_DEDUPLICATION="${ENABLE_DEDUPLICATION:-true}"
export ENABLE_COVERAGE_CHECK="${ENABLE_COVERAGE_CHECK:-true}"
export MAX_JSON_REPAIR_RETRIES="${MAX_JSON_REPAIR_RETRIES:-2}"
export REQUIRE_STRUCTURED_OUTPUT="${REQUIRE_STRUCTURED_OUTPUT:-true}"

# Context/request: vượt context thì dừng, không cắt bản án để kết luận sai audit.
# TOKENIZER_PATH tuỳ chọn local tokenizer để đếm chính xác; rỗng dùng byte upper bound.
# API_EXTRA_BODY JSON chung; *_EXTRA_BODY ghi đè có log, không cho ghi đè messages/model.
# Giới hạn INPUT + OUTPUT của từng request, không cộng hai agent với nhau.
# Đây là guard phía client, không thay đổi context length đang cấu hình trên server.
# Giữ giá trị này <= giới hạn thật server hỗ trợ.
# 262144 chừa chỗ cho 100000 input + 131073 output của MỘT request.
# Server cần hỗ trợ cả max_tokens=131073 và tổng context tương ứng.
export MAX_CONTEXT_TOKENS="${MAX_CONTEXT_TOKENS:-262144}"
# Giới hạn riêng cho toàn prompt đầu vào: system/schema/sources/debate history.
export MAX_INPUT_TOKENS="${MAX_INPUT_TOKENS:-100000}"
export TRUNCATION_POLICY="${TRUNCATION_POLICY:-error}"
export TOKENIZER_PATH="${TOKENIZER_PATH:-}"
# auto: tokenizer local nếu có; nếu backend vLLM dùng /tokenize chính xác.
# Nếu /tokenize không sẵn, auto log và dùng byte upper bound, không tự cắt nguồn.
# vllm: bắt buộc /tokenize; utf8_byte_upper_bound: guard bảo thủ cũ.
export TOKEN_COUNT_METHOD="${TOKEN_COUNT_METHOD:-auto}"
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
[[ -f "$FEWSHOT_PATH" ]] || { echo "Không tìm thấy FEWSHOT_PATH: $FEWSHOT_PATH" >&2; exit 2; }
[[ -d "$PROMPT_DIR" ]] || { echo "Không tìm thấy PROMPT_DIR: $PROMPT_DIR" >&2; exit 2; }
[[ -x "$PYTHON_BIN" ]] || { echo "Không tìm thấy Python >=3.10: $PYTHON_BIN; xem README.md" >&2; exit 2; }
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m legal_issue_pipeline.cli "${1:-run}"
