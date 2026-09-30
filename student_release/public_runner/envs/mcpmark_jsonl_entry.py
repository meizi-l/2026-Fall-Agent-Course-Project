from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, TextIO

try:
    from public_runner.envs.mcpmark_case_config import MCPMarkCase, resolve_mcpmark_case
except ModuleNotFoundError:
    from mcpmark_case_config import MCPMarkCase, resolve_mcpmark_case


FILESYSTEM_SERVER_PACKAGE = "@modelcontextprotocol/server-filesystem@2025.12.18"
POSTGRES_MCP_PACKAGE = "postgres-mcp==0.3.0"


def resolve_public_case(case_id: str, case_config: dict[str, Any] | None = None) -> MCPMarkCase:
    return resolve_mcpmark_case(case_id, case_config)


class MCPMarkSession:
    def __init__(self, mcpmark_root: Path, work_root: Path | None = None) -> None:
        self.mcpmark_root = mcpmark_root.resolve()
        self.work_root = work_root or Path(tempfile.mkdtemp(prefix="course_mcpmark_"))
        self.case: MCPMarkCase | None = None
        self.case_id: str | None = None
        self.task: Any | None = None
        self.task_manager: Any | None = None
        self.state_manager: Any | None = None
        self.server: Any | None = None
        self.filesystem_root: Path | None = None
        self.loop = asyncio.new_event_loop()
        self.instruction = ""
        self.messages: list[dict[str, Any]] = []
        self._closed = False
        self.cleanup_error: str | None = None

    def start(self, case_id: str, case_config: dict[str, Any] | None = None) -> dict[str, Any]:
        self.case = resolve_mcpmark_case(case_id, case_config)
        self.case_id = case_id
        self._load_mcpmark_imports()

        if self.case.service == "filesystem":
            return self._start_filesystem()
        if self.case.service == "postgres":
            return self._start_postgres()
        raise ValueError(f"unsupported MCPMark service: {self.case.service}")

    def _start_filesystem(self) -> dict[str, Any]:
        from src.agents.mcp.stdio_server import MCPStdioServer
        from src.mcp_services.filesystem.filesystem_state_manager import FilesystemStateManager
        from src.mcp_services.filesystem.filesystem_task_manager import FilesystemTaskManager

        self.task_manager = FilesystemTaskManager(
            tasks_root=self.mcpmark_root / "tasks",
            task_suite=self.case.task_suite,
        )
        tasks = self.task_manager.filter_tasks(self.case.task_filter)
        if len(tasks) != 1:
            raise RuntimeError(f"expected exactly one MCPMark task for {self.case.task_filter}, found {len(tasks)}")
        self.task = tasks[0]
        self.state_manager = FilesystemStateManager()
        if not self.state_manager.set_up(self.task):
            raise RuntimeError(f"MCPMark filesystem state setup failed for {self.task.name}")

        self.instruction = self.task_manager.get_task_instruction(self.task)
        test_directory = self.state_manager.get_service_config_for_agent().get("test_directory")
        if not test_directory:
            raise RuntimeError("MCPMark filesystem state manager did not provide test_directory")
        self.filesystem_root = Path(str(test_directory)).resolve()

        server_js = os.getenv("MCPMARK_FILESYSTEM_SERVER_JS", "")
        if server_js and Path(server_js).exists():
            command = shutil.which("node") or "node"
            args = [server_js, str(self.filesystem_root)]
        else:
            package = os.getenv("FILESYSTEM_SERVER_PACKAGE", FILESYSTEM_SERVER_PACKAGE)
            command = "npx"
            args = ["-y", package, str(self.filesystem_root)]
        self.server = MCPStdioServer(
            command=command,
            args=args,
            timeout=int(os.getenv("MCPMARK_MCP_INIT_TIMEOUT", "30")),
        )
        self.loop.run_until_complete(self.server.__aenter__())
        self.messages = [{"role": "user", "content": self.instruction}]
        return self.observe()

    def _start_postgres(self) -> dict[str, Any]:
        from src.agents.mcp.stdio_server import MCPStdioServer
        from src.mcp_services.postgres.postgres_state_manager import PostgresStateManager
        from src.mcp_services.postgres.postgres_task_manager import PostgresTaskManager

        self.task_manager = PostgresTaskManager(
            tasks_root=self.mcpmark_root / "tasks",
            task_suite=self.case.task_suite,
        )
        tasks = self.task_manager.filter_tasks(self.case.task_filter)
        if len(tasks) != 1:
            raise RuntimeError(f"expected exactly one MCPMark task for {self.case.task_filter}, found {len(tasks)}")

        self.task = tasks[0]
        self.state_manager = PostgresStateManager(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DATABASE", "postgres"),
            username=os.getenv("POSTGRES_USERNAME", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "password"),
        )
        if not self.state_manager.set_up(self.task):
            raise RuntimeError(f"MCPMark postgres state setup failed for {self.task.name}")

        self.instruction = self.task_manager.get_task_instruction(self.task)
        service_config = self.state_manager.get_service_config_for_agent()
        database_url = service_config.get("database_url")
        if not database_url:
            raise RuntimeError("MCPMark postgres state manager did not provide database_url")

        separate_postgres_mcp_command = self.mcpmark_root / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
        postgres_mcp_command = (
            separate_postgres_mcp_command
            if separate_postgres_mcp_command.exists()
            else Path(sys.executable).parent / "postgres-mcp"
        )
        command = os.getenv("MCPMARK_POSTGRES_MCP_COMMAND", str(postgres_mcp_command))
        args = os.getenv("MCPMARK_POSTGRES_MCP_ARGS")
        server_args = args.split() if args else ["--access-mode=unrestricted"]
        self.server = MCPStdioServer(
            command=command,
            args=server_args,
            env={"DATABASE_URI": database_url},
            timeout=int(os.getenv("MCPMARK_MCP_INIT_TIMEOUT", "60")),
        )
        self.loop.run_until_complete(self.server.__aenter__())
        self.messages = [{"role": "user", "content": self.instruction}]
        return self.observe()

    def observe(self) -> dict[str, Any]:
        self._require_started()
        observation = {
            "case_id": self.case_id,
            "official_task_path": self.case.official_task_path,
            "instruction": self.instruction,
        }
        if self.case.service == "filesystem":
            observation["test_directory"] = str(self.state_manager.get_test_directory())
        elif self.case.service == "postgres":
            service_config = self.state_manager.get_service_config_for_agent()
            observation["database"] = service_config.get("current_database") or service_config.get("database")
        return observation

    def tools(self) -> list[dict[str, Any]]:
        self._require_started()
        raw_tools = self.loop.run_until_complete(self.server.list_tools())
        return [_mcp_tool_to_openai_function(tool) for tool in raw_tools]

    def execute_tool(self, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_started()
        if self.case.service == "filesystem":
            tool_arguments = normalize_filesystem_tool_arguments(tool_arguments, self.filesystem_root)
        self.messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": tool_name, "arguments": tool_arguments}}],
            }
        )
        raw_result = self.loop.run_until_complete(self.server.call_tool(tool_name, tool_arguments))
        result = _jsonable(raw_result)
        self.messages.append({"role": "tool", "name": tool_name, "content": result})
        return result if isinstance(result, dict) else {"result": result}

    def score(self, final_content: str) -> dict[str, Any]:
        self._require_started()
        self.messages.append({"role": "assistant", "content": final_content})
        messages_path = self._write_messages()
        self.state_manager.set_verification_environment(str(messages_path))
        task_result = self.task_manager.execute_task(
            self.task,
            {
                "success": True,
                "output": self.messages,
                "turn_count": len([message for message in self.messages if message.get("role") == "assistant"]),
                "token_usage": {},
            },
        )
        grading_score = 1.0 if task_result.success else 0.0
        status = "scored_success" if task_result.success else "scored_failure"
        details = {
            "score_source": "mcpmark_official",
            "official_task_path": self.case.official_task_path,
            "mcpmark_task_name": task_result.task_name,
            "verification_error": task_result.verification_error,
            "verification_output": task_result.verification_output,
            "work_dir": str(self.work_root),
        }
        try:
            self.close()
        except Exception as exc:
            self.cleanup_error = str(exc) or type(exc).__name__
            details["cleanup_error"] = self.cleanup_error
        return {
            "status": status,
            "grading_score": grading_score,
            "analysis_score": grading_score,
            "min_score": 0.0,
            "max_score": 1.0,
            "reward": grading_score,
            "max_reward": 1.0,
            "details": details,
        }

    def close(self) -> dict[str, bool]:
        if self._closed:
            return {"closed": True}
        if self.server is not None:
            try:
                self.loop.run_until_complete(self.server.__aexit__(None, None, None))
            except Exception as exc:
                self.cleanup_error = str(exc) or type(exc).__name__
            finally:
                self.server = None
        if self.state_manager is not None and self.task is not None:
            self.state_manager.clean_up(self.task)
        if not self.loop.is_closed():
            self.loop.close()
        self._closed = True
        return {"closed": True}

    def _write_messages(self) -> Path:
        path = self.work_root / "messages.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"messages": self.messages}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _load_mcpmark_imports(self) -> None:
        root = str(self.mcpmark_root)
        if root not in sys.path:
            sys.path.insert(0, root)

    def _require_started(self) -> None:
        if self.case is None or self.case_id is None or self.task is None or self.state_manager is None or self.server is None:
            raise RuntimeError("MCPMark session has not been started")


MCPMarkFilesystemSession = MCPMarkSession


def _mcp_tool_to_openai_function(tool: dict[str, Any]) -> dict[str, Any]:
    name = str(tool.get("name") or "")
    description = str(tool.get("description") or "")
    parameters = tool.get("inputSchema") or tool.get("input_schema") or {"type": "object"}
    function: dict[str, Any] = {
        "name": name,
        "description": description,
        "parameters": parameters,
    }
    annotations = tool.get("annotations")
    if isinstance(annotations, dict):
        function["annotations"] = annotations
    return {"type": "function", "function": function}


def normalize_filesystem_tool_arguments(arguments: dict[str, Any], root: Path | None) -> dict[str, Any]:
    if root is None:
        return dict(arguments)
    normalized = dict(arguments)
    for key in ("path", "source", "destination"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = _normalize_filesystem_path(value, root)
    value = normalized.get("paths")
    if isinstance(value, list):
        normalized["paths"] = [
            _normalize_filesystem_path(item, root) if isinstance(item, str) else item
            for item in value
        ]
    return normalized


def _normalize_filesystem_path(value: str, root: Path) -> str:
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str((root / path).resolve())


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def handle_request(session: MCPMarkSession, request: dict[str, Any]) -> Any:
    command = request.get("command")
    if command == "start":
        case_config = request.get("case")
        if case_config is not None and not isinstance(case_config, dict):
            raise ValueError("case must be an object when provided")
        return session.start(str(request["case_id"]), case_config)
    if command == "tools":
        return session.tools()
    if command == "observe":
        return session.observe()
    if command == "execute_tool":
        arguments = request.get("tool_arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("tool_arguments must be an object")
        return session.execute_tool(str(request["tool_name"]), arguments)
    if command == "score":
        return session.score(str(request.get("final_content", "")))
    if command == "close":
        return session.close()
    raise ValueError(f"unknown MCPMark adapter command: {command!r}")


def serve(session: MCPMarkSession, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    for line in stdin:
        if not line.strip():
            continue
        request: dict[str, Any] | None = None
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = handle_request(session, request)
            response = {"ok": True, "result": result}
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            response = {"ok": False, "error_type": type(exc).__name__, "message": str(exc) or type(exc).__name__}
        stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        stdout.flush()
        if request is not None and request.get("command") == "close":
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCPMark course adapter")
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--mcpmark-root", required=True)
    parser.add_argument("--work-root")
    args = parser.parse_args(argv)

    work_root = Path(args.work_root) if args.work_root else None
    session = MCPMarkSession(Path(args.mcpmark_root), work_root)
    return serve(session)


if __name__ == "__main__":
    raise SystemExit(main())
