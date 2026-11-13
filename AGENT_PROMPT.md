> Historical initial task specification. Current roles and quote-free semantic requirements are documented in [docs/semantic_grounding.md](docs/semantic_grounding.md) and the active seven files under `prompts/`. This older specification does not override the current contract.

# YÊU CẦU CODEX: XÂY DỰNG PIPELINE TẠO GOLD LEGAL ISSUES BẰNG MULTI-AGENT DEBATE

## 1. Vai trò và mục tiêu

Bạn là Senior AI/ML Engineer, chuyên xây dựng hệ thống LLM inference, multi-agent, legal NLP, structured generation và data processing.

Hãy trực tiếp xây dựng một project Python hoàn chỉnh, có thể chạy thực tế, tại:

`/mnt/hdd/nhatminh/LegalDataset`

Input:

`/mnt/hdd/nhatminh/LegalDataset/input/judgment_with_situation.jsonl`

Mục tiêu là tạo ra bộ gold labels chất lượng cao cho tác vụ **Vietnamese Legal Issue Spotting**, dựa trên dữ liệu bản án tiếng Việt.

Pipeline sử dụng hai agent:

- **Generator Agent:** Trích xuất các vấn đề pháp lý từ `situation`.
- **Judge Agent:** Kiểm chứng các vấn đề pháp lý bằng cách tham khảo `situation`, bản án gốc và các thông tin trích dẫn pháp luật; đồng thời kiểm tra việc `situation` có thiếu dữ kiện quan trọng so với bản án không.

Hai agent có khả năng tranh luận, phản biện, sửa đổi nhận định qua nhiều lượt.

Cả hai sử dụng model DeepSeek V4.1 Flash, có thể được phục vụ qua cùng một OpenAI-compatible endpoint.

**Yêu cầu cốt lõi: Đây là pipeline tạo candidate gold labels cho benchmark, không phải pipeline dự đoán kết quả vụ án. Phải ưu tiên tính chính xác, độ bao phủ, tính trung thành với tình huống và khả năng kiểm toán hơn tốc độ.**

Không được chỉ tạo skeleton, pseudocode hoặc TODO. Hãy triển khai source code thực sự, unit tests, integration tests và shell scripts có thể sử dụng.

## 2. Khảo sát dữ liệu trước khi code

Đầu tiên, hãy đọc file JSONL thực tế, kiểm tra schema, kiểu dữ liệu, những trường có giá trị null và các tình huống đặc biệt.

Các trường chính:

- `situation`: Chuỗi mô tả tình huống vụ việc.
- `markdown`: Nội dung bản án đầy đủ dạng Markdown.
- `citations_law`: List các object chứa trích dẫn luật được trích xuất từ bản án. Có những trường như `article`, `clause`, `point`, `law_name`, `law_type`, `ref`, `span`, `year`.
- `citations`: List các object trích dẫn luật khác, với những trường như `dieu`, `khoan`, `diem`, `raw`, `target`, `source`, `kind`.
- `doc_name`: Định danh tài liệu.

Lưu ý: File thực tế đã tồn tại trường `situation_error`, với giá trị null trong các bản ghi hiện tại. Output cần ghi đè giá trị này bằng boolean, không được tạo trùng key.

Không giả định rằng hai trường citations hoàn toàn chính xác hoặc tương đương nhau. Không coi mỗi citation là một vấn đề pháp lý riêng.

Các trường citations chứa tham chiếu pháp luật, không nhất thiết chứa nguyên văn quy phạm pháp luật. Không được giả vờ rằng model đã kiểm tra nội dung điều luật nếu input không thực sự cung cấp nội dung đó.

Mỗi dòng input là một JSON object. Phải giữ nguyên thứ tự dòng, dữ liệu gốc và tất cả các trường không liên quan.

## 3. Output bắt buộc

File output mặc định:

`/mnt/hdd/nhatminh/LegalDataset/output/judgment_with_issues.jsonl`

Mỗi dòng output phải chứa toàn bộ object gốc, thêm hoặc cập nhật đúng hai trường:

`issues`: List các chuỗi legal issues.

`situation_error`: Boolean `true` hoặc `false`.

Ví dụ định dạng:

    {
      "...original_fields": "...",
      "issues": [
        "Việc xác định quyền yêu cầu ly hôn của người chồng khi người vợ đã bị Tòa án tuyên bố mất tích",
        "Thủ tục giải quyết yêu cầu ly hôn của người chồng khi người vợ vắng mặt tại phiên tòa sau hai lần được triệu tập hợp lệ"
      ],
      "situation_error": false
    }

Đây chỉ là ví dụ định dạng.

Không thêm các trường debug, score, judge feedback, metadata hay reasoning vào file output chính.

Thay vào đó, tạo thư mục riêng:

`output/audit/`

để lưu thông tin bổ sung phục vụ kiểm tra chất lượng, ví dụ:

- Các issue ở từng vòng.
- Feedback của Judge.
- Phản biện của Generator.
- Quyết định được chấp nhận hoặc bị bác bỏ.
- Các dữ kiện thiếu được phát hiện.
- Số vòng tranh luận.
- Trạng thái đạt đồng thuận hoặc chưa giải quyết được.
- Thời gian, token usage, cấu hình model và lỗi API.

Cần có file tổng hợp JSONL hoặc CSV phục vụ phân tích sau khi pipeline chạy.

**Không được tự động gán nhãn thành công khi một record thất bại do API, lỗi parse JSON hoặc lỗi validation.** Các trường hợp này phải được ghi vào failure log, và mặc định pipeline phải dừng an toàn để có thể resume. Không được thay thế kết quả lỗi bằng `issues=[]` và `situation_error=false` rồi coi là hoàn thành.

## 4. Định nghĩa chuẩn của Legal Issue

Mỗi legal issue phải là một cụm danh từ duy nhất, ngắn gọn, thể hiện vấn đề pháp lý cần giải quyết.

Cấu trúc bắt buộc theo đúng thứ tự:

**[Trọng tâm yêu cầu giải quyết] + [Hành vi/Đối tượng thuộc quan hệ pháp luật và chủ thể] + [khi / trong trường hợp + Tình tiết quyết định/đặc biệt]**

### 4.1. Nhóm mở đầu được phép

Bắt buộc chọn một trong bốn nhóm:

**Nhóm 1 — Trách nhiệm**

- Trách nhiệm pháp lý…
- Trách nhiệm hình sự…
- Trách nhiệm hành chính…
- Trách nhiệm dân sự…
- Trách nhiệm bồi thường thiệt hại…

**Nhóm 2 — Tính hợp pháp hoặc hiệu lực**

- Tính hợp pháp của…
- Hiệu lực pháp lý của…

**Nhóm 3 — Xác định vấn đề pháp lý**

- Việc xác định tư cách…
- Việc xác định đối tượng…
- Việc xác định giá trị…
- Việc xác định quyền…
- Việc xác định nghĩa vụ…
- Việc xác định quyền và nghĩa vụ…

**Nhóm 4 — Thẩm quyền, thời hiệu hoặc thủ tục**

- Thẩm quyền…
- Thời hiệu…
- Thủ tục giải quyết…

### 4.2. Quy tắc xác định trách nhiệm

Mặc định phải sử dụng **“Trách nhiệm pháp lý”** đối với hành vi có dấu hiệu vi phạm pháp luật.

Chỉ sử dụng một loại trách nhiệm cụ thể như hình sự, hành chính, dân sự hoặc bồi thường thiệt hại khi:

1. Tình huống đã xác nhận rõ căn cứ lựa chọn, chẳng hạn đã khởi tố, truy tố, ban hành quyết định xử phạt hoặc có yêu cầu bồi thường tương ứng.
2. Hoặc câu hỏi/yêu cầu gốc trong `situation` chỉ định đích danh loại trách nhiệm đó.

Việc Judge nhìn thấy bản án đã kết luận trách nhiệm hình sự KHÔNG đủ để ép Generator dùng “Trách nhiệm hình sự” nếu `situation` không chứa thông tin phù hợp với quy tắc trên.

### 4.3. Các quy tắc bổ sung

- Issue phải được hỗ trợ bởi dữ kiện thực sự xuất hiện trong `situation`.
- Không tự ý bổ sung chủ thể, hành vi, tình tiết hoặc hậu quả.
- Không suy diễn kết luận pháp lý cuối cùng thành issue.
- Không biến mỗi điều luật được viện dẫn thành một issue.
- Không tạo những issue mang tính giả định, quá xa yêu cầu giải quyết thực tế.
- Không bỏ sót các vấn đề pháp lý trọng tâm.
- Không trùng lặp về mặt ngữ nghĩa.
- Mỗi issue phải có một trọng tâm giải quyết rõ ràng.
- Nếu hai vấn đề có thể được đánh giá pháp lý độc lập, cân nhắc tách thành hai issues.
- Ưu tiên ngắn gọn nhưng không được bỏ tình tiết quyết định.
- Không cố tạo một số lượng issues cố định cho mỗi vụ.
- Không cần xuất sự kiện pháp lý thành một task hoặc nhãn riêng.

Ví dụ:

1. Việc xác định quyền thừa kế theo pháp luật và phân chia di sản thừa kế đối với tài sản riêng của người chết khi có người thừa kế là con đang định cư ở nước ngoài và có yêu cầu loại trừ người thừa kế đó.

2. Trách nhiệm hình sự của người thực hiện hành vi mua bán động vật hoang dã khi không có giấy phép của cơ quan có thẩm quyền.

3. Hiệu lực pháp lý của hợp đồng tặng cho quyền sử dụng đất khi hợp đồng được ký kết nhằm che giấu giao dịch mua bán thực tế và trốn thuế.

Các ví dụ minh họa phải được sử dụng theo nguyên tắc không mâu thuẫn với quy tắc chọn loại trách nhiệm và tính atomic. Nếu guideline có trường hợp chưa rõ, hãy thiết kế validator theo khả năng cấu hình, thay vì hard-code một cách hiểu pháp lý không thể thay đổi.

## 5. Generator Agent

### Input

Generator chỉ được truy cập:

- `situation`.
- Danh sách issues của chính Generator ở vòng trước, nếu có.
- Feedback được Judge cho phép chuyển sang Generator.
- Lịch sử phản biện tường minh của chính vụ việc đang xử lý.

Generator tuyệt đối không được nhận trực tiếp:

- `markdown`.
- `citations`.
- `citations_law`.
- Kết luận hoặc dữ kiện chỉ có trong bản án mà không tồn tại trong `situation`.

Ở vòng đầu, Generator chỉ nhận `situation` và system prompt quy định cách trích xuất.

Ở những vòng tiếp theo, Generator có thể nhận feedback, nhưng feedback không được tiết lộ những tình tiết ngoài `situation` như những dữ kiện bắt buộc phải chấp nhận.

### Nhiệm vụ

1. Đọc hiểu tình huống.
2. Xác định các vấn đề pháp lý trọng tâm và các vấn đề độc lập liên quan.
3. Sinh issues theo đúng format.
4. Với mỗi issue, đưa ra metadata nội bộ: ba thành phần của issue, trích đoạn bằng chứng nguyên văn từ `situation` và mức độ trọng tâm.
5. Khi nhận feedback, tự kiểm tra và quyết định chấp nhận hay phản bác từng nhận xét.
6. Nếu phản bác, phải nêu bằng chứng cụ thể từ `situation`.
7. Nếu đồng ý, sửa issue tương ứng.
8. Không thay đổi những issue đã đúng nếu không cần thiết.

Generator không được mặc định coi Judge luôn đúng.

Phản hồi giữa các agent phải ở dạng structured JSON, được kiểm tra bằng schema.

## 6. Judge Agent

### Input

Judge được nhận:

- `situation`.
- `markdown`.
- `citations_law`.
- `citations`.
- Issues hiện tại của Generator.
- Feedback và tranh biện trước đó của cùng vụ việc.

Judge có system prompt riêng, API client riêng và inference request riêng.

### Nhiệm vụ 1 — Đánh giá từng issue

Kiểm tra:

- Đúng format ba thành phần hay không.
- Đúng một trong bốn nhóm mở đầu hay không.
- Đúng loại trách nhiệm hay không.
- Có bằng chứng trong situation hay không.
- Có tự suy diễn tình tiết hay không.
- Có đưa ra kết luận quá sớm hay không.
- Có vấn đề thừa, trùng lặp hay không.
- Có gộp nhiều vấn đề độc lập hay không.
- Tình tiết đặc biệt có thực sự quan trọng hay không.

Judge phải chỉ ra lỗi cụ thể thay vì chỉ trả lời “sai” hoặc “chưa tốt”.

### Nhiệm vụ 2 — Kiểm tra coverage

Judge phải tự phân tích những vấn đề pháp lý trọng tâm phát sinh từ `situation`, tham khảo bản án và citations để phát hiện những vấn đề Generator có thể bỏ sót.

Không chỉ kiểm tra các issue đã có.

Mỗi issue bổ sung phải đi kèm bằng chứng trong `situation`.

Nếu vấn đề chỉ có thể nhận diện bằng thông tin từ `markdown` mà `situation` không cung cấp, Judge không được tự động yêu cầu Generator thêm issue đó.

Thay vào đó, cần xem xét đây có phải một lỗi thiếu dữ kiện quan trọng của `situation` hay không.

Nên có tùy chọn cấu hình để Judge thực hiện một lượt blind issue discovery trước khi đối chiếu với issues của Generator, nhằm giảm thiên lệch do nhìn thấy câu trả lời trước.

### Nhiệm vụ 3 — Kiểm tra `situation_error`

Judge phải so sánh `situation` với nội dung bản án `markdown`.

Mặc định:

`situation_error = true` nếu `situation` bỏ sót một hoặc nhiều dữ kiện thực tế quan trọng có trong bản án, khiến khả năng nhận diện hoặc diễn đạt chính xác các vấn đề pháp lý trọng tâm bị ảnh hưởng đáng kể.

`situation_error = false` nếu không phát hiện thiếu dữ kiện trọng yếu như vậy.

Không được đặt `true` chỉ vì situation không kể lại tất cả nội dung bản án.

Không tính những thông tin không ảnh hưởng đến issue-spotting như phần hành chính không liên quan, chi tiết trình bày lặp lại, hoặc chỉ đơn thuần thiếu các điều luật đã được viện dẫn.

Khi kết luận true, Judge phải cung cấp trong audit:

- Dữ kiện bị thiếu.
- Trích đoạn cụ thể từ `markdown` làm bằng chứng.
- Lý do dữ kiện này quan trọng.
- Issue nào bị ảnh hưởng, hoặc vấn đề pháp lý nào không thể nhận diện đầy đủ.
- Đánh giá liệu dữ kiện có thực sự không được diễn đạt tương đương trong `situation` hay không.

Cần phân biệt thiếu dữ kiện với diễn đạt khác nhau.

Đối với sai lệch hoặc mâu thuẫn giữa `situation` và bản án, ghi riêng trong audit; thiết kế chính sách cấu hình để tùy chọn có tính các sai lệch trọng yếu đó vào `situation_error` hay không.

Giá trị mặc định chỉ tính **material missing facts**.

Với những trường hợp không chắc chắn, phải ghi trạng thái `needs_review` trong audit; không được giả vờ đã xác minh hoàn toàn.

### Nhiệm vụ 4 — Phản biện Generator

Judge phải kiểm tra từng phản biện của Generator.

Nếu Generator viện dẫn được bằng chứng từ `situation` chứng minh rằng feedback trước của Judge sai, Judge phải có khả năng thay đổi quan điểm.

Nếu Judge không đồng ý, Judge phải đưa ra phản biện mới hoặc chỉ rõ bằng chứng chưa thỏa đáng.

Không được lặp lại feedback cũ mà không xét lập luận mới.

Judge không phải là nguồn chân lý tuyệt đối.

### Nhiệm vụ 5 — Phân tách feedback

Judge cần tạo hai loại output nội bộ:

**Private audit:**

Có thể chứa trích dẫn từ bản án, citations, thông tin thiếu và nhận định về `situation_error`.

**Generator-visible feedback:**

Chỉ chứa những nhận xét và bằng chứng mà Generator có thể kiểm tra từ `situation`, cùng các yêu cầu sửa issues được hỗ trợ bởi tình huống.

Không chuyển nguyên văn dữ kiện độc quyền từ `markdown` sang Generator rồi bắt Generator coi đó là sự thật trong `situation`.

Hãy triển khai phần phân tách này thành code rõ ràng, không chỉ viết một câu trong prompt.

## 7. Cơ chế Multi-Agent Debate

Đây là thành phần quan trọng nhất.

Không được triển khai dưới dạng Generator sinh → Judge phán quyết → Generator bắt buộc nghe theo.

Hai agent phải có khả năng tranh luận thực sự.

### Quy trình

**Bước 1 — Initial generation**

Generator inference độc lập, chỉ nhận `situation`, tạo danh sách issues lần đầu.

**Bước 2 — Judge evaluation**

Judge inference riêng, dùng các nguồn thông tin được phép, đánh giá issues và tạo feedback có cấu trúc.

**Bước 3 — Generator rebuttal/revision**

Generator nhận feedback, với từng nhận xét có thể:

- `ACCEPT`: Chấp nhận và sửa.
- `CONTEST`: Bác bỏ, kèm bằng chứng.
- `PARTIALLY_ACCEPT`: Chấp nhận một phần và giải thích.

Generator tạo danh sách issues mới nếu cần.

**Bước 4 — Judge reconsideration**

Judge nhận phản biện, đánh giá lại trên căn cứ cụ thể và đưa ra nhận định mới.

**Bước 5 — Iterate**

Lặp cho đến khi đạt điều kiện dừng hoặc hết số vòng tối đa.

Một debate round được định nghĩa là một chu trình Judge evaluation → Generator response. Sau lượt Generator sửa cuối cùng vẫn cần Judge kiểm tra bản sửa đó, để tránh xuất kết quả chưa từng được đánh giá.

### Điều kiện dừng sớm

Có thể dừng nếu:

- Không còn lỗi format.
- Judge không phát hiện issue thiếu hoặc thừa quan trọng.
- Các issue đều có bằng chứng trong `situation`.
- Những phản biện còn lại đã được giải quyết.
- Không còn thay đổi thực chất qua các vòng.
- Judge trả về `PASS` và validator xác nhận các điều kiện máy kiểm tra được.

Không cần ép phải chạy đủ số vòng nếu đã đạt điều kiện.

### Giới hạn vòng

Cấu hình mặc định:

`MAX_DEBATE_ROUNDS=8`

Cho phép đổi thành 5, 6, 7, 9 hoặc 10.

Nếu hết lượt mà chưa thống nhất:

- Không được mặc định Judge thắng.
- Không được mặc định Generator thắng.
- Không được tự động coi là đạt gold.
- Chọn candidate hợp lệ nhất dựa trên các tiêu chí và bằng chứng đã ghi nhận.
- Ghi rõ `UNRESOLVED` hoặc `NEEDS_REVIEW` trong audit.
- Không được âm thầm bỏ đi các bất đồng.
- Có chính sách cấu hình để dừng toàn bộ run hoặc tiếp tục sinh candidate labels có đánh dấu chưa được phê duyệt.

Mục tiêu là tạo dữ liệu đáng tin cậy, không phải tối đa hóa tỷ lệ PASS giả tạo.

### Chống vòng lặp vô ích

Cần phát hiện:

- Hai agent lặp lại cùng lập luận.
- Issues thay đổi qua lại giữa hai phiên bản.
- Feedback không mang thông tin mới.
- Số lượng issues tăng lên nhưng không có thêm căn cứ.
- Judge liên tục đổi ý mà không có bằng chứng.

Có thể sử dụng hash, comparison và các trạng thái tranh luận có cấu trúc.

Không dùng sự giống nhau của chuỗi làm điều kiện duy nhất để kết luận hai issue tương đương.

## 8. Structured output và validation

Hãy thiết kế Pydantic schemas cho các output của agent.

Generator nên trả về những dữ liệu nội bộ như:

- `issue_id`
- `issue_text`
- `focus_group`
- `focus`
- `subject_action`
- `decisive_fact`
- `situation_evidence_quotes`
- `importance`
- `responses_to_feedback`

Judge nên trả về:

- `per_issue_reviews`
- `error_codes`
- `feedback`
- `suggested_missing_issues`
- `generator_visible_feedback`
- `rebuttal_assessments`
- `situation_audit`
- `overall_verdict`
- `unresolved_disputes`

Các error codes nên chuẩn hóa, ví dụ:

`INVALID_FORMAT`, `UNSUPPORTED_FACT`, `WRONG_LIABILITY`, `MISSING_CORE_ISSUE`, `DUPLICATE`, `NON_ATOMIC`, `LOW_RELEVANCE`, `PREMATURE_CONCLUSION`.

Tạo deterministic validator bằng Python cho những phần kiểm tra được bằng code.

Những đánh giá mang tính ngữ nghĩa hoặc cần hiểu pháp luật phải giao cho agent, không giả vờ có thể giải quyết hoàn toàn bằng regex.

Phải đảm bảo:

- Parse JSON an toàn.
- Validate schema.
- Repair output không hợp lệ trong giới hạn số lần cấu hình.
- Kiểm tra các evidence quotes có xuất hiện trong nguồn tương ứng khi được yêu cầu trích dẫn nguyên văn.
- Không silent parsing failure.
- Có logging cụ thể khi model không tuân thủ format.
- Không đưa reasoning nội bộ của model vào output chính.

## 9. Hai inference phải độc lập

Generator và Judge dùng cùng DeepSeek V4.1 Flash là được, nhưng phải thực hiện hai inference độc lập.

Yêu cầu:

1. Mỗi agent có một instance riêng.
2. Mỗi agent có API client hoặc client wrapper riêng.
3. Mỗi agent có system prompt riêng.
4. Mỗi agent có lịch sử conversation riêng, được phân tách theo case và role.
5. Không chia sẻ trạng thái hội thoại ngầm.
6. Không gửi toàn bộ message history của Generator sang Judge.
7. Không gửi toàn bộ message history của Judge sang Generator.
8. Chỉ trao đổi qua các message có cấu trúc được debate controller cho phép.
9. Không chuyển private audit của Judge sang Generator.
10. Không để context của vụ trước lọt sang vụ tiếp theo.
11. Không tự động chuyển reasoning_content của agent này sang agent khác.
12. Cho phép cấu hình endpoint, model name, API key, sampling và thinking effort khác nhau cho từng agent.

Hai client có thể trỏ đến cùng một URL và cùng model ID.

Cần hiểu rằng điều này tạo ra inference và context độc lập, không có nghĩa là hai mô hình có trọng số khác nhau hoặc lỗi của chúng độc lập về mặt thống kê.

Nếu endpoint có session state hoặc server-side cache, cần bảo đảm việc tái sử dụng endpoint không làm lẫn lịch sử hội thoại. KV-cache optimization không phải bản thân nó là lỗi nếu không làm lẫn nội dung giữa requests.

Viết unit test chứng minh generator không bao giờ nhận `markdown`, `citations_law` hoặc `citations`, kể cả trong quá trình tranh biện.

## 10. LLM API và Thinking Mode

Sử dụng OpenAI-compatible API client, cho phép kết nối đến endpoint DeepSeek self-hosted.

Mặc định model ID có thể là `deepseek-flash`, nhưng phải cấu hình được vì model ID do server vLLM/SGLang expose có thể khác.

Không hard-code tên model.

Hỗ trợ:

- Enable/disable thinking.
- Thinking effort riêng cho Generator và Judge.
- `medium`, `high`, `extra_high`.
- Các mức native như `low`, `high`, `max` khi backend hỗ trợ.
- Extra request body khi backend cần.
- Timeout.
- Retry.
- Concurrency.
- Context length.
- Maximum output tokens.
- Sampling parameters khi backend hỗ trợ.
- API keys.
- Stop conditions.

**Quan trọng:** DeepSeek V4.1 Flash theo API chính thức sử dụng các mức reasoning `low`, `high`, `max`, không phải trực tiếp `extra_high`.

Hãy cho phép người dùng đặt `extra_high` trong shell script như một alias của pipeline, ánh xạ thành `max` đối với DeepSeek backend và log giá trị thực sự gửi.

`medium` có thể bị DeepSeek ánh xạ thành `high`; phải ghi rõ điều này. Không tuyên bố rằng `medium` là mức tính toán khác biệt nếu backend không hỗ trợ.

Không mặc định gửi `temperature` hay các tham số không có hiệu lực trong thinking mode của DeepSeek. Adapter phải xử lý theo backend, ghi cảnh báo nếu giá trị bị bỏ qua.

Không âm thầm bỏ hoặc thay đổi tham số mà người dùng đã cấu hình.

Nếu endpoint không hỗ trợ mức thinking được yêu cầu, phải có hành vi xác định bằng cấu hình: fail rõ ràng hoặc fallback có log.

Phải hỗ trợ tối thiểu hai adapter:

- DeepSeek OpenAI-compatible endpoint.
- Generic OpenAI-compatible endpoint, phục vụ test bằng Qwen.

Có thể sử dụng vLLM hoặc SGLang trên B200; không hard-code backend server.

## 11. Kiến trúc OOP và module

Hãy thiết kế một project Python package có cấu trúc rõ ràng. Có thể điều chỉnh cấu trúc sau nếu có lý do kỹ thuật:

    LegalDataset/
    ├── input/
    ├── output/
    │   ├── audit/
    │   ├── logs/
    │   └── checkpoints/
    ├── scripts/
    │   ├── run_pipeline.sh
    │   ├── run_smoke_test.sh
    │   └── serve_qwen_local.sh
    ├── prompts/
    │   ├── generator_system.md
    │   ├── judge_system.md
    │   ├── generator_revision.md
    │   └── judge_reconsideration.md
    ├── src/
    │   └── legal_issue_pipeline/
    │       ├── config.py
    │       ├── schemas.py
    │       ├── llm/
    │       │   ├── base_client.py
    │       │   ├── openai_client.py
    │       │   └── client_factory.py
    │       ├── agents/
    │       │   ├── base_agent.py
    │       │   ├── generator.py
    │       │   └── judge.py
    │       ├── debate/
    │       │   ├── controller.py
    │       │   ├── state.py
    │       │   └── stopping.py
    │       ├── validators/
    │       │   ├── format_validator.py
    │       │   ├── evidence_validator.py
    │       │   └── output_validator.py
    │       ├── io/
    │       │   ├── jsonl_reader.py
    │       │   ├── jsonl_writer.py
    │       │   └── checkpoint.py
    │       ├── pipeline/
    │       │   └── runner.py
    │       └── cli.py
    ├── tests/
    │   ├── unit/
    │   ├── integration/
    │   └── fixtures/
    ├── pyproject.toml
    ├── requirements.txt
    └── README.md

Yêu cầu áp dụng OOP hợp lý, có separation of concerns, type hints và dependency injection.

Tránh một class khổng lồ làm mọi việc.

Các trách nhiệm chính nên phân tách:

**GeneratorAgent:** Xây dựng prompt, gọi model, sinh và sửa issues, phản biện feedback.

**JudgeAgent:** Kiểm tra issues, kiểm tra tình huống, xử lý tranh biện, trả structured feedback.

**DebateController:** Điều phối vòng tranh luận, kiểm soát trạng thái và quyết định dừng.

**LLMClient:** Giao tiếp với endpoint, xử lý request, response, timeout, retry, thinking config.

**Validators:** Kiểm tra format và evidence.

**PipelineRunner:** Xử lý toàn bộ records, resume, batching, output và failure isolation.

**JSONLReader/Writer:** Đọc và ghi dữ liệu ổn định, không làm mất các trường gốc.

**CheckpointManager:** Lưu trạng thái xử lý để không phải chạy lại những vụ đã hoàn thành.

Có thể tạo các interface/protocol cho agent, client và validator để dễ thay model hoặc thay Judge trong tương lai.

## 12. Shell script cấu hình tập trung

Đây là yêu cầu bắt buộc.

Toàn bộ những tham số người dùng có thể cần sửa khi chạy trên B200 phải được đưa ra shell script chính:

`scripts/run_pipeline.sh`

Không được bắt người dùng mở nhiều file Python để đổi các cấu hình thông thường.

Shell script phải khai báo rõ và có comment giải thích cho từng nhóm tham số.

Ít nhất gồm:

### Input / Output

    PROJECT_ROOT
    INPUT_PATH
    OUTPUT_PATH
    AUDIT_DIR
    LOG_DIR
    CHECKPOINT_DIR
    RESUME
    OVERWRITE_OUTPUT

### GPU / Runtime

    CUDA_VISIBLE_DEVICES
    MAX_WORKERS
    MAX_CONCURRENT_REQUESTS
    BATCH_SIZE
    START_INDEX
    LIMIT
    RANDOM_SEED

### Generator

    GEN_API_BASE
    GEN_API_KEY
    GEN_MODEL
    GEN_BACKEND
    GEN_THINKING_ENABLED
    GEN_THINKING_EFFORT
    GEN_MAX_OUTPUT_TOKENS
    GEN_TEMPERATURE
    GEN_TOP_P
    GEN_SEED
    GEN_TIMEOUT
    GEN_MAX_RETRIES

### Judge

    JUDGE_API_BASE
    JUDGE_API_KEY
    JUDGE_MODEL
    JUDGE_BACKEND
    JUDGE_THINKING_ENABLED
    JUDGE_THINKING_EFFORT
    JUDGE_MAX_OUTPUT_TOKENS
    JUDGE_TEMPERATURE
    JUDGE_TOP_P
    JUDGE_SEED
    JUDGE_TIMEOUT
    JUDGE_MAX_RETRIES

### Debate

    MAX_DEBATE_ROUNDS
    ENABLE_EARLY_STOP
    ENABLE_GENERATOR_REBUTTAL
    ENABLE_JUDGE_RECONSIDERATION
    ENABLE_BLIND_JUDGE_DISCOVERY
    STOP_ON_STAGNATION
    MAX_STAGNANT_ROUNDS
    FINALIZE_POLICY
    UNRESOLVED_POLICY

### Validation

    STRICT_FORMAT
    ENABLE_EVIDENCE_VALIDATION
    ENABLE_DEDUPLICATION
    ENABLE_COVERAGE_CHECK
    ENABLE_SITUATION_AUDIT
    SITUATION_ERROR_POLICY
    MAX_JSON_REPAIR_RETRIES
    REQUIRE_STRUCTURED_OUTPUT

### Context / Request

    MAX_CONTEXT_TOKENS
    MAX_INPUT_TOKENS
    TRUNCATION_POLICY
    API_REQUEST_TIMEOUT
    RETRY_BACKOFF
    RETRY_JITTER
    API_EXTRA_BODY
    THINKING_UNSUPPORTED_POLICY

### Logging / Debug

    LOG_LEVEL
    SAVE_DEBATE_HISTORY
    SAVE_RAW_RESPONSES
    SAVE_TOKEN_USAGE
    DRY_RUN
    FAIL_ON_RECORD_ERROR

Tất cả các giá trị có default hợp lý và có thể override bằng environment variables.

Ví dụ mặc định:

    PROJECT_ROOT=/mnt/hdd/nhatminh/LegalDataset
    INPUT_PATH=$PROJECT_ROOT/input/judgment_with_situation.jsonl
    OUTPUT_PATH=$PROJECT_ROOT/output/judgment_with_issues.jsonl

    CUDA_VISIBLE_DEVICES=0

    GEN_API_BASE=http://127.0.0.1:8000/v1
    JUDGE_API_BASE=http://127.0.0.1:8000/v1

    GEN_MODEL=deepseek-flash
    JUDGE_MODEL=deepseek-flash

    GEN_THINKING_ENABLED=true
    JUDGE_THINKING_ENABLED=true

    GEN_THINKING_EFFORT=extra_high
    JUDGE_THINKING_EFFORT=extra_high

    MAX_DEBATE_ROUNDS=8
    ENABLE_EARLY_STOP=true
    RESUME=true

Đây là giá trị minh họa. Các cấu hình còn lại cũng phải hiện diện trong file .sh, không được giấu trong Python constants.

Đối với API key, hỗ trợ đọc qua environment hoặc secret file. Không ghi credential thật vào repository hoặc log.

Cho phép cấu hình `GEN_API_BASE` và `JUDGE_API_BASE` khác nhau trong tương lai, dù mặc định giống nhau.

Shell script phải dùng `set -euo pipefail`, kiểm tra các đường dẫn cần thiết và hiển thị cấu hình hiệu lực trước khi chạy, ngoại trừ secrets.

Không được sửa input file gốc.

## 13. Resume, checkpoint và fault tolerance

Vì pipeline sẽ chạy inference trên B200 và có thể tốn nhiều thời gian, bắt buộc hỗ trợ resume.

Yêu cầu:

- Xử lý JSONL theo từng record.
- Có case identifier ổn định dựa trên vị trí dòng và định danh bản án.
- Lưu checkpoint sau mỗi record thành công.
- Có trạng thái `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `NEEDS_REVIEW`.
- Khi chạy lại không tính toán lại các record đã hoàn thành nếu input và cấu hình liên quan không thay đổi.
- Không ghi trùng dòng trong output.
- Không ghi JSONL bị cắt giữa chừng.
- Có cơ chế atomic write hoặc durable append hợp lý.
- Kiểm tra input fingerprint và config/prompt fingerprint khi resume.
- Nếu cấu hình thay đổi làm kết quả cũ không còn tương thích, cảnh báo hoặc yêu cầu tạo run mới.
- Có thể resume sau khi mất kết nối tới model server.
- Retry với exponential backoff cho lỗi mạng và rate limiting.
- Không retry vô hạn.
- Cho phép chạy tuần tự mặc định và tăng concurrency bằng cấu hình.
- Dữ liệu output phải giữ đúng thứ tự như input, kể cả khi chạy concurrent.
- Không chia sẻ state của các vụ việc giữa các workers.
- Kiểm tra số lượng records và tính hợp lệ của output sau khi hoàn tất.

Thiết kế audit logs để truy vết từng vấn đề và từng cuộc tranh biện.

Nếu lưu raw model response, phải là tùy chọn. Không tự động ghi bí mật API hoặc private reasoning vào logs.

## 14. Kiểm thử bằng Qwen local

Trên máy local hiện có model:

`/mnt/hdd/nhatminh/SpecDecode/models/Qwen3-4B/`

Hãy kiểm tra xem đường dẫn có tồn tại và model có thể load không.

Mục đích sử dụng Qwen3-4B là **smoke test tính đúng đắn về mặt kỹ thuật của pipeline**, không phải chứng minh gold labels có chất lượng pháp lý cao.

Yêu cầu:

1. Kiểm tra môi trường Python, CUDA, PyTorch và thư viện inference hiện có.
2. Nếu phần cứng và dependencies cho phép, host Qwen3-4B qua vLLM hoặc backend OpenAI-compatible tương đương.
3. Tạo `scripts/serve_qwen_local.sh`.
4. Tạo `scripts/run_smoke_test.sh`.
5. Cho cả Generator và Judge kết nối tới local Qwen endpoint.
6. Chạy pipeline trên ít nhất 1–2 records đầu tiên, nếu điều kiện máy cho phép.
7. Chỉ sử dụng output thử nghiệm trong đường dẫn riêng, không ghi đè output production.
8. Kiểm tra tính hợp lệ của JSONL đầu ra.
9. Kiểm tra `issues` có đúng kiểu list chuỗi.
10. Kiểm tra `situation_error` có đúng kiểu boolean.
11. Kiểm tra toàn bộ các trường input được giữ nguyên.
12. Kiểm tra debate log và state transitions.
13. Kiểm tra hai agent thật sự sử dụng các inference request riêng.
14. Kiểm tra Generator không nhận những trường bị cấm.

Đối với Qwen, thinking configuration có thể khác DeepSeek. Hãy dùng adapter tương ứng và không áp dụng mù quáng tham số DeepSeek vào Qwen.

Không được tự tuyên bố end-to-end smoke test thành công nếu model không load hoặc server không trả response hợp lệ.

Nếu không thể chạy inference thật vì thiếu GPU, VRAM hoặc dependencies, vẫn phải chạy unit tests/mocked integration tests và báo cáo chính xác bước nào chưa được kiểm chứng.

Không cần thử host DeepSeek V4.1 Flash trên máy local. Model DeepSeek production sẽ chạy trên B200 hoặc một endpoint được cung cấp sau.

## 15. Unit tests bắt buộc

Dùng pytest, tạo các test độc lập không cần GPU hoặc server.

Phải kiểm tra ít nhất các trường hợp:

1. Đọc JSONL có đủ fields.
2. `situation_error: null` được thay bằng boolean.
3. Không mất hoặc thay đổi các trường gốc.
4. Generator không nhận `markdown` hoặc citations.
5. Judge được nhận đúng các trường quy định.
6. Hai agent không chia sẻ message history.
7. Generator có thể bác feedback của Judge.
8. Judge có thể thay đổi quyết định sau khi nhận phản biện hợp lệ.
9. Judge có thể bảo lưu quyết định và giải thích.
10. Debate dừng sớm khi đã đạt yêu cầu.
11. Debate dừng đúng giới hạn.
12. Debate phát hiện stagnation.
13. Có final validation sau lượt sửa cuối.
14. JSON response bị lỗi.
15. API timeout hoặc server unavailable.
16. Retry thành công và retry thất bại.
17. Resume không ghi trùng record.
18. Định dạng vấn đề pháp lý không hợp lệ.
19. Một issue không có căn cứ trong situation.
20. Judge phát hiện dữ kiện trọng yếu bị thiếu.
21. Judge không coi một thông tin hành chính không quan trọng là `situation_error`.
22. Không chuyển private markdown evidence từ Judge vào Generator.
23. Output chính không có các trường metadata ngoài hai trường yêu cầu.
24. Thứ tự records được bảo toàn khi chạy concurrent.
25. Việc thay đổi prompt hoặc cấu hình có thể được phát hiện khi resume.

Nên bổ sung property-based tests hoặc validation tests nếu thực sự hữu ích.

## 16. Logging và kết quả phân tích

Sau mỗi run, tạo một summary rõ ràng:

- Tổng số records.
- Số records đã hoàn thành.
- Số thất bại.
- Số cần human review.
- Tổng số issues.
- Trung bình issues/vụ.
- Số vụ có `situation_error=true`.
- Số vụ có `situation_error=false`.
- Số lượt tranh luận trung bình.
- Số vụ dừng sớm.
- Số vụ đạt PASS.
- Số vụ hết lượt nhưng chưa thống nhất.
- Số lần Generator contest Judge.
- Số lần Judge thay đổi quyết định.
- Tổng token usage nếu API cung cấp.
- Thời gian inference nếu có thể ghi nhận.
- Model, prompts version và effective thinking effort.

Không coi Judge PASS rate là thước đo duy nhất của độ chính xác gold labels.

Những số liệu về độ đúng pháp lý thực sự phải được đánh giá riêng trên dữ liệu có human annotations.

## 17. README và deployment

Viết README đầy đủ bằng tiếng Việt, bao gồm:

- Mục tiêu pipeline.
- Kiến trúc OOP.
- Luồng dữ liệu.
- Sự khác biệt giữa inference độc lập và hai model checkpoints khác nhau.
- Quy tắc Generator được phép nhìn thấy dữ liệu nào.
- Quy tắc Judge được phép nhìn thấy dữ liệu nào.
- Cách hoạt động của debate.
- Định nghĩa `situation_error`.
- Các trường hợp `NEEDS_REVIEW`.
- Cách cài dependencies.
- Cách cấu hình shell script.
- Cách host Qwen local.
- Cách chạy smoke test.
- Cách chuyển sang endpoint DeepSeek trên B200.
- Cách chạy pipeline production.
- Cách resume.
- Cách kiểm tra output.
- Cách xem audit logs.
- Cách điều chỉnh thinking mode.
- Các hạn chế và rủi ro chất lượng của phương pháp LLM-as-Judge.

Cần ghi rõ rằng pipeline tạo candidate gold labels với kiểm chứng tự động, nhưng không bảo đảm độ chính xác tuyệt đối về pháp lý.

## 18. Tiêu chí hoàn thành

Chỉ xem nhiệm vụ hoàn thành khi:

- Source code đã được tạo trong đúng project root.
- Các module OOP đã được triển khai.
- Prompt files thực sự được sử dụng bởi code.
- `scripts/run_pipeline.sh` có đầy đủ cấu hình.
- Hai agent thực hiện inference độc lập.
- Debate hai chiều được triển khai thực sự.
- `situation_error` được tính có căn cứ.
- Output đúng yêu cầu.
- Resume và audit hoạt động.
- Unit tests đã chạy.
- Smoke test Qwen đã được thực hiện nếu môi trường cho phép.
- README có hướng dẫn chạy trên B200.
- Không còn mock logic hoặc placeholder trong production path.

Nếu một chức năng chưa thể kiểm chứng thực tế, phải ghi rõ trong báo cáo cuối cùng.

## 19. Cách thực hiện công việc

Hãy chủ động thực hiện đầy đủ nhiệm vụ trong project directory.

Bước đầu tiên là khảo sát dữ liệu và môi trường hiện có. Sau đó thiết kế kiến trúc, triển khai các module, viết prompt, bổ sung scripts, chạy tests và sửa lỗi được phát hiện.

Không dừng lại ở việc đưa ra kế hoạch.

Không cần hỏi xác nhận về các quyết định triển khai nhỏ nếu có thể lựa chọn phương án kỹ thuật hợp lý và giải thích trong README.

Không được tự xóa hay ghi đè những dữ liệu quan trọng đang tồn tại. Không dùng destructive commands không cần thiết.

Cuối cùng, hãy báo cáo:

1. Cấu trúc thư mục đã tạo.
2. Các thành phần đã triển khai.
3. Các lệnh chạy pipeline và smoke test.
4. Những tests đã chạy và kết quả thực tế.
5. Những chức năng chưa thể kiểm chứng.
6. Những thay đổi cần thiết khi chuyển từ Qwen local sang DeepSeek V4.1 Flash trên B200.
7. Những rủi ro còn lại liên quan đến chất lượng gold labels.

**Ưu tiên cao nhất: đúng dữ liệu, đúng quyền truy cập thông tin của từng agent, debate thực sự hai chiều, kiểm chứng được và có khả năng chạy ổn định trên B200.**