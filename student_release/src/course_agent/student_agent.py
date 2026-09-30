from __future__ import annotations

from typing import Any

from course_agent.protocol import AgentRequest, AgentResponse
from course_agent.runtime import CourseLLMClient


class StudentAgent:
    """Student-editable agent template.

    This file is intentionally a template, not a working benchmark strategy.
    Build your own MCPMark, tau2 airline, and DeepPlanning logic in the marked
    student-designed section below.
    """

    ##### LOCKED COURSE INTERFACE ###########################################

    def __init__(self, llm_client: CourseLLMClient | None = None) -> None:
        # You may add fields here, such as per-context memory, caches, prompts,
        # or planner state. Keep ``_llm_client`` so tests can inject a fake
        # client and the course runtime can lazy-load the configured client.
        self._llm_client = llm_client
        self._state: dict[str, dict[str, Any]] = {}

    @property
    def llm_client(self) -> CourseLLMClient:
        """Course-provided synchronous LLM client.

        The client applies course timeout, retry, token, and model-call limits.
        Keep this property available even if your agent wraps it in additional
        helper methods.
        """

        if self._llm_client is None:
            self._llm_client = CourseLLMClient()
        return self._llm_client

    def respond(self, request: AgentRequest) -> AgentResponse:
        """Dispatch one runner request to the benchmark-specific solver."""

        handlers = {
            "mcpmark": self.solve_mcpmark,
            "tau2_airline": self.solve_tau2_airline,
            "deepplanning": self.solve_deepplanning,
        }
        response = handlers[request.benchmark](request)
        response.validate()
        return response

    ##### RESPONSE SCHEMA REQUIREMENTS ######################################

    # Every solver must return exactly one AgentResponse:
    #
    # 1. Final answer:
    #    AgentResponse.final(request.request_id, "your final text")
    #
    # 2. Single tool call:
    #    AgentResponse.tool_call(
    #        request.request_id,
    #        "tool_name",
    #        {"argument_name": "argument_value"},
    #    )
    #
    # 3. Multiple tool calls:
    #    AgentResponse.tool_calls(
    #        request.request_id,
    #        [
    #            {"tool_name": "read_tool", "tool_arguments": {}},
    #            {"tool_name": "write_tool", "tool_arguments": {}},
    #        ],
    #    )
    #
    # Tool names and argument schemas come from ``request.tools``. The runner
    # enforces per-turn tool limits, mutating-tool limits, read-before-write
    # ordering, and terminal-tool rules.

    ##### OPTIONAL COURSE HELPERS ###########################################

    def _tool_names(self, request: AgentRequest) -> list[str]:
        """Return available tool names from either supported tool schema style."""

        names: list[str] = []
        for tool in request.tools:
            name = tool.get("name")
            if isinstance(name, str):
                names.append(name)
                continue
            function = tool.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.append(function["name"])
        return names

    def _case_state(self, request: AgentRequest) -> dict[str, Any]:
        """Mutable memory scoped to one benchmark case/context."""

        key = f"{request.benchmark}:{request.context_id}"
        return self._state.setdefault(key, {})

    ##### STUDENT-DESIGNED BENCHMARK LOGIC #################################

    def solve_mcpmark(self, request: AgentRequest) -> AgentResponse:
        """Design your MCPMark agent here.

        Input contract:
        - ``request.text`` contains the task text.
        - ``request.observation`` contains environment observations and previous
          ``tool_results``.
        - ``request.tools`` contains the available MCP tools for this turn.

        Output contract:
        - Return a valid ``AgentResponse`` following the schema section above.
        """

        return self._placeholder_final(request, "TODO: implement MCPMark strategy.")

    def solve_tau2_airline(self, request: AgentRequest) -> AgentResponse:
        """Design your tau2 airline customer-service agent here.

        To speak to the simulated user, call the provided ``respond_to_user``
        tool when it is present in ``request.tools``.
        """

        return self._placeholder_final(request, "TODO: implement tau2 airline strategy.")

    def solve_deepplanning(self, request: AgentRequest) -> AgentResponse:
        """Design your DeepPlanning Shopping agent here.

        Official tasks expose shopping tools. The simplified smoke backend may
        expose ``submit_plan`` only to validate the JSONL protocol.
        """

        return self._placeholder_final(request, "TODO: implement DeepPlanning strategy.")

    ##### ADD YOUR OWN HELPERS BELOW ########################################

    def _placeholder_final(self, request: AgentRequest, message: str) -> AgentResponse:
        """Schema-valid placeholder so smoke tests can load the template."""

        return AgentResponse.final(request.request_id, message)
