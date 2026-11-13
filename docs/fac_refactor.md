> Historical v3 report. Current quote-free semantic contract and commands: [semantic_grounding.md](semantic_grounding.md).

# Báo cáo refactor FAC: full-judgment Generator, facts-only Judge

> Đây là báo cáo kiểm chứng của lần refactor ban đầu. Fix startup few-shot tiếp theo (sửa một nhãn reference và dùng span IDs thay quote do model chép) ở [fewshot_startup_fix.md](fewshot_startup_fix.md); bản án/facts gốc vẫn giữ nguyên.

Triển khai theo task ngày 2026-11-13. Đây là contract hiện hành; các báo cáo situation-only Generator/full-judgment Judge trước đây là lịch sử.

## Thay đổi chính và các file liên quan

- `io/records.py` (mới), `io/jsonl_reader.py`: xác thực bốn trường FAC bắt buộc và markdown/doc_name, allowlist nguồn đầy đủ cho Generator; báo lỗi xung đột issues/explain, không fallback situation.
- `schemas.py`: Issue có explain và facts evidence cho cả nhãn/giải thích; GeneratorOutput có private_judicial_support riêng. JudgeCandidate/PublicIssue/SafeResponse/SafeHistory là các schema độc lập không tham chiếu Generator private schema. ID và action được giới hạn bằng regex/enum, tránh dùng ID như kênh văn bản tùy ý. JudgeOutput có rubric 8 tiêu chí facts-only; không có markdown evidence, court_scope_confirmed hay situation_audit.
- `agents/generator.py`: nhận đủ năm nguồn, 5 ví dụ đã chuẩn hóa, initial/revision đều self-check facts/public/private và scope; evidence riêng từ application/conclusion được kiểm chứng đúng nguồn. Phản biện công khai dùng facts_clean.
- `agents/judge.py`: API nhận facts_clean string và JudgeCandidate, từ chối full record/GeneratorOutput. Public projection chỉ giữ issue_id/issue_text/explain, phản biện chỉ enum/ID/quotes. Previous judgment/history đều được chiếu lại theo schema safe; không chuyển private narratives. Blind discovery chỉ facts_clean, request mới không lẫn state.
- `io/fewshot.py` (mới), `prompts/generator_fewshot_validation.md` (mới): normalize 5 category và ghép cặp issue/explain, loại toàn bộ nguồn private của ví dụ; Generator kiểm tra grounding ngữ nghĩa trước khi dùng làm demonstrations. Không có role LLM thứ ba. Cache kiểm tra trong SQLite metadata theo manifest. Nếu ví dụ không đạt, run bị chặn rõ ràng và audit ghi lý do; không âm thầm dùng ví dụ đó.
- `validators/format_validator.py`, `validators/judge_validator.py`, `validators/output_validator.py`: ba phần/prefix/facts evidence, explain không viện dẫn nhận định/phán quyết, 8 tiêu chí PASS, coverage/duplicates và output projection đúng hai trường issues/explain.
- `debate/controller.py`, `state.py`, `stopping.py`: giữ tranh biện hai chiều; giới hạn 6 lần sửa + final Judge, early stop/stagnation, explain nằm trong chữ ký tiến triển. Chỉ final revision PASS được xuất; candidate best-valid chỉ phục vụ audit.
- `io/checkpoint.py`, `io/result_exporter.py`, `pipeline/runner.py`: cache approval few-shot, audit riêng, giải thích ghép cặp và private Generator proof được kiểm tra, rejected/failed độc lập, atomic ordered output. Manifest có few-shot SHA256 và export policy `fac_facts_only_v3`; checkpoint cũ bị từ chối.
- `config.py`, `scripts/run_pipeline.sh`: root B200/endpoint/model giữ nguyên; input sample_input, FEWSHOT_PATH mới, 40/40 workers/requests, batch 100, high=50, 6 rounds. Python và shell cùng defaults. Các budget/timeout/output/checkpoint infrastructure không đổi.
- `llm/openai_client.py`: TOKEN_COUNT_METHOD=auto có thể dùng /tokenize của server vLLM với đúng messages và thinking kwargs, tránh nhầm byte upper bound với token count khi nguồn full judgment + few-shot lớn. Dùng chung HTTP semaphore. Không đổi token budget, không cắt nguồn; thất bại trong auto có warning và guard byte bảo thủ. Chế độ vllm bắt buộc /tokenize. Hợp đồng tham số dựa trên [protocol chính thức](https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/serve/tokenize/protocol/), nhưng endpoint B200 thực tế chưa kiểm chứng được từ workspace.
- Cả 6 prompt cũ được sửa theo contract mới, giữ tiếng Anh và nhãn/giải thích tiếng Việt. README/B200 cập nhật; hướng dẫn cũ được giữ trong docs/history.
- Tests của contract cũ được giữ ở tests/legacy_situation_contract/*.txt vì chúng cố tình yêu cầu quyền truy cập và output ngược với task mới. API/HTTP retry/thinking tests giữ active; các tests mới kiểm tra những bảo đảm có ích cùng contract FAC.

## Luồng dữ liệu và giới hạn kiểm chứng

Input original được bảo toàn -> Generator full sources + examples đã duyệt -> GeneratorOutput có public issue/explain/facts evidence và private judicial evidence -> code dựng JudgeCandidate mới chỉ có issue_id, issue_text, explain và phản biện facts-only -> Judge facts-only chấm 8 tiêu chí -> feedback an toàn -> Generator phản biện/sửa -> final Judge -> chỉ PASS thành main output, đúng issues/explain cùng thứ tự.

Không còn assumption rằng Judge xác minh phạm vi Tòa trực tiếp giải quyết; đó là trách nhiệm riêng của Generator từ application/conclusion. Exact quotes chỉ xác minh provenance, booleans/rubric là đánh giá ngữ nghĩa của LLM. Code không giả vờ dùng regex để chứng minh toàn bộ một câu diễn giải được facts hỗ trợ. Private source fields/metadata/narratives bị loại bằng allowlist; verbatim private evidence được chặn khi chép vào public pair. Judge phải phát hiện các diễn đạt unsupported còn lại và không PASS. Cần human evaluation để đo độ chính xác của labels và scope trong thực tế.

## Dữ liệu thực tế và few-shot overlap

`input/sample_input.jsonl`: 62 records hợp schema. `input/fewshot.jsonl`: 5 records, 5 category, nhãn dạng object issue/explain. Không thay đổi bất kỳ file input nào; SHA256 cả 3 file JSONL được so trước/sau và khớp.

Năm ví dụ cũng có trong input, ở index 7, 10, 20, 30, 52. Vụ bình thường dùng đủ 5 ví dụ. Riêng mỗi vụ trùng bỏ chính ví dụ đó và dùng 4 ví dụ khác, ghi warning và audit `excluded_fewshot_examples`; không đưa đáp án của chính vụ vào prompt. Dry-run liệt kê đầy đủ các overlap. Approval few-shot chỉ thấy facts/labels để kiểm tra ví dụ; nó không dùng ví dụ chưa duyệt làm câu trả lời chuẩn và không làm lộ examples sang Judge.

## Kiểm thử và smoke

- `.venv/bin/python -m pytest -q`: **138 passed in 3.30s**. Log: [fac_test_results.txt](fac_test_results.txt).
- `PROJECT_ROOT="$PWD" DRY_RUN=true bash scripts/run_pipeline.sh`: thành công trên toàn bộ 62 bản án; 5 examples và 5 overlaps được báo; hai vai trò high=50, 40 workers/requests, batch 100, max rounds 6, mỗi request output 131073. Log: [fac_dry_run.txt](fac_dry_run.txt).
- `bash -n scripts/run_pipeline.sh scripts/run_smoke_test.sh`: thành công.
- Test HTTP qua httpx.MockTransport kiểm tra request serialized thật: một Generator approval request, Generator initial, Judge blind, Judge evaluation, Generator revision, Judge final. Header/model, high=50, max_tokens=131073 và token usage được kiểm tra. Các request Judge không chứa sentinels chỉ có trong application/conclusion/raw facts/markdown/private metadata/private rebuttal narratives, kể cả repair/history.
- Test giải thích unsupported ngăn PASS dù issue hợp lý; kiểm tra cấu trúc/nguồn evidence, feedback missing/duplicate/non-atomic/format/premature conclusion và phản biện WITHDRAW. Các trường hợp CACHED old policy/few-shot/prompt/model/input/effort đổi đều bị từ chối.
- Test max-rounds đo đúng 6 lần sửa, 7 evaluations; chưa PASS là REJECTED, không có lần sửa thứ 7. Early PASS có 0 revisions; stagnation không tự thành PASS.
- Test runner 100 bản án tổng hợp đo peak 40 workers và output đúng thứ tự. Test HTTP đo peak 40 request dùng chung cả hai vai trò. API timeout/retry/finish_reason, FAILED/resume, REJECTED và preservation tests đều thành công.
- Test /tokenize dùng cùng template và bảo vệ context; nếu count endpoint không có, không âm thầm bỏ guard. Tests cấm private fields trong Judge schema và typed history chứa private quote/ID tùy ý.
- GET `http://172.29.62.173:8000/v1/models` từ workspace: **ConnectTimeout**. Chưa chạy inference thật hoặc production dataset, chưa xác minh throughput 40 vụ hay /tokenize trên deployment đó. Không khởi động Qwen/GPU local để giả lập kết quả DeepSeek. Grounding ngữ nghĩa thật của 5 few-shot vẫn phải được runtime Generator kiểm tra khi chạy trên B200; dry-run chưa thực hiện việc này.

## Lệnh production B200

Đồng bộ src, toàn bộ 7 prompts, scripts và input/fewshot mới sang root B200. Không copy .venv local. Chọn RUN_DIR mới vì schema/prompt/manifest đã đổi:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
RUN_DIR="$PWD/output/fac_facts_only_v1"

PROJECT_ROOT="$PWD" \
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

Lặp đúng lệnh để resume. Namespace cũ của pipeline situation không được dùng lại. Để kiểm tra trước, chạy DRY_RUN=true; pilot LIMIT=2 dùng một RUN_DIR riêng. Output/inputs luôn đúng root B200. FAIL_ON_RECORD_ERROR=true vẫn là default; false cho phép tiếp tục vụ khác khi một vụ FAILED, và các lỗi vẫn được lưu riêng, không biến thành PASS.
