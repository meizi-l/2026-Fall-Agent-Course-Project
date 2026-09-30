from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TAU2_AIRLINE_MUTATING_TOOLS = frozenset(
    {
        "book_reservation",
        "cancel_reservation",
        "respond_to_user",
        "send_certificate",
        "update_reservation_baggages",
        "update_reservation_flights",
        "update_reservation_passengers",
    }
)

TAU2_AIRLINE_TERMINAL_TOOLS = frozenset({"respond_to_user"})

DEEPLANNING_SHOPPING_MUTATING_TOOLS = frozenset(
    {
        "add_product_to_cart",
        "delete_product_from_cart",
        "add_coupon_to_cart",
        "delete_coupon_from_cart",
        "submit_plan",
    }
)

DEEPLANNING_SHOPPING_TERMINAL_TOOLS = frozenset({"submit_plan"})

READ_NAME_PREFIXES = ("read", "list", "search", "query", "select", "get", "describe", "filter", "sort", "calculate")


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    tool_arguments: dict[str, Any]


class ToolCallPolicyError(ValueError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def tool_name_from_schema(tool: dict[str, Any]) -> str:
    if isinstance(tool.get("name"), str):
        return str(tool["name"])
    function = tool.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return str(function["name"])
    return ""


def default_max_tool_calls_per_turn(benchmark: str) -> int:
    return {"tau2_airline": 3, "deepplanning": 5, "mcpmark": 4}.get(benchmark, 1)


def default_max_mutating_tool_calls_per_turn(benchmark: str) -> int:
    return {"tau2_airline": 1, "deepplanning": 3, "mcpmark": 1}.get(benchmark, 1)


def terminal_tool_names_for_benchmark(benchmark: str) -> set[str]:
    if benchmark == "tau2_airline":
        return set(TAU2_AIRLINE_TERMINAL_TOOLS)
    if benchmark == "deepplanning":
        return set(DEEPLANNING_SHOPPING_TERMINAL_TOOLS)
    return set()


def classify_tool(benchmark: str, tool_name: str, tool_schema: dict[str, Any] | None = None) -> str:
    if benchmark == "tau2_airline":
        return "mutating" if tool_name in TAU2_AIRLINE_MUTATING_TOOLS else "read"
    if benchmark == "deepplanning":
        return "mutating" if tool_name in DEEPLANNING_SHOPPING_MUTATING_TOOLS else "read"
    if _read_only_hint(tool_schema):
        return "read"
    if tool_name.lower().startswith(READ_NAME_PREFIXES):
        return "read"
    return "mutating"


def validate_tool_batch(
    *,
    benchmark: str,
    calls: list[ToolCall],
    available_tools: list[dict[str, Any]],
    limits: dict[str, Any],
    terminal_tool_names: set[str] | None = None,
) -> None:
    terminal_tool_names = terminal_tool_names or set()
    if not calls:
        raise ToolCallPolicyError("ToolCallValidationError", "tool_calls response must contain at least one tool call")

    allow_multi = bool(limits.get("allow_multi_tool_calls", True))
    if not allow_multi and len(calls) > 1:
        raise ToolCallPolicyError("ToolCallLimitExceeded", "multiple tool calls are disabled for this benchmark")

    max_tool_calls = _positive_int(limits.get("max_tool_calls_per_turn"), default_max_tool_calls_per_turn(benchmark))
    if len(calls) > max_tool_calls:
        raise ToolCallPolicyError(
            "ToolCallLimitExceeded",
            f"tool call limit exceeded for one turn: {len(calls)} > {max_tool_calls}",
        )

    schemas_by_name = {tool_name_from_schema(tool): tool for tool in available_tools if tool_name_from_schema(tool)}
    for call in calls:
        if call.tool_name not in schemas_by_name:
            raise ToolCallPolicyError("UnknownToolError", f"unknown tool for this turn: {call.tool_name}")

    terminal_calls = [call.tool_name for call in calls if call.tool_name in terminal_tool_names]
    if terminal_calls and len(calls) > 1:
        names = ", ".join(sorted(set(terminal_calls)))
        raise ToolCallPolicyError("ToolCallOrderError", f"{names} cannot be combined with other tool calls")

    max_mutating = _positive_int(
        limits.get("max_mutating_tool_calls_per_turn"),
        default_max_mutating_tool_calls_per_turn(benchmark),
    )
    classifications = [
        classify_tool(benchmark, call.tool_name, schemas_by_name.get(call.tool_name))
        for call in calls
    ]
    mutating_count = sum(1 for item in classifications if item == "mutating")
    if mutating_count > max_mutating:
        raise ToolCallPolicyError(
            "ToolCallLimitExceeded",
            f"mutating tool call limit exceeded for one turn: {mutating_count} > {max_mutating}",
        )

    seen_mutating = False
    for classification in classifications:
        if classification == "mutating":
            seen_mutating = True
        elif seen_mutating:
            raise ToolCallPolicyError(
                "ToolCallOrderError",
                "mutating tool calls must come after read-only tool calls",
            )


def should_stop_after_tool_error(
    *,
    benchmark: str,
    failed_call: ToolCall,
    remaining_calls: list[ToolCall],
    available_tools: list[dict[str, Any]],
) -> bool:
    if benchmark == "mcpmark":
        return True
    schemas_by_name = {tool_name_from_schema(tool): tool for tool in available_tools if tool_name_from_schema(tool)}
    failed_classification = classify_tool(benchmark, failed_call.tool_name, schemas_by_name.get(failed_call.tool_name))
    if failed_classification == "mutating":
        return True
    return any(
        classify_tool(benchmark, call.tool_name, schemas_by_name.get(call.tool_name)) == "mutating"
        for call in remaining_calls
    )


def _read_only_hint(tool_schema: dict[str, Any] | None) -> bool:
    if not isinstance(tool_schema, dict):
        return False
    annotations = tool_schema.get("annotations")
    if isinstance(annotations, dict) and annotations.get("readOnlyHint") is True:
        return True
    function = tool_schema.get("function")
    if isinstance(function, dict):
        annotations = function.get("annotations")
        if isinstance(annotations, dict) and annotations.get("readOnlyHint") is True:
            return True
    return False


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
