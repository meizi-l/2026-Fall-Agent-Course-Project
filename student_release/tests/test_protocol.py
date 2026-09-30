import pytest

from course_agent.protocol import AgentRequest, AgentResponse, ProtocolError


def test_request_round_trip_with_limits_and_tools():
    raw = {
        "request_id": "req-1",
        "context_id": "ctx-1",
        "benchmark": "tau2_airline",
        "case_id": "3",
        "step": 2,
        "text": "hello",
        "observation": {"user": "I need help"},
        "tools": [{"name": "lookup", "parameters": {"type": "object"}}],
        "limits": {"max_agent_turns": 100},
    }

    request = AgentRequest.from_dict(raw)

    assert request.request_id == "req-1"
    assert request.benchmark == "tau2_airline"
    assert request.to_dict() == raw


def test_response_tool_call_round_trip():
    response = AgentResponse.tool_call("req-1", "lookup", {"confirmation": "ABC123"})

    assert response.to_dict() == {
        "request_id": "req-1",
        "kind": "tool_call",
        "tool_name": "lookup",
        "tool_arguments": {"confirmation": "ABC123"},
        "content": "",
    }
    assert AgentResponse.from_dict(response.to_dict()) == response


def test_response_tool_calls_round_trip():
    response = AgentResponse.tool_calls(
        "req-1",
        [
            {"tool_name": "lookup", "tool_arguments": {"confirmation": "ABC123"}},
            {"tool_name": "reserve", "tool_arguments": {"seat": "12A"}},
        ],
    )

    assert response.to_dict() == {
        "request_id": "req-1",
        "kind": "tool_calls",
        "tool_calls": [
            {"tool_name": "lookup", "tool_arguments": {"confirmation": "ABC123"}},
            {"tool_name": "reserve", "tool_arguments": {"seat": "12A"}},
        ],
        "content": "",
    }
    assert AgentResponse.from_dict(response.to_dict()) == response


def test_response_final_rejects_tool_fields():
    with pytest.raises(ProtocolError, match="final response must not contain tool fields"):
        AgentResponse.from_dict(
            {
                "request_id": "req-1",
                "kind": "final",
                "tool_name": "lookup",
                "tool_arguments": {},
                "content": "done",
            }
        )


def test_response_rejects_unknown_kind():
    with pytest.raises(ProtocolError, match="Unsupported response kind"):
        AgentResponse.from_dict(
            {
                "request_id": "req-1",
                "kind": "other",
                "tool_name": None,
                "tool_arguments": {},
                "content": "",
            }
        )
