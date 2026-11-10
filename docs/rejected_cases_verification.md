# Kiểm chứng bản cập nhật chỉ xuất PASS — 10/11/2026

Yêu cầu mới được ưu tiên hơn chính sách cho phép xuất candidate trước đây. Source hiện chỉ xuất record đã có final Judge PASS và validation bắt buộc đạt; các vụ bị loại lưu `REJECTED` riêng, lỗi kỹ thuật giữ `FAILED`.

## Kiểm thử tự động

Lần chạy `.venv/bin/python -m pytest -q` sau cập nhật: **92 passed in 2.44s**. Kiểm tra cú pháp cả ba shell scripts, compile Python và dry-run input thật 54 bản ghi đều qua. SHA256 input gốc vẫn là `12dde34f38e914766a5d0f52feb08b5eefef0584ceecd2a2079900a8c36ddf49`.

Các kiểm tra bổ sung gồm:

- Giới hạn 1/5/8/10 rounds; sau lần sửa cuối vẫn có Judge evaluation; không đạt thì REJECTED.
- Vụ bị loại nằm giữa hai vụ PASS không chặn output phía sau; thứ tự sau lọc được giữ.
- File rejected ghi doc_name, số vòng thực tế, issues cuối cùng, lý do và feedback history, kể cả khi `SAVE_DEBATE_HISTORY=false`.
- `FINALIZE_POLICY=best_valid` có chọn candidate cũ trong audit thì rejected file vẫn dùng issues của lần sửa cuối.
- API unavailable, timeout hoặc JSON hỏng vào FAILED; không xuất trong rejected hoặc main output.
- PASS với `situation_error=true` vẫn được chấp nhận.
- Resume bỏ qua cả COMPLETED và REJECTED, khôi phục hai JSONL từ checkpoint khi file projection bị hỏng, không ghi trùng.
- Thay input/model/prompt phát hiện mismatch và yêu cầu run mới.
- Mixed concurrent run: accepted=3, rejected=2, failed=1; cả hai file xuất đúng thứ tự.
- CLI validate đối chiếu đúng input index khi doc_name trùng; kiểm tra được output ít dòng hơn input và trường hợp mọi vụ bị loại.
- CLI run trên checkpoint toàn REJECTED trả exit 0, không inference lại; có FAILED thì vẫn chưa hoàn tất.
- Giá trị cũ `UNRESOLVED_POLICY=stop/continue` không thể xuất candidate chưa PASS.

## Qwen thật với exporter mới

Server Transformers OpenAI-compatible đã nạp Qwen3-4B local trên RTX 3090. Lệnh đã chạy:

```bash
INPUT_PATH="$PWD/tests/fixtures/example.jsonl" LIMIT=1 MAX_DEBATE_ROUNDS=1 \
SMOKE_ROOT="$PWD/output/qwen_pass_only_check" \
bash scripts/run_smoke_test.sh
```

Kết quả: accepted=1, rejected=0, failed=0; exit 0. Main output 1 dòng và rejected file rỗng; CLI báo `valid=true, records=1, rejected=0, failed=0, pending=0, selected_records=1`. Artifacts ở `output/qwen_pass_only_check/`. Fixture chỉ kiểm tra kỹ thuật và trùng ví dụ trong prompt; không đo chất lượng pháp lý hoặc khả năng tổng quát hóa.

Chạy lại cùng lệnh để resume cũng exit 0: không request API mới, output vẫn 1 dòng, file rejected rỗng, state transitions vẫn đúng 3 bước PENDING/RUNNING/COMPLETED. Server Qwen thử nghiệm đã được dừng sau kiểm tra để giải phóng GPU.

Nhánh REJECTED nhiều vòng và lọc các trạng thái hỗn hợp đã được kiểm tra bằng mocked integration tests; không tuyên bố đã kiểm chứng nhánh này với DeepSeek/B200. Các kết quả Qwen trên input thật và hạn chế chất lượng model ở bản trước vẫn được ghi tại [verification.md](verification.md).

Checkpoint trước cập nhật không được tự động tái sử dụng vì export policy, source và prompt fingerprints đã đổi. Giữ nguyên artifacts cũ; dùng bộ đường dẫn output/rejected/audit/log/checkpoint mới. Các lần resume của run mới sẽ bỏ qua COMPLETED/REJECTED theo yêu cầu.
