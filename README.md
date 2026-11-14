# Vietnamese Legal Issue Spotting: full-judgment Generator, facts-only Judge

Contract hiện tại: `fac_semantic_grounding_v4`. Không yêu cầu evidence quotes, exact substring matching hay source span IDs. Pipeline dùng schema FAC: Generator đọc bản án đầy đủ để chọn CORE issues và giải thích bằng `benchmark_seed.facts_clean`; Judge độc lập chỉ đọc facts_clean, cặp issue/explain và lịch sử facts-only. Hai vai trò có client, system prompt và request riêng dù dùng cùng DeepSeek đã serve. Chỉ bản án Judge PASS và đạt validation mới được xuất. Đây là candidate gold labels có kiểm chứng tự động; cần đánh giá chuyên gia để xác định độ chính xác pháp lý thực tế.

## Input và output

Script production mặc định đọc `/workspace/storage-shared/nlp/hieplh8/research/VT-LegalBench/output/rule_extraction/haipl_filtered/clean.jsonl`, chọn tối đa 1000 bản án đầu. Đổi `INPUT_PATH` và `LIMIT` ngay trong `scripts/run_pipeline.sh`; file mẫu phát triển vẫn là `input/sample_input.jsonl`. Bắt buộc mỗi dòng có `doc_name`, `markdown` là chuỗi không rỗng, cùng object `benchmark_seed` có bốn chuỗi không rỗng: `facts_clean`, `facts`, `application`, `conclusion`. Không dùng fallback sang situation hoặc tự tạo dữ liệu thiếu. Mọi metadata khác giữ nguyên. JSON duplicate keys/non-finite numbers bị từ chối. Nếu top-level đã có `issues` hoặc `explain`, pipeline báo xung đột và dừng trước inference, không ghi đè.

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
2. Chính Generator audit **ngữ nghĩa** tất cả cặp issue/explain trong 5 ví dụ trước khi dùng chúng. Request chỉ có facts_clean, labels và IDs ví dụ/cặp để bookkeeping; không có quotes, source spans hoặc span IDs. Mỗi cặp có issue_supported, explain_supported và explanation. Semantic rejection của reference được báo riêng bằng FewShotGroundingError, giữ nguyên gold labels/facts và không retry để ép đổi false thành true. Kết quả approval được cache theo manifest. Dry-run chỉ kiểm tra cấu trúc.
3. Generator nhận đủ facts_clean, facts, application, conclusion và markdown qua allowlist, cùng ví dụ được phép. Generator chọn CORE issues thực sự được application xử lý và phù hợp conclusion; issue/explain và public rebuttal chỉ dựa trên facts_clean.
4. Issue có issue_id, issue_text, explain và metadata ba thành phần để kiểm tra định dạng. private_judicial_support chỉ có issue_id, hai semantic scope flags và explanation riêng; không có trích dẫn. Scope chưa xác nhận được xem là vấn đề semantic để Generator xem xét lại hoặc loại issue, không ném lỗi kỹ thuật chỉ vì false flag.
5. Judge nhận một projection mới: facts_clean, public issue/explain pairs và facts_argument công khai. Không truyền full record, raw facts, application, conclusion, markdown, citations, few-shot hay private scope metadata. SafeHistory chỉ chứa typed public feedback, facts_arguments và Judge assessments. Không chuyển private source notes hoặc reasoning_content. Những public claims chưa được xác minh tiếp tục được Judge đối chiếu về ý nghĩa với facts.
6. Blind discovery là request facts-only độc lập của cùng Judge. Mỗi đề xuất có một giải thích semantic, không cần evidence fields; đề xuất có thể bị loại sau khi đánh giá coverage.
7. Judge chấm 8 tiêu chí: grounding, legal_relevance, coverage, independence, format, explanation_quality, consistency, deduplication. Mỗi cặp có **hai flags issue_supported/explain_supported riêng**. Paraphrase đúng và suy luận pháp lý hợp lý là hợp lệ; thêm sự kiện không được facts hỗ trợ là lỗi. Judge không khẳng định đã xác minh phạm vi xét xử thực tế.
8. Feedback nêu issue, lỗi, chi tiết thiếu/mâu thuẫn/suy diễn, lý do và cách sửa trong explanation. Generator được ACCEPT/CONTEST/PARTIALLY_ACCEPT bằng facts_argument; Judge WITHDRAW/UPHOLD/PARTIALLY_WITHDRAW có explanation. Tối đa 6 lượt revision và 7 Judge evaluations; final revision luôn được đánh giá, giữ early stop và stagnation. Stagnation theo candidate/arguments lặp lại, không theo việc có quote mới hay không.
9. Chỉ final candidate với cả hai grounding flags, 8 tiêu chí, coverage, private scope và mechanical validation đều đạt mới COMPLETED. Candidate semantic không đạt sau debate là REJECTED. API/parsing/schema/ID/format không sửa được sau retry là FAILED. Một lỗi grounding được Judge ghi REVISE không tự biến thành exception.

Python tiếp tục kiểm tra JSON/schema, IDs, pairing, prefix/focus group, ba phần, duplicate cơ học, coverage references, PASS consistency và input/output preservation. Grounding của diễn đạt tự nhiên do Judge đánh giá, không dùng exact/fuzzy matching, embeddings hay source spans. Chi tiết và tests A-G: [semantic_grounding.md](docs/semantic_grounding.md).

## Few-shot

`FEWSHOT_PATH=$PROJECT_ROOT/input/fewshot.jsonl`, đúng 5 ví dụ thuộc Marriage & Family, Criminal, Civil, Commercial, Administrative. Loader hỗ trợ `issues: [{issue, explain, ...}]` hoặc `issues: [string]` kèm `explain: [string]`; chuẩn hóa thành `facts_clean`, `issues`, `explain` cùng category/example_id. Không đưa application/conclusion/markdown của ví dụ vào request.

Reference `1178738-I03` đã được sửa để bỏ chi tiết "hợp đồng thế chấp đã được công chứng" không có trong facts_clean. Chỉ nhãn này thay đổi, không sửa facts hoặc bản án; bản gốc được giữ ở `docs/history/fewshot_before_grounding_fix.jsonl`. Khi đồng bộ B200 cần copy cả `input/fewshot.jsonl` đã sửa, không chỉ Python/prompts. Bản sửa này giữ nguyên byte của input/fewshot. Báo cáo correction trước đây ở [fewshot_startup_fix.md](docs/fewshot_startup_fix.md) là lịch sử; cơ chế span IDs trong báo cáo đó đã được thay bằng semantic audit.

Thông thường Generator nhận đủ 5 ví dụ ở mọi lượt. Nếu doc_name/official_document_id/web_url hoặc facts chuẩn hóa khớp ví dụ, loại chính ví dụ đó và ghi warning/audit `excluded_fewshot_examples`; không tự tạo mẫu thay thế. Với 5 vụ trùng trong input mẫu, mỗi vụ dùng 4 ví dụ khác. Judge không nhận ví dụ ở bất kỳ giai đoạn nào.

## Chạy trên B200

Giữ nguyên project root `/workspace/storage-shared/nlp/minhpn19/LegalDataset`, Generator `http://172.29.62.173:8000/v1`, Judge `http://172.29.62.175:8000/v1`, model ID `DeepSeek-V4.1-Flash-1017`. Client chỉ gọi HTTP, không load weights/GPU local. Python >=3.10; dependencies runtime chỉ Pydantic và httpx.

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
# Chỉ khi chưa cài package/dependencies trong environment:
.venv/bin/python -m pip install -e '.[test]'

DRY_RUN=true bash scripts/run_pipeline.sh
```

Sau khi đồng bộ scripts sang B200, chỉnh tên run trực tiếp trong `scripts/run_pipeline.sh`:

```bash
export RUN_DIR="${RUN_DIR:-$PROJECT_ROOT/output/run_1k_dual_server}"
```

Năm đường dẫn luôn được dựng theo RUN_DIR, kể cả khi terminal còn export các đường dẫn cũ:

```text
RUN_DIR/
  judgment_with_issues.jsonl
  rejected_cases.jsonl
  audit/
  logs/
  checkpoints/
```

Sau đó chỉ cần:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
bash scripts/run_pipeline.sh
```

Giữ cùng RUN_DIR/input/cấu hình semantic để resume. Không đổi START_INDEX theo số dòng output: output chỉ chứa bản án PASS. `LIMIT=1000` là default trong script; `LIMIT=0` chọn toàn bộ input. Batch 100 cho phép 40 vụ chạy và các vụ đang chờ tiếp tục khi worker rảnh. GPU scheduling thực tế do server quyết định. Để resume run đang nằm ở `output/1k`, đặt RUN_DIR thành `$PROJECT_ROOT/output/1k`.

Để chạy thử 1–2 vụ, dùng LIMIT=2 và một RUN_DIR khác, không dùng checkpoint pilot cho full dataset. Nếu dùng environment đang active, đặt `PYTHON_BIN="$(command -v python)"`. Chạy local để phát triển bằng `PROJECT_ROOT="$PWD"`; script vẫn giữ default root B200.

## Cấu hình

Toàn bộ biến runtime được đưa ra `scripts/run_pipeline.sh`. RUN_DIR có thể được cấu hình trong file hoặc từ môi trường; cả 5 đường dẫn kết quả luôn lấy từ RUN_DIR, không đọc các biến *_PATH cũ trong terminal. Các biến còn lại giữ cơ chế environment override; nếu đã export INPUT_PATH/LIMIT/endpoint từ trước, giá trị đó vẫn có ưu tiên hơn default của chúng trong file. Đã bỏ ENABLE_EVIDENCE_VALIDATION; semantic grounding luôn là điều kiện PASS của Judge, không phải một quote-validation toggle.

| Nhóm | Defaults chính |
| --- | --- |
| Input | `INPUT_PATH=.../haipl_filtered/clean.jsonl`, `FEWSHOT_PATH=$PROJECT_ROOT/input/fewshot.jsonl` |
| Output | `RUN_DIR=$PROJECT_ROOT/output/run_1k_dual_server`; cả 5 đường dẫn trong run này |
| Agent | Generator `.173`, Judge `.175`; hai backend `deepseek_vllm`, thinking bật, effort `high` → budget **50** |
| Runtime | `MAX_WORKERS=40`, `MAX_CONCURRENT_REQUESTS=40`, `BATCH_SIZE=100`, `START_INDEX=0`, `LIMIT=1000` |
| Debate | `MAX_DEBATE_ROUNDS=6` (cho phép 1–6), early stop/stagnation bật |
| Tokens | **131073 token sinh mới riêng cho mỗi request của mỗi vai trò**, input guard 100000, context guard 262144 |
| Count | `TOKEN_COUNT_METHOD=auto`, `TOKENIZER_PATH` rỗng |
| Failure | `API_REQUEST_TIMEOUT=300`, mỗi vai trò max_retries=3, `MAX_JSON_REPAIR_RETRIES=2`, `FAIL_ON_RECORD_ERROR=false` |
| Resume/log | `RESUME=true`, `OVERWRITE_OUTPUT=false`, raw responses mặc định false |

vLLM gửi `chat_template_kwargs={"thinking":true,"reasoning_effort":50}`. Có thể chọn low=25, high=50, xhigh=75, max=100 hoặc budget số 1–100. `extra_high` là alias cũ cho 100, có log; medium/minimal mặc định lỗi. Tắt bằng THINKING_ENABLED=false hoặc effort=none. Hosted API/generic Qwen vẫn có adapter riêng. Effort 50 không phải giới hạn 50 token. Tham khảo [recipe vLLM](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4.1-Flash).

`TOKEN_COUNT_METHOD=auto` dùng tokenizer local khi có, còn DeepSeek vLLM thì gọi `/tokenize` với đúng messages và thinking kwargs; không chạy inference thứ ba và không cần weights phía client. Nếu endpoint không sẵn, log và dùng UTF-8 byte upper bound bảo thủ. `vllm` bắt buộc count endpoint; `utf8_byte_upper_bound` giữ cách guard cũ. `/tokenize` dùng chung giới hạn HTTP của hai vai trò. Đây là cách tránh từ chối sớm bản án tiếng Việt đầy đủ + few-shot chỉ vì số bytes lớn; không tăng token/context budget hoặc cắt nguồn. Tham khảo [protocol tokenization vLLM](https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/serve/tokenize/protocol/).

Nếu server không hỗ trợ output 131073/context tương ứng, request vẫn lỗi rõ ràng; client không tự hạ budget. Các biến API_KEY/secret file và sampling vẫn hoạt động; secrets không được log. Sampling null không gửi.

## Failure, resume và audit

Main output chỉ chứa COMPLETED. `rejected_cases.jsonl` chứa doc_name, rounds, issues/explain cuối, final verdict, lý do và toàn bộ feedback_history. FAILED lưu trong logs/failures.jsonl, không nhầm với REJECTED. Với FAIL_ON_RECORD_ERROR=true, ngừng nhận vụ mới khi có lỗi và chờ vụ đang chạy; false cho phép xử lý tiếp những vụ khác. Có thể tăng timeout/giảm workers bằng environment khi server chậm. Exit 0 khi toàn bộ selection đã COMPLETED hoặc REJECTED; exit 2 khi còn FAILED/PENDING hoặc có lỗi cấu hình. Không cam kết tất cả input sẽ PASS.

SQLite là nguồn trạng thái chính, output/rejected được ghi atomic theo index input. Skip COMPLETED/REJECTED khi resume, retry FAILED/RUNNING/PENDING. Manifest hash toàn input, 7 prompts, source code, cấu hình semantic, few-shot và export policy `fac_semantic_grounding_v4`. Checkpoint quote/span contract v3 bị từ chối trước khi mở SQLite để ghi; dùng RUN_DIR mới ở trên, không xóa checkpoint cũ. Đổi few-shot/prompts/nguồn/model/effort/selection cần bộ đường dẫn mới; thay concurrency, timeout, retry, logging không làm đổi semantic hash. Không xóa checkpoint cũ để lách kiểm tra.

Audit từng vụ giữ candidate/private semantic scope notes của Generator, facts-only Judge reviews, explains, debate, excluded examples và request usage. `audit/fewshot_validation.json` lưu semantic review/report với support flags và explanations; không có quotes hoặc span IDs. Lỗi phê duyệt ghi toàn bộ findings (doc_name, issue_index, issue/explain, lý do), review, sanitized API calls và usage vào `fewshot_validation_failed.json`/checkpoint. Summary đánh dấu `global_status=FAILED`, `fewshot_grounding=NOT_APPROVED` khi startup bị chặn, không dùng ví dụ lỗi hoặc đánh dấu vụ giả thành công. SAVE_RAW_RESPONSES=true lưu final JSON để debug, vẫn loại reasoning_content. Dữ liệu private không vào request Judge hoặc thêm vào main output ngoài input gốc.

## Kiểm chứng

```bash
.venv/bin/python -m pytest -q
PROJECT_ROOT="$PWD" INPUT_PATH="$PWD/input/sample_input.jsonl" DRY_RUN=true bash scripts/run_pipeline.sh
```

Các test contract cũ trái với thiết kế mới được giữ tại `tests/legacy_situation_contract/*.txt`; chúng không còn là kiểm thử của API hiện tại. Tests mới kiểm tra full sources, facts-only allowlist qua blind/retry/rebuttal/final, paraphrase/unsupported-detail debate, private metadata isolation, 5 examples/overlap/screening, 6 revisions, output preservation, reject/failure, resume/fingerprints, 40 workers và 40 HTTP requests. Các API/retry/effort tests vẫn chạy. Báo cáo hiện tại ở [docs/semantic_grounding.md](docs/semantic_grounding.md); [docs/fac_refactor.md](docs/fac_refactor.md) mô tả contract v3 lịch sử. Các báo cáo Qwen/situation cũ là lịch sử, không phải kết quả kiểm chứng contract mới.
