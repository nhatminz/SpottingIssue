> Historical contract: situation-only Generator / full-judgment Judge. Current FAC implementation and commands: [fac_refactor.md](fac_refactor.md).

# Định nghĩa Legal Issue, adapter vLLM và 60 vụ đồng thời

## Phạm vi prompts

`prompts/benchmark_scope.md` chứa định nghĩa Legal Issue, Legal Issue Spotting và năm điều kiện đồng thời của Core Legal Issue: Legal Question, Fact Grounding, Judicial Relevance, Independence, Non-conclusiveness. `BaseAgent` nối nguyên khối này vào system prompt của Generator, Judge Stage B và Judge Stage A, kể cả các lượt sửa JSON. Các prompt vai trò, revision và reconsideration được cập nhật tương ứng, toàn bộ hướng dẫn vẫn bằng tiếng Anh; issues, evidence và explanations vẫn dùng tiếng Việt.

Generator tự xác định yêu cầu giải quyết, câu hỏi trọng tâm và tình tiết quyết định trước khi sinh nhãn. Nó chỉ thấy situation và feedback được firewall cho phép. Judicial Relevance của Generator/Stage A là đánh giá tạm thời từ situation; chỉ Stage B có bản án để đối chiếu. Không yêu cầu hai bên phải tranh chấp: một vấn đề Tòa cần xác định độc lập để ra quyết định vẫn có thể là CORE. Không đưa điều kiện, tiền đề hoặc bước lập luận thành issue riêng dù Tòa có nhắc trong nhận định.

Judge áp dụng phép kiểm tra: nếu bỏ issue thì có mất một câu hỏi pháp lý độc lập mà Tòa thực sự cần giải quyết không? Đối chiếu cả precision và coverage. Vấn đề tố tụng có tình tiết đặc biệt vẫn có thể được giữ khi cần quyết định độc lập; kiểm tra thủ tục thường lệ bị loại. Blind discovery dùng cùng định nghĩa và không liệt kê mọi vấn đề pháp lý tiềm tàng.

Các phân loại trong prompt được ánh xạ vào schema hiện có:

| Khái niệm | Biểu diễn hiện có |
| --- | --- |
| CORE_ISSUE | `classification=CORE`, Generator `importance=CORE` |
| SUPPORTING_FACT | `classification=SUPPORTING_FACT`, tích hợp tình tiết vào CORE liên quan |
| ROUTINE_PROCEDURAL | `classification=IRRELEVANT`, `error_code=ANCILLARY_ISSUE` |
| IRRELEVANT | `classification=IRRELEVANT` |
| DUPLICATE | `classification=DUPLICATE`, tham chiếu CORE đã bao phủ |

Không thêm enum hoặc trường JSON. Năm tiêu chí được giải thích trong review hiện có và ánh xạ vào bốn trường rubric cũ: legal_relevance chứa Legal Question/Judicial Relevance/Independence; grounding chứa Fact Grounding; format kiểm tra Non-conclusiveness và cấu trúc cụm danh từ; coverage kiểm tra thiếu CORE. Các prefix tiếng Việt và cấu trúc ba thành phần giữ nguyên. Output chính vẫn chỉ thêm/cập nhật `issues` và `situation_error`, chỉ xuất bản án đã PASS; REJECTED và FAILED giữ chính sách cũ.

Định nghĩa là tổng hợp hướng dẫn học thuật; giới hạn chỉ CORE và cách biểu diễn cụm danh từ là quy ước riêng của benchmark:

- [American Bar Association](https://www.americanbar.org/groups/law_students/resources/student-lawyer/student-essentials/guide-to-case-briefing-in-law-school/): phân biệt sự kiện có ý nghĩa pháp lý, câu hỏi được Tòa trả lời và kết luận.
- [Australian National University](https://www.anu.edu.au/students/academic-skills/writing-assessment/other-assessments/writing-in-law): tách Issue, Rule, Application và Conclusion.
- [Monash University](https://www.monash.edu/student-academic-success/excel-at-writing/annotated-assessment-samples/law/law-legal-problem-solving/issue-identify-and-state-the-issues): câu hỏi pháp lý cụ thể khác với mô tả sự kiện đơn thuần.
- [Suffolk University Law School](https://lawguides.suffolk.edu/research-toolkit/researchplan): nhận diện câu hỏi từ dữ kiện, chủ thể, yêu cầu và phạm vi nghiên cứu.

## DeepSeek V4.1 trên vLLM

Theo [recipe chính thức của vLLM](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4.1-Flash), adapter mới `deepseek_vllm` dùng `chat_template_kwargs`, không áp dụng cách ánh xạ của hosted API:

| Cấu hình effort | Budget gửi trong template |
| --- | ---: |
| low | 25 |
| high | 50 |
| xhigh | 75 |
| max | 100 |
| Số nguyên 1–100 | Chính số đó |
| extra_high | 100, alias cũ của pipeline có warning |

`GEN_THINKING_EFFORT=75` được đọc từ biến môi trường thành số nguyên trong JSON. `*_THINKING_ENABLED=false` hoặc `*_THINKING_EFFORT=none` gửi `thinking=false`, không gửi budget. `medium`/`minimal` mặc định báo lỗi ở preflight trước khi tạo checkpoint; fallback chỉ xảy ra khi cấu hình rõ `THINKING_UNSUPPORTED_POLICY=fallback` và được log. Danh sách `*_SUPPORTED_EFFORTS` giới hạn alias được phép; budget số 1–100 vẫn được hỗ trợ. Extra-body có hai công tắc thinking phải có cùng giá trị boolean; budget sai hoặc các mức mâu thuẫn bị chặn trước HTTP.

Mặc định cả hai vai trò dùng `deepseek_vllm` và `xhigh`. Body gửi:

```json
{
  "model": "DeepSeek-V4.1-Flash-1017",
  "chat_template_kwargs": {"thinking": true, "reasoning_effort": 75},
  "max_tokens": 131073
}
```

Đây là phần tham số, body thật còn có messages/response_format. Effort 75 không có nghĩa 75 token; mỗi request mỗi vòng vẫn có output budget 131073 riêng. Adapter vLLM gửi sampling nếu bạn đặt giá trị khác null. Adapter hosted API `deepseek` và generic Qwen vẫn có thể chọn riêng. Audit lưu `actual_thinking_parameters.chat_template_kwargs.reasoning_effort`; không lưu reasoning_content hoặc tùy chọn template riêng không thuộc allowlist. Preflight log backend, trạng thái thinking, effort yêu cầu và effort hiệu lực của mỗi vai trò.

## Chạy 100 bản án với tối đa 60 vụ đồng thời

Script production mặc định `MAX_WORKERS=60`, `MAX_CONCURRENT_REQUESTS=60`, `BATCH_SIZE=100`, `LIMIT=0`. 100 tác vụ được đưa vào cùng đợt; tối đa 60 vụ giữ worker, các vụ chờ tiếp tục khi có worker rảnh. Mỗi vụ vẫn chạy các giai đoạn lần lượt; request limit 60 được dùng chung cả hai vai trò. Đây là giới hạn phía client; số sequence thực sự chạy và thời gian xếp hàng phụ thuộc server vLLM đang serve. Script smoke Qwen giữ 1 worker, 1 request, batch 8.

Đồng bộ `src/`, `prompts/`, `scripts/` mới sang B200 trước. Tạo run mới vì prompt/source/config đã đổi và toàn bộ sáu prompt được hash tự động:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset

RUN_DIR="$PWD/output/academic_scope_vllm_v1"

GEN_BACKEND=deepseek_vllm \
JUDGE_BACKEND=deepseek_vllm \
GEN_THINKING_EFFORT=xhigh \
JUDGE_THINKING_EFFORT=xhigh \
MAX_WORKERS=60 \
MAX_CONCURRENT_REQUESTS=60 \
BATCH_SIZE=100 \
START_INDEX=0 \
LIMIT=0 \
OUTPUT_PATH="$RUN_DIR/judgment_with_issues.jsonl" \
REJECTED_PATH="$RUN_DIR/rejected_cases.jsonl" \
AUDIT_DIR="$RUN_DIR/audit" \
LOG_DIR="$RUN_DIR/logs" \
CHECKPOINT_DIR="$RUN_DIR/checkpoints" \
bash scripts/run_pipeline.sh
```

Endpoint/model, blind discovery, 8 vòng tối đa và max output 131073 mỗi lượt đã là defaults trong script. Để dùng budget khác, sửa hai biến effort, ví dụ `63`; dùng bộ đường dẫn mới khi đổi tham số suy luận. Lặp đúng lệnh cho cùng run để resume; COMPLETED/REJECTED không chạy lại. Không xóa checkpoint cũ để lách fingerprint mismatch.

Kiểm tra input trước khi inference:

```bash
DRY_RUN=true bash scripts/run_pipeline.sh
```

Xem `total_input_records` và `selected_records`. Input local hiện có 54 bản án và không bị sửa; file 100 bản án trên B200 sẽ chọn đủ 100 khi `LIMIT=0`. Không hard-code input count hoặc thêm bản án giả vào dữ liệu production.

## Kiểm chứng

Kết quả: **169 tests passed in 5.18s** với `.venv/bin/python -m pytest -q`; log đầy đủ ở [academic_scope_vllm_test_results.txt](academic_scope_vllm_test_results.txt). `bash -n` hai script và dry-run input thực đều thành công, cấu hình hiệu lực xác nhận 60 workers / 60 requests / batch 100, effort vLLM 75 và mỗi vai trò có output budget 131073.

Tests kiểm tra các body HTTP thực qua MockTransport, bốn mức/numeric budget, tắt thinking, alias cũ, fail/fallback, xung đột template, preflight và log audit an toàn. Test runner dùng 100 bản án tổng hợp, đo đỉnh 60 worker và xác nhận output đúng thứ tự; test HTTP riêng đo đỉnh 60 request dùng chung cả hai vai trò. Các test scope xác nhận khối định nghĩa được cung cấp thật cho cả ba giai đoạn, loại supporting premise dù có trong nhận định Tòa, giữ thủ tục đặc biệt không có phản đối, phát hiện thiếu CORE và thay đổi cả sáu prompt gây fingerprint mismatch.

Hash JSON schemas của GeneratorOutput/JudgeOutput/DiscoveryOutput và SHA256 input được so sánh trước/sau, giữ nguyên. Smoke HTTP dùng các request độc lập và output budget 131073 mỗi request. Các tests dùng câu trả lời giả lập để kiểm chứng hợp đồng/điều phối; chưa chứng minh chất lượng ngữ nghĩa của model thật sau thay đổi prompts.

GET `/v1/models` từ workspace hiện tại bị ConnectTimeout. Chưa xác minh inference thật, mức effort thực thi hoặc throughput 60 vụ trên endpoint B200. Không khởi động model local hay dùng GPU client để thay thế phép kiểm tra này.
