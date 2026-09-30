import json

import pytest

from course_agent.runtime import ChatConfig, CourseLLMClient, LLMToolCall, load_chat_config


def test_load_chat_config_reads_required_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-02-01-preview")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "course-model")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")

    assert load_chat_config() == ChatConfig(
        endpoint="https://example.openai.azure.com",
        api_version="2025-02-01-preview",
        deployment="course-model",
        api_key="key",
        model="course-model",
        timeout_sec=300,
        max_input_tokens=64000,
        max_output_tokens=4096,
        max_attempts=2,
    )


def test_load_chat_config_reports_missing_env(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        load_chat_config()


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FlakyCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("temporary upstream failure")
        return {"choices": [{"message": {"content": "Recovered", "tool_calls": []}}]}


class _FakeClient:
    def __init__(self, response):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(response)})()


class _FlakyClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FlakyCompletions()})()


def test_course_llm_client_sends_limits_and_parses_tool_calls():
    response = {
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "function": {
                                "name": "lookup_flight",
                                "arguments": '{"flight":"CX123"}',
                            }
                        }
                    ],
                }
            }
        ]
    }
    fake_client = _FakeClient(response)
    llm = CourseLLMClient(
        ChatConfig(
            endpoint="https://example.openai.azure.com",
            api_version="2025-02-01-preview",
            deployment="gpt-5-mini",
            api_key="key",
            model="gpt-5-mini",
            timeout_sec=12,
            max_input_tokens=64000,
            max_output_tokens=123,
            max_attempts=2,
        ),
        client=fake_client,
    )

    result = llm.chat(
        [{"role": "user", "content": "Need flight help"}],
        tools=[{"type": "function", "function": {"name": "lookup_flight", "parameters": {"type": "object"}}}],
    )

    assert fake_client.chat.completions.calls == [
        {
            "model": "gpt-5-mini",
            "messages": [{"role": "user", "content": "Need flight help"}],
            "max_tokens": 123,
            "timeout": 12,
            "tools": [{"type": "function", "function": {"name": "lookup_flight", "parameters": {"type": "object"}}}],
            "tool_choice": "auto",
        }
    ]
    assert result.content == ""
    assert result.tool_calls == [LLMToolCall(name="lookup_flight", arguments={"flight": "CX123"})]
    assert result.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert llm.calls_made == 1


def test_course_llm_client_records_usage_event(tmp_path, monkeypatch):
    usage_path = tmp_path / "llm_usage.jsonl"
    monkeypatch.setenv("COURSE_LLM_USAGE_PATH", str(usage_path))
    fake_client = _FakeClient(
        {
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            "choices": [{"message": {"content": "ok", "tool_calls": []}}],
        }
    )
    llm = CourseLLMClient(
        ChatConfig(
            endpoint="https://example.openai.azure.com",
            api_version="2025-02-01-preview",
            deployment="gpt-5-mini",
            api_key="key",
            model="gpt-5-mini",
            timeout_sec=12,
            max_input_tokens=64000,
            max_output_tokens=123,
            max_attempts=2,
        ),
        client=fake_client,
    )

    llm.chat([{"role": "user", "content": "hi"}])

    events = [json.loads(line) for line in usage_path.read_text().splitlines()]
    assert len(events) == 1
    assert events[0]["event"] == "llm_call"
    assert events[0]["status"] == "success"
    assert events[0]["model"] == "gpt-5-mini"
    assert events[0]["deployment"] == "gpt-5-mini"
    assert events[0]["attempt"] == 1
    assert events[0]["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert events[0]["estimated_input_tokens"] > 0


def test_course_llm_client_retries_transient_chat_failure_once():
    fake_client = _FlakyClient()
    llm = CourseLLMClient(
        ChatConfig(
            endpoint="https://example.openai.azure.com",
            api_version="2025-02-01-preview",
            deployment="gpt-5-mini",
            api_key="key",
            model="gpt-5-mini",
            timeout_sec=12,
            max_input_tokens=64000,
            max_output_tokens=123,
            max_attempts=2,
        ),
        client=fake_client,
    )

    result = llm.chat([{"role": "user", "content": "Need flight help"}])

    assert result.content == "Recovered"
    assert len(fake_client.chat.completions.calls) == 2
    assert llm.calls_made == 2


def test_course_llm_client_rejects_oversized_input():
    llm = CourseLLMClient(
        ChatConfig(
            endpoint="https://example.openai.azure.com",
            api_version="2025-02-01-preview",
            deployment="gpt-5-mini",
            api_key="key",
            model="gpt-5-mini",
            timeout_sec=12,
            max_input_tokens=1,
            max_output_tokens=123,
            max_attempts=2,
        ),
        client=_FakeClient({"choices": [{"message": {"content": "unused"}}]}),
    )

    with pytest.raises(RuntimeError, match="input exceeds"):
        llm.chat([{"role": "user", "content": "This input is too long for a one-token estimate."}])
