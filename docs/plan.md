# Plan: Xây dựng Ontology QA Agent theo hướng ARUQULA

## Summary

Mục tiêu tiếp theo là nối các tool đã xây dựng thành một agent LangGraph v1 có khả năng tự tìm entity/property/class, inspect knowledge graph, thử SPARQL, sửa query khi lỗi, và dừng khi có SPARQL cuối cùng hợp lệ.

Hiện đã có tầng tool:

- Search tools: `search_entity_by_label`, `search_property_by_label`, `search_class_by_label`.
- KG tools: `execute_sparql`, `get_knowledgegraph_entry`, `get_property_examples`.

Bước tiếp theo là xây tầng orchestration tương tự ARUQULA/SPINACH, nhưng dùng LangGraph v1 và tool-calling hiện đại thay vì parse text `Action: ...` thủ công.

## 1. Controller / Reasoning Loop

Controller là tầng quyết định agent sẽ làm gì tiếp theo ở mỗi vòng lặp.

Cần implement hành vi:

- Nhận `question` từ user.
- Nhìn `action_history` hoặc `steps` đã thực hiện.
- Chọn đúng một action tiếp theo: search, inspect, execute, hoặc stop.
- Nếu chưa chắc URI entity, dùng `search_entity_by_label`.
- Nếu chưa chắc predicate/relation/attribute, dùng `search_property_by_label`.
- Nếu chưa chắc ontology type/category, dùng `search_class_by_label`.
- Nếu cần xem facts của một entity, dùng `get_knowledgegraph_entry`.
- Nếu cần ví dụ cách dùng một property, dùng `get_property_examples`.
- Nếu đã có giả thuyết SPARQL, dùng `execute_sparql`.
- Không lặp lại cùng một action với cùng argument nếu observation trước đó đã có.

Tham chiếu ARUQULA:

- ARUQULA dùng `controller.prompt` để sinh `Thought` + `Action`.
- Sau đó dùng `format_actions.prompt` để ép output về JSON action.
- Với LangGraph v1 hiện đại, nên dùng tool-calling trực tiếp thay vì parse text `Action: ...`.

Prompt agent nên dựa trên `ARUQULA/spinach_agent/prompts/controller.prompt`, nhưng cần chỉnh cho dataset hiện tại:

- Entity trong data không có `rdfs:label/comment`, nên entity grounding phải đi qua Elasticsearch `search_entity_by_label`.
- Property/class dùng Elasticsearch schema index.
- Luôn verify SPARQL bằng `execute_sparql` trước khi final.
- Phân biệt query rỗng hợp lệ `[]` với query lỗi JSON `{"ok": false, ...}`.

## 2. Graph State

State cần lưu đủ thông tin để agent biết mình đã làm gì và có thể dừng đúng lúc.

State tối thiểu:

- `question`: câu hỏi hiện tại.
- `messages`: message history cho LLM/tool-calling.
- `actions` hoặc `steps`: lịch sử các action/tool call và observation.
- `generated_sparqls`: các SPARQL đã được agent thử qua `execute_sparql`.
- `last_execution_result`: kết quả gần nhất của `execute_sparql`.
- `final_sparql`: SPARQL cuối cùng được chấp nhận.
- `iteration_count`: số vòng lặp hiện tại.

Khuyến nghị:

- Lưu tool observations dạng compact text để prompt không quá dài.
- Lưu raw result của `execute_sparql` riêng với formatted observation.
- Chỉ cập nhật `final_sparql` khi query gần nhất đã execute thành công và có result hợp lệ.

## 3. LangGraph Agent Graph

Graph tối thiểu nên có:

- `agent` node: LLM nhận state/messages và quyết định gọi tool hay trả final answer.
- `tools` node: `ToolNode(SEARCH_TOOLS + KG_TOOLS)`.
- Router:
  - Nếu LLM có tool call -> chuyển sang `tools`.
  - Sau `tools` -> quay lại `agent`.
  - Nếu LLM không gọi tool và đã có final answer hợp lệ -> end.
  - Nếu vượt quá giới hạn vòng lặp -> end với báo cáo thất bại/partial.

Giới hạn vòng lặp:

- Mặc định `15`, giống ARUQULA.
- Nếu agent lặp lại action quá nhiều lần, cần chèn observation nói rõ action đó đã được thực hiện và yêu cầu thử hướng khác.

Public interface để gọi agent nên đơn giản:

```python
agent = build_ontology_qa_agent()
result = agent.invoke({"question": "What is the length of Type 052D destroyer?"})
```

Output nên gồm:

- `final_sparql`
- `result`
- `answer`
- `steps` hoặc `messages` để debug

## 4. Final SPARQL Extraction / Validation

ARUQULA có logic `stop()` chỉ chấp nhận khi query cuối có result. Agent mới cũng cần rule tương tự.

Validation rules:

- Nếu `execute_sparql` trả result hợp lệ và không rỗng -> có thể final.
- Nếu `execute_sparql` trả boolean `True` hoặc `False` cho ASK query -> có thể final.
- Nếu `execute_sparql` trả JSON lỗi với `ok=false` -> agent phải sửa query, không final.
- Nếu `execute_sparql` trả `[]` -> query hợp lệ nhưng không có kết quả; agent phải thử hướng khác hoặc báo fail khi hết lượt.
- Nếu final answer không có SPARQL đã execute trước đó -> không chấp nhận final, yêu cầu agent execute query trước.

Final response nên chứa:

- SPARQL cuối cùng.
- Result hoặc sample result.
- Giải thích ngắn gọn vì sao query trả lời câu hỏi.

Nếu sau 15 vòng vẫn không có query hợp lệ:

- Báo rõ các bước đã thử.
- Nếu có SPARQL gần đúng nhưng lỗi/rỗng, trả lại SPARQL đó và error/result rỗng để debug.

## Implementation Plan

1. Tạo `agents/ontology_qa_agent.py`.
2. Import và kết hợp tools:
   - `SEARCH_TOOLS`
   - `KG_TOOLS`
3. Tạo system prompt dựa trên ARUQULA controller prompt.
4. Tạo state schema cho LangGraph.
5. Build graph gồm `agent`, `tools`, router, và loop limit.
6. Thêm helper format observation cho search/KG/SPARQL result nếu cần.
7. Thêm smoke test cho agent.
8. Thêm notebook demo agent.

## Test Plan

Tạo smoke test, dự kiến `utils/test_ontology_qa_agent.py`.

Test các câu đơn giản:

- `What is the length of Type 052D destroyer?`
- `Is Type 052D destroyer a Ship?`
- `What is the birth place of Albert Einstein?`

Kiểm tra agent behavior:

- Có gọi search tool trước khi dùng URI khi cần resolve entity/property/class.
- Có gọi `execute_sparql` trước khi final.
- Query lỗi `{"ok": false, ...}` không được final.
- Query rỗng `[]` không bị nhầm là lỗi runtime.
- Final output có `final_sparql` và result.

Tạo notebook demo, dự kiến `notebooks/agent_demo.ipynb`:

- Cell import agent.
- Cell khởi tạo graph.
- Cell invoke một vài câu hỏi.
- Cell in final SPARQL và result.

## Assumptions

- Dùng LangGraph v1 với `ToolNode`.
- Dùng tool-calling thay vì parse text `Action: ...` như ARUQULA gốc.
- Elasticsearch và GraphDB đã chạy.
- Index hiện tại giữ nguyên: `entity_index`, `schema_index`.
- Chưa làm Qdrant/hybrid vector search trong bước này.
- Chưa làm full evaluation trên `test_questions_v1.0.xlsx` cho đến khi agent smoke test chạy ổn.
