# SPARQL Generation Baseline

## Overview

Baseline này đánh giá pipeline sinh SPARQL một lượt để lấy evidence từ GraphDB, sau đó dùng evidence đó để chọn đáp án trắc nghiệm.

Phương pháp này có GraphDB grounding nhưng chưa có vòng self-correction. Mỗi câu tối đa có một SPARQL query được sinh và thực thi.

## Pipeline

```text
question + options
-> central routing agent
-> SPARQL generation agent
-> GraphDB query
-> final answering agent
-> JSON answer
-> parse answer
-> evaluate
```

Các LLM call chính:

| Step | Purpose |
| --- | --- |
| `central_route` | Quyết định có cần dùng GraphDB không và tạo mô tả truy vấn trung lập. |
| `sparql_generate` | Sinh một query SPARQL `SELECT` hoặc `ASK`. |
| `central_final_graphdb_answer` | Chọn đáp án dựa trên GraphDB result. |
| `central_final_fallback_answer` | Chọn đáp án fallback nếu không có evidence usable. |

## Input Data

Dataset:

```text
data/ontologyqa_test_questions_v1.csv
```

Tổng số câu hỏi:

```text
62
```

Các cột chính:

| Column | Meaning |
| --- | --- |
| `number` | ID câu hỏi. |
| `vi_question` | Câu hỏi tiếng Việt. |
| `question_type` | Nhóm câu hỏi. |
| `answer` | ID đáp án đúng, từ 1 đến 5. |
| `option_1` đến `option_5` | Các lựa chọn trắc nghiệm. |

## Prompt And Answer Format

Benchmark user prompt template:

```text
Bạn là hệ thống trả lời trắc nghiệm tiếng Việt.
Chỉ trả về JSON hợp lệ, không giải thích, không markdown, không thêm ký tự khác.
Schema bắt buộc: {"answer":"1"}.
Giá trị answer hợp lệ là chuỗi từ "1" đến "{num_options}".

Câu hỏi: {question}

Các đáp án:
1. {option_1}
2. {option_2}
3. {option_3}
4. {option_4}
5. {option_5}

If SPARQL/GraphDB evidence is available, choose the option supported by that evidence and return {"answer":"1","evidence":["short evidence"]}; only guess the most likely option when no usable SPARQL evidence exists.
JSON:
```

### Central Routing Agent

System prompt:

```text
You are a central agent. Return only routing JSON.
```

Expected routing format:

```json
{
  "use_graphdb": true,
  "query_description": "neutral fact lookup description without answer options",
  "reason": "short reason"
}
```

If GraphDB is not needed:

```json
{
  "use_graphdb": false,
  "query_description": "",
  "reason": "short reason"
}
```

Important behavior:

- Answer options and option IDs must not be passed into the SPARQL coder.
- `query_description` should describe the neutral fact lookup needed to answer the core question.

### SPARQL Generation Agent

System prompt:

```text
You are a SPARQL coder. Return only SPARQL JSON.
```

Expected SPARQL format:

```json
{
  "sparql": "SELECT ... WHERE { ... }"
}
```

If no useful query can be created:

```json
{
  "sparql": ""
}
```

SPARQL constraints:

- Only `SELECT` or `ASK`.
- No `INSERT`, `DELETE`, `UPDATE`, `SERVICE`, or other write/external operations.
- Prefer neutral factual evidence such as entities, relationships, labels, dates, counts, and literal values.
- Do not include answer choices, option IDs, `VALUES` blocks for choices, or `BIND` mappings from choices to options.

### Final Answer Agent

Expected final answer format:

```json
{
  "answer": "1",
  "evidence": ["short evidence text"]
}
```

Behavior:

- If GraphDB rows are available, compare those facts with the original options and choose the option supported by evidence.
- Evidence should cite concrete values, entities, relationships, dates, counts, or literals from GraphDB result.
- If GraphDB result is empty or errored, choose the most likely option from general knowledge and mark evidence as fallback.

## Configuration

Các biến môi trường cần có trong `.env`:

```dotenv
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_PROVIDER_ONLY=...
CHAT_TEMPERATURE=0.2
REQUEST_DELAY_SECONDS=0

GRAPHDB_ENDPOINT=http://host:7200/repositories/DBPEDIA
GRAPHDB_TIMEOUT=30
GRAPHDB_MAX_ROWS=20
```

## How To Run

Notebook:

```text
experiments/sparql_gen.ipynb
```

CLI smoke test:

```bash
conda run -n ontology-qa python -m experiments.runners.sparql_gen --limit 1
```

CLI full run:

```bash
conda run -n ontology-qa python -m experiments.runners.sparql_gen
```

Trong notebook:

```python
LIMIT = 1  # smoke test
LIMIT = 0  # full 62 questions
```

## Outputs

Output directory:

```text
experiments/results/sparql_gen/{run_id}/
```

Files:

```text
results.csv
results.jsonl
summary.json
```

Các cột quan trọng:

| Column | Meaning |
| --- | --- |
| `question_id` | ID câu hỏi. |
| `question_type` | Nhóm câu hỏi. |
| `correct_answer` | ID đáp án đúng. |
| `predicted_answer` | ID đáp án model chọn. |
| `is_correct` | `true` nếu `predicted_answer == correct_answer`. |
| `has_db_evidence` | `true` nếu final response có evidence không phải fallback. |
| `routing_decision` | JSON routing decision. |
| `sparql` | SPARQL được sinh và chạy. |
| `graphdb_result_summary` | Tóm tắt GraphDB result. |
| `graphdb_error` | Lỗi GraphDB nếu có. |
| `llm_calls` | Danh sách LLM call và token từng call. |
| `input_tokens` | Tổng input tokens của mọi LLM call trong câu. |
| `output_tokens` | Tổng output tokens của mọi LLM call trong câu. |
| `total_tokens` | Tổng token của mọi LLM call trong câu. |
| `latency_seconds` | End-to-end latency cho câu hỏi. |
| `raw_response` | Final response gốc trước khi parse answer. |

## Metric Definitions

```text
Accuracy = number of correct predictions / total questions
Avg Input Tokens = mean(input_tokens)
Avg Output Tokens = mean(output_tokens)
Avg Total Tokens = mean(total_tokens)
Avg Time = mean(latency_seconds)
DB Evidence Rate = number of final answers with non-fallback evidence / successful questions
```

Với SPARQL Generation, `input_tokens` và `output_tokens` của mỗi câu là tổng token của tất cả LLM calls trong pipeline.
