"""Register a tau2 agent that talks to the course JSONL subprocess protocol."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import uuid
from datetime import datetime, timezone

STUDENT_RELEASE_ROOT = Path(__file__).resolve().parents[2]
if str(STUDENT_RELEASE_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDENT_RELEASE_ROOT))

from public_runner.envs.tool_policy import ToolCall as CourseToolCall
from public_runner.envs.tool_policy import (
    ToolCallPolicyError,
    terminal_tool_names_for_benchmark,
    validate_tool_batch,
)
from public_runner.jsonl_ipc import JSONLProcess
from public_runner.student_launcher import student_process_launch

from pydantic import BaseModel, Field

from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage, UserMessage
from tau2.environment.tool import Tool
from tau2.registry import registry


RESPOND_TOOL_NAME = "respond_to_user"
STUDENT_AGENT_NAME = "student_jsonl_agent"


class JSONLAgentState(BaseModel):
    context_id: str | None = None
    step: int = 0
    tool_names: dict[str, str] = Field(default_factory=dict)


class StudentProcessClient:
    def __init__(self, student_root: Path, python: str, timeout: float) -> None:
        command, env = student_process_launch(student_root, python)
        self.timeout = timeout
        self._proc = JSONLProcess(
            command,
            cwd=student_root, timeout=timeout, env=env,
        )

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._proc.send(request)

    def close(self) -> None:
        self._proc.close()


class StudentJSONLAgent(HalfDuplexAgent[JSONLAgentState]):
    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        student_root: str,
        python: str,
        timeout: float = 300,
        limits: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.student_root = Path(student_root).resolve()
        self.python = python
        self.timeout = timeout
        self.limits = limits or {"timeout_sec": timeout}
        self._client: StudentProcessClient | None = None

    def get_init_state(self, message_history: list[Any] | None = None) -> JSONLAgentState:
        del message_history
        return JSONLAgentState(context_id=uuid.uuid4().hex)

    @property
    def client(self) -> StudentProcessClient:
        if self._client is None:
            self._client = StudentProcessClient(self.student_root, self.python, self.timeout)
        return self._client

    def generate_next_message(
        self,
        message: ValidAgentInputMessage,
        state: JSONLAgentState,
    ) -> tuple[AssistantMessage, JSONLAgentState]:
        max_agent_turns = _positive_int(self.limits.get("max_agent_turns"), 0)
        if max_agent_turns and state.step >= max_agent_turns:
            raise RuntimeError(f"student agent exceeded {max_agent_turns} turns")
        request_id = uuid.uuid4().hex
        request = {
            "request_id": request_id,
            "context_id": state.context_id or uuid.uuid4().hex,
            "benchmark": "tau2_airline",
            "case_id": _case_id_from_message(message),
            "step": state.step,
            "text": _message_text(message, state.tool_names),
            "observation": _message_observation(message, state.tool_names),
            "tools": _tool_schemas(self.tools),
            "limits": self.limits,
        }
        _append_agent_event({"event": "request", "request": request})
        try:
            response = self.client.send(request)
            _append_agent_event({"event": "response", "response": response})
            assistant_message = _response_to_tau_message(response, request_id, self.limits, request["tools"])
        except Exception as exc:
            _append_agent_event({"event": "error", "error_type": type(exc).__name__, "message": str(exc)})
            raise
        for tool_call in assistant_message.tool_calls or []:
            state.tool_names[tool_call.id] = tool_call.name
        state.step += 1
        return assistant_message, state

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _tool_schemas(tools: list[Tool]) -> list[dict[str, Any]]:
    schemas = [tool.openai_schema for tool in tools]
    schemas.append(
        {
            "type": "function",
            "function": {
                "name": RESPOND_TOOL_NAME,
                "description": "Respond directly to the simulated user instead of calling a domain tool.",
                "parameters": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
        }
    )
    return schemas


def _message_text(message: ValidAgentInputMessage, tool_names: dict[str, str]) -> str:
    if isinstance(message, UserMessage):
        return str(message.content or "")
    if isinstance(message, MultiToolMessage):
        return "\n".join(
            f"Tool '{tool_names.get(item.id, item.id)}' result: {item.content}" for item in message.tool_messages
        )
    if isinstance(message, ToolMessage):
        return f"Tool '{tool_names.get(message.id, message.id)}' result: {message.content}"
    return str(message)


def _message_observation(message: ValidAgentInputMessage, tool_names: dict[str, str]) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        return {"message_type": "user", "content": message.content}
    if isinstance(message, MultiToolMessage):
        return {
            "message_type": "tool_results",
            "tool_results": [
                {
                    "tool_call_id": item.id,
                    "tool_name": tool_names.get(item.id, item.id),
                    "content": item.content,
                }
                for item in message.tool_messages
            ],
        }
    if isinstance(message, ToolMessage):
        return {
            "message_type": "tool_result",
            "tool_call_id": message.id,
            "tool_name": tool_names.get(message.id, message.id),
            "content": message.content,
        }
    return {"message_type": type(message).__name__, "content": str(message)}


def _case_id_from_message(message: ValidAgentInputMessage) -> str:
    task = getattr(message, "task", None)
    task_id = getattr(task, "id", None)
    return str(task_id or os.getenv("TAU2_CURRENT_TASK_ID", "unknown"))


def _response_to_tau_message(
    response: dict[str, Any],
    request_id: str,
    limits: dict[str, Any] | None = None,
    available_tools: list[dict[str, Any]] | None = None,
) -> AssistantMessage:
    if response.get("request_id") not in {request_id, None}:
        raise RuntimeError(f"student agent returned mismatched request_id: {response.get('request_id')!r}")
    kind = response.get("kind")
    if kind in {"tool_call", "tool_calls"}:
        tool_calls = _response_tool_calls(response)
        _validate_tau2_tool_calls(tool_calls, limits or {}, available_tools)
        respond_calls = [call for call in tool_calls if call["tool_name"] == RESPOND_TOOL_NAME]
        if respond_calls:
            if len(tool_calls) > 1:
                raise RuntimeError(f"{RESPOND_TOOL_NAME} cannot be combined with domain tool calls")
            arguments = respond_calls[0]["tool_arguments"]
            return AssistantMessage(role="assistant", content=str(arguments.get("content", "")), tool_calls=None)
        return AssistantMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=call["tool_name"],
                    arguments=call["tool_arguments"],
                    requestor="assistant",
                )
                for call in tool_calls
            ],
        )
    if kind == "final":
        return AssistantMessage(role="assistant", content=str(response.get("content", "")), tool_calls=None)
    if kind == "error":
        raise RuntimeError(f"student agent error: {response.get('error_type')}: {response.get('message')}")
    raise RuntimeError(f"student agent returned unsupported response kind: {kind!r}")


def _validate_tau2_tool_calls(
    tool_calls: list[dict[str, Any]],
    limits: dict[str, Any],
    available_tools: list[dict[str, Any]] | None,
) -> None:
    if available_tools is None:
        available_tools = [
            {"type": "function", "function": {"name": call["tool_name"], "parameters": {"type": "object"}}}
            for call in tool_calls
        ]
    calls = [CourseToolCall(call["tool_name"], call["tool_arguments"]) for call in tool_calls]
    try:
        validate_tool_batch(
            benchmark="tau2_airline",
            calls=calls,
            available_tools=available_tools,
            limits=limits,
            terminal_tool_names=terminal_tool_names_for_benchmark("tau2_airline"),
        )
    except ToolCallPolicyError as exc:
        raise RuntimeError(exc.message) from exc


def _response_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("kind") == "tool_call":
        return [
            {
                "tool_name": str(response.get("tool_name") or ""),
                "tool_arguments": response.get("tool_arguments") or {},
            }
        ]
    raw_calls = response.get("tool_calls") or []
    if not isinstance(raw_calls, list) or not raw_calls:
        raise RuntimeError("tool_calls response must include a non-empty tool_calls list")
    calls: list[dict[str, Any]] = []
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, dict):
            raise RuntimeError(f"tool_calls[{index}] must be an object")
        tool_name = str(raw_call.get("tool_name") or "")
        if not tool_name:
            raise RuntimeError(f"tool_calls[{index}].tool_name is required")
        arguments = raw_call.get("tool_arguments") or {}
        if not isinstance(arguments, dict):
            raise RuntimeError(f"tool_calls[{index}].tool_arguments must be an object")
        calls.append({"tool_name": tool_name, "tool_arguments": arguments})
    return calls


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _append_agent_event(event: dict[str, Any]) -> None:
    path = os.getenv("COURSE_TAU2_AGENT_TRAJECTORY")
    if not path:
        return
    payload = dict(event)
    payload.setdefault("time", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


def create_student_jsonl_agent(
    tools: list[Tool],
    domain_policy: str,
    llm: str | None = None,
    llm_args: dict[str, Any] | None = None,
    **kwargs: Any,
) -> StudentJSONLAgent:
    del llm
    args = llm_args or {}
    student_root = str(args.get("student_root") or Path(__file__).resolve().parents[2])
    python = str(args.get("python") or sys.executable)
    timeout = float(args.get("timeout", 300))
    limits = args.get("limits")
    if not isinstance(limits, dict):
        limits = {"timeout_sec": timeout}
    return StudentJSONLAgent(
        tools=tools,
        domain_policy=domain_policy,
        student_root=student_root,
        python=python,
        timeout=timeout,
        limits=limits,
        **kwargs,
    )


registry.register_agent_factory(create_student_jsonl_agent, STUDENT_AGENT_NAME)


if __name__ == "__main__":
    from tau2.cli import main

    main()
