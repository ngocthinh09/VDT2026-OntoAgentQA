# LLM Only Baseline

## Overview

Baseline này đánh giá khả năng model trả lời trực tiếp câu hỏi trắc nghiệm OntologyQA mà không dùng SPARQL, GraphDB, retrieval hay self-correction.

Mục tiêu chính là đo năng lực trả lời zero-shot của LLM trên cùng bộ 62 câu hỏi.

## Pipeline

```text
question + options
-> LLM
-> JSON answer
-> parse answer
-> evaluate
```

Mỗi câu hỏi chỉ có một LLM call.

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
| `question_type` | Nhóm câu hỏi, ví dụ `entity`, `counting`, `list`, `boolean`, `multi-hop`, `comparison`, `schema`, `attribute`, `superlative`. |
| `answer` | ID đáp án đúng, từ 1 đến 5. |
| `option_1` đến `option_5` | Các lựa chọn trắc nghiệm. |

## Prompt And Answer Format

System prompt:

```text
Bạn là một chatbot tiếng Việt hữu ích, trả lời ngắn gọn và rõ ràng.
```

User prompt template:

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

JSON:
```

Required answer format:

```json
{"answer":"1"}
```

Parser lấy giá trị `answer` trong JSON. Nếu model không trả JSON sạch, parser thử fallback bằng regex để tìm option ID hợp lệ từ 1 đến số lượng option.

## Configuration

Các biến môi trường cần có trong `.env`:

```dotenv
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_PROVIDER_ONLY=...
REQUEST_DELAY_SECONDS=0
CHAT_TEMPERATURE=0.2
```

`OPENROUTER_PROVIDER_ONLY` là optional. Nếu có, request sẽ yêu cầu OpenRouter route qua provider đó.

## How To Run

Notebook:

```text
experiments/llm_only.ipynb
```

CLI smoke test:

```bash
conda run -n ontology-qa python -m experiments.runners.llm_only --limit 1
```

CLI full run:

```bash
conda run -n ontology-qa python -m experiments.runners.llm_only
```

Trong notebook:

```python
LIMIT = 1  # smoke test
LIMIT = 0  # full 62 questions
```

## Outputs

Output directory:

```text
experiments/results/llm_only/{run_id}/
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
| `input_tokens` | Token input của LLM call. |
| `output_tokens` | Token output của LLM call. |
| `total_tokens` | Tổng token. |
| `cost` | Chi phí nếu provider trả về. |
| `latency_seconds` | End-to-end latency cho câu hỏi. |
| `raw_response` | Text response gốc của model. |

## Metric Definitions

```text
Accuracy = number of correct predictions / total questions
Avg Input Tokens = mean(input_tokens)
Avg Output Tokens = mean(output_tokens)
Avg Total Tokens = mean(total_tokens)
Avg Time = mean(latency_seconds)
```

Với LLM-only, token của mỗi câu chính là token của một LLM call duy nhất.
