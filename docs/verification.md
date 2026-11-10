# Báo cáo kiểm chứng thực tế — 10/11/2026

Đây là báo cáo lịch sử trước bản cập nhật chỉ xuất PASS. Kiểm chứng chính sách REJECTED và output đã lọc hiện tại nằm ở [rejected_cases_verification.md](rejected_cases_verification.md).

Source được triển khai trong `/mnt/hdd/nhatminh/LegalDataset`. Dữ liệu gốc không bị sửa. Không chạy DeepSeek production hoặc tạo nhãn production.

## Môi trường và dữ liệu

- RTX 3090 24 GB, driver 555.42.06; PyTorch 2.6.0+cu124, CUDA khả dụng.
- `.venv` Python 3.10.20; Transformers 4.57.6; lm-format-enforcer 0.11.3; Pydantic 2.14.3.
- Qwen3-4B local có đầy đủ 3 shards safetensors và đã nạp thành công qua Transformers/SDPA/BF16.
- Không có vLLM/SGLang trong environment sẵn có. Đã dùng server OpenAI-compatible Transformers thật, không dùng response giả.
- Input 54 bản ghi, schema kiểm tra toàn bộ; `situation_error=null` ở 54/54 dòng.
- Chi tiết: [environment.json](environment.json), [data_profile.json](data_profile.json).

## Kiểm tra tự động

Kết quả cuối: **65 passed in 1.04s**, stdout đầy đủ trong [test_results.txt](test_results.txt). Unit và integration tests không cần GPU. Bao phủ quyền truy cập, private feedback firewall, hai chiều contest/withdraw/uphold, early stop/round limit/stagnation/final evaluation, format/evidence, JSON repair, API retry/timeouts, output preservation, concurrent order, checkpoint/resume/fingerprint và chính sách NEEDS_REVIEW. Test transport đi qua adapter/HTTP serialization thật bằng MockTransport; mocks chỉ ở test path.

`bash -n` qua cho cả ba scripts. Dry-run kiểm tra 54 input records, cấu hình và fingerprints thành công, không gọi API hoặc tạo nhãn; stdout trong [dry_run.txt](dry_run.txt).

## Inference Qwen thật trên hai bản ghi đầu của input

Lệnh cuối cùng trên dữ liệu thật:

```bash
SMOKE_ROOT="$PWD/output/smoke_verified" \
MAX_DEBATE_ROUNDS=1 JUDGE_MAX_OUTPUT_TOKENS=4096 \
FAIL_ON_RECORD_ERROR=false SAVE_RAW_RESPONSES=true \
bash scripts/run_smoke_test.sh
```

Kết quả **không thành công end-to-end trên dữ liệu thật**:

- Selected 2, FAILED 2, COMPLETED 0, NEEDS_REVIEW 0, output 0 dòng; exit code 2.
- Generator trả JSON nhưng sai prefix/metadata và/hoặc evidence không khớp nguồn, vẫn không sửa đúng sau 2 repair retries mỗi record.
- Tổng 6 Generator inference requests, 17.806 tokens API báo cáo.
- Judge không được gọi trong lượt cuối này vì initial Generator chưa qua validation. Các lượt khảo sát trước đó đã gọi Judge riêng nhưng model lặp explanation đến giới hạn 8.192/4.096 tokens; cũng bị từ chối, không xuất labels.
- Audit và failure logs được giữ tại `output/smoke_verified/audit/summary.json`, `output/smoke_verified/logs/failures.jsonl` và các file case tương ứng. Kết quả các lượt khảo sát giữ ở `output/smoke_initial`, `output/smoke`, `output/smoke_final`.

Lỗi Unicode ban đầu của grammar đã được sửa: alphabet hỗ trợ tiếng Việt. Sampling/chống lặp và giới hạn explanation đã được bổ sung. Không nới validation để ép Qwen PASS. File chính rỗng là kết quả dừng an toàn, không phải run thành công.

## Inference Qwen thật trên fixture ngắn

```bash
INPUT_PATH="$PWD/tests/fixtures/example.jsonl" LIMIT=1 MAX_DEBATE_ROUNDS=1 \
SMOKE_ROOT="$PWD/output/qwen_fixture" SAVE_RAW_RESPONSES=true \
bash scripts/run_smoke_test.sh
```

Kết quả kỹ thuật **thành công**, exit code 0:

- COMPLETED 1, FAILED 0, output 1 dòng, 1 issue; `situation_error=false` đúng kiểu boolean.
- Generator 1 request và Judge 1 request riêng, tổng 4.867 tokens; thinking tắt đúng adapter Qwen.
- PASS ban đầu, 0 debate rounds; không chạy nhiều vòng trên fixture vì early stop.
- Output giữ toàn bộ fields input, chỉ thêm `issues` và cập nhật `situation_error`; CLI validate báo `valid=true, records=1`.
- Trạng thái ghi nhận `PENDING -> RUNNING -> COMPLETED`.
- Chạy lại cùng lệnh để resume: exit 0, không inference mới, không thêm state transitions, output vẫn 1 dòng.
- Artifacts: `output/qwen_fixture/judgment_with_issues.jsonl`, `output/qwen_fixture/audit/summary.json`, `output/qwen_fixture/audit/states.jsonl`.

Fixture này là ví dụ ngắn cũng xuất hiện trong system prompt, chỉ chứng minh đường kết nối API và kiểm tra dữ liệu hoạt động. Không suy ra chất lượng pháp lý hoặc khả năng khái quát hóa từ PASS này.

Server Qwen thử nghiệm đã được dừng sau kiểm tra để giải phóng GPU. Khởi động lại bằng `bash scripts/serve_qwen_local.sh` trước khi chạy inference mới.

## Chưa kiểm chứng thực tế

- DeepSeek V4.1 Flash endpoint, thinking low/high/max và throughput trên B200; adapter mapping đã được unit test.
- Host Qwen bằng vLLM/SGLang; nhánh Transformers đã chạy thật.
- Debate nhiều vòng bằng hai LLM thật; logic này được kiểm tra bằng mocked integration tests, fixture thật dừng sớm.
- Chạy dài concurrent với GPU server, mất điện giữa transaction và phục hồi server trong thực tế. Concurrent ordering, failure isolation, timeout, retries và resume được mô phỏng trong tests; resume record hoàn thành đã kiểm tra thật.
- Độ đúng pháp lý, recall/precision và độ tin cậy gold; cần endpoint production mạnh hơn và human annotations độc lập.
