import json

import httpx
import openai
import pytest

from course_agent.runtime import ChatConfig, CourseLLMClient, LLMToolCall, load_chat_config


def test_load_chat_config_reads_required_env(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://hkust.azure-api.net/hkust-genai/v1")
    monkeypatch.setenv("COURSE_API_KEY", "key")
    monkeypatch.setenv("COURSE_LLM_MODEL", "course-model")
    for name in ("COURSE_LLM_TIMEOUT_SEC", "COURSE_LLM_MAX_INPUT_TOKENS",
                 "COURSE_LLM_MAX_OUTPUT_TOKENS", "COURSE_LLM_MAX_ATTEMPTS"):
        monkeypatch.delenv(name, raising=False)

    assert load_chat_config() == ChatConfig(
        base_url="https://hkust.azure-api.net/hkust-genai/v1",
        api_key="key",
        model="course-model",
        timeout_sec=300,
        max_input_tokens=64000,
        max_output_tokens=4096,
        max_attempts=2,
    )


def test_load_chat_config_reports_missing_env(monkeypatch):
    for name in (
        "OPENAI_BASE_URL",
        "COURSE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="COURSE_API_KEY"):
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
            base_url="https://hkust.azure-api.net/hkust-genai/v1",
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
            "max_completion_tokens": 123,
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
            base_url="https://hkust.azure-api.net/hkust-genai/v1",
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
    assert len(events) == 2
    assert events[0]["event"] == "llm_call_started"
    assert events[0]["call_id"] == events[1]["call_id"]
    assert events[1]["event"] == "llm_call"
    assert events[1]["status"] == "success"
    assert events[1]["model"] == "gpt-5-mini"
    assert events[1]["provider"] == "hkust_genai"
    assert "deployment" not in events[1]
    assert events[1]["attempt"] == 1
    assert events[1]["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert events[1]["estimated_input_tokens"] > 0


def test_course_llm_client_retries_transient_chat_failure_once():
    fake_client = _FlakyClient()
    llm = CourseLLMClient(
        ChatConfig(
            base_url="https://hkust.azure-api.net/hkust-genai/v1",
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
            base_url="https://hkust.azure-api.net/hkust-genai/v1",
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


@pytest.mark.parametrize("status", [200, 429])
def test_genai_http_contract_and_attempt_budget(monkeypatch, tmp_path, status):
    """Exercise the real SDK: a hidden SDK retry would exceed two HTTP requests."""
    requests = []

    def handle(request):
        requests.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "gpt-5-mini",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "lookup", "arguments": '{"id":1}'},
                }],
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        })

    real_openai = openai.OpenAI
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: real_openai(
        http_client=httpx.Client(transport=httpx.MockTransport(handle)), **kwargs))
    monkeypatch.setenv("COURSE_API_KEY", "test-genai-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://hkust.azure-api.net/hkust-genai/v1")
    monkeypatch.setenv("COURSE_LLM_MODEL", "gpt-5-mini")
    # Old provider settings must never redirect the migrated client.
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://old.invalid")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "stale-secret")
    usage = tmp_path / "usage.jsonl"
    monkeypatch.setenv("COURSE_LLM_USAGE_PATH", str(usage))
    llm = CourseLLMClient()
    limits = {"model_output_tokens": 75, "case_timeout_sec": 7, "llm_max_attempts": 2}
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    try:
        if status == 200:
            result = llm.chat([{"role": "user", "content": "lookup"}], tools=tools, limits=limits)
            assert result.tool_calls == [LLMToolCall("lookup", {"id": 1})]
            assert result.usage["total_tokens"] == 14
        else:
            with pytest.raises(RuntimeError, match="after 2 attempt"):
                llm.chat([{"role": "user", "content": "lookup"}], tools=tools, limits=limits)
        assert len(requests) == (1 if status == 200 else 2)
        for request in requests:
            assert str(request.url) == "https://hkust.azure-api.net/hkust-genai/v1/chat/completions"
            assert request.headers["api-key"] == "test-genai-secret"
            assert request.extensions["timeout"]["read"] == 7
            body = json.loads(request.content)
            assert body["model"] == "gpt-5-mini"
            assert body["max_completion_tokens"] == 75
            assert "max_tokens" not in body
            assert body["tools"] == tools
        assert "test-genai-secret" not in usage.read_text()
        assert "stale-secret" not in usage.read_text()
    finally:
        if llm._client is not None:
            llm.client.close()


def test_task_limits_override_client_fallbacks_and_bound_retries():
    llm = CourseLLMClient(
        ChatConfig("https://hkust.azure-api.net/hkust-genai/v1", "key", "gpt-5-mini", 300, 64000, 4096, 2),
        client=_FlakyClient(),
    )
    with pytest.raises(RuntimeError, match="LLM call limit exceeded"):
        llm.chat([{"role": "user", "content": "hi"}], limits={"max_model_calls": 1})
    assert llm.calls_made == 1
    with pytest.raises(RuntimeError, match="input exceeds"):
        llm.chat([{"role": "user", "content": "hello"}], limits={"model_input_tokens": 1})
