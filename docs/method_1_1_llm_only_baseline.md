# Method 1.1 - LLM-only Baseline

## Mục Tiêu

Method 1.1 là baseline bắt buộc cho bài toán OntologyQA. Phương pháp này đưa trực tiếp câu hỏi tiếng Việt và các lựa chọn trắc nghiệm cho LLM, sau đó yêu cầu model chọn một đáp án.

Phương pháp này **không** dùng SPARQL, không gọi SPARQL endpoint, không dùng ontology/schema, không dùng retrieval và không có self-correction. Vì vậy kết quả của 1.1 phản ánh năng lực parametric memory và suy luận trực tiếp của LLM trên câu hỏi trắc nghiệm.

## Notebook Chính

Notebook batch chính:

```text
notebooks/1-llm-only.ipynb
```

Notebook này được viết theo OOP và chạy toàn bộ sample hợp lệ trong `test_questions_v1.0.xlsx`.

Notebook smoke test một sample vẫn có thể dùng để kiểm tra nhanh:

```text
notebooks/ontology-qa.ipynb
```

## Input

Input lấy từ `test_questions_v1.0.xlsx` ở project root.

Các cột chính:

- `number`: id của sample.
- `vi_question`: câu hỏi tiếng Việt.
- `question_type`: subset dùng để thống kê, ví dụ `entity`, `counting`, `list`, `boolean`, `multi-hop`, `comparison`, `schema`, `attribute`, `superlative`.
- `Unnamed: 3`: gold answer semantic; trong code được rename thành `gold_answer`.
- `answer`: chỉ số option đúng.
- `option_1` đến `option_5`: các lựa chọn trắc nghiệm.

Các dòng chưa hoàn thiện bị bỏ qua nếu thiếu `vi_question`, thiếu `answer`, hoặc có ít hơn 2 lựa chọn.

## Prompt Và Output

Prompt được viết bằng tiếng Việt. Prompt chỉ chứa:

- câu hỏi tiếng Việt;
- `question_type`;
- danh sách option;
- yêu cầu model chọn đúng một option;
- yêu cầu trả JSON hợp lệ.

Output kỳ vọng từ model:

```json
{
  "selected_option": 3,
  "answer_text": "Việt Nam",
  "reason": "Giải thích ngắn"
}
```

Metric đúng/sai chính:

```text
is_correct = predicted_option == correct_option
```

## Thiết Kế OOP

| Class | Trách nhiệm |
| --- | --- |
| `BaselineConfig` | Tìm project root, load `.env`, giữ cấu hình model/API/provider/delay. |
| `QuestionDataset` | Đọc Excel bằng pandas, normalize dòng dữ liệu, lấy sample theo id hoặc toàn bộ sample hợp lệ. |
| `LLMOnlyPromptBuilder` | Tạo prompt baseline 1.1 từ câu hỏi và options. |
| `OpenRouterChatClient` | Gọi OpenRouter qua OpenAI SDK và đo round-trip latency. |
| `ResponseParser` | Parse `selected_option` từ response JSON hoặc fallback regex. |
| `BaselineEvaluator` | Chấm đúng/sai và gom token/cost/latency vào result. |
| `ResultLogger` | Ghi JSONL, CSV chi tiết và CSV summary theo `question_type`. |
| `LLMOnlyBaselineRunner` | Orchestrate pipeline cho một sample hoặc toàn bộ dataset. |

## Luồng Chạy Batch

1. `BaselineConfig.from_env()` load `.env`.
2. `QuestionDataset.load_valid_samples()` đọc Excel bằng `pandas.read_excel(..., engine="openpyxl")`.
3. Với mỗi sample hợp lệ:
   - tạo prompt LLM-only;
   - gọi OpenRouter;
   - đo `round_trip_latency_ms` bằng `time.perf_counter()`;
   - lấy `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost` từ `completion.usage` nếu provider trả về;
   - parse `selected_option`;
   - chấm `is_correct`.
4. Nếu một sample lỗi, ví dụ rate limit 429, notebook vẫn ghi một dòng với `status="error"` để không làm mất dấu sample đó.
5. Sau khi chạy xong, notebook ghi file kết quả vào `results/method_1_1/<run_id>/`.

## Metadata Cần Lưu

Mỗi dòng kết quả lưu các trường:

| Field | Ý nghĩa |
| --- | --- |
| `run_id` | Id của lần chạy. |
| `method_id` | Luôn là `1.1`. |
| `method_name` | `LLM-only baseline`. |
| `timestamp_utc` | Thời điểm ghi log. |
| `sample_id` | Id câu hỏi từ cột `number`. |
| `question_type` | Subset dùng để thống kê. |
| `question` | Câu hỏi tiếng Việt. |
| `gold_answer` | Đáp án semantic từ Excel. |
| `correct_option` | Option đúng từ cột `answer`. |
| `predicted_option` | Option model chọn sau parse. |
| `is_correct` | Đúng/sai theo option accuracy. |
| `parse_success` | Có parse được option từ response không. |
| `status` | `success` hoặc `error`. |
| `error_type` | Loại lỗi nếu có. |
| `error_message` | Nội dung lỗi nếu có. |
| `model` | Model slug dùng trên OpenRouter. |
| `provider_only` | Provider cố định nếu cấu hình `OPENROUTER_PROVIDER_ONLY`. |
| `temperature` | Sampling temperature. |
| `max_tokens` | Giới hạn output token. |
| `input_tokens` | Số token input, lấy từ `usage.prompt_tokens`. |
| `output_tokens` | Số token output, lấy từ `usage.completion_tokens`. |
| `total_tokens` | Tổng token, lấy từ `usage.total_tokens`. |
| `cost` | Chi phí nếu OpenRouter trả về trong `usage.cost`. |
| `round_trip_latency_ms` | Thời gian gọi đi/gọi về ở client, tính bằng milliseconds. |
| `raw_response` | Text response gốc của model. |

Với yêu cầu hiện tại, **không dùng generation metadata endpoint** của OpenRouter cho method 1.1. Latency được hiểu là round-trip latency, không tách riêng inference server-side.

## Output Files

Khi chạy `notebooks/1-llm-only.ipynb`, kết quả được lưu tại:

```text
results/method_1_1/{run_id}/
```

Gồm:

```text
method_1_1_results.jsonl
method_1_1_results.csv
method_1_1_summary_by_question_type.csv
```

`method_1_1_results.csv` là bảng chi tiết từng sample. `method_1_1_summary_by_question_type.csv` là bảng tổng hợp nhanh theo subset.

## Cấu Hình `.env`

```dotenv
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=google/gemma-4-26b-a4b-it
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
SAMPLE_ID=1
OPENROUTER_PROVIDER_ONLY=nextbit
REQUEST_DELAY_SECONDS=0
```

`OPENROUTER_PROVIDER_ONLY` dùng để yêu cầu OpenRouter route qua provider cụ thể nếu provider đó khả dụng. `REQUEST_DELAY_SECONDS` có thể tăng lên khi chạy model free để giảm rủi ro rate limit.

## Thống Kê

Các thống kê chính:

- Accuracy overall: `mean(is_correct)` trên các dòng `status="success"`.
- Accuracy theo subset: `groupby(question_type).mean(is_correct)`.
- Parse success rate theo subset: `groupby(question_type).mean(parse_success)`.
- Token trung bình theo subset: `groupby(question_type).mean(input_tokens, output_tokens, total_tokens)`.
- Latency trung bình theo subset: `groupby(question_type).mean(round_trip_latency_ms)`.
- Cost tổng hoặc trung bình theo subset nếu OpenRouter trả về `usage.cost`.

## Hạn Chế

- 1.1 không grounded vào knowledge graph, nên dễ trả lời sai với dữ liệu chỉ có trong KB.
- Không sinh SPARQL nên không đánh giá được khả năng truy vấn ontology.
- Round-trip latency có chứa network overhead, client overhead và provider processing time; đây là metric đơn giản để so sánh runtime end-to-end, không phải inference-only latency.
- Model free trên OpenRouter có thể bị rate limit hoặc route không ổn định; vì vậy notebook ghi cả lỗi theo sample để thống kê không bị mất dòng.
