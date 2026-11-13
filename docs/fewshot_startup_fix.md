> Historical v3 report. Current quote-free semantic contract and commands: [semantic_grounding.md](semantic_grounding.md).

# Fix lỗi startup kiểm tra few-shot trên B200

## Lỗi đã tái hiện

Log gửi từ B200 cho thấy /tokenize và chat/completions đều trả HTTP 200. Pipeline dừng trong Generator.validate_fewshot, trước khi bắt đầu inference cho các bản án. Có hai nguyên nhân riêng:

1. Reference E4, doc_name `1178738`, issue_index `2` (issue thứ ba, `1178738-I03`) có chi tiết "hợp đồng thế chấp đã được công chứng". Facts chỉ xác lập hợp đồng thế chấp được ký, khoản nợ quá hạn và việc doanh nghiệp không có khả năng trả nợ. Không có căn cứ trong facts_clean để đưa điều kiện công chứng vào nhãn.
2. Audit trước đây buộc model chép exact quotes từ facts_clean chứa OCR, xuống dòng và Unicode. Quote không khớp gây repair chung; một lần model phát hiện đúng lỗi nội dung E4 nhưng thông báo cuối lại bị thay bằng quote error sau retry. Semantic rejection bị xử lý như lỗi JSON có thể sửa, trong khi sửa JSON không thể làm một tình tiết ngoài facts trở thành có căn cứ.

## Sửa reference và giữ nguyên dữ kiện

Chỉ sửa trường issue của reference `1178738-I03` trong `input/fewshot.jsonl` thành:

> Việc xác định quyền xử lý tài sản bảo đảm của Agribank đối với tàu cá KG 94472 TS khi DNTN Trường Huy còn nợ quá hạn và không có khả năng trả nợ

Không thêm/bớt/sửa facts_clean, application, conclusion, explain hoặc các labels khác. Giữ đủ 5 examples/categories. Bản gốc nguyên byte lưu ở [history/fewshot_before_grounding_fix.jsonl](history/fewshot_before_grounding_fix.jsonl); hash và thay đổi cụ thể ở [fewshot_grounding_correction.json](fewshot_grounding_correction.json). Các file bản án sample_input.jsonl và judgment_with_situation.jsonl giữ nguyên hash.

## Sửa cơ chế audit

- `schemas.py`: tách FewShotReview (model chọn facts_span_ids) khỏi FewShotValidation (report với quotes được code lấy từ nguồn).
- `io/fewshot.py`: đánh ID duy nhất theo example cho từng đoạn facts, như E4-S12; model chỉ được chọn IDs có thật của đúng example. Code resolve từng ID về exact substring gốc, giữ nguyên Unicode/OCR. Không fuzzy-match hoặc tự công nhận quote diễn đạt lại. Nhãn/ref đầy đủ và facts_clean vẫn được gửi cho Generator để đánh giá ngữ nghĩa, IDs chỉ giải quyết provenance.
- `agents/generator.py` và `prompts/generator_fewshot_validation.md`: yêu cầu model đọc mọi cặp và chọn IDs, không chép quotes. Review được lưu để audit và khôi phục cache.
- Semantic false ném `FewShotGroundingError` riêng, dừng ngay, không đi qua JSON repair hoặc ép model đổi false thành true. Báo toàn bộ findings với doc_name, issue_index (0-based), số issue (1-based), issue/explain và lý do. Lỗi thiếu pair/JSON/unknown span IDs vẫn được repair hữu hạn. Semantic rejection được giữ kể cả khi bằng chứng IDs trong response đó không hợp lệ.
- `pipeline/runner.py`: lưu nguyên review/findings và sanitized calls/usage khi startup fail, tính cả usage của lần audit thất bại, summary ghi `global_status=FAILED`, `fewshot_grounding=NOT_APPROVED`. Không biến thành REJECTED của một bản án hay xuất candidate giả. Approval lưu method source_span_ids_v1, cả raw review và report resolved; resume kiểm tra hai phần khớp nhau.
- Không thay đổi Judge facts-only firewall, output chỉ issues/explain, debate tối đa 6 revisions, mô hình/endpoint, path root B200, high=50, workers/requests=40, batch 100 hoặc max_tokens=131073 mỗi request.

Đây là sửa reference và provenance của audit; việc đánh giá hỗ trợ về ngữ nghĩa vẫn là đánh giá của model, không tuyên bố regex/chọn ID chứng minh được chất lượng pháp lý.

## Kiểm chứng

- Full suite: **154 passed in 3.56s**. [Log tests](fewshot_startup_fix_tests.txt).
- HTTP regression dùng reference gốc tái hiện đúng lỗi E4: một lần review, findings xác định doc_name 1178738 issue #3, không retry để lật rejection, không xử lý bản án hoặc xuất nhãn. Failed startup usage được thống kê.
- Cùng HTTP regression dùng reference đã sửa đi qua approval -> Generator -> Judge -> PASS, sau đó resume không gọi lại model. Test transport là mock có kiểm tra body thật; không phải kết quả DeepSeek thật.
- Các tests kiểm tra exact Unicode/OCR spans, IDs khác example, unknown IDs, duplicate/missing pairs, bounded repair, semantic false không bị quote error che, bản gốc backup và chỉ một label thay đổi.
- Dry-run trên 62 records và 5 examples thành công; high=50, 40/40 workers/requests, batch 100, max rounds 6 giữ nguyên. Bash syntax pass.
- GET /v1/models từ workspace hiện tại: ConnectTimeout. Chưa xác minh lại inference DeepSeek thật sau fix; cần chạy lại trên B200. Không chạy production dataset hoặc model local trong lần sửa này.

## Chạy lại trên B200

**Cần đồng bộ cả `input/fewshot.jsonl` đã sửa**, ngoài src và prompts. Nếu chỉ cập nhật Python mà giữ reference cũ thì hệ thống sẽ tiếp tục báo unsupported một cách đúng đắn. Giữ file gốc trong history để kiểm toán; không sửa facts cho khớp nhãn sai.

Dùng run directory mới vì code/prompt/few-shot fingerprint đã đổi; không xóa checkpoint cũ:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
RUN_DIR="$PWD/output/new_style_facts_v2"

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

Lặp đúng lệnh cho resume của run v2. Có thể chạy DRY_RUN=true trước; dry-run kiểm tra cấu trúc/hashes, không giả vờ đã hoàn tất semantic approval.
