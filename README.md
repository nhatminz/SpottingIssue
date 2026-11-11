# Pipeline tạo candidate gold legal issues tiếng Việt

Project trích xuất vấn đề pháp lý từ `situation`, dùng Generator và Judge tranh biện hai chiều, đồng thời kiểm tra tình huống có thiếu dữ kiện trọng yếu so với bản án hay không. Kết quả là **candidate gold labels có kiểm chứng tự động**. Cần chuyên gia kiểm tra để công nhận gold; Judge PASS không bảo đảm đúng tuyệt đối về pháp lý.

**Chính sách hiện tại: chỉ PASS được xuất.** Vụ không đạt chất lượng sau debate được REJECTED vào file riêng và pipeline tiếp tục. Báo cáo bản cập nhật (92 tests và Qwen fixture) ở [docs/rejected_cases_verification.md](docs/rejected_cases_verification.md).

**Rubric hiện tại:** chỉ CORE thuộc nội dung Tòa trực tiếp giải quyết được làm gold. Judge phải xác nhận Legal Relevance, Coverage, Grounding và Format; blind discovery mặc định bật và chỉ nhận situation. Chi tiết thay đổi, kiểm chứng và lệnh chạy bằng run mới ở [docs/strict_scope.md](docs/strict_scope.md). Các báo cáo Qwen trước đây phản ánh rubric cũ.

## 1. Chạy trên B200 với endpoint đã serve

Project root mặc định là `/workspace/storage-shared/nlp/minhpn19/LegalDataset`. Script đã trỏ cả Generator và Judge tới `http://172.29.62.173:8000/v1`, model ID `DeepSeek-V4.1-Flash-1017`. **Client chỉ gọi HTTP, không cần GPU/CUDA/PyTorch hoặc weights model local.** Nếu chưa có environment, cài Python >=3.10 và `.venv/bin/python -m pip install -e .` trong một venv mới tại B200. Chi tiết setup, đường dẫn và giải thích workers/concurrency/token budgets ở [docs/B200.md](docs/B200.md).

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset

# Kiểm tra input, config, prompt, fingerprint; không gọi API hoặc tạo output.
DRY_RUN=true bash scripts/run_pipeline.sh

# Chạy inference qua endpoint đã serve; không khởi động server/model local.
bash scripts/run_pipeline.sh

# Unit + integration tests, không dùng GPU/server.
.venv/bin/python -m pytest -q
```

Phần Qwen dưới đây là kiểm thử GPU local tùy chọn, **không dùng khi chạy client DeepSeek trên B200**. Đường dẫn Qwen là model của máy phát triển trước đây; B200 không cần có model này. Để tái lập thử nghiệm local, override PROJECT_ROOT về checkout local. Dùng hai terminal:

```bash
# Terminal 1: nạp Qwen3-4B, giữ terminal mở.
cd /mnt/hdd/nhatminh/LegalDataset
CUDA_VISIBLE_DEVICES=0 \
QWEN_MODEL_PATH=/mnt/hdd/nhatminh/SpecDecode/models/Qwen3-4B \
bash scripts/serve_qwen_local.sh
```

```bash
# Terminal 2: đợi terminal 1 báo Application startup complete.
cd /mnt/hdd/nhatminh/LegalDataset
curl --fail http://127.0.0.1:8001/health
bash scripts/run_smoke_test.sh
```

Nếu `output/smoke` đã có lần chạy với code/config cũ, chọn thư mục mới:

```bash
SMOKE_ROOT="$PWD/output/smoke_new" bash scripts/run_smoke_test.sh
```

Mặc định smoke chạy hai bản ghi đầu, generic adapter, thinking tắt, tối đa hai lượt sửa. Sampling dùng temperature=0.7, top_p=0.8, seed=42 và repetition_penalty=1.05 để hạn chế vòng lặp greedy của Qwen. Chỉ bản án PASS và đạt validation bắt buộc vào output. Vụ không đạt được ghi `REJECTED` vào `output/smoke/rejected_cases.jsonl`, tiếp tục vụ kế tiếp. Lỗi API/schema/evidence vẫn là `FAILED`, trả exit code 2; không tạo nhãn thay thế. File smoke ở `output/smoke/judgment_with_issues.jsonl`, tách khỏi production. Chi tiết kết quả kiểm chứng thực tế được ghi tại `docs/verification.md`.

**Kết quả thực tế ngày 10/11/2026:** Qwen đã nạp được và chạy end-to-end thành công trên fixture ngắn. Hai bản ghi thật đầu tiên vẫn thất bại vì model không đáp ứng format/metadata/evidence sau repair; không có nhãn production được tạo. Vì vậy không kỳ vọng lệnh smoke trên dữ liệu thật tự động PASS với Qwen3-4B. Để tái lập kiểm tra API kỹ thuật đã qua, giữ server mở và chạy:

```bash
INPUT_PATH="$PWD/tests/fixtures/example.jsonl" LIMIT=1 MAX_DEBATE_ROUNDS=1 \
SMOKE_ROOT="$PWD/output/qwen_fixture_new" \
bash scripts/run_smoke_test.sh
```

Fixture này trùng ví dụ định dạng trong system prompt, chỉ kiểm tra kết nối/serialization/validation/checkpoint, không đo chất lượng pháp lý hoặc khả năng khái quát hóa.

## 2. Cài đặt client / kiểm thử local tùy chọn

Client pipeline chỉ cần Python >=3.10, Pydantic và httpx; không cần CUDA/PyTorch nếu dùng endpoint có sẵn. Python hệ thống máy phát triển là 3.8 nên không dùng trực tiếp.

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

Để host Qwen bằng Transformers, cài thêm PyTorch phù hợp driver/CUDA, sau đó:

```bash
.venv/bin/python -m pip install -e '.[local]'
bash scripts/serve_qwen_local.sh
```

Transformers được giới hạn `>=4.51,<5` do tương thích integration của `lm-format-enforcer`. Server này chạy inference CUDA thật với SDPA, BF16 và ép JSON có hỗ trợ Unicode tiếng Việt; serialize các requests để kiểm tra kỹ thuật trên 3090. Đây là server smoke gọn, không thay thế vLLM/SGLang khi cần throughput cao. Model, tokenizer và weights được đọc local, không tự tải model thay thế hoặc dùng mock response.

Nếu đã có môi trường vLLM tương thích GPU/driver:

```bash
PYTHON_BIN=/path/to/vllm-env/bin/python \
QWEN_SERVER_BACKEND=vllm CUDA_VISIBLE_DEVICES=0 \
QWEN_TENSOR_PARALLEL_SIZE=1 QWEN_GPU_MEMORY_UTILIZATION=0.85 \
bash scripts/serve_qwen_local.sh
```

Không cài vLLM chồng lên môi trường PyTorch quan trọng. Endpoint vLLM có thể chạy trong environment riêng; client tiếp tục dùng `.venv`. Backend SGLang cũng sử dụng được nếu cung cấp `/v1/chat/completions` và nhận request parameters đã cấu hình. Nhánh vLLM và DeepSeek/B200 cần được kiểm chứng trên môi trường triển khai thực tế.

## 3. Chạy production DeepSeek

Mặc định trỏ cả hai agent tới `http://172.29.62.173:8000/v1`, model ID `DeepSeek-V4.1-Flash-1017`, theo cấu hình bạn đã cung cấp. `DEEPSEEK_API_BASE` và `DEEPSEEK_MODEL` trong shell đặt default chung; `GEN_*`/`JUDGE_*` vẫn override riêng được. Model ID phải khớp tên server expose, không phải đường dẫn weights ở client. DeepSeek đã được host sẵn; không cần chạy script serve Qwen hoặc xin GPU cho client.

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset

# Endpoint không cần key: bỏ GEN_API_KEY_FILE/JUDGE_API_KEY_FILE.
# Secret files chứa CHỈ key, không thêm tên biến hoặc dấu nháy.
GEN_API_BASE=http://172.29.62.173:8000/v1 \
JUDGE_API_BASE=http://172.29.62.173:8000/v1 \
GEN_MODEL=DeepSeek-V4.1-Flash-1017 JUDGE_MODEL=DeepSeek-V4.1-Flash-1017 \
GEN_BACKEND=deepseek JUDGE_BACKEND=deepseek \
GEN_API_KEY_FILE=/secure/generator.key \
JUDGE_API_KEY_FILE=/secure/judge.key \
MAX_WORKERS=2 MAX_CONCURRENT_REQUESTS=2 BATCH_SIZE=8 \
GEN_THINKING_ENABLED=true JUDGE_THINKING_ENABLED=true \
GEN_THINKING_EFFORT=extra_high JUDGE_THINKING_EFFORT=extra_high \
MAX_DEBATE_ROUNDS=8 \
bash scripts/run_pipeline.sh
```

Nếu dùng endpoint không xác thực, lệnh cụ thể tối thiểu:

```bash
bash scripts/run_pipeline.sh
```

Nên chạy ít records vào đường dẫn riêng trước khi chạy toàn bộ:

```bash
LIMIT=2 \
OUTPUT_PATH="$PWD/output/deepseek_check/issues.jsonl" \
AUDIT_DIR="$PWD/output/deepseek_check/audit" \
LOG_DIR="$PWD/output/deepseek_check/logs" \
CHECKPOINT_DIR="$PWD/output/deepseek_check/checkpoints" \
bash scripts/run_pipeline.sh
```

Đổi input/output bất kỳ bằng `INPUT_PATH`, `OUTPUT_PATH`, `AUDIT_DIR`, `LOG_DIR`, `CHECKPOINT_DIR`. Để đổi phạm vi `LIMIT`/`START_INDEX`, model, prompt hoặc tham số suy luận, dùng bộ đường dẫn run mới. Không sửa input gốc trong lúc chạy.

## 4. Cấu hình tập trung trong shell

Mọi trường cấu hình của `PipelineConfig` và `AgentConfig` đều có biến shell trong `scripts/run_pipeline.sh`, có comment theo nhóm. Script dùng `set -euo pipefail`, kiểm tra input/prompt/Python, in cấu hình hiệu lực đã bỏ secrets. Dùng `PYTHON_BIN` nếu environment ở nơi khác.

| Nhóm | Các biến chính và ý nghĩa |
| --- | --- |
| Endpoint dùng chung | `DEEPSEEK_API_BASE`, `DEEPSEEK_MODEL`: defaults chung cho hai agent; không có model weights path ở client |
| I/O | `PROJECT_ROOT`, `INPUT_PATH`, `OUTPUT_PATH`, `REJECTED_PATH`, `AUDIT_DIR`, `LOG_DIR`, `CHECKPOINT_DIR`, `PROMPT_DIR`, `RESUME`, `OVERWRITE_OUTPUT` |
| Runtime | `CUDA_VISIBLE_DEVICES`, `MAX_WORKERS` (số vụ), `MAX_CONCURRENT_REQUESTS` (tổng request của cả hai vai), `BATCH_SIZE` (số vụ mỗi đợt), `START_INDEX` (0-based), `LIMIT` (0=toàn bộ), `RANDOM_SEED` (jitter) |
| Generator/Judge | Cùng bộ biến với prefix `GEN_`/`JUDGE_`: `API_BASE`, `API_KEY`, `API_KEY_FILE`, `MODEL`, `BACKEND`, `THINKING_ENABLED`, `THINKING_EFFORT`, `MAX_OUTPUT_TOKENS`, `TEMPERATURE`, `TOP_P`, `SEED`, `TIMEOUT`, `MAX_RETRIES` |
| Backend bổ sung | `*_GENERIC_THINKING_STYLE`, `*_SUPPORTED_EFFORTS` (JSON list), `*_FALLBACK_EFFORT`, `*_STRUCTURED_OUTPUT_MODE`, `*_STOP` (JSON list), `*_EXTRA_BODY` (JSON object) |
| Debate | `MAX_DEBATE_ROUNDS`, `ENABLE_EARLY_STOP`, `ENABLE_GENERATOR_REBUTTAL`, `ENABLE_JUDGE_RECONSIDERATION`, `ENABLE_BLIND_JUDGE_DISCOVERY`, `STOP_ON_STAGNATION`, `MAX_STAGNANT_ROUNDS`, `FINALIZE_POLICY`, `UNRESOLVED_POLICY` |
| Validation | `STRICT_FORMAT`, `ENABLE_EVIDENCE_VALIDATION`, `ENABLE_DEDUPLICATION`, `ENABLE_COVERAGE_CHECK`, `ENABLE_SITUATION_AUDIT`, `SITUATION_ERROR_POLICY`, `MAX_JSON_REPAIR_RETRIES`, `REQUIRE_STRUCTURED_OUTPUT` |
| Context/request | `MAX_CONTEXT_TOKENS`, `MAX_INPUT_TOKENS`, `TRUNCATION_POLICY`, `TOKENIZER_PATH`, `API_REQUEST_TIMEOUT`, `RETRY_BACKOFF`, `RETRY_JITTER`, `API_EXTRA_BODY`, `THINKING_UNSUPPORTED_POLICY` |
| Logging/debug | `LOG_LEVEL`, `SAVE_DEBATE_HISTORY`, `SAVE_RAW_RESPONSES`, `SAVE_TOKEN_USAGE`, `DRY_RUN`, `FAIL_ON_RECORD_ERROR` |

`GEN_TIMEOUT`/`JUDGE_TIMEOUT=null` dùng timeout chung. Sampling `null` nghĩa là không gửi, không tự gán temperature. `*_API_KEY` có ưu tiên hơn secret file; không đưa key thật vào repository. Extra body được fingerprint nhưng cấu hình public chỉ in tên keys. Không đưa credentials vào URL. Không dùng `bash -x` với secrets.

GPU của server được chọn lúc host server. Đặt `CUDA_VISIBLE_DEVICES` trong client không thay GPU của endpoint đang chạy. `GEN_MODEL`/`JUDGE_MODEL` là ID API; `QWEN_MODEL_PATH` là đường dẫn weights của script host Qwen.

## 5. Thinking và structured output

DeepSeek adapter gửi `thinking.type=enabled/disabled`; khi bật gửi `reasoning_effort`. Mapping của pipeline:

| Giá trị shell | DeepSeek gửi thực tế |
| --- | --- |
| `low` | `low` |
| `medium` | `high` (không phải mức tính toán riêng) |
| `high` | `high` |
| `extra_high` | `max` (alias riêng của pipeline) |
| `max` | `max` |

Các alias luôn có warning và thông số thực được ghi trong audit/summary. Adapter mặc định không gửi temperature/top_p/seed khi DeepSeek thinking bật; nếu bạn đặt chúng sẽ có warning rằng bị bỏ qua. Đây là chính sách thận trọng cho nhiều self-hosted variants. DeepSeek Flash có phiên bản hỗ trợ top_p trong thinking; nếu đã xác nhận server, có thể opt-in rõ bằng `GEN_EXTRA_BODY='{"top_p":0.95}'` và `JUDGE_EXTRA_BODY` tương ứng. Không giả định tham số có hiệu lực chỉ vì server nhận HTTP 200.

`GEN_SUPPORTED_EFFORTS`/`JUDGE_SUPPORTED_EFFORTS` mô tả mức server đã được bạn xác nhận hỗ trợ. Với mức không nằm trong danh sách: `THINKING_UNSUPPORTED_POLICY=fail` báo lỗi; `fallback` dùng `*_FALLBACK_EFFORT` có warning. Server vẫn có thể từ chối request: HTTP 400 dừng rõ ràng, không tự đoán fallback hoặc tắt kiểm tra JSON. Khi đổi adapter/server cần kiểm tra request compatibility trên run riêng.

Qwen generic dùng `chat_template_kwargs.enable_thinking`; mặc định smoke `*_THINKING_ENABLED=false`, `*_THINKING_EFFORT=none`. Để bật Qwen:

```bash
SMOKE_ROOT="$PWD/output/qwen_thinking" \
GEN_THINKING_ENABLED=true JUDGE_THINKING_ENABLED=true \
GEN_THINKING_EFFORT=none JUDGE_THINKING_EFFORT=none \
bash scripts/run_smoke_test.sh
```

Qwen switch không bảo đảm phân biệt high/max. Nếu đặt effort khác `none` cho Qwen thì `fail`, hoặc `fallback` có warning về việc chỉ dùng switch. Generic endpoint có dial riêng dùng `*_GENERIC_THINKING_STYLE=reasoning_effort`; endpoint không có thinking dùng `none` và tắt thinking.

DeepSeek mặc định `*_STRUCTURED_OUTPUT_MODE=json_object` cho tương thích; JSON schema vẫn nằm trong system prompt và Pydantic kiểm tra mọi đáp án. Qwen smoke dùng `json_schema` để server ép cấu trúc. Các trường explanation/feedback nội bộ giới hạn 1500 ký tự để hạn chế lặp; không tự cắt đáp án, không giới hạn số issues/findings. `REQUIRE_STRUCTURED_OUTPUT=false` chỉ bỏ request response_format, không bỏ Pydantic. Repair JSON/schema và lỗi cơ học của Generator có giới hạn; không trích JSON bằng regex hoặc im lặng nhận dữ liệu hỏng. Response `finish_reason=length` luôn lỗi, không coi kết quả dở dang là hợp lệ.

Giới hạn context được kiểm tra trước request. Nếu có `TOKENIZER_PATH`, client dùng tokenizer local; nếu không, dùng số UTF-8 bytes cộng overhead làm upper bound bảo thủ cho byte-fallback tokenizer, có thể từ chối sớm. Với tokenizer có quy tắc khác, cấu hình tokenizer đúng model. `TRUNCATION_POLICY=error` là chính sách duy nhất được hỗ trợ: không tự cắt nguồn khi đánh giá thiếu dữ kiện. `MAX_OUTPUT_TOKENS` cần đủ cả thinking và final content theo backend.

Production mặc định `GEN_MAX_OUTPUT_TOKENS=131073` và `JUDGE_MAX_OUTPUT_TOKENS=131073` **riêng cho mỗi request ở mỗi vòng**, không chia sẻ hoặc trừ dần giữa các lượt/agent. `MAX_CONTEXT_TOKENS=262144` là guard cho input + output của từng request, chừa chỗ cho `MAX_INPUT_TOKENS=100000`. Server phải hỗ trợ ngân sách này; cấu hình client không tự tăng giới hạn server.

Tài liệu tham khảo chính thức: [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/), [Qwen vLLM](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md), [vLLM structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/).

## 6. Kiến trúc và quyền truy cập

```text
input JSONL -> JSONLReader -> PipelineRunner (bounded concurrency)
                              -> một DebateController/vụ
                                 -> GeneratorAgent + client riêng
                                 -> JudgeAgent + client riêng
                                 -> Validators + FeedbackFirewall
                              -> CheckpointManager (SQLite WAL/FULL)
                              -> JSONLWriter (atomic, đúng thứ tự)
                              -> audit JSON/JSONL, logs, summary
```

Các class có dependency injection cho clients/controller, type hints và trách nhiệm riêng; không có model giả hoặc fallback sang mock trong production. Test doubles chỉ ở `tests/`.

Generator lần đầu chỉ nhận `situation`. Các lượt sau nhận issues trước đó, feedback đã lọc, đánh giá phản biện đã lọc và lịch sử phản hồi tường minh của chính Generator. **Không nhận `markdown`, `citations`, `citations_law`, private audit hoặc reasoning của Judge.**

Judge có hai giai đoạn. Stage A (blind, mặc định bật) chỉ nhận `situation` và system guideline/scope, chưa xem Generator hoặc nguồn riêng. Stage B là request/context mới, nhận `situation`, `markdown`, `citations_law`, `citations`, candidate hiện tại cùng metadata, kết quả blind discovery và trao đổi có cấu trúc của vụ hiện tại. Không nối toàn bộ conversation history giữa hai stage hoặc giữa hai agent. Các trường phụ từ input không tự động vào prompt.

`FeedbackFirewall` không cố lọc chữ trong văn xuôi: nó chỉ cho qua các enum biết trước, issue IDs hiện tại, feedback ID dạng `F1`, `F2` và quotes xuất hiện nguyên văn trong `situation`. Explanation, suggested issue text, markdown evidence, audit và mọi free text từ Judge đều private. Generator tự suy ra cách sửa từ code lỗi và bằng chứng trong nguồn được phép. Judge giữ nguyên lời giải thích đầy đủ để kiểm toán.

Mỗi record có agent instances, HTTP clients, message histories, debate state riêng. API là stateless theo request; không gửi session ID, không tái dùng server conversation. Hai vai có thể dùng cùng endpoint và cùng weights: độc lập inference/context **không** làm hai checkpoints khác nhau và không bảo đảm lỗi độc lập thống kê. KV-cache reuse không đồng nghĩa lẫn hội thoại nếu request nội dung vẫn cách ly.

## 7. Debate và chọn candidate

1. Judge Stage A tự tìm các vấn đề trọng tâm từ situation trong một inference độc lập; kết quả này là đề xuất, không phải đáp án chuẩn.
2. Generator sinh issues và metadata chỉ từ situation. Judge Stage B dùng request riêng để đối chiếu hai danh sách với situation và phạm vi giải quyết trong bản án; tự tìm cả vấn đề mà hai danh sách bỏ sót.
3. Generator trả lời từng feedback: `ACCEPT`, `CONTEST`, `PARTIALLY_ACCEPT`; phản bác phải có bằng chứng tình huống.
4. Judge đọc phản hồi mới, trả `WITHDRAW`, `UPHOLD`, `PARTIALLY_WITHDRAW` và giải thích có quotes. Không được bỏ qua phản bác.
5. Lặp đến PASS có validation, stagnation hoặc giới hạn vòng.

**Một round = Judge evaluation -> Generator response.** Với `MAX_DEBATE_ROUNDS=N`, tối đa N lần sửa và N+1 Stage B evaluations (chưa tính blind discovery/repair). Bản sửa cuối luôn được Judge kiểm tra. PASS ban đầu có thể dừng với 0 rounds; với blind mặc định bật, có 3 inference riêng: Stage A, Generator, Stage B.

Mỗi review có `classification=CORE|SUPPORTING_FACT|IRRELEVANT|DUPLICATE`. PASS chỉ khi toàn bộ issues là CORE, có quotes nguyên văn từ situation và quotes từ nhận định/quyết định xác nhận phạm vi Tòa xét xử; cả bốn tiêu chí rubric đều PASS và inventory coverage không có vấn đề trọng tâm chưa được khớp. SUPPORTING_FACT được Generator tích hợp vào tình tiết quyết định của CORE liên quan rồi bỏ issue riêng, không bị exporter âm thầm lọc để tạo PASS. Các vấn đề án phí, kháng cáo, thủ tục thường lệ hoặc tăng/giảm nhẹ mặc định ngoài scope trừ khi thực sự là yêu cầu/tranh chấp độc lập hoặc vấn đề đặc biệt được giải quyết. Đây là đánh giá ngữ nghĩa của Judge có evidence; code chỉ xác minh nguồn trích dẫn và tính nhất quán, không giả vờ dùng regex để hiểu pháp luật.

Stagnation xét cấu trúc trọng tâm/chủ thể/tình tiết, evidence, codes/action của feedback, quyết định phản bác và assessment: nhận diện lặp lập luận, đảo phiên bản, số issue tăng không thêm bằng chứng, Judge đổi verdict không thêm bằng chứng. Đây là heuristic phát hiện vòng lặp; không dùng độ giống chuỗi để tự kết luận hai issue tương đương về pháp lý. Semantic duplication và atomicity do Judge đánh giá.

`MAX_DEBATE_ROUNDS` mặc định 8, có thể đặt 5–10 cho production. Nếu lần đánh giá cuối vẫn không PASS, vụ đó chuyển thành **REJECTED**, không ghi bất kỳ record/candidate nào vào output chính; pipeline tiếp tục vụ kế tiếp. Nếu dừng sớm vì stagnation hoặc situation không chắc chắn, vụ không đạt cũng được REJECTED với số vòng thực tế và stop reason. Đặt `STOP_ON_STAGNATION=false` để không dừng sớm do lặp lập luận.

`UNRESOLVED_POLICY=reject` là chính sách hiện tại. Giá trị cũ `stop` hoặc `continue` được chuyển thành `reject` có warning; không còn tùy chọn xuất candidate chưa PASS. `FINALIZE_POLICY=best_valid|last_valid` chỉ chọn candidate tham khảo trong private audit; **file rejected luôn ghi issues của lần sửa cuối**, kể cả khi private audit chọn bản cũ. API, timeout, parse JSON và validation không sửa được vẫn là `FAILED`, không được chuyển thành `REJECTED`.

Tắt các kiểm tra cốt lõi (format/evidence/coverage/dedup/situation audit), rebuttal hoặc reconsideration không đáp ứng điều kiện nhận labels, nên vụ bị REJECTED và audit ghi lý do. Các flags `needs_review`/Judge `NEEDS_REVIEW` vẫn phục vụ kiểm toán; không phải quyền đưa candidate vào output chính.

## 8. `situation_error` và giới hạn kiểm chứng

Mặc định `SITUATION_ERROR_POLICY=material_missing`: `true` khi Judge phát hiện ít nhất một dữ kiện thực tế trọng yếu có trong bản án, không có diễn đạt tương đương trong situation, ảnh hưởng nhận diện/diễn đạt issue trọng tâm. Không yêu cầu situation kể toàn bộ bản án; không tính chi tiết hành chính không liên quan hay chỉ thiếu citations.

Mỗi finding trong audit có fact, quote bản án, lý do quan trọng, issue bị ảnh hưởng và đánh giá tương đương. Code kiểm tra quotes nguồn nguyên văn; việc thiếu/quan trọng/diễn đạt tương đương vẫn cần suy luận ngữ nghĩa. Contradictions lưu riêng. `material_missing_or_contradiction` có thể tính thêm sai lệch trọng yếu vào boolean.

**`situation_error=true` không phải lý do tự động loại bản án.** Nếu Judge PASS về chất lượng issues và validation bắt buộc đạt, record vẫn vào output với boolean true. Tình huống có thiếu trọng yếu vẫn có thể nhận labels phù hợp với phần situation đang có; không bơm dữ kiện thiếu vào Generator. Không chắc chắn => `needs_review=true`, không tự công nhận hoàn toàn xác minh. `situation_error=false` chỉ nghĩa không phát hiện thiếu trọng yếu theo quá trình kiểm tra, không chứng minh tình huống hoàn hảo.

## 9. Resume, độ bền và lỗi

Trạng thái: `PENDING -> RUNNING -> COMPLETED | REJECTED | FAILED`. Case ID kết hợp index dòng và hash `doc_name`, vẫn phân biệt hai dòng trùng doc_name. Checkpoint SQLite WAL, `synchronous=FULL`, commit sau mỗi vụ được chấp nhận hoặc bị loại; result và audit được commit cùng transaction. Hai file JSONL xuất bằng temp+fsync+atomic replace; lock ngăn hai process ghi chung output/rejected/checkpoint. Nếu dừng giữa hai lần ghi file, resume dựng lại cả hai từ SQLite.

```bash
# Chạy lại CÙNG lệnh với cùng cấu hình semantic; RESUME mặc định true.
RESUME=true bash scripts/run_pipeline.sh
```

`COMPLETED` và `REJECTED` đã cache không gọi model lại và không ghi trùng dòng. `FAILED` và `RUNNING` bị gián đoạn được thử lại. Nếu input, config liên quan, prompt hoặc code đổi, fingerprint từ chối resume không tương thích; tạo run mới để đánh giá lại. **Bản cập nhật PASS-only này thay đổi export policy/schema: checkpoint trước bản cập nhật cần bộ đường dẫn run mới**, không tự biến candidate cũ thành labels.

Manifest kiểm tra SHA256 toàn input, cấu hình semantic, từng prompt, source code và export policy. Đổi model/sampling/thinking/prompt/phạm vi/policy làm mismatch; dùng output/rejected/audit/log/checkpoint paths mới. Có thể đổi concurrency, timeout, retry, logging hoặc credential để resume. Không xóa checkpoint nhằm lách mismatch. Output hoặc rejected file có sẵn mà không có checkpoint tương ứng bị từ chối; `OVERWRITE_OUTPUT=true` có chủ đích sẽ backup cả hai file cũ rồi tạo mới, không xóa input.

Default lỗi record dừng an toàn. Network/timeouts/HTTP 408/409/429/5xx retry hữu hạn với exponential backoff+jitter; 400/401/403 không tự retry. `FAIL_ON_RECORD_ERROR=false` cho phép xử lý các vụ khác, nhưng run vẫn incomplete/exit 2 khi có failure.

Output chứa toàn bộ vụ COMPLETED, theo thứ tự tương đối của input sau khi lọc. REJECTED và FAILED không tạo dòng trống hoặc record thay thế. Khi resume sửa một FAILED thành COMPLETED, file được dựng lại đúng thứ tự, không append trùng. Output/rejected cập nhật sau mỗi batch và cuối run; kết quả đã commit nhưng chưa export được khôi phục từ checkpoint. Run hoàn tất khi `accepted + rejected == selected_records`, kể cả trường hợp mọi vụ bị loại và output rỗng. Có FAILED/PENDING thì run chưa hoàn tất và CLI trả exit 2.

API/schema/evidence errors không được thay bằng `issues=[]`/`false`. Một list rỗng chỉ có thể là đáp án model được schema+Judge coverage kiểm tra, không phải fallback xử lý lỗi.

## 10. Output và audit

Output chính mặc định `output/judgment_with_issues.jsonl`: **chỉ record đã PASS**, giữ tất cả fields gốc và thứ tự tương đối của các vụ được nhận, cập nhật đúng `issues: list[str]`, `situation_error: bool` (ghi đè null, không key trùng). Không thêm metadata. Byte spacing/Unicode escaping có thể khác input, nhưng giá trị JSON các trường gốc được bảo toàn.

`REJECTED_PATH` mặc định `output/rejected_cases.jsonl` (nằm cạnh `OUTPUT_PATH` nếu đổi output). Mỗi dòng gồm `doc_name`, `case_id`, `input_index`, `rounds`, `issues` của bản cuối, `judge_verdict`, `stop_reason`, `rejection_reasons`, `feedback_history`, `situation_error`, `needs_review`. Record REJECTED không có main-output payload trong checkpoint. Failed cases chỉ nằm trong failure log, không vào file rejected.

```bash
# Xác minh PASS/validation, các fields gốc, thứ tự và accepted/rejected counts.
# Cần checkpoint tương ứng: không đối chiếu output đã lọc bằng số dòng input.
bash scripts/run_pipeline.sh validate

# Xem tổng hợp (có thể dùng Python thay jq).
cat output/audit/summary.json
head -n 5 output/audit/records.jsonl
tail -n 30 output/logs/pipeline.log
cat output/logs/failures.jsonl
head -n 5 output/rejected_cases.jsonl
```

| Artifact | Nội dung |
| --- | --- |
| `rejected_cases.jsonl` | Vụ bị loại do chất lượng, số vòng thực tế, issues cuối, lý do và toàn bộ feedback history |
| `audit/<case_id>.json` | Issues/feedback từng lần đánh giá, classification, scope_rubric, coverage_analysis, blind_discovery, blind_comparison, responses, assessments, missing facts, lựa chọn cuối, trạng thái, request IDs, latency, usage |
| `audit/records.jsonl` | Một dòng/vụ, index, status, số issues, boolean, rounds, consensus, stop reason |
| `audit/states.jsonl` | Lịch sử chuyển trạng thái qua các lần resume |
| `audit/summary.json` | `total_input_records`, `selected_records`, `accepted`/`completed`, `rejected`, `failed`, `pending`, output count; issues trung bình trên vụ được nhận, situation errors của vụ được nhận, rounds trung bình, PASS/early stop/max rounds, contests/Judge changes, token usage, fingerprints, thinking thực tế |
| `logs/pipeline.log` | Log vận hành, retry, parse/validation và trạng thái record |
| `logs/failures.jsonl` | Các vụ hiện đang FAILED; sau resume thành công không còn trong danh sách hiện tại |
| `checkpoints/state.sqlite3` | Trạng thái và kết quả bền vững; không sửa tay |
| `checkpoints/manifest.json` | Fingerprints xác định run |

`SAVE_DEBATE_HISTORY=false` bỏ history thông thường, nhưng **không bỏ feedback_history bắt buộc của vụ REJECTED**. `SAVE_RAW_RESPONSES=true` lưu final content để debug, vẫn bỏ `reasoning_content` và đoạn `<think>...</think>`. Không có raw reasoning hoặc key trong output chính. Logs/audit/rejected có dữ liệu vụ án, nên lưu ở nơi phù hợp với chính sách dữ liệu của bạn. Tổng latency là tổng thời gian requests, có thể lớn hơn wall time khi concurrent. Usage chỉ có khi API cung cấp; không suy ra chi phí tiền tệ.

## 11. Dữ liệu đã khảo sát và kiểm thử

Input thực tế có 54 dòng hợp lệ, 39 fields; `situation_error` null ở cả 54 dòng. `category` null ở 2 dòng, `precedent_number` và `confidence` null ở toàn bộ. `situation` dài 342–6.627 ký tự, `markdown` dài 1.752–25.227 ký tự. Hai citations lists có schema khác nhau và không được giả định tương đương. Báo cáo máy đọc được: `docs/data_profile.json`.

```bash
.venv/bin/python -m pytest -q
bash -n scripts/run_pipeline.sh scripts/run_smoke_test.sh scripts/serve_qwen_local.sh
DRY_RUN=true bash scripts/run_pipeline.sh
```

Tests sử dụng inference giả lập ở test path để kiểm tra: input/null/preservation, cách ly hai agent và private feedback, contest/withdraw/uphold, early stop/max rounds/stagnation/final Judge, JSON repair và lỗi, retries/timeouts/unavailable, evidence sai nguồn, material missing vs administrative/equivalent/contradiction, resume/fingerprint/concurrency, accepted/rejected filtering và validation sau lọc, bảo vệ credentials và input/output. Các test này không xác nhận độ đúng pháp lý của LLM.

## 12. Rủi ro chất lượng còn lại

Generator và Judge có thể mắc lỗi tương quan khi dùng cùng weights. Regex và quotes nguyên văn chỉ kiểm tra cơ học, không chứng minh đầy đủ ý nghĩa, căn cứ trách nhiệm hoặc atomicity. Judge có thể bỏ sót dữ kiện, đánh giá nhầm tương đương, chịu ảnh hưởng phán quyết gốc hoặc citations nhiễu. Firewall hạn chế chuyển dữ kiện ngoài situation nhưng không chứng minh mọi gợi ý enum của Judge đều đúng ngữ nghĩa. Phải xem audit và đánh giá độc lập trên tập có human annotations; không dùng tỷ lệ PASS làm thước đo duy nhất.

Qwen3-4B chỉ smoke kỹ thuật. Thay model production cần pilot mới để kiểm tra giới hạn context, schema compliance, thinking request format và chất lượng. Không có chức năng tự tải luật hoặc xác minh hiệu lực luật ngoài những nội dung nguồn thực sự cung cấp; không tuyên bố citations là nguyên văn quy phạm.
