# SPARQL Generation With Self Correction

## Overview

Baseline này đánh giá pipeline sinh SPARQL có vòng self-correction. Sau mỗi SPARQL attempt, central control agent nhìn lại execution history để quyết định trả lời ngay hay sinh thêm một truy vấn SPARQL khác.

Phương pháp này dùng GraphDB grounding và có thể chạy nhiều lượt SPARQL cho cùng một câu hỏi.

## Pipeline

```text
question + options
-> central routing agent
-> SPARQL generation agent
-> GraphDB query
-> central next-action agent
-> repeat SPARQL generation if needed
-> answer formatter agent
-> JSON answer
-> parse answer
-> evaluate
```

Các LLM call chính:

| Step | Purpose |
| --- | --- |
| `central_route` | Quyết định có cần GraphDB không và tạo mô tả truy vấn đầu tiên. |
| `sparql_generate` | Sinh SPARQL cho từng attempt. |
| `central_next_action` | Quyết định `answer` hoặc tiếp tục `sparql` sau mỗi attempt. |
| `answer_formatter_final` | Tạo final answer từ original prompt và full execution history. |

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

Important behavior:

- The initial `query_description` must not include answer options or option IDs.
- It should describe the neutral fact lookup needed by the core question.

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

SPARQL constraints:

- Only `SELECT` or `ASK`.
- No write queries or `SERVICE`.
- Do not encode answer choices into SPARQL.
- Prefer evidence needed by the core question: entity labels, relationships, dates, counts, literal values, and relevant predicates.

### Central Next-Action Agent

System prompt:

```text
You are a central control agent. Return only action JSON.
```

The agent receives:

- original prompt;
- full execution history;
- current SPARQL attempt count;
- maximum SPARQL attempts.

Expected format when enough information is available:

```json
{
  "action": "answer",
  "query_description": "",
  "reason": "short reason"
}
```

Expected format when another lookup is needed:

```json
{
  "action": "sparql",
  "query_description": "neutral fact lookup description",
  "reason": "short reason"
}
```

Rules:

- Choose `answer` if history contains enough concrete evidence or further attempts are unlikely to help.
- Choose `sparql` if one more neutral GraphDB lookup is useful.
- Do not include answer option IDs or answer choices in `query_description`.
- Avoid repeating failed or already-executed lookups from history.

### Answer Formatter Agent

System role:

```text
You are the answer formatting agent for a Vietnamese chatbot.
```

The formatter receives:

- original user prompt, including options;
- full execution history;
- all SPARQL attempts;
- GraphDB result summaries and errors.

Required final answer format:

```json
{
  "answer": "1",
  "evidence": ["short evidence text"]
}
```

Behavior:

- If GraphDB rows are available in history, compare facts with the original choices and choose the supported option.
- Evidence should cite concrete values, entities, relationships, dates, counts, or literals from the history when possible.
- If no usable SPARQL evidence exists after the loop stops, choose the most likely answer from general knowledge and mark evidence as best-effort fallback.

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

MAX_SPARQL_ATTEMPTS=5
QUESTION_TIMEOUT_SECONDS=1200
QUESTION_FINALIZATION_RESERVE_SECONDS=240
```

## How To Run

Notebook:

```text
experiments/sparql_self_correct.ipynb
```

CLI smoke test:

```bash
conda run -n ontology-qa python -m experiments.runners.sparql_self_correct --limit 1
```

CLI full run:

```bash
conda run -n ontology-qa python -m experiments.runners.sparql_self_correct
```

Trong notebook:

```python
LIMIT = 1  # smoke test
LIMIT = 0  # full 62 questions
```

## Outputs

Output directory:

```text
experiments/results/sparql_self_correct/{run_id}/
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
| `sparql_attempts` | Số lượt SPARQL execution đã thử. |
| `history` | Full execution history dùng bởi answer formatter. |
| `latest_graphdb_result_summary` | Tóm tắt GraphDB result usable gần nhất. |
| `latest_graphdb_error` | Lỗi GraphDB gần nhất nếu không có result usable. |
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
Avg SPARQL Attempts = mean(sparql_attempts)
DB Evidence Rate = number of final answers with non-fallback evidence / successful questions
```

Với SPARQL Generation + Self Correction, `input_tokens` và `output_tokens` của mỗi câu là tổng token của toàn bộ LLM calls trong pipeline, bao gồm routing, SPARQL generation, next-action decisions và answer formatter.
