# Hierarchical Judge — contract v5

Contract/manifest: `fac_hierarchical_judge_v5`. Nâng cấp trên kiến trúc hai vai trò hiện có; không thêm agent/model hoặc inference theo từng criterion. Blind discovery vẫn là request riêng của cùng Judge; mỗi evaluation thực hiện cả ba giai đoạn trong một inference: đánh giá từng cặp, kiểm tra chéo danh sách, tổng hợp verdict/feedback.

## Schema và điều kiện chấp nhận

Mỗi IssueReview bắt buộc có bốn nhóm:

| Nhóm | Atomic criteria |
| --- | --- |
| factual_grounding | actor_grounding, conduct_grounding, object_grounding, decisive_fact_grounding, semantic_inference |
| subject_liability | subject_precision, conduct_attribution, liability_precision, subject_grouping |
| atomicity | atomicity, independence, overlap, granularity |
| explanation_review | factual_basis, legal_connection, issue_alignment |

Mỗi criterion có `status=PASS/FAIL/UNCERTAIN` và `reason` ngắn. Năm grounding criteria có thêm `basis=FACT/SUPPORTED_INFERENCE/UNSUPPORTED/UNCERTAIN`; basis phải phù hợp status. Hai compatibility flags `issue_supported`/`explain_supported` phải bằng kết quả nhóm grounding/explanation. Có FAIL thì issue REVISE/REMOVE; chỉ còn UNCERTAIN thì NEEDS_REVIEW. Chưa biết kết quả pháp lý cuối cùng không tự tạo UNCERTAIN.

`coverage_analysis` giữ inventory C IDs, matched I IDs và bốn `tests`: facts_grounding, legal_relevance, independence, existing_coverage. Existing coverage PASS nghĩa là đã kiểm tra và xác định đúng các matches, hoặc xác nhận không có câu hỏi hiện tại bao quát. ADD chỉ hợp lệ với inventory không match và cả bốn tests PASS; feedback phải gắn coverage_ids cụ thể. Blind đề xuất sai, trùng hoặc chỉ là tiền đề có thể EXCLUDED.

`cross_issue_evaluation` gồm bốn criterion reviews: coverage, deduplication, fragmentation, over_merging; findings có X ID, kind, issue_ids, explanation. Có lỗi xác định thì FAIL và finding/feedback liên kết. Uncertainty cũng chặn PASS. Giữ đủ tám global rubrics; chúng phải nhất quán với kết quả chi tiết, không lấy điểm trung bình để bỏ qua lỗi.

Feedback mới bắt buộc:

```json
{
  "feedback_id": "F1",
  "issue_ids": ["I1"],
  "failed_criterion": "explanation_review.issue_alignment",
  "error_code": "INCONSISTENT_EXPLANATION",
  "action": "REVISE",
  "problem": "Explain trình bày khoản vay trong khi issue là quyền ly hôn.",
  "reason": "Dữ kiện vay có thật nhưng không giải thích vì sao quyền ly hôn phát sinh.",
  "requested_change": "Giải thích yêu cầu ly hôn và tình trạng mất tích từ facts_clean."
}
```

Các trường tùy chọn `criterion_refs=[{issue_id,criterion}]`, `coverage_ids`, `cross_issue_ids` liên kết feedback nhóm, câu hỏi thiếu và cross-list findings. Mọi adverse criterion phải có feedback trực tiếp hoặc criterion_refs rõ ràng. Không còn feedback.explanation; summary/assessment explanation vẫn giữ.

`scope_rubric_passes` được dùng ở cả controller và exporter. COMPLETED yêu cầu mọi atomic criterion PASS, mọi cặp CORE/PASS, compatibility flags nhất quán, tám rubrics PASS, bốn cross-checks PASS/không findings, mọi CORE có coverage, blind chỉ MATCHED/EXCLUDED, không error codes/feedback/disputes, cùng các kiểm tra format/ID/cấu hình bắt buộc. Exporter còn đối chiếu reviews với candidate thực tế và blind discovery đã lưu, không tin một tập con tự ghi PASS.

## Semantic findings khác lỗi kỹ thuật

Pydantic và `validate_structure` kiểm tra field/type, unknown/duplicate IDs, mỗi cặp đúng một review, các reference hợp lệ và đủ rebuttal assessments. Schema/format không hợp lệ mới vào bounded JSON repair; API/timeout/parsing không phục hồi là FAILED.

`consistency_errors` kiểm tra status/basis/flags/verdict/rubrics, feedback cho từng adverse criterion và coverage/cross-list agreement. Đây là kiểm tra semantic consistency, không ném exception để yêu cầu model đổi nhận định. Judge tự ghi overall PASS nhưng criterion FAIL/UNCERTAIN vẫn bị chặn. Raw Judge được giữ nguyên trong audit, kèm `judge_consistency_errors` ở từng evaluation và kết quả cuối. Có feedback thì Generator có thể sửa/CONTEST; không có feedback để xử lý một judgment mâu thuẫn thì REJECTED sớm với `JUDGE_INCONSISTENT`. Không tự sửa false thành true hoặc bịa feedback pháp lý.

Giữ tối đa sáu revisions và bảy evaluations; final revision luôn được Judge đánh giá lại đầy đủ. Có early stop/stagnation như trước. Nếu hết lượt chưa đạt thì REJECTED, lưu issues/explain cuối, reasons và toàn bộ feedback_history; không ghi main output. FAILED chỉ dành cho lỗi kỹ thuật. Main output bảo toàn input và chỉ thêm issues/explain ghép cặp.

## Scope và dữ liệu riêng

Generator vẫn đọc đủ facts_clean/facts/application/conclusion/markdown cùng các ví dụ được phép. Bản án giúp hiểu vụ việc nhưng không giới hạn labels vào những gì Tòa đã xét xử. Chỉ facts_clean làm căn cứ cho issue/explain và public facts_argument. `private_judicial_support` vẫn lưu hai flags và explanation trung thực trong audit; việc chưa được Tòa giải quyết không phủ quyết câu hỏi facts-supported. Do đó compensation/no extra claim, child support/no request và tài sản/nợ chung chưa được Tòa giải quyết không tự bị loại; cũng không tự thêm khi facts không có căn cứ.

Judge chỉ nhận facts_clean, projection public của candidate và typed SafeHistory. Không dump full GeneratorOutput hoặc private notes vào Judge, kể cả retry/rebuttal/reconsideration. Candidate/argument vẫn là claims cần đối chiếu, không trở thành facts mới. Không dùng exact quotes, spans, substring grounding, embeddings hoặc LLM thứ ba. Five-shot semantic startup audit giữ nguyên bằng chính Generator; input và gold reference không thay đổi trong bản nâng cấp này.

## Checkpoint và chạy B200

Giữ nguyên cấu hình script: root B200 `/workspace/storage-shared/nlp/minhpn19/LegalDataset`; Generator `.173`, Judge `.175`, model DeepSeek-V4.1-Flash-1017, effort high, 40 workers/requests, batch 100, sáu revisions, max new tokens 131073 riêng từng request. Các đường dẫn production mặc định không được sửa trong bản nâng cấp này.

Vì schema/prompts/source thay đổi, **chọn RUN_DIR mới trong scripts/run_pipeline.sh** trước lần chạy đầu, ví dụ:

```bash
export RUN_DIR="${RUN_DIR:-$PROJECT_ROOT/output/run_1k_hierarchical_v5}"
```

Sau khi đồng bộ src/prompts/scripts lên B200, chạy:

```bash
cd /workspace/storage-shared/nlp/minhpn19/LegalDataset
bash scripts/run_pipeline.sh
```

Cả năm output paths tự lấy theo RUN_DIR. Nếu terminal còn export RUN_DIR cũ, xóa biến đó hoặc mở terminal mới trước khi chạy để default mới có hiệu lực. Giữ nguyên RUN_DIR/input/semantic config cho các lần resume tiếp theo. Manifest có export_policy v5 cùng hash source/prompts/input/config/fewshot; v4 và các schema cũ bị từ chối read-only, không migrate/xóa kết quả cũ.

## Kiểm chứng

```bash
.venv/bin/python -m pytest -q
PROJECT_ROOT="$PWD" INPUT_PATH="$PWD/input/sample_input.jsonl" DRY_RUN=true bash scripts/run_pipeline.sh
```

`tests/integration/test_hierarchical_judge.py` kiểm tra từng criterion FAIL/UNCERTAIN chặn forged PASS (32 tổ hợp), đủ mọi criterion, feedback required fields và grouped references, supported paraphrase, invented violence, actor attribution, aligned explanation, shared actors, unknown final outcome, no-extra-compensation, family non-adjudication, SPLIT, omitted interest ADD với bốn tests, duplicate principal, blind premise EXCLUDED, sáu revisions/uncertainty, raw contradictory PASS không repair, structural repair và exporter revalidation. Các tests hiện có tiếp tục kiểm tra CONTEST/WITHDRAW, private sentinels qua blind/schema retry/history/revision/final, HTTP payload, output preservation, FAILED/REJECTED isolation, resume và từ chối checkpoint cũ không sửa file.

Semantic responses trong tests được định nghĩa trước. Tests chứng minh protocol, routing, privacy và deterministic gate, không chứng minh độ chính xác pháp lý của model thật. Báo cáo kết quả thực tế: `hierarchical_judge_validation.txt`, dry-run: `hierarchical_judge_dry_run.txt`. Hai endpoint private đều connect timeout từ máy phát triển, nên chưa có live inference smoke test cho v5 và không chạy production dataset.

## Các file đã sửa

- Schema: `src/legal_issue_pipeline/schemas.py`.
- Agents và kiểm tra Judge: `src/legal_issue_pipeline/agents/judge.py`, `agents/generator.py`, `validators/judge_validator.py`.
- Điều phối và stagnation: `src/legal_issue_pipeline/debate/controller.py`, `debate/stopping.py`.
- Export/checkpoint: `src/legal_issue_pipeline/io/result_exporter.py`, `io/checkpoint.py` (comment về tương thích contract; cơ chế SQLite không đổi).
- Sáu prompts: `prompts/judge_system.md`, `judge_reconsideration.md`, `judge_blind_discovery.md`, `generator_system.md`, `generator_revision.md`, `benchmark_scope.md`.
- Regression tests mới: `tests/integration/test_hierarchical_judge.py`. Cập nhật fixtures và tests theo schema/scope mới: `tests/conftest.py`, `tests/integration/test_fac_agents_and_debate.py`, `tests/integration/test_semantic_grounding.py`, `tests/unit/test_fac_contract.py`.
- Tài liệu: `README.md`, file này, banner lịch sử `docs/semantic_grounding.md`, và liên kết contract hiện tại trong `AGENT_PROMPT.md`.
- Báo cáo: `docs/hierarchical_judge_validation.txt`, `docs/hierarchical_judge_dry_run.txt`.

Không sửa `scripts/run_pipeline.sh`, input, few-shot, model/client adapters hoặc cấu hình B200. Input và few-shot giữ nguyên SHA256 trước/sau.

Kết quả ngày 2026-11-14: **244 tests passed** (full suite); dry-run kiểm tra **62 records**, **5 few-shot**, nhận diện đúng 5 overlaps; không tạo output namespace hoặc checkpoint. Bash syntax, compileall và git diff whitespace checks đều đạt. GET `/v1/models` của cả hai endpoint đều connect timeout sau khoảng 3 giây trên máy này, nên không thực hiện live inference smoke test.
