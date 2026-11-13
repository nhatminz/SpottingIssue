# Vietnamese Legal Issue Spotting: full-judgment Generator, facts-only Judge

Pipeline hiện dùng schema FAC: Generator đọc bản án đầy đủ để chọn CORE issues và giải thích bằng `benchmark_seed.facts_clean`; Judge độc lập chỉ đọc facts_clean, cặp issue/explain và lịch sử facts-only. Hai vai trò có client, system prompt và request riêng dù dùng cùng DeepSeek đã serve. Chỉ bản án Judge PASS và đạt validation mới được xuất. Đây là candidate gold labels có kiểm chứng tự động; cần đánh giá chuyên gia để xác định độ chính xác pháp lý thực tế.

## Input và output

Mặc định input `$PROJECT_ROOT/input/sample_input.jsonl`. Bắt buộc mỗi dòng có `doc_name`, `markdown` là chuỗi không rỗng, cùng object `benchmark_seed` có bốn chuỗi không rỗng: `facts_clean`, `facts`, `application`, `conclusion`. Không dùng fallback sang situation hoặc tự tạo dữ liệu thiếu. Mọi metadata khác giữ nguyên. JSON duplicate keys/non-finite numbers bị từ chối. Nếu top-level đã có `issues` hoặc `explain`, pipeline báo xung đột và dừng trước inference, không ghi đè.

Output giữ toàn bộ record input, chỉ thêm:

```json
{
  "issues": ["Việc xác định ... khi ..."],
  "explain": ["Các tình tiết cụ thể trong facts_clean làm phát sinh vấn đề ..."]
}
```

Hai list cùng độ dài, đúng thứ tự và ghép cặp. Issue là cụm danh từ pháp lý có ba phần và prefix cho phép, không phải câu hỏi hay kết luận. Explain phải cụ thể, chỉ dùng facts_clean, không trích nhận định/phán quyết. Pipeline không tạo/cập nhật situation_error hoặc metadata nội bộ trong main output. Nếu input có metadata situation_error sẵn, giá trị gốc vẫn được giữ nguyên theo yêu cầu bảo toàn input.

## Luồng dữ liệu và ranh giới truy cập

1. Preflight kiểm tra toàn bộ JSONL, cấu hình, prompts, file few-shot và trùng ví dụ.
2. Trước khi dùng ví dụ, chính Generator audit grounding của toàn bộ cặp issue/explain trong 5 few-shot bằng một request riêng chỉ chứa facts_clean và nhãn mẫu. Tất cả phải được hỗ trợ, quotes đúng nguồn; ví dụ không đạt chặn run rõ ràng. Kết quả được lưu trong checkpoint/audit và không gọi lại khi resume cùng manifest. Đây vẫn là vai trò Generator, không phải Judge hay role thứ ba. Dry-run chỉ kiểm tra cấu trúc, không tuyên bố đã kiểm chứng grounding bằng model.
3. Generator của từng vụ nhận nguyên vẹn facts_clean, facts, application, conclusion và markdown qua allowlist nguồn; dùng ví dụ đã duyệt. Các bước revision tiếp tục nhận đủ nguồn và ví dụ được phép.
4. Generator chọn câu hỏi thực sự được application phân tích và conclusion giải quyết, nhưng issue/explain chỉ dùng facts_clean. Mỗi issue có facts evidence cho cả issue/explain, cộng evidence application/conclusion và xác nhận phạm vi ở `private_judicial_support`. Phần này chỉ vào audit.
5. Code dựng `JudgeCandidate` mới, chỉ gồm issue_id, issue_text, explain và phản biện đã lọc xuống enum/ID/quotes facts. Không truyền GeneratorOutput hoặc full record. API Judge chỉ nhận facts_clean dạng chuỗi, không có API nhận full record. Không chuyển private explanation, metadata, raw facts, trích luật hoặc few-shot. SafeHistory là schema riêng; dict tùy ý bị từ chối. Retry/repair của Judge chỉ lặp lại request facts-only của chính nó.
6. Nếu bật blind discovery (mặc định true), cùng Judge thực hiện request mới chỉ có facts_clean; không thấy Generator candidate. Stage evaluation dùng facts và các đề xuất tạm thời, có thể loại đề xuất blind hoặc phát hiện vấn đề cả hai danh sách bỏ sót.
7. Judge chấm 8 tiêu chí: grounding, legal_relevance, coverage, independence, format/non-conclusiveness, explanation_quality, consistency và deduplication. Judge không được tuyên bố xác minh phạm vi xét xử thực tế vì không thấy bản án.
8. Judge phản hồi có mã lỗi, ID, hành động, giải thích và facts evidence. Generator có thể ACCEPT/CONTEST/PARTIALLY_ACCEPT; Judge đánh giá lại và WITHDRAW/UPHOLD/PARTIALLY_WITHDRAW. Tối đa 6 chu trình Judge → Generator, thêm một Judge đánh giá bản sửa thứ 6; không có lần sửa thứ 7. Có early stop và stagnation detection, trong đó thay đổi explain được tính vào tiến triển.
9. Chỉ final candidate PASS mới COMPLETED. REJECTED không vào main output; API/timeout/parsing/validation thất bại là FAILED, không tạo nhãn thay thế.

Exact quotes kiểm tra nguồn gốc, không chứng minh ngữ nghĩa. Code chặn verbatim private evidence trong public pair, tách hoàn toàn private metadata/history; Judge chịu trách nhiệm ngữ nghĩa facts-only của các diễn đạt còn lại. Không giả vờ rằng regex có thể chứng minh mọi tình tiết của một câu diễn giải.

## Few-shot

`FEWSHOT_PATH=$PROJECT_ROOT/input/fewshot.jsonl`, đúng 5 ví dụ thuộc Marriage & Family, Criminal, Civil, Commercial, Administrative. Loader hỗ trợ `issues: [{issue, explain, ...}]` hoặc `issues: [string]` kèm `explain: [string]`; chuẩn hóa thành `facts_clean`, `issues`, `explain` cùng category/example_id. Không đưa application/conclusion/markdown của ví dụ vào request.

Thông thường Generator nhận đủ 5 ví dụ ở mọi lượt. Nếu doc_name/official_document_id/web_url hoặc facts chuẩn hóa khớp ví dụ, loại chính ví dụ đó và ghi warning/audit `excluded_fewshot_examples`; không tự tạo mẫu thay thế. Với 5 vụ trùng trong input mẫu, mỗi vụ dùng 4 ví dụ khác. Judge không nhận ví dụ ở bất kỳ giai đoạn nào.

## Chạy trên B200

Giữ nguyên project root `/workspace/storage-shared/nlp/minhpn19/LegalDataset`, endpoint `http://172.29.62.173:8000/v1`, model ID `DeepSeek-V4.1-Flash-1017`. Client chỉ gọi HTTP, không load weights/GPU local. Python >=3.10; dependencies runtime chỉ Pydantic và httpx.

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
# Chỉ khi chưa cài package/dependencies trong environment:
.venv/bin/python -m pip install -e '.[test]'

DRY_RUN=true bash scripts/run_pipeline.sh
```

Sau khi đồng bộ src/prompts/scripts và hai file input/fewshot sang đúng root B200, dùng namespace mới vì contract đã đổi:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
RUN_DIR="$PWD/output/fac_facts_only_v1"

INPUT_PATH="$PWD/input/sample_input.jsonl" \
FEWSHOT_PATH="$PWD/input/fewshot.jsonl" \
GEN_BACKEND=deepseek_vllm \
JUDGE_BACKEND=deepseek_vllm \
GEN_THINKING_EFFORT=high \
JUDGE_THINKING_EFFORT=high \
MAX_WORKERS=40 \
MAX_CONCURRENT_REQUESTS=40 \
BATCH_SIZE=100 \
MAX_DEBATE_ROUNDS=6 \
START_INDEX=0 \
LIMIT=0 \
OUTPUT_PATH="$RUN_DIR/judgment_with_issues.jsonl" \
REJECTED_PATH="$RUN_DIR/rejected_cases.jsonl" \
AUDIT_DIR="$RUN_DIR/audit" \
LOG_DIR="$RUN_DIR/logs" \
CHECKPOINT_DIR="$RUN_DIR/checkpoints" \
bash scripts/run_pipeline.sh
```

Lặp đúng lệnh để resume. Không đổi START_INDEX theo số dòng output: output chỉ chứa bản án PASS. `LIMIT=0` chọn toàn bộ input; batch 100 cho phép 40 vụ chạy và các vụ đang chờ tiếp tục khi worker rảnh. GPU scheduling thực tế do server quyết định.

Để chạy thử 1–2 vụ, dùng LIMIT=2 và một RUN_DIR khác, không dùng checkpoint pilot cho full dataset. Nếu dùng environment đang active, đặt `PYTHON_BIN="$(command -v python)"`. Chạy local để phát triển bằng `PROJECT_ROOT="$PWD"`; script vẫn giữ default root B200.

## Cấu hình

Toàn bộ biến runtime được đưa ra `scripts/run_pipeline.sh` và có thể override từ môi trường.

| Nhóm | Defaults chính |
| --- | --- |
| Input | `INPUT_PATH=$PROJECT_ROOT/input/sample_input.jsonl`, `FEWSHOT_PATH=$PROJECT_ROOT/input/fewshot.jsonl` |
| Output | `output/judgment_with_issues.jsonl`, `output/rejected_cases.jsonl`, audit/log/checkpoint riêng |
| Agent | hai backend `deepseek_vllm`, thinking bật, effort `high` → budget **50** |
| Runtime | `MAX_WORKERS=40`, `MAX_CONCURRENT_REQUESTS=40`, `BATCH_SIZE=100`, `START_INDEX=0`, `LIMIT=0` |
| Debate | `MAX_DEBATE_ROUNDS=6` (cho phép 1–6), early stop/stagnation bật |
| Tokens | **131073 token sinh mới riêng cho mỗi request của mỗi vai trò**, input guard 100000, context guard 262144 |
| Count | `TOKEN_COUNT_METHOD=auto`, `TOKENIZER_PATH` rỗng |
| Failure | `API_REQUEST_TIMEOUT=300`, mỗi vai trò max_retries=3, `MAX_JSON_REPAIR_RETRIES=2`, `FAIL_ON_RECORD_ERROR=true` |
| Resume/log | `RESUME=true`, `OVERWRITE_OUTPUT=false`, raw responses mặc định false |

vLLM gửi `chat_template_kwargs={"thinking":true,"reasoning_effort":50}`. Có thể chọn low=25, high=50, xhigh=75, max=100 hoặc budget số 1–100. `extra_high` là alias cũ cho 100, có log; medium/minimal mặc định lỗi. Tắt bằng THINKING_ENABLED=false hoặc effort=none. Hosted API/generic Qwen vẫn có adapter riêng. Effort 50 không phải giới hạn 50 token. Tham khảo [recipe vLLM](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4.1-Flash).

`TOKEN_COUNT_METHOD=auto` dùng tokenizer local khi có, còn DeepSeek vLLM thì gọi `/tokenize` với đúng messages và thinking kwargs; không chạy inference thứ ba và không cần weights phía client. Nếu endpoint không sẵn, log và dùng UTF-8 byte upper bound bảo thủ. `vllm` bắt buộc count endpoint; `utf8_byte_upper_bound` giữ cách guard cũ. `/tokenize` dùng chung giới hạn HTTP của hai vai trò. Đây là cách tránh từ chối sớm bản án tiếng Việt đầy đủ + few-shot chỉ vì số bytes lớn; không tăng token/context budget hoặc cắt nguồn. Tham khảo [protocol tokenization vLLM](https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/serve/tokenize/protocol/).

Nếu server không hỗ trợ output 131073/context tương ứng, request vẫn lỗi rõ ràng; client không tự hạ budget. Các biến API_KEY/secret file và sampling vẫn hoạt động; secrets không được log. Sampling null không gửi.

## Failure, resume và audit

Main output chỉ chứa COMPLETED. `rejected_cases.jsonl` chứa doc_name, rounds, issues/explain cuối, final verdict, lý do và toàn bộ feedback_history. FAILED lưu trong logs/failures.jsonl, không nhầm với REJECTED. Với FAIL_ON_RECORD_ERROR=true, ngừng nhận vụ mới khi có lỗi và chờ vụ đang chạy; false cho phép xử lý tiếp những vụ khác. Có thể tăng timeout/giảm workers bằng environment khi server chậm. Exit 0 khi toàn bộ selection đã COMPLETED hoặc REJECTED; exit 2 khi còn FAILED/PENDING hoặc có lỗi cấu hình. Không cam kết tất cả input sẽ PASS.

SQLite là nguồn trạng thái chính, output/rejected được ghi atomic theo index input. Skip COMPLETED/REJECTED khi resume, retry FAILED/RUNNING/PENDING. Manifest hash toàn input, 7 prompts, source code, cấu hình semantic, few-shot và export policy `fac_facts_only_v3`. Checkpoint của contract cũ bị từ chối. Đổi few-shot/prompts/nguồn/model/effort/selection cần bộ đường dẫn mới; thay concurrency, timeout, retry, logging không làm đổi semantic hash. Không xóa checkpoint cũ để lách kiểm tra.

Audit từng vụ giữ candidate/private judicial evidence của Generator, facts-only Judge reviews, explains, debate, excluded examples và request usage. `audit/fewshot_validation.json` ghi kiểm tra ví dụ được duyệt; lỗi phê duyệt ghi `fewshot_validation_failed.json` và summary, không dùng ví dụ lỗi hoặc đánh dấu vụ giả thành công. SAVE_RAW_RESPONSES=true lưu final JSON để debug, vẫn loại reasoning_content. Dữ liệu private không vào request Judge hoặc thêm vào main output ngoài input gốc.

## Kiểm chứng

```bash
.venv/bin/python -m pytest -q
PROJECT_ROOT="$PWD" DRY_RUN=true bash scripts/run_pipeline.sh
```

Các test contract cũ trái với thiết kế mới được giữ tại `tests/legacy_situation_contract/*.txt`; chúng không còn là kiểm thử của API hiện tại. Tests mới kiểm tra full sources, facts-only allowlist qua blind/retry/rebuttal/final, explanations, private evidence, 5 examples/overlap/screening, 6 revisions, output preservation, reject/failure, resume/fingerprints, 40 workers và 40 HTTP requests. Các API/retry/effort tests vẫn chạy. Chi tiết báo cáo ở [docs/fac_refactor.md](docs/fac_refactor.md). Các báo cáo Qwen/situation cũ là lịch sử, không phải kết quả kiểm chứng contract mới.
