from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChatConfig:
    endpoint: str
    api_version: str
    deployment: str
    api_key: str
    model: str
    timeout_sec: int
    max_input_tokens: int
    max_output_tokens: int
    max_attempts: int


@dataclass(frozen=True)
class LLMToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResult:
    content: str
    tool_calls: list[LLMToolCall]
    usage: dict[str, int] | None = None


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def load_chat_config() -> ChatConfig:
    required_names = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
    ]
    missing = [name for name in required_names if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required LLM environment variables: {', '.join(missing)}")

    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    return ChatConfig(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        deployment=deployment,
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        model=os.getenv("COURSE_LLM_MODEL", deployment),
        timeout_sec=_int_env("COURSE_LLM_TIMEOUT_SEC", 300),
        max_input_tokens=_int_env("COURSE_LLM_MAX_INPUT_TOKENS", 64000),
        max_output_tokens=_int_env("COURSE_LLM_MAX_OUTPUT_TOKENS", 4096),
        max_attempts=_int_env("COURSE_LLM_MAX_ATTEMPTS", 2),
    )


class CourseLLMClient:
    """Small synchronous OpenAI SDK wrapper with course limits."""

    def __init__(self, config: ChatConfig | None = None, client: Any | None = None) -> None:
        self.config = config or load_chat_config()
        self._client = client
        self.calls_made = 0

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _make_openai_client(self.config)
        return self._client

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        limits: dict[str, Any] | None = None,
    ) -> LLMResult:
        limits = limits or {}
        max_calls = _positive_int(limits.get("max_model_calls"), 0)

        max_input_tokens = _positive_int(limits.get("model_input_tokens"), self.config.max_input_tokens)
        estimated_input_tokens = _estimate_tokens({"messages": messages, "tools": tools or []})
        if estimated_input_tokens > max_input_tokens:
            raise RuntimeError(f"LLM input exceeds limit: estimated {estimated_input_tokens} > {max_input_tokens}")

        max_output_tokens = _positive_int(limits.get("model_output_tokens"), self.config.max_output_tokens)
        timeout = _positive_int(limits.get("case_timeout_sec"), self.config.timeout_sec)
        max_attempts = _positive_int(limits.get("llm_max_attempts"), self.config.max_attempts)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "timeout": timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        completions = self.client.chat.completions
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            if max_calls and self.calls_made >= max_calls:
                raise RuntimeError(f"LLM call limit exceeded: {max_calls}") from last_exc
            try:
                response = completions.create(**kwargs)
            except Exception as exc:
                self.calls_made += 1
                last_exc = exc
                _record_llm_usage_event(
                    {
                        "event": "llm_call",
                        "status": "error",
                        "provider": "azure_openai",
                        "model": self.config.model,
                        "deployment": self.config.deployment,
                        "attempt": attempt + 1,
                        "estimated_input_tokens": estimated_input_tokens,
                        "usage": {},
                        "error_type": type(exc).__name__,
                    }
                )
                continue
            self.calls_made += 1
            result = _parse_chat_response(response)
            _record_llm_usage_event(
                {
                    "event": "llm_call",
                    "status": "success",
                    "provider": "azure_openai",
                    "model": self.config.model,
                    "deployment": self.config.deployment,
                    "attempt": attempt + 1,
                    "estimated_input_tokens": estimated_input_tokens,
                    "usage": result.usage or {},
                }
            )
            return result
        raise RuntimeError(f"LLM chat failed after {max_attempts} attempt(s)") from last_exc


def _make_openai_client(config: ChatConfig) -> Any:
    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise RuntimeError("The OpenAI SDK is not installed. Run `uv sync --locked` in student_release.") from exc
    return AzureOpenAI(
        azure_endpoint=config.endpoint,
        api_version=config.api_version,
        api_key=config.api_key,
        timeout=config.timeout_sec,
    )


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _estimate_tokens(payload: Any) -> int:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return max(1, (len(text) + 3) // 4)


def _parse_chat_response(response: Any) -> LLMResult:
    choices = _get(response, "choices") or []
    if not choices:
        return LLMResult(content="", tool_calls=[], usage=_parse_usage(_get(response, "usage") or {}))
    message = _get(choices[0], "message") or {}
    content = _get(message, "content") or ""
    raw_tool_calls = _get(message, "tool_calls") or []
    tool_calls = [_parse_tool_call(tool_call) for tool_call in raw_tool_calls]
    return LLMResult(content=str(content), tool_calls=tool_calls, usage=_parse_usage(_get(response, "usage") or {}))


def _parse_usage(raw_usage: Any) -> dict[str, int]:
    usage: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _get(raw_usage, key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            usage[key] = parsed
    return usage


def _parse_tool_call(tool_call: Any) -> LLMToolCall:
    function = _get(tool_call, "function") or {}
    name = str(_get(function, "name") or "")
    raw_arguments = _get(function, "arguments") or "{}"
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {"_raw_arguments": raw_arguments}
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        arguments = {"_raw_arguments": raw_arguments}
    if not isinstance(arguments, dict):
        arguments = {"_raw_arguments": arguments}
    return LLMToolCall(name=name, arguments=arguments)


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _record_llm_usage_event(event: dict[str, Any]) -> None:
    path = os.getenv("COURSE_LLM_USAGE_PATH")
    if not path:
        return
    payload = dict(event)
    payload.setdefault("time", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError:
        return
