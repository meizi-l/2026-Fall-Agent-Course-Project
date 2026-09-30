from course_agent.protocol import AgentRequest
from course_agent.runtime import LLMResult
import inspect

from course_agent.student_agent import StudentAgent


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat(self, messages, tools=None, tool_choice="auto", limits=None):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice, "limits": limits})
        return self.result


def _tau_request(tools):
    return AgentRequest.from_dict(
        {
            "request_id": "req-1",
            "context_id": "ctx-1",
            "benchmark": "tau2_airline",
            "case_id": "3",
            "step": 0,
            "text": "I need to change my flight.",
            "observation": {"message_type": "user", "content": "I need to change my flight."},
            "tools": tools,
            "limits": {"max_agent_turns": 100, "model_input_tokens": 64000},
        }
    )


def _deepplanning_request(tools, observation=None):
    return AgentRequest.from_dict(
        {
            "request_id": "req-dp",
            "context_id": "ctx-dp",
            "benchmark": "deepplanning",
            "case_id": "shopping/level_1/case_12",
            "step": 0,
            "text": "Find suitable products.",
            "observation": observation or {"query": "Find suitable products.", "cart": {"items": []}},
            "tools": tools,
            "limits": {"max_model_calls": 100, "model_input_tokens": 64000},
        }
    )


def _mcpmark_request(tools, observation=None):
    return AgentRequest.from_dict(
        {
            "request_id": "req-mcp",
            "context_id": "ctx-mcp",
            "benchmark": "mcpmark",
            "case_id": "filesystem/desktop/timeline_extraction",
            "step": 0,
            "text": "Read the files and answer the task.",
            "observation": observation or {"task": "Read the files and answer the task."},
            "tools": tools,
            "limits": {"max_model_calls": 100, "model_input_tokens": 64000},
        }
    )


def _clear_llm_env(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_student_agent_template_exposes_locked_solver_contract():
    for method_name in ("solve_mcpmark", "solve_tau2_airline", "solve_deepplanning"):
        signature = inspect.signature(getattr(StudentAgent, method_name))
        assert list(signature.parameters) == ["self", "request"]


def test_student_agent_template_returns_valid_response_for_each_benchmark():
    agent = StudentAgent(llm_client=FakeLLM(LLMResult(content="ok", tool_calls=[])))

    responses = [
        agent.respond(_mcpmark_request([])),
        agent.respond(_tau_request([])),
        agent.respond(_deepplanning_request([])),
    ]

    assert [response.kind for response in responses] == ["final", "final", "final"]
    assert all(response.request_id for response in responses)


def test_student_agent_template_keeps_lazy_llm_client_hook():
    llm = FakeLLM(LLMResult(content="ok", tool_calls=[]))
    agent = StudentAgent(llm_client=llm)

    assert agent.llm_client is llm


def test_student_agent_template_has_clear_release_sections():
    source = inspect.getsource(StudentAgent)

    assert "##### LOCKED COURSE INTERFACE" in source
    assert "##### RESPONSE SCHEMA REQUIREMENTS" in source
    assert "##### OPTIONAL COURSE HELPERS" in source
    assert "##### STUDENT-DESIGNED BENCHMARK LOGIC" in source
    assert "##### ADD YOUR OWN HELPERS" in source
