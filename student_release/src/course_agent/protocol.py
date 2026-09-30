from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


BenchmarkName = Literal["mcpmark", "tau2_airline", "deepplanning"]
ResponseKind = Literal["tool_call", "tool_calls", "final", "error"]
VALID_BENCHMARKS = frozenset({"mcpmark", "tau2_airline", "deepplanning"})


class ProtocolError(ValueError):
    """Raised when a course JSONL request or response violates the contract."""


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{name} must be a JSON object")
    return value


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class AgentRequest:
    request_id: str
    context_id: str
    benchmark: BenchmarkName
    case_id: str
    step: int
    text: str = ""
    observation: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentRequest":
        data = _require_dict(value, "request")
        benchmark = _require_str(data.get("benchmark"), "benchmark")
        if benchmark not in VALID_BENCHMARKS:
            raise ProtocolError(f"Unsupported benchmark: {benchmark!r}")
        step = data.get("step")
        if not isinstance(step, int) or step < 0:
            raise ProtocolError("step must be a non-negative integer")
        text = data.get("text", "")
        if not isinstance(text, str):
            raise ProtocolError("text must be a string")
        tools = data.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
            raise ProtocolError("tools must be a list of JSON objects")
        return cls(
            request_id=_require_str(data.get("request_id"), "request_id"),
            context_id=_require_str(data.get("context_id"), "context_id"),
            benchmark=benchmark,  # type: ignore[arg-type]
            case_id=_require_str(data.get("case_id"), "case_id"),
            step=step,
            text=text,
            observation=_require_dict(data.get("observation", {}), "observation"),
            tools=tools,
            limits=_require_dict(data.get("limits", {}), "limits"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "context_id": self.context_id,
            "benchmark": self.benchmark,
            "case_id": self.case_id,
            "step": self.step,
            "text": self.text,
            "observation": self.observation,
            "tools": self.tools,
            "limits": self.limits,
        }


@dataclass(frozen=True)
class AgentResponse:
    request_id: str | None
    kind: ResponseKind
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_call_list: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""
    error_type: str | None = None
    message: str | None = None

    @classmethod
    def tool_call(cls, request_id: str, tool_name: str, tool_arguments: dict[str, Any]) -> "AgentResponse":
        return cls(request_id=request_id, kind="tool_call", tool_name=tool_name, tool_arguments=tool_arguments)

    @classmethod
    def tool_calls(cls, request_id: str, tool_calls: list[dict[str, Any]]) -> "AgentResponse":
        return cls(request_id=request_id, kind="tool_calls", tool_call_list=tool_calls)

    @classmethod
    def final(cls, request_id: str, content: str) -> "AgentResponse":
        return cls(request_id=request_id, kind="final", content=content)

    @classmethod
    def error(cls, request_id: str | None, error_type: str, message: str) -> "AgentResponse":
        return cls(request_id=request_id, kind="error", error_type=error_type, message=message)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentResponse":
        data = _require_dict(value, "response")
        kind = data.get("kind")
        if kind not in {"tool_call", "tool_calls", "final", "error"}:
            raise ProtocolError(f"Unsupported response kind: {kind!r}")
        response = cls(
            request_id=data.get("request_id"),
            kind=kind,
            tool_name=data.get("tool_name"),
            tool_arguments=data.get("tool_arguments", {}),
            tool_call_list=data.get("tool_calls", []),
            content=data.get("content", ""),
            error_type=data.get("error_type"),
            message=data.get("message"),
        )
        response.validate()
        return response

    def validate(self) -> None:
        if self.request_id is not None and not isinstance(self.request_id, str):
            raise ProtocolError("request_id must be a string or null")
        if self.kind == "tool_call":
            _require_str(self.request_id, "request_id")
            _require_str(self.tool_name, "tool_name")
            _require_dict(self.tool_arguments, "tool_arguments")
            if self.content:
                raise ProtocolError("tool_call content must be empty")
            return
        if self.kind == "tool_calls":
            _require_str(self.request_id, "request_id")
            if self.tool_name is not None or self.tool_arguments:
                raise ProtocolError("tool_calls response must not contain single tool fields")
            if not isinstance(self.tool_call_list, list) or not self.tool_call_list:
                raise ProtocolError("tool_calls must be a non-empty list")
            for index, call in enumerate(self.tool_call_list):
                _require_dict(call, f"tool_calls[{index}]")
                _require_str(call.get("tool_name"), f"tool_calls[{index}].tool_name")
                _require_dict(call.get("tool_arguments", {}), f"tool_calls[{index}].tool_arguments")
            if self.content:
                raise ProtocolError("tool_calls content must be empty")
            return
        if self.kind == "final":
            _require_str(self.request_id, "request_id")
            if self.tool_name is not None or self.tool_arguments or self.tool_call_list:
                raise ProtocolError("final response must not contain tool fields")
            if not isinstance(self.content, str):
                raise ProtocolError("content must be a string")
            return
        if self.kind == "error":
            _require_str(self.error_type, "error_type")
            _require_str(self.message, "message")
            return
        raise ProtocolError(f"Unsupported response kind: {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        if self.kind == "error":
            return {
                "request_id": self.request_id,
                "kind": "error",
                "error_type": self.error_type,
                "message": self.message,
            }
        if self.kind == "tool_calls":
            return {
                "request_id": self.request_id,
                "kind": "tool_calls",
                "tool_calls": self.tool_call_list,
                "content": self.content,
            }
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "tool_name": self.tool_name,
            "tool_arguments": self.tool_arguments,
            "content": self.content,
        }
