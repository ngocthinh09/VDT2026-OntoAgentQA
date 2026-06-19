from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.ontology_qa_agent import (
    REPORTER_SYSTEM_PROMPT,
    _finalize_node,
    _initial_messages,
    _make_reporter_node,
)


class FakeReporterModel:
    def __init__(self) -> None:
        self.received_messages: list[Any] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.received_messages = messages
        return AIMessage(
            content=json.dumps(
                {
                    "selection_id": "2",
                    "answer_text": "Les Misérables (manga)",
                    "explanation": "Kết quả truy vấn khớp với lựa chọn 2.",
                },
                ensure_ascii=False,
            )
        )


def test_controller_messages_do_not_contain_options() -> None:
    question = "Victor Hugo có tác phẩm nào là truyện tranh không?"
    options = [{"id": 2, "text": "Les Misérables (manga)"}]

    messages = _initial_messages(question)

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == question
    assert options[0]["text"] not in str(messages)


def test_reporter_receives_options_and_preserves_query_evidence() -> None:
    model = FakeReporterModel()
    reporter = _make_reporter_node(model)
    result = [
        {
            "work": {
                "type": "uri",
                "value": "http://dbpedia.org/resource/Les_Misérables_(manga)",
            }
        }
    ]
    sparql = "SELECT ?work WHERE { ?work dbo:author dbr:Victor_Hugo . }"
    state = {
        "question": "Victor Hugo có tác phẩm nào là truyện tranh không?",
        "options": [
            {"id": 1, "text": "Không có"},
            {"id": 2, "text": "Les Misérables (manga)"},
        ],
        "answer": "Có Les Misérables (manga).",
        "final_sparql": sparql,
        "result": result,
    }

    update = reporter(state)

    assert update["selection_id"] == 2
    assert update["answer_text"] == "Les Misérables (manga)"
    assert update["answer"] == state["answer"]
    assert update["result"] is result
    assert update["final_sparql"] == sparql
    assert len(model.received_messages) == 2
    assert model.received_messages[0].content == REPORTER_SYSTEM_PROMPT
    reporter_payload = json.loads(model.received_messages[1].content)
    assert reporter_payload["options"] == state["options"]
    assert reporter_payload["controller_answer"] == state["answer"]


def test_finalize_uses_successful_evidence_stored_in_state() -> None:
    selected_result = [{"answer": {"value": "selected"}}]
    diagnostic_result = [{"answer": {"value": "diagnostic"}}]
    selected_query = "SELECT ?answer WHERE { ?s ?p ?answer }"
    state = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "final_sparql": selected_query,
                        "answer": "Controller conclusion",
                        "result": "untrusted controller copy",
                    }
                )
            )
        ],
        "executions": [
            {"query": selected_query, "result": selected_result, "ok": True},
            {
                "query": "SELECT ?answer WHERE { ?x ?y ?answer }",
                "result": diagnostic_result,
                "ok": True,
            },
        ],
        "final_sparql": selected_query,
        "result": selected_result,
    }

    update = _finalize_node(state)

    assert update["final_sparql"] == selected_query
    assert update["result"] is selected_result
    assert update["answer"] == "Controller conclusion"
    assert update["finalization_error"] is None


if __name__ == "__main__":
    test_controller_messages_do_not_contain_options()
    test_reporter_receives_options_and_preserves_query_evidence()
    test_finalize_uses_successful_evidence_stored_in_state()
    print("Reporter agent tests passed.")
