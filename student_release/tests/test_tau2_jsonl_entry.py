from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]


def _module(name: str) -> types.ModuleType:
    return types.ModuleType(name)


def _load_tau2_entry_with_stubs(monkeypatch):
    registered_names: list[str] = []

    pydantic = _module("pydantic")

    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def Field(default_factory=None, **_):
        return default_factory() if default_factory is not None else None

    pydantic.BaseModel = BaseModel
    pydantic.Field = Field

    base_agent = _module("tau2.agent.base_agent")

    class HalfDuplexAgent:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, tools, domain_policy):
            self.tools = tools
            self.domain_policy = domain_policy

    base_agent.HalfDuplexAgent = HalfDuplexAgent
    base_agent.ValidAgentInputMessage = object

    message = _module("tau2.data_model.message")

    class AssistantMessage:
        def __init__(self, role, content=None, tool_calls=None):
            self.role = role
            self.content = content
            self.tool_calls = tool_calls

    class ToolCall:
        def __init__(self, id, name, arguments, requestor):
            self.id = id
            self.name = name
            self.arguments = arguments
            self.requestor = requestor

    class ToolMessage:
        pass

    class UserMessage:
        pass

    class MultiToolMessage:
        pass

    message.AssistantMessage = AssistantMessage
    message.ToolCall = ToolCall
    message.ToolMessage = ToolMessage
    message.UserMessage = UserMessage
    message.MultiToolMessage = MultiToolMessage

    tool = _module("tau2.environment.tool")

    class Tool:
        pass

    tool.Tool = Tool

    registry_module = _module("tau2.registry")

    class Registry:
        def register_agent_factory(self, _factory, name):
            registered_names.append(name)

    registry_module.registry = Registry()

    modules = {
        "pydantic": pydantic,
        "tau2": _module("tau2"),
        "tau2.agent": _module("tau2.agent"),
        "tau2.agent.base_agent": base_agent,
        "tau2.data_model": _module("tau2.data_model"),
        "tau2.data_model.message": message,
        "tau2.environment": _module("tau2.environment"),
        "tau2.environment.tool": tool,
        "tau2.registry": registry_module,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(
        "tau2_jsonl_entry_under_test",
        ROOT / "public_runner" / "envs" / "tau2_jsonl_entry.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, registered_names


def test_tau2_student_client_uses_configured_launcher(tmp_path, monkeypatch):
    module, _ = _load_tau2_entry_with_stubs(monkeypatch)
    captured = {}

    class FakeProcess:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["env"] = kwargs["env"]

        def close(self):
            pass

    monkeypatch.setattr(module, "JSONLProcess", FakeProcess)
    monkeypatch.setenv("COURSE_AGENT_PROCESS_COMMAND", '["sandbox", "{student_root}", "{python}"]')
    monkeypatch.setenv("COURSE_STUDENT_API_KEY", "student-token")
    monkeypatch.setenv("COURSE_API_KEY", "staff-token")
    module.StudentProcessClient(tmp_path, sys.executable, 2).close()
    assert captured["argv"][0] == "sandbox"
    assert captured["env"]["COURSE_API_KEY"] == "student-token"


def test_tau2_response_adapter_preserves_multiple_tool_calls(monkeypatch):
    module, _registered_names = _load_tau2_entry_with_stubs(monkeypatch)

    assistant_message = module._response_to_tau_message(
        {
            "request_id": "req-1",
            "kind": "tool_calls",
            "tool_calls": [
                {"tool_name": "lookup_flight", "tool_arguments": {"flight": "CX123"}},
                {"tool_name": "check_bag", "tool_arguments": {"bag": "1"}},
            ],
        },
        "req-1",
    )

    assert assistant_message.content is None
    assert [tool_call.name for tool_call in assistant_message.tool_calls] == ["lookup_flight", "check_bag"]
    assert [tool_call.arguments for tool_call in assistant_message.tool_calls] == [{"flight": "CX123"}, {"bag": "1"}]


def test_tau2_response_adapter_rejects_too_many_tool_calls(monkeypatch):
    module, _registered_names = _load_tau2_entry_with_stubs(monkeypatch)

    response = {
        "request_id": "req-1",
        "kind": "tool_calls",
        "tool_calls": [
            {"tool_name": "get_user_details", "tool_arguments": {"user_id": "u1"}},
            {"tool_name": "get_reservation_details", "tool_arguments": {"reservation_id": "r1"}},
            {"tool_name": "search_direct_flight", "tool_arguments": {"origin": "SFO", "destination": "JFK", "date": "2024-05-20"}},
            {"tool_name": "calculate", "tool_arguments": {"expression": "1 + 1"}},
        ],
    }

    try:
        module._response_to_tau_message(response, "req-1", {"max_tool_calls_per_turn": 3})
    except RuntimeError as exc:
        assert "tool call limit exceeded" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_tau2_response_adapter_rejects_mutating_tool_before_read(monkeypatch):
    module, _registered_names = _load_tau2_entry_with_stubs(monkeypatch)

    response = {
        "request_id": "req-1",
        "kind": "tool_calls",
        "tool_calls": [
            {"tool_name": "update_reservation_baggages", "tool_arguments": {"reservation_id": "r1"}},
            {"tool_name": "get_reservation_details", "tool_arguments": {"reservation_id": "r1"}},
        ],
    }

    try:
        module._response_to_tau_message(response, "req-1", {"max_tool_calls_per_turn": 3})
    except RuntimeError as exc:
        assert "mutating tool calls must come after read-only tool calls" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_tau2_response_adapter_rejects_respond_to_user_mixed_with_tools(monkeypatch):
    module, _registered_names = _load_tau2_entry_with_stubs(monkeypatch)

    response = {
        "request_id": "req-1",
        "kind": "tool_calls",
        "tool_calls": [
            {"tool_name": "get_user_details", "tool_arguments": {"user_id": "u1"}},
            {"tool_name": "respond_to_user", "tool_arguments": {"content": "hello"}},
        ],
    }

    try:
        module._response_to_tau_message(response, "req-1", {"max_tool_calls_per_turn": 3})
    except RuntimeError as exc:
        assert "respond_to_user cannot be combined" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_tau2_entry_registers_readable_student_agent_name(monkeypatch):
    _module, registered_names = _load_tau2_entry_with_stubs(monkeypatch)

    assert registered_names == ["student_jsonl_agent"]


def test_tau2_student_agent_writes_request_response_sidecar(tmp_path, monkeypatch):
    module, _registered_names = _load_tau2_entry_with_stubs(monkeypatch)
    sidecar = tmp_path / "agent_events.jsonl"
    monkeypatch.setenv("COURSE_TAU2_AGENT_TRAJECTORY", str(sidecar))

    class FakeTool:
        openai_schema = {
            "type": "function",
            "function": {"name": "get_reservation_details", "parameters": {"type": "object"}},
        }

    class FakeClient:
        def send(self, request):
            return {"request_id": request["request_id"], "kind": "final", "content": "hello"}

    agent = module.StudentJSONLAgent(
        tools=[FakeTool()],
        domain_policy="",
        student_root=str(ROOT),
        python=sys.executable,
        limits={"max_agent_turns": 3},
    )
    agent._client = FakeClient()
    message = module.UserMessage()
    message.content = "I need help with my booking."
    message.task = types.SimpleNamespace(id="3")

    assistant_message, _state = agent.generate_next_message(message, agent.get_init_state())

    assert assistant_message.content == "hello"
    events = [json.loads(line) for line in sidecar.read_text().splitlines()]
    assert [event["event"] for event in events] == ["request", "response"]
    assert events[0]["request"]["benchmark"] == "tau2_airline"
    assert events[0]["request"]["case_id"] == "3"
    assert events[1]["response"]["content"] == "hello"
