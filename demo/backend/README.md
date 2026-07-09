# OntoAgentQA Demo Backend

FastAPI backend for the local OntoAgentQA demo. It exposes a small HTTP API that
wraps the existing LangGraph agent and returns both the final answer and
traceable tool execution steps.

## Run

Install dependencies from the repository root or from this directory:

```bash
cd demo/backend
pip install -r requirements.txt
```

The backend automatically reads the repository root `.env`. Optionally create a
backend-specific override file:

```bash
cp .env.example .env
```

Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Ask a question:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Có mấy tàu có cảng đăng ký tại Cam Ranh?"}'
```

Swagger UI is available at:

```text
http://localhost:8000/docs
```

## Response Shape

```json
{
  "answer": "Final answer",
  "trace": [
    {
      "step": 1,
      "type": "search",
      "tool": "search_entity_by_label",
      "input": {"query": "Cam Ranh"},
      "output": [],
      "duration_ms": null,
      "status": "success",
      "error": null
    }
  ],
  "sparql": "SELECT ...",
  "raw_result": [],
  "metadata": {
    "elapsed_ms": 1234,
    "event_count": 8,
    "finalization_error": null
  }
}
```

