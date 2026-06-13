# Method 1.1 - LLM-only Baseline

## Mục tiêu

Method 1.1 là baseline thấp nhất cho bài toán OntologyQA. Hệ thống đưa câu hỏi tiếng Việt và các lựa chọn trắc nghiệm trực tiếp cho LLM, sau đó yêu cầu model chọn một đáp án.

Baseline này không sinh SPARQL, không gọi SPARQL endpoint, không dùng ontology fragment, không dùng Milvus và không có self-correction. Vai trò của nó là tạo mốc so sánh để chứng minh các phương pháp 1.2-1.4 tốt hơn LLM-only.

## Input và Output

Input lấy từ `test_questions_v1.0.xlsx`.

- `vi_question`: câu hỏi tiếng Việt.
- `question_type`: loại câu hỏi nếu có.
- cột thứ 4 trong Excel: gold answer semantic, đang không có header nên notebook ánh xạ thành `gold_answer`.
- `answer`: chỉ số option đúng.
- `option_1` đến `option_5`: các lựa chọn trắc nghiệm.

Output kỳ vọng từ model:

```json
{
  "selected_option": 3,
  "answer_text": "Việt Nam",
  "reason": "Giải thích ngắn"
}
```

Khi chấm điểm, `selected_option` được so sánh với cột `answer`.

## Thuật toán

1. Đọc file Excel bằng `pandas.read_excel(..., engine="openpyxl")`.
2. Bỏ qua các dòng chưa hoàn thiện, cụ thể là dòng không có `vi_question`, không có chỉ số đáp án đúng hoặc có ít hơn 2 lựa chọn.
3. Lấy mẫu theo `SAMPLE_ID` trong cột `number`; các dòng thiếu câu hỏi, đáp án đúng hoặc options được bỏ qua.
4. Tạo prompt LLM-only:
   - chỉ cung cấp câu hỏi, loại câu hỏi và options;
   - nhắc rõ không sinh SPARQL và không dùng knowledge graph;
   - yêu cầu trả về JSON hợp lệ.
5. Load cấu hình từ `.env` bằng `python-dotenv`.
6. Gọi OpenRouter bằng `openai` SDK:
   - `base_url="https://openrouter.ai/api/v1"`;
   - model mặc định `google/gemma-4-26b-a4b-it:free`;
   - API key lấy từ `OPENROUTER_API_KEY`.
7. Lấy raw response headers để phục vụ đo metric hệ thống ở các thí nghiệm sau.
8. Parse `selected_option` từ response và so sánh với nhãn đúng.

## Cách chạy smoke test

Tạo môi trường Python và cài dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Điền API key vào `.env`:

```dotenv
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=google/gemma-4-26b-a4b-it:free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
SAMPLE_ID=1
```

Mở và chạy notebook:

```text
ontology-qa.ipynb
```

## Tiêu chí thành công

- Notebook đọc được `test_questions_v1.0.xlsx`.
- Notebook lấy được 1 mẫu hợp lệ.
- OpenRouter trả về response từ model đã cấu hình.
- Response parse được `selected_option`.
- Notebook in được usage và các HTTP headers liên quan đến OpenRouter/provider/latency/rate-limit nếu chúng có mặt trong response.

## Ghi chú kỹ thuật

OpenRouter hỗ trợ dùng OpenAI SDK như một drop-in client bằng cách đổi `base_url` sang `https://openrouter.ai/api/v1`. Tài liệu Models API của OpenRouter mô tả model slug là định danh dùng trong request, ví dụ `google/gemma-4-26b-a4b-it:free`.

Notebook dùng `pandas` để đọc file test Excel. `openpyxl` vẫn được giữ trong `requirements.txt` vì đây là engine đọc `.xlsx` mà pandas dùng cho file này.

Ở bước smoke test, notebook vẫn tính `wall_time_s` phía client để debug, nhưng đây chưa phải metric chính thức cho báo cáo. Theo yêu cầu dự án, các thí nghiệm chính cần ưu tiên metadata/headers từ OpenRouter khi có sẵn để tách latency phía provider khỏi độ trễ phía client.

## Hạn chế

- Vì không dùng SPARQL/ontology, baseline này dễ trả lời theo trí nhớ sai hoặc chọn option theo pattern.
- Với câu hỏi cần dữ liệu cập nhật hoặc dữ liệu chỉ có trong KB, kết quả có thể không ổn định.
- Model free trên OpenRouter có thể bị rate limit hoặc route qua provider khác nhau, nên cần lưu metadata response khi chạy batch.
