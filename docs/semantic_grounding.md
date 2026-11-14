> Tài liệu lịch sử contract v4. Contract hiện tại là v5: xem [hierarchical_judge.md](hierarchical_judge.md). Quy tắc private scope và schema Judge bên dưới đã được thay thế.

# Quote-free semantic grounding — contract v4

Refactor theo yêu cầu ngày 2026-11-13 tại `/mnt/hdd/nhatminh/LegalDataset`.
Contract/manifest hiện tại: **`fac_semantic_grounding_v4`**. Không chạy production
inference hoặc thay input/few-shot trong lần chỉnh sửa này.

## Cơ chế được thay đổi

Đã loại bỏ toàn bộ evidence quote fields và source span IDs khỏi Generator,
Judge, blind discovery, coverage, feedback, rebuttal, history và few-shot audit.
Xóa `validators/evidence_validator.py` và mọi lời gọi `validate_quotes` trong
production path. Không thay bằng fuzzy matching, embeddings hoặc một hệ thống
trích dẫn khác. Bỏ config `enable_evidence_validation`/`ENABLE_EVIDENCE_VALIDATION`;
đánh giá semantic grounding vẫn luôn là điều kiện PASS.

`Issue` giữ `issue_id`, `issue_text`, `explain` và bốn structural metadata fields:
`focus_group`, `focus`, `subject_action`, `decisive_fact`. Matching metadata với
chính `issue_text` phục vụ kiểm tra định dạng ba phần, không so sánh với source.
Đã bỏ field `importance=CORE` dư thừa; Generator vẫn được hướng dẫn chỉ sinh
CORE, và Judge kiểm tra classification cho từng cặp.

Giữ JSON/schema validation, prefix/focus group, component order, IDs, mapping,
duplicate cơ học, coverage references và input/output validation. Chỉ bỏ những
exception cơ học đánh giá nội dung explain/quote; nội dung do Judge đánh giá.

## Grounding và ranh giới hai agent

Generator nhận nguyên vẹn `facts_clean`, `facts`, `application`, `conclusion` và
`markdown`, cùng các ví dụ được phép. Generator dùng toàn bộ bản án để chọn
issues thực sự được Tòa giải quyết; public issue/explain dựa trên facts_clean.
`private_judicial_support` chỉ còn issue_id, hai boolean semantic scope flags và
explanation riêng. Chúng được lưu vào audit, không được gửi Judge.

Judge API nhận facts_clean và một `JudgeCandidate` projection riêng, không
nhận full record. Projection chỉ có issue_id/text/explain và public
`facts_argument` cho phản biện. SafeHistory chứa typed feedback explanation,
public facts_argument và Judge assessment explanation. Không có raw source,
Generator private scope notes, few-shot, citations hoặc reasoning_content.
Không truyền nguyên candidate/private metadata bằng cách dump toàn bộ object.

`facts_argument` là phần lập luận công khai riêng; Generator được hướng dẫn chỉ
dùng facts_clean. Candidate/argument là các claims cần đánh giá, không phải
nguồn facts mới. Nếu Generator vẫn đưa unsupported detail vào public text,
Judge nhìn thấy claim đó trong cặp issue/explain và phải phản hồi semantic;
code không tuyên bố có thể chứng minh ngữ nghĩa bằng phép dò chuỗi.

Mỗi `IssueReview` có `issue_supported` và `explain_supported` riêng, classification,
verdict, error codes và explanation. Judge giữ đủ tám rubric criteria:
grounding, legal relevance, coverage, independence, format, explanation quality,
consistency và deduplication. Feedback giải thích cụ thể claim nào sai/thiếu,
vì sao facts không hỗ trợ, và cần sửa/bỏ/thêm/tách/làm rõ như thế nào.

Được phép paraphrase, tổng hợp và suy luận pháp lý hợp lý. Không được thêm sự
kiện chỉ vì nó phù hợp một câu chuyện pháp lý. Ví dụ lấy và bán điện thoại để
tiêu xài hỗ trợ cách diễn đạt về chiếm đoạt tài sản cho mục đích cá nhân; riêng
việc lấy điện thoại không xác lập việc dùng vũ lực/đe dọa. Judge không khẳng
định đã kiểm chứng phạm vi xét xử từ application/conclusion vì không có nguồn đó.

## Debate, trạng thái và acceptance

Giữ ACCEPT/CONTEST/PARTIALLY_ACCEPT của Generator; Judge được WITHDRAW/UPHOLD/
PARTIALLY_WITHDRAW. Các lập luận và phản hồi có thể paraphrase, không cần quote.
Giữ 6 revisions tối đa, 7 Judge evaluations, final evaluation sau revision cuối,
early stop và stagnation. Stagnation dùng signature của candidate/arguments để
nhận biết lặp lại/oscillation; không đánh đồng thiếu quote mới với thiếu grounding.

False Generator scope flag là unresolved semantic finding. Controller cho
Generator tự xem xét lại nó bằng nguồn đầy đủ qua `private_scope_findings`,
không đưa nguồn/findings riêng sang Judge. Nếu không giải quyết được, candidate
bị REJECTED dù Judge facts-only PASS.

- **COMPLETED:** final candidate có Judge PASS, cả hai support flags true trên
  từng cặp, tám rubric PASS, coverage/ID consistency, private scope và các
  mechanical checks đạt. PASS cũ không được dùng cho candidate đã thay đổi.
- **REJECTED:** semantic findings chưa giải quyết được sau debate/early stop,
  kể cả private scope còn unresolved. Có lý do và feedback history riêng.
- **FAILED:** API/parsing/schema/ID/format hoặc consistency kỹ thuật không sửa
  được sau retry. Một `UNSUPPORTED_FACT` review hợp lệ dùng debate, không ném
  exception chỉ vì câu không giống nguyên văn source.

Main JSONL chỉ chứa COMPLETED, bảo toàn toàn bộ input và chỉ thêm `issues` và
`explain`, ghép cặp theo index. Không thêm status, quotes, scores hay metadata
nội bộ. Rejected/audit/logs lưu riêng như trước.

## Few-shot

Giữ nguyên `$PROJECT_ROOT/input/fewshot.jsonl`, cả facts và gold labels. Đúng 5
ví dụ/categories; chỉ Generator nhận. Matching-case exclusion vẫn hoạt động để
không đưa đáp án của chính case đó làm demonstration.

Startup audit vẫn là một request của Generator, chỉ đánh giá semantic support
của mỗi issue/explain từ facts_clean. Schema duy nhất `FewShotValidation` gồm
example_id, issue_index, hai support flags và explanation. Không tạo spans,
không cấp span IDs, không resolve quotes. Approval cache ghi
`method=semantic_grounding_v1`. JSON/ID mapping sai được repair hữu hạn;
semantic false của reference vẫn được báo rõ bằng `FewShotGroundingError`,
không tự sửa nhãn hoặc retry để ép PASS.

## Manifest, checkpoint và production

Schema/prompt/source đã đổi nên checkpoint v3 không tương thích. Dùng namespace
v4 mới; không xóa hoặc ghi đè checkpoint `new_style_facts_v2` trước đây.
CheckpointManager kiểm tra manifest read-only trước SQLite writes, và test đã
kiểm tra database/export/manifest cũ giữ nguyên byte khi từ chối resume.

Giữ toàn bộ production defaults: root B200, endpoint/model, thinking high,
40 workers, 40 HTTP requests, batch 100, 6 rounds, token/context limits, resume,
checkpoint/logging/export mechanisms. Chỉ bỏ evidence-validation toggle đã lỗi thời.

Đồng bộ **src, cả bảy prompts và scripts** lên B200; không đồng bộ đè output hoặc
checkpoint cũ. Chạy production bằng environment hiện tại:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
RUN_DIR="$PWD/output/semantic_grounding_v4"

PROJECT_ROOT="$PWD" \
INPUT_PATH="$PWD/input/sample_input.jsonl" \
FEWSHOT_PATH="$PWD/input/fewshot.jsonl" \
GEN_API_BASE=http://172.29.62.173:8000/v1 \
JUDGE_API_BASE=http://172.29.62.173:8000/v1 \
GEN_MODEL=DeepSeek-V4.1-Flash-1017 \
JUDGE_MODEL=DeepSeek-V4.1-Flash-1017 \
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
RESUME=true \
DRY_RUN=false \
OVERWRITE_OUTPUT=false \
OUTPUT_PATH="$RUN_DIR/judgment_with_issues.jsonl" \
REJECTED_PATH="$RUN_DIR/rejected_cases.jsonl" \
AUDIT_DIR="$RUN_DIR/audit" \
LOG_DIR="$RUN_DIR/logs" \
CHECKPOINT_DIR="$RUN_DIR/checkpoints" \
bash scripts/run_pipeline.sh
```

Chạy lại đúng lệnh, cùng RUN_DIR để resume contract v4. COMPLETED/REJECTED được
skip; FAILED/PENDING/RUNNING được thử lại. Không tăng START_INDEX theo số dòng
output. FAIL_ON_RECORD_ERROR giữ default true: lỗi kỹ thuật có thể dừng nhận
case mới; semantic REJECTED không kích hoạt fail-fast.

Outputs nằm dưới RUN_DIR đã chọn: `judgment_with_issues.jsonl`,
`rejected_cases.jsonl`, `audit/summary.json`, `audit/fewshot_validation.json`,
`audit/<case_id>.json`, `logs/failures.jsonl`, `logs/pipeline.log` và
`checkpoints/state.sqlite3`. Default paths của launcher không bị đổi.

## Files thay đổi

- Schemas/config: `src/legal_issue_pipeline/schemas.py`, `config.py`.
- Agents: `agents/generator.py`, `agents/judge.py`, `agents/base_agent.py`.
- Debate: `debate/controller.py`, `debate/stopping.py`.
- Validators: `validators/format_validator.py`, `validators/judge_validator.py`;
  xóa `validators/evidence_validator.py`.
- IO/pipeline: `io/fewshot.py`, `io/result_exporter.py`, `io/checkpoint.py`,
  `pipeline/runner.py`.
- Launcher: `scripts/run_pipeline.sh` (chỉ bỏ evidence-validation toggle).
- Cả 7 files `prompts/benchmark_scope.md`, `generator_system.md`,
  `generator_revision.md`, `generator_fewshot_validation.md`, `judge_system.md`,
  `judge_blind_discovery.md`, `judge_reconsideration.md`.
- Tests: `tests/conftest.py`, `tests/unit/test_fac_contract.py`,
  `tests/integration/test_fac_agents_and_debate.py`,
  `tests/integration/test_fewshot_failure_regression.py`;
  thay `tests/unit/test_fewshot_span_review.py` bằng
  `tests/unit/test_fewshot_semantic_review.py`; thêm
  `tests/integration/test_semantic_grounding.py`.
- Docs: `README.md`, `docs/B200.md`, file này và
  `docs/semantic_grounding_dry_run.txt`. Đánh dấu các mô tả cũ trong
  `AGENT_PROMPT.md`, `docs/fac_refactor.md`, `docs/fewshot_startup_fix.md` là historical.

Input, few-shot labels, API adapter/client, worker/request scheduling và
checkpoint data cũ không thay đổi.

## Validation

Baseline trước refactor: 154 tests pass. Sau refactor: **164 tests pass**. Bộ
test đầy đủ gồm các yêu cầu A-G và production regression tests:

- A/F: đúng ví dụ paraphrase được chấp nhận; giữ nguyên input, chỉ thêm hai fields.
- B: chi tiết dùng vũ lực không có trong facts bị Judge feedback, Generator sửa,
  Judge đánh giá lại và PASS; không biến thành FAILED vì non-verbatim.
- C: fact chỉ có trong application/conclusion không trở thành nguồn Judge;
  unsupported public claim bị semantic review. Private metadata/sentinels không
  xuất hiện trong blind, retry, revision, history hoặc final Judge requests.
- D: CONTEST/PARTIALLY_ACCEPT không quotes, Judge có thể rút lại feedback sai.
- E: toàn bộ structured schemas và acceptance path không phụ thuộc quote/span.
- G: input/output schema, IDs, 6 revisions/7 evaluations, early stop/stagnation,
  PASS-only export, independent requests, 40 workers/40 concurrent HTTP calls,
  ordering/resume và bảo vệ checkpoint v3.

Mock Judge responses kiểm tra routing và acceptance; không phải bằng chứng model
live luôn đánh giá đúng ngữ nghĩa. Không chạy inference thật trên dataset.

```bash
.venv/bin/python -m pytest -q
PROJECT_ROOT="$PWD" PYTHON_BIN="$PWD/.venv/bin/python" DRY_RUN=true \
bash scripts/run_pipeline.sh
```

Dry-run thực tế trên sample input: **62 records, 5 examples, 5 overlaps, exit 0**,
manifest v4. Không tạo run directory hay thay input/output/checkpoint cũ.
Log đầy đủ ở `semantic_grounding_dry_run.txt`. Input SHA256
`a6bb9bd22f57e4f773a63d2a7ab98885b77b154f1caebc3940b25c717a20b0bf`,
few-shot SHA256 `bf57c4334ea9c10e5d809b86c466bcb6d19b8d0a790dd0a3c89946b89f24f95a`
giữ nguyên so với trước refactor.
