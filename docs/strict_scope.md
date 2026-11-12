# Rubric CORE và blind discovery độc lập

Bổ sung hiện tại: định nghĩa học thuật, năm tiêu chí CORE, phép kiểm tra tính độc lập và adapter vLLM được ghi tại [academic_scope_vllm.md](academic_scope_vllm.md). CORE có thể là vấn đề cần Tòa xác định độc lập dù các bên không tranh chấp; bốn trường rubric và schemas vẫn giữ nguyên.

Bản cập nhật chỉ tập trung scope, đánh giá Judge và blind discovery. Model/endpoint DeepSeek, token budget 131073 cho mỗi request của mỗi agent, số vòng từ shell, debate hai chiều, API retries, checkpoint/resume và schema output chính được giữ nguyên. `ENABLE_BLIND_JUDGE_DISCOVERY` đổi default thành true theo yêu cầu.

## Điều kiện nhận gold

- CORE: vấn đề pháp lý độc lập suy ra được từ situation, gắn với yêu cầu/quyền/nghĩa vụ cần giải quyết, được đối chiếu với nhận định hoặc quyết định Tòa trong markdown.
- SUPPORTING_FACT: dữ kiện bổ trợ; tích hợp vào tình tiết quyết định của CORE liên quan nếu trọng yếu, không xuất thành issue riêng.
- IRRELEVANT: không đủ căn cứ, ngoài yêu cầu hoặc ngoài phạm vi giải quyết, hay chỉ là vấn đề phụ thông thường.
- DUPLICATE: cùng một câu hỏi pháp lý với CORE khác dù diễn đạt khác.

Các vấn đề phụ (án phí, kháng cáo, thủ tục thường lệ, tình tiết tăng/giảm nhẹ) không bị cấm theo từ khóa. Chúng chỉ được CORE khi thực sự có yêu cầu/tranh chấp độc lập hoặc vấn đề đặc biệt được Tòa trực tiếp giải quyết. Bạo lực chỉ làm căn cứ ly hôn, tình tiết định hình hình phạt hoặc người liên quan không được xem xét trách nhiệm không tự tạo thêm issue.

Judge phải trả bốn đánh giá độc lập trong rubric: `legal_relevance`, `coverage`, `grounding`, `format`, mỗi tiêu chí PASS/FAIL/NEEDS_REVIEW. Đúng format không đủ để PASS. Mỗi review có classification, `court_scope_confirmed`, quotes situation, quotes từ nhận định/quyết định và IDs CORE liên quan nếu là supporting fact/duplicate.

`coverage_analysis` ghi inventory các câu hỏi CORE được nguồn xác nhận, với evidence ở cả hai nguồn và mapping tới issues hiện tại. CORE còn thiếu phải có suggested_missing_issues và feedback ADD được situation hỗ trợ. `blind_comparison` kiểm tra từng đề xuất blind bằng MATCHED/MISSING/EXCLUDED/NEEDS_REVIEW; danh sách blind có thể sai và bị loại.

Acceptance gate dùng chung ở controller và exporter yêu cầu cả bốn tiêu chí PASS, chỉ có CORE với evidence phạm vi Tòa, và không còn gap coverage hoặc bất đồng blind. Không tự xóa vấn đề phụ rồi công nhận một bản sửa chưa được Judge chấm: Generator phải sửa và Judge phải kiểm tra bản mới. Không PASS sau giới hạn/dừng sớm vẫn REJECTED; API/JSON/validation thất bại vẫn FAILED.

`situation_error` vẫn độc lập: verified material missing facts không tự làm một bộ issues đúng theo situation bị loại. Vấn đề chỉ nhận diện được nhờ dữ kiện riêng của markdown phải đi vào situation_audit, không ép Generator thêm facts/issue ngoài situation.

## Hai giai đoạn

1. Judge Stage A: signature `discover(situation: str)`. Payload chỉ có situation; system prompt riêng cùng benchmark scope và DiscoveryOutput schema. Không nhận record, markdown, citations, output Generator hay feedback/lịch sử cũ. Mỗi inference dựng messages mới; trace history không tự được đưa vào request.
2. Generator: vẫn chỉ nhận situation, sau đó feedback qua firewall và lịch sử phản hồi của chính mình.
3. Judge Stage B: request mới nhận nguồn đầy đủ, candidate Generator và kết quả A, xác minh hai danh sách rồi tự tìm các CORE mà cả hai có thể đã bỏ sót.

Kết quả A, comparison, rubric, coverage và reviews nằm trong audit mỗi vụ. Khi Stage A thành công nhưng Generator lỗi, discovery đã hoàn tất vẫn được lưu trong failure audit. Phần giải thích/scope quotes bản án/coverage/blind không đi qua firewall sang Generator; chỉ enum, IDs được phép và quotes situation đã kiểm tra đi qua.

Validator kiểm tra structure, references, consistency và exact quotes. Nó không chứng minh tính đúng pháp lý, semantic duplication hoặc recall thực tế; các đánh giá đó vẫn cần LLM và kiểm tra độc lập bằng human annotations.

## Các file liên quan

- `prompts/benchmark_scope.md` (mới): scope chung được cả Generator, Judge và blind stage sử dụng.
- `prompts/judge_blind_discovery.md` (mới): instruction riêng cho Stage A.
- `prompts/judge_system.md`, `judge_reconsideration.md`: rubric, classifications, coverage và comparison với evidence.
- `prompts/generator_system.md`, `generator_revision.md`: core-only scope và xử lý feedback supporting/ancillary/out-of-scope.
- `src/legal_issue_pipeline/schemas.py`: thêm fields/schemas nội bộ bắt buộc; không đổi schema JSONL chính.
- `agents/base_agent.py`, `agents/judge.py`: dùng scope chung, request Stage A situation-only, validate contract đánh giá mới.
- `validators/judge_validator.py` (mới), `debate/controller.py`, `io/result_exporter.py`: acceptance gate CORE/rubric/coverage và audit.
- `config.py`, `scripts/run_pipeline.sh`: default blind=true, giữ cấu hình khác.
- `pipeline/runner.py`: kiểm tra các prompt bắt buộc và giữ discovery trong failure audit; cơ chế checkpoint/API không đổi.
- `tests/conftest.py`, `tests/unit/test_agents_and_debate.py`, `tests/fixtures/example.jsonl`: cập nhật fixtures cho contract mới và một đoạn quyết định Tòa tổng hợp.
- `tests/unit/test_judge_scope.py`, `tests/integration/test_blind_scope.py` (mới): scope filtering, missing/extra issues, hai giai đoạn không leakage, sửa supporting facts, bổ sung CORE còn thiếu, export gate và fingerprint.
- `README.md`, `docs/B200.md`, tài liệu này: hướng dẫn theo rubric mới.

## Chạy trên B200

Đồng bộ cả source và prompts mới tới project B200. Dùng namespace mới vì config, source và prompt fingerprints đã đổi; không sửa checkpoint cũ để ép resume. Tất cả file .py và .md prompt đã được fingerprint, nên PASS theo rubric trước không được tái sử dụng.

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset

RUN_DIR="$PWD/output/core_scope_v2"
OUTPUT_PATH="$RUN_DIR/judgment_with_issues.jsonl" \
REJECTED_PATH="$RUN_DIR/rejected_cases.jsonl" \
AUDIT_DIR="$RUN_DIR/audit" \
LOG_DIR="$RUN_DIR/logs" \
CHECKPOINT_DIR="$RUN_DIR/checkpoints" \
ENABLE_BLIND_JUDGE_DISCOVERY=true \
MAX_DEBATE_ROUNDS=8 \
bash scripts/run_pipeline.sh
```

Endpoint vẫn là `http://172.29.62.173:8000/v1`, model ID `DeepSeek-V4.1-Flash-1017` cho hai agent. Nếu dùng Python environment đang activate thay vì `.venv`, truyền `PYTHON_BIN="$(command -v python)"` trước lệnh bash. Chạy lại cùng lệnh để resume run mới.

Để pilot 2 records, dùng `LIMIT=2` và RUN_DIR khác, chẳng hạn `output/core_scope_pilot`; không đổi LIMIT rồi dùng lại checkpoint của pilot cho full run.

## Kiểm tra kỹ thuật

```bash
.venv/bin/python -m pytest -q
PROJECT_ROOT="$PWD" DRY_RUN=true bash scripts/run_pipeline.sh
bash -n scripts/run_pipeline.sh scripts/run_smoke_test.sh
```

HTTP smoke trong tests đi qua OpenAI-compatible client/adapters, ba request riêng (blind, Generator, evaluation), schemas, output, audit và checkpoint với MockTransport. Đây là smoke giả lập endpoint để kiểm tra kỹ thuật, không phải xác nhận chất lượng pháp lý của DeepSeek thật. Không chạy Qwen/GPU local cho lần cập nhật này.

Kết quả thực tế ngày 11/11/2026:

- Full suite: **123 passed in 3.08s**, stdout trong [strict_scope_test_results.txt](strict_scope_test_results.txt).
- Riêng hai test modules scope/blind mới: **31 passed in 0.41s**. Bao gồm một vòng phát hiện CORE còn thiếu, Generator bổ sung bằng evidence situation, Judge reconsideration rồi PASS; thông tin riêng của bản án không xuất hiện trong request Generator.
- Shell syntax qua; dry-run kiểm tra toàn bộ 54 input records qua. Default blind=true, MAX_DEBATE_ROUNDS=8 và output budget 131073 cho cả hai agent được kiểm tra.
- SHA256 input gốc không đổi. Prompt mới được đưa vào manifest, và tests thay từng file scope/blind sau một run PASS đều nhận fingerprint mismatch.
- GET `http://172.29.62.173:8000/v1/models` từ workspace hiện tại bị **ConnectTimeout**. Vì vậy chưa chạy/xác minh inference DeepSeek thật với rubric mới và không tuyên bố đã cải thiện precision/recall thực tế. Cần chạy pilot từ B200 và đối chiếu human annotations để đánh giá chất lượng pháp lý.
