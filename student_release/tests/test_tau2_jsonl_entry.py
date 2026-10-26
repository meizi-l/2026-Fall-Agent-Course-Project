from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import textwrap
import types

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_tau2_genai_auth_is_transport_only_and_endpoint_scoped(monkeypatch):
    import asyncio

    module, _ = _load_tau2_entry_with_stubs(monkeypatch)
    monkeypatch.setenv("COURSE_API_KEY", "test-simulator-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://hkust.azure-api.net/hkust-genai/v1")
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    aclient = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    llm_utils = _module("tau2.utils.llm_utils")
    llm_utils.litellm = types.SimpleNamespace(client_session=client, aclient_session=aclient)
    utils = _module("tau2.utils")
    utils.llm_utils = llm_utils
    monkeypatch.setitem(sys.modules, "tau2.utils", utils)
    monkeypatch.setitem(sys.modules, "tau2.utils.llm_utils", llm_utils)

    module._configure_user_llm_transport()
    assert llm_utils.litellm.api_base == "https://hkust.azure-api.net/hkust-genai/v1"
    assert llm_utils.litellm.api_key == "test-simulator-secret"
    payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]}
    url = "https://hkust.azure-api.net/hkust-genai/v1/chat/completions"
    try:
        client.post(url, json=payload)
        for wrong_url in ("https://api.openai.com/v1/chat/completions",
                          "https://hkust.azure-api.net/other/chat/completions"):
            with pytest.raises(RuntimeError, match="OPENAI_BASE_URL"):
                client.post(wrong_url, json=payload)

        async def call_async():
            try:
                await aclient.post(url, json=payload)
            finally:
                await aclient.aclose()

        asyncio.run(call_async())
        assert len(seen) == 2
        for request in seen:
            assert request.headers["api-key"] == "test-simulator-secret"
            assert json.loads(request.content) == payload
        assert "test-simulator-secret" not in json.dumps(payload)
    finally:
        client.close()


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


@pytest.mark.parametrize(
    "policy", ["", 'Airline policy: "no insurance" means deny cancellation.\n\u89c4\u5219\uff1a\u4e0d\u5f97\u64c5\u81ea\u53d6\u6d88\u3002\n' * 500],
    ids=["empty-policy", "long-unicode-policy"],
)
def test_tau2_policy_reaches_jsonl_child_on_every_message_type(tmp_path, monkeypatch, policy):
    module, _ = _load_tau2_entry_with_stubs(monkeypatch)
    sidecar = tmp_path / "agent_events.jsonl"
    monkeypatch.setenv("COURSE_TAU2_AGENT_TRAJECTORY", str(sidecar))
    # Use the real IPC/AgentRequest parser; this child needs no agent strategy/API.
    child = textwrap.dedent('''
        import json, sys
        from course_agent.protocol import AgentRequest, AgentResponse
        for line in sys.stdin:
            request = AgentRequest.from_dict(json.loads(line))
            response = AgentResponse.final(request.request_id, json.dumps(request.to_dict()))
            print(json.dumps(response.to_dict()), flush=True)
    ''')
    monkeypatch.setenv("COURSE_AGENT_PROCESS_COMMAND", json.dumps(["{python}", "-u", "-c", child]))
    monkeypatch.setenv("COURSE_STUDENT_API_KEY", "test-ipc-token")
    monkeypatch.setenv("TAU2_CURRENT_TASK_ID", "49")

    class Tool:
        openai_schema = {"type": "function", "function": {
            "name": "get_reservation_details", "parameters": {"type": "object"},
        }}

    user = module.UserMessage()
    user.content = "Please cancel my flight."
    tool = module.ToolMessage()
    tool.id, tool.content = "lookup-1", '{"insurance":"no"}'
    other = module.ToolMessage()
    other.id, other.content = "lookup-2", '{"user_id":"u1"}'
    multi = module.MultiToolMessage()
    multi.tool_messages = [tool, other]
    expected = [
        {"message_type": "user", "content": "Please cancel my flight."},
        {"message_type": "tool_result", "tool_call_id": "lookup-1",
         "tool_name": "get_reservation_details", "content": '{"insurance":"no"}'},
        {"message_type": "tool_results", "tool_results": [
            {"tool_call_id": "lookup-1", "tool_name": "get_reservation_details", "content": '{"insurance":"no"}'},
            {"tool_call_id": "lookup-2", "tool_name": "get_user_details", "content": '{"user_id":"u1"}'},
        ]},
    ]
    limits = {"case_timeout_sec": 300, "max_agent_turns": 3, "max_tool_calls_per_turn": 3}
    agent = module.StudentJSONLAgent(
        tools=[Tool()], domain_policy=policy, student_root=str(ROOT),
        python=sys.executable, timeout=5, limits=limits,
    )
    state = agent.get_init_state()
    state.tool_names = {"lookup-1": "get_reservation_details", "lookup-2": "get_user_details"}
    received = []
    try:
        for step, (message, observation) in enumerate(zip([user, tool, multi], expected, strict=True)):
            response, state = agent.generate_next_message(message, state)
            request = json.loads(response.content)
            received.append(request)
            assert request["observation"] == {**observation, "domain_policy": policy}
            assert request["limits"] == limits
            assert request["tools"][0] == Tool.openai_schema
            assert [t["function"]["name"] for t in request["tools"]] == ["get_reservation_details", "respond_to_user"]
            assert request["case_id"] == "49"
            assert request["benchmark"] == "tau2_airline"
            assert request["step"] == step
            assert request["context_id"] == state.context_id
        assert state.step == 3
    finally:
        agent.close()
    events = [json.loads(line) for line in sidecar.read_text().splitlines()]
    assert [e["event"] for e in events] == ["request", "response"] * 3
    assert [e["request"] for e in events if e["event"] == "request"] == received
    assert [e["response"]["request_id"] for e in events if e["event"] == "response"] == [r["request_id"] for r in received]
