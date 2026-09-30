from __future__ import annotations

from typing import Any

from public_runner.envs.base import TaskEnvironment


class SimplifiedMCPMarkEnvironment(TaskEnvironment):
    def __init__(self, case: dict[str, Any]) -> None:
        super().__init__("mcpmark", case)

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "read_file",
                "description": "Read a visible task file.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            },
            {
                "name": "query_database",
                "description": "Run a tiny read-only SQL query.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
        ]

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "read_file":
            result = {"path": arguments.get("path"), "content": "baseline public file content"}
        elif name == "query_database":
            result = {"rows": [{"answer": 1}], "query": arguments.get("query")}
        else:
            result = {"error": f"unknown tool {name}"}
        self._tool_results.append({"tool_name": name, "result": result})
        return result


class SimplifiedTau2AirlineEnvironment(TaskEnvironment):
    def __init__(self, case: dict[str, Any]) -> None:
        super().__init__("tau2_airline", case)

    def observe(self) -> dict[str, Any]:
        observation = super().observe()
        observation["user_message"] = "I need help checking my flight."
        return observation

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "respond_to_user",
                "description": "Send a response to the simulated airline customer.",
                "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]},
            },
            {
                "name": "lookup_reservation",
                "description": "Look up a reservation.",
                "parameters": {"type": "object", "properties": {"confirmation": {"type": "string"}}, "required": ["confirmation"]},
            },
        ]

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "respond_to_user":
            result = {"accepted": True, "content": arguments.get("content", "")}
            self._done = True
        elif name == "lookup_reservation":
            result = {"reservation": {"confirmation": arguments.get("confirmation"), "status": "confirmed"}}
        else:
            result = {"error": f"unknown tool {name}"}
        self._tool_results.append({"tool_name": name, "result": result})
        return result


class SimplifiedDeepPlanningEnvironment(TaskEnvironment):
    def __init__(self, case: dict[str, Any]) -> None:
        super().__init__("deepplanning", case)

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_products",
                "description": "Search a tiny product catalog.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
            {
                "name": "submit_plan",
                "description": "Submit a shopping plan.",
                "parameters": {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"]},
            },
        ]

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_products":
            result = {"products": [{"id": "baseline-item", "price": 1.0}]}
        elif name == "submit_plan":
            result = {"accepted": True, "plan": arguments.get("plan", {})}
            self._done = True
        else:
            result = {"error": f"unknown tool {name}"}
        self._tool_results.append({"tool_name": name, "result": result})
        return result


class SimplifiedBackend:
    name = "simplified"

    def create_environment(self, benchmark: str, case: dict[str, Any]) -> TaskEnvironment:
        if benchmark == "mcpmark":
            return SimplifiedMCPMarkEnvironment(case)
        if benchmark == "tau2_airline":
            return SimplifiedTau2AirlineEnvironment(case)
        if benchmark == "deepplanning":
            return SimplifiedDeepPlanningEnvironment(case)
        raise ValueError(f"Unsupported benchmark: {benchmark}")
