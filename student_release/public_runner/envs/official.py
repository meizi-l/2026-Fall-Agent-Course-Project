from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from public_runner.envs.base import BackendCaseResult, CaseScore, TaskEnvironment
from public_runner.envs.mcpmark_case_config import MCPMARK_ALLOWED_SERVICES, mcpmark_case_service, validate_mcpmark_task_files
from public_runner.jsonl_ipc import JSONLProcess


MCPMARK_FILESYSTEM_SERVER_PACKAGE = "@modelcontextprotocol/server-filesystem@2025.12.18"
MCPMARK_POSTGRES_MCP_PACKAGE = "postgres-mcp==0.3.0"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _student_release_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _course_project_root() -> Path:
    return _repo_root() / "course_project"


class OfficialUnavailableEnvironment(TaskEnvironment):
    def __init__(self, benchmark: str, case: dict[str, Any], setup_report: dict[str, Any]) -> None:
        super().__init__(benchmark, case)
        self.setup_report = setup_report

    def tools(self) -> list[dict[str, Any]]:
        return []

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": "official environment unavailable", "tool_name": name, "arguments": arguments}

    def run(self) -> BackendCaseResult:
        return BackendCaseResult(
            status="official_setup_error",
            reward=0.0,
            max_reward=1.0,
            grading_score=0.0,
            analysis_score=0.0,
            max_score=1.0,
            events=[
                {
                    "event": "error",
                    "error_type": "OfficialSetupError",
                    "message": self.setup_report["message"],
                    "setup_report": self.setup_report,
                }
            ],
        )


class OfficialMCPMarkEnvironment(TaskEnvironment):
    def __init__(self, case: dict[str, Any], setup_report: dict[str, Any] | None = None) -> None:
        TaskEnvironment.__init__(self, "mcpmark", case)
        self.setup_report = setup_report or _mcpmark_setup_report()
        self._client: _MCPMarkAdapterClient | None = None
        self._work_root: Path | None = None
        self._tools: list[dict[str, Any]] | None = None
        self._last_observation: dict[str, Any] | None = None

    def start(self) -> None:
        report = _mcpmark_setup_report()
        if report["missing"]:
            self.setup_report = report
            raise RuntimeError(report["message"])
        service = _mcpmark_case_service(self.case)
        if service not in MCPMARK_ALLOWED_SERVICES:
            raise RuntimeError(
                f"Unsupported MCPMark service {service!r}. "
                "The course release only enables filesystem and postgres."
            )
        if service == "postgres":
            postgres_report = _mcpmark_postgres_runtime_report(report)
            if postgres_report["missing"]:
                self.setup_report = postgres_report
                raise RuntimeError(postgres_report["message"])
            report = postgres_report
        self.setup_report = report
        work_parent = _student_release_root() / "trajectories" / ".adapter_work" / "mcpmark"
        work_parent.mkdir(parents=True, exist_ok=True)
        self._work_root = Path(
            tempfile.mkdtemp(
                prefix=f"course_mcpmark_{self.case.get('case_key', self.case_id)}_",
                dir=work_parent,
            )
        )
        self._client = _MCPMarkAdapterClient(
            python=Path(report["mcpmark_python"]),
            mcpmark_root=Path(report["mcpmark_repo"]),
            work_root=self._work_root,
            timeout=_limit_int(self.limits, "case_timeout_sec", int(os.getenv("MCPMARK_TIMEOUT", "300"))) + 30,
            env=_mcpmark_subprocess_env(report),
        )
        self._client.start()
        self._last_observation = self._client.send({"command": "start", "case_id": self.case_id, "case": self.case})
        self._started = True

    def observe(self) -> dict[str, Any]:
        self._require_client()
        self._last_observation = self._client.send({"command": "observe"})
        return dict(self._last_observation)

    def tools(self) -> list[dict[str, Any]]:
        self._require_client()
        if self._tools is None:
            self._tools = self._client.send({"command": "tools"})
        return list(self._tools)

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_client()
        result = self._client.send({"command": "execute_tool", "tool_name": name, "tool_arguments": arguments})
        self._tool_results.append({"tool_name": name, "result": result})
        return result

    def score(self, final_content: str) -> Any:
        self._require_client()
        result = self._client.send({"command": "score", "final_content": final_content})
        self._done = True
        return CaseScore(
            status=str(result["status"]),
            reward=float(result.get("reward", result.get("grading_score", 0.0))),
            max_reward=float(result.get("max_reward", result.get("max_score", 1.0))),
            details=dict(result.get("details", {})),
            grading_score=float(result.get("grading_score", result.get("reward", 0.0))),
            analysis_score=float(result.get("analysis_score", result.get("grading_score", result.get("reward", 0.0)))),
            max_score=float(result.get("max_score", result.get("max_reward", 1.0))),
            min_score=float(result.get("min_score", 0.0)),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _require_client(self) -> None:
        if self._client is None:
            raise RuntimeError("MCPMark environment has not been started")


class OfficialTau2AirlineEnvironment(OfficialUnavailableEnvironment):
    def __init__(self, case: dict[str, Any], setup_report: dict[str, Any] | None = None) -> None:
        super().__init__("tau2_airline", case, setup_report or _tau2_setup_report())

    def run(self) -> BackendCaseResult:
        report = _tau2_setup_report()
        if report["missing"]:
            self.setup_report = report
            return super().run()

        llm_env_error = _tau2_llm_env_error()
        if llm_env_error:
            return BackendCaseResult(
                status="official_setup_error",
                reward=0.0,
                max_reward=1.0,
                grading_score=0.0,
                analysis_score=0.0,
                max_score=1.0,
                events=[
                    {
                        "event": "error",
                        "error_type": "Tau2LLMEnvironmentError",
                        "message": llm_env_error,
                    }
                ],
            )

        tau_repo = Path(report["tau2_repo"])
        output_root = Path(tempfile.mkdtemp(prefix=f"course_tau2_{self.case_id}_"))
        agent_event_path = output_root / "course_agent_events.jsonl"
        command = _tau2_command(tau_repo, self.case_id, output_root, self.limits)
        events: list[dict[str, Any]] = [
            {
                "event": "official_command",
                "benchmark": self.benchmark,
                "case_id": self.case_id,
                "command": _redact_command(command),
                "cwd": str(tau_repo),
                "output_dir": str(output_root),
                "agent_trajectory_path": str(agent_event_path),
            }
        ]
        env = _tau2_subprocess_env(self.case_id)
        env["COURSE_TAU2_AGENT_TRAJECTORY"] = str(agent_event_path)
        completed = subprocess.run(
            command,
            cwd=tau_repo,
            env=env,
            text=True,
            capture_output=True,
            timeout=_limit_int(self.limits, "case_timeout_sec", int(os.getenv("TAU2_TIMEOUT", "300"))) + 30,
        )
        events.append(
            {
                "event": "official_process",
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
        )
        events.extend(_load_tau2_agent_events(agent_event_path))
        if completed.returncode != 0:
            events.append(
                {
                    "event": "error",
                    "error_type": "OfficialTau2ProcessError",
                    "message": f"tau2-bench exited with code {completed.returncode}",
                }
            )
            return BackendCaseResult(
                status="official_runtime_error",
                reward=0.0,
                max_reward=1.0,
                grading_score=0.0,
                analysis_score=0.0,
                max_score=1.0,
                events=events,
            )

        try:
            result_payload = _load_tau2_results(output_root)
            result_path = _find_results_json(output_root)
            reward = _extract_tau2_reward(result_payload)
        except Exception as exc:
            events.append(
                {
                    "event": "error",
                    "error_type": "OfficialTau2ResultError",
                    "message": str(exc),
                    "output_dir": str(output_root),
                }
            )
            return BackendCaseResult(
                status="official_runtime_error",
                reward=0.0,
                max_reward=1.0,
                grading_score=0.0,
                analysis_score=0.0,
                max_score=1.0,
                events=events,
            )
        score = CaseScore(
            status="scored_success" if reward >= 1.0 else "scored_failure",
            reward=reward,
            max_reward=1.0,
            grading_score=reward,
            analysis_score=reward,
            max_score=1.0,
            details={"score_source": "tau2_official"},
        )
        events.append({"event": "official_result", "result_path": str(result_path)})
        events.append(
            {
                "event": "score",
                **score.details,
                "grading_score": score.grading_score,
                "analysis_score": score.analysis_score,
                "max_score": score.max_score,
                "reward": score.reward,
                "max_reward": score.max_reward,
                "status": score.status,
            }
        )
        return BackendCaseResult(
            status=score.status,
            reward=score.reward,
            max_reward=score.max_reward,
            grading_score=score.grading_score,
            analysis_score=score.analysis_score,
            max_score=score.max_score,
            events=events,
        )


class OfficialDeepPlanningEnvironment(TaskEnvironment):
    def __init__(self, case: dict[str, Any], setup_report: dict[str, Any] | None = None) -> None:
        TaskEnvironment.__init__(self, "deepplanning", case)
        self.setup_report = setup_report or _deepplanning_setup_report()
        self._client: _DeepPlanningAdapterClient | None = None
        self._work_root: Path | None = None
        self._tools: list[dict[str, Any]] | None = None
        self._last_observation: dict[str, Any] | None = None

    def start(self) -> None:
        report = _deepplanning_setup_report()
        if report["missing"]:
            self.setup_report = report
            raise RuntimeError(report["message"])
        self.setup_report = report
        self._work_root = Path(tempfile.mkdtemp(prefix=f"course_deepplanning_{self.case.get('case_key', self.case_id)}_"))
        self._client = _DeepPlanningAdapterClient(
            python=Path(report["deepplanning_python"]),
            benchmark_root=Path(report["deepplanning_benchmark_root"]),
            work_root=self._work_root,
            timeout=_limit_int(self.limits, "case_timeout_sec", int(os.getenv("DEEPLANNING_TIMEOUT", "300"))) + 30,
        )
        self._client.start()
        self._last_observation = self._client.send({"command": "start", "case_id": self.case_id})
        self._started = True

    def observe(self) -> dict[str, Any]:
        self._require_client()
        self._last_observation = self._client.send({"command": "observe"})
        return dict(self._last_observation)

    def tools(self) -> list[dict[str, Any]]:
        self._require_client()
        if self._tools is None:
            self._tools = self._client.send({"command": "tools"})
        return list(self._tools)

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_client()
        result = self._client.send({"command": "execute_tool", "tool_name": name, "tool_arguments": arguments})
        self._tool_results.append({"tool_name": name, "result": result})
        return result

    def score(self, final_content: str) -> Any:
        self._require_client()
        result = self._client.send({"command": "score", "final_content": final_content})
        self._done = True
        return CaseScore(
            status=str(result["status"]),
            reward=float(result.get("reward", result.get("grading_score", 0.0))),
            max_reward=float(result.get("max_reward", result.get("max_score", 1.0))),
            details=dict(result.get("details", {})),
            grading_score=float(result.get("grading_score", result.get("reward", 0.0))),
            analysis_score=float(result.get("analysis_score", result.get("grading_score", result.get("reward", 0.0)))),
            max_score=float(result.get("max_score", result.get("max_reward", 1.0))),
            min_score=float(result.get("min_score", 0.0)),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _require_client(self) -> None:
        if self._client is None:
            raise RuntimeError("DeepPlanning environment has not been started")


class OfficialPublicBackend:
    name = "official"

    def setup_report(self) -> dict[str, Any]:
        root = _repo_root()
        course_root = _course_project_root()
        mcpmark_repo = _default_mcpmark_repo(root)
        checks = {
            "course_project": course_root,
            "third_party": course_root / "third_party",
            "student_release": course_root / "student_release",
            "staff_side": course_root / "staff_side",
            "tau2_repo": _default_tau2_repo(root),
            "mcpmark_repo": mcpmark_repo,
            "mcpmark_python": mcpmark_repo / ".venv-mcpmark" / "bin" / "python",
            "mcpmark_pipeline": mcpmark_repo / "pipeline.py",
            "deepplanning_repo": _default_deepplanning_repo(root),
        }
        found = {name: path.exists() for name, path in checks.items()}
        missing = [name for name, exists in found.items() if not exists]
        message = (
            "Official public benchmark backends are configured from course_project only. "
            "Run the setup scripts under course_project/third_party before using real official-public scoring."
        )
        return {
            "message": message,
            "repo_root": str(root),
            "course_project_root": str(course_root),
            "found": found,
            "missing": missing,
        }

    def create_environment(self, benchmark: str, case: dict[str, Any]) -> TaskEnvironment:
        report = self.setup_report()
        if benchmark == "mcpmark":
            mcpmark_report = _mcpmark_setup_report()
            try:
                service = _mcpmark_case_service(case)
            except ValueError as exc:
                unsupported_report = {
                    **mcpmark_report,
                    "message": str(exc),
                    "missing": ["mcpmark_public_case"],
                }
                return OfficialUnavailableEnvironment("mcpmark", case, unsupported_report)
            if mcpmark_report["missing"]:
                return OfficialUnavailableEnvironment("mcpmark", case, mcpmark_report)
            try:
                validate_mcpmark_task_files(Path(mcpmark_report["mcpmark_repo"]), case)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                return OfficialUnavailableEnvironment("mcpmark", case, {
                    **mcpmark_report, "message": str(exc), "missing": ["mcpmark_selected_task"],
                })
            if service == "postgres":
                postgres_report = _mcpmark_postgres_runtime_report(mcpmark_report)
                if postgres_report["missing"]:
                    return OfficialUnavailableEnvironment("mcpmark", case, postgres_report)
            return OfficialMCPMarkEnvironment(case, mcpmark_report)
        if benchmark == "tau2_airline":
            return OfficialTau2AirlineEnvironment(case)
        if benchmark == "deepplanning":
            deepplanning_report = _deepplanning_setup_report()
            if deepplanning_report["missing"]:
                return OfficialUnavailableEnvironment("deepplanning", case, deepplanning_report)
            return OfficialDeepPlanningEnvironment(case, deepplanning_report)
        raise ValueError(f"Unsupported benchmark: {benchmark}")


class _MCPMarkAdapterClient:
    def __init__(self, *, python: Path, mcpmark_root: Path, work_root: Path, timeout: int, env: dict[str, str]) -> None:
        self.python = python
        self.mcpmark_root = mcpmark_root
        self.work_root = work_root
        self.timeout = timeout
        self.env = env
        self._proc: JSONLProcess | None = None

    def start(self) -> None:
        entry = Path(__file__).with_name("mcpmark_jsonl_entry.py")
        self._proc = JSONLProcess(
            [
                str(self.python),
                str(entry),
                "serve",
                "--mcpmark-root",
                str(self.mcpmark_root),
                "--work-root",
                str(self.work_root),
            ],
            env=self.env, cwd=self.mcpmark_root, timeout=self.timeout,
        )

    def send(self, request: dict[str, Any]) -> Any:
        proc = self._require_proc()
        response = proc.send(request)
        if not response.get("ok"):
            raise RuntimeError(f"{response.get('error_type', 'MCPMarkAdapterError')}: {response.get('message', '')}")
        return response.get("result")

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.timeout = min(self.timeout, 5)
                self.send({"command": "close"})
        except Exception:
            pass
        proc.close()
        self._proc = None

    def _require_proc(self) -> JSONLProcess:
        if self._proc is None:
            raise RuntimeError("MCPMark adapter process has not been started")
        return self._proc


class _DeepPlanningAdapterClient:
    def __init__(self, *, python: Path, benchmark_root: Path, work_root: Path, timeout: int) -> None:
        self.python = python
        self.benchmark_root = benchmark_root
        self.work_root = work_root
        self.timeout = timeout
        self._proc: JSONLProcess | None = None

    def start(self) -> None:
        entry = Path(__file__).with_name("deepplanning_jsonl_entry.py")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self._proc = JSONLProcess(
            [
                str(self.python),
                str(entry),
                "serve",
                "--benchmark-root",
                str(self.benchmark_root),
                "--work-root",
                str(self.work_root),
            ],
            env=env, cwd=Path.cwd(), timeout=self.timeout,
        )

    def send(self, request: dict[str, Any]) -> Any:
        proc = self._require_proc()
        response = proc.send(request)
        if not response.get("ok"):
            raise RuntimeError(f"{response.get('error_type', 'DeepPlanningAdapterError')}: {response.get('message', '')}")
        return response.get("result")

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.timeout = min(self.timeout, 5)
                self.send({"command": "close"})
        except Exception:
            pass
        proc.close()
        self._proc = None

    def _require_proc(self) -> JSONLProcess:
        if self._proc is None:
            raise RuntimeError("DeepPlanning adapter process has not been started")
        return self._proc


def _default_tau2_repo(root: Path) -> Path:
    configured = os.getenv("TAU2_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    return root / "course_project" / "third_party" / "tau2-bench"


def _default_deepplanning_repo(root: Path) -> Path:
    configured = os.getenv("DEEPPLANNING_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    return root / "course_project" / "third_party" / "qwen-agent"


def _default_mcpmark_repo(root: Path) -> Path:
    configured = os.getenv("MCPMARK_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    return root / "course_project" / "third_party" / "mcpmark"


def _mcpmark_case_service(case: dict[str, Any]) -> str:
    service = mcpmark_case_service(case)
    if service not in MCPMARK_ALLOWED_SERVICES:
        raise ValueError(
            f"Unsupported MCPMark service {service!r}. "
            "The course release only enables filesystem and postgres."
        )
    return service


def _tau2_setup_report() -> dict[str, Any]:
    root = _repo_root()
    tau_repo = _default_tau2_repo(root)
    python = tau_repo / ".venv" / "bin" / "python"
    entry = Path(__file__).with_name("tau2_jsonl_entry.py")
    checks = {
        "tau2_repo": tau_repo,
        "tau2_pyproject": tau_repo / "pyproject.toml",
        "tau2_python": python,
        "tau2_jsonl_entry": entry,
    }
    found = {name: path.exists() for name, path in checks.items()}
    missing = [name for name, exists in found.items() if not exists]
    message = (
        "tau2-bench is configured for official public runs."
        if not missing
        else (
            "tau2-bench is not configured. Run `cd course_project && "
            "bash third_party/setup_tau2_bench.sh`, or set TAU2_REPO to a prepared tau2-bench checkout."
        )
    )
    return {
        "message": message,
        "repo_root": str(root),
        "tau2_repo": str(tau_repo),
        "found": found,
        "missing": missing,
    }


def _deepplanning_setup_report() -> dict[str, Any]:
    root = _repo_root()
    qwen_repo = _default_deepplanning_repo(root)
    python = qwen_repo / ".venv-deepplanning" / "bin" / "python"
    benchmark_root = qwen_repo / "benchmark" / "deepplanning" / "shoppingplanning"
    checks = {
        "deepplanning_repo": qwen_repo,
        "deepplanning_git": qwen_repo / ".git",
        "deepplanning_requirements": qwen_repo / "benchmark" / "deepplanning" / "requirements.txt",
        "deepplanning_python": python,
        "shopping_tool_schema": benchmark_root / "tools" / "shopping_tool_schema.json",
        "shopping_level_1_metadata": benchmark_root / "data" / "level_1_query_meta.json",
        "shopping_level_2_metadata": benchmark_root / "data" / "level_2_query_meta.json",
        "shopping_level_3_metadata": benchmark_root / "data" / "level_3_query_meta.json",
        "shopping_database_level1": benchmark_root / "database_level1",
        "shopping_database_level2": benchmark_root / "database_level2",
        "shopping_database_level3": benchmark_root / "database_level3",
    }
    found = {name: path.exists() for name, path in checks.items()}
    missing = [name for name, exists in found.items() if not exists]
    message = (
        "DeepPlanning Shopping is configured for official public runs."
        if not missing
        else (
            "DeepPlanning Shopping is not configured. Run `cd course_project && "
            "bash third_party/setup_deepplanning.sh`, download the Qwen/DeepPlanning "
            "Shopping database archives if needed, then run `bash third_party/setup_deepplanning.sh --check-only`."
        )
    )
    return {
        "message": message,
        "repo_root": str(root),
        "deepplanning_repo": str(qwen_repo),
        "deepplanning_python": str(python),
        "deepplanning_benchmark_root": str(benchmark_root),
        "found": found,
        "missing": missing,
    }


def _mcpmark_setup_report() -> dict[str, Any]:
    root = _repo_root()
    course_root = _course_project_root()
    mcpmark_repo = _default_mcpmark_repo(root)
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    entry = Path(__file__).with_name("mcpmark_jsonl_entry.py")
    local_node_bin = course_root / "third_party" / ".local" / "node20" / "bin"
    filesystem_server_js = (
        course_root
        / "third_party"
        / ".local"
        / "mcp-filesystem-server"
        / "node_modules"
        / "@modelcontextprotocol"
        / "server-filesystem"
        / "dist"
        / "index.js"
    )
    path_for_lookup = str(local_node_bin) + os.pathsep + os.environ.get("PATH", "")
    checks = {
        "mcpmark_repo": mcpmark_repo,
        "mcpmark_git": mcpmark_repo / ".git",
        "mcpmark_pyproject": mcpmark_repo / "pyproject.toml",
        "mcpmark_python": python,
        "mcpmark_pipeline": mcpmark_repo / "pipeline.py",
        "mcpmark_jsonl_entry": entry,
        "mcpmark_filesystem_tasks": mcpmark_repo / "tasks" / "filesystem",
        "mcpmark_postgres_tasks": mcpmark_repo / "tasks" / "postgres",
        "mcpmark_filesystem_server_js": filesystem_server_js,
    }
    found = {name: path.exists() for name, path in checks.items()}
    found["node"] = shutil.which("node", path=path_for_lookup) is not None
    missing = [name for name, exists in found.items() if not exists]
    message = (
        "MCPMark filesystem and postgres task metadata are configured for official public runs."
        if not missing
        else (
            "MCPMark is not configured. Run `cd course_project && "
            "bash third_party/setup_mcpmark.sh`, then "
            "`bash third_party/install_mcpmark_system_deps.sh --local-node --install`, "
            "and verify with `bash third_party/check_mcpmark_runtimes.sh filesystem`."
        )
    )
    return {
        "message": message,
        "repo_root": str(root),
        "mcpmark_repo": str(mcpmark_repo),
        "mcpmark_python": str(python),
        "filesystem_server_package": MCPMARK_FILESYSTEM_SERVER_PACKAGE,
        "postgres_mcp_package": MCPMARK_POSTGRES_MCP_PACKAGE,
        "local_node_bin": str(local_node_bin),
        "filesystem_server_js": str(filesystem_server_js),
        "found": found,
        "missing": missing,
    }


def _mcpmark_postgres_runtime_report(report: dict[str, Any]) -> dict[str, Any]:
    mcpmark_repo = Path(str(report.get("mcpmark_repo", "")))
    python_bin = Path(str(report.get("mcpmark_python", ""))).parent
    path_for_lookup = str(python_bin) + os.pathsep + os.environ.get("PATH", "")
    container_runtime_name = _mcpmark_container_runtime_name(path_for_lookup)
    container_runtime_ready = _mcpmark_container_runtime_ready(container_runtime_name, path_for_lookup)
    postgres_connection_ready = _mcpmark_postgres_connection_ready(path_for_lookup)
    postgres_mcp_command = mcpmark_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    runtime_found = {
        "mcpmark_postgres_container_runtime": container_runtime_name is not None,
        "mcpmark_postgres_container_runtime_name": container_runtime_name,
        "mcpmark_postgres_container_runtime_ready": container_runtime_ready,
        "mcpmark_postgres_database_connection": postgres_connection_ready,
        "mcpmark_postgres_psql": shutil.which("psql", path=path_for_lookup) is not None,
        "mcpmark_postgres_createdb": shutil.which("createdb", path=path_for_lookup) is not None,
        "mcpmark_postgres_pg_restore": shutil.which("pg_restore", path=path_for_lookup) is not None,
        "mcpmark_postgres_mcp_server": postgres_mcp_command.exists(),
    }
    missing = list(report.get("missing", [])) + [
        name
        for name, exists in runtime_found.items()
        if name != "mcpmark_postgres_container_runtime_name" and not exists
    ]
    message = (
        "MCPMark postgres is configured for official public runs."
        if not missing
        else (
            "MCPMark postgres is not configured. Install/start Docker or Podman, install PostgreSQL 17 client tools, "
            "and ensure a Postgres service is reachable at POSTGRES_HOST/POSTGRES_PORT. "
            "Run `cd course_project && bash third_party/setup_mcpmark.sh`, start the pinned Postgres container if needed, "
            "then verify with "
            "`bash third_party/check_mcpmark_runtimes.sh postgres`."
        )
    )
    return {
        **report,
        "postgres_mcp_command": str(postgres_mcp_command),
        "message": message,
        "found": {**dict(report.get("found", {})), **runtime_found},
        "missing": missing,
    }


def _mcpmark_container_runtime_name(path_for_lookup: str) -> str | None:
    override = os.environ.get("MCPMARK_CONTAINER_RUNTIME")
    if override:
        if override not in {"docker", "podman"}:
            return None
        return override if shutil.which(override, path=path_for_lookup) is not None else None
    for runtime in ("docker", "podman"):
        if shutil.which(runtime, path=path_for_lookup) is not None:
            return runtime
    return None


def _mcpmark_container_runtime_ready(runtime_name: str | None, path_for_lookup: str) -> bool:
    if runtime_name is None:
        return False
    runtime_path = shutil.which(runtime_name, path=path_for_lookup)
    if runtime_path is None:
        return False
    try:
        completed = subprocess.run(
            [runtime_path, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _mcpmark_postgres_connection_ready(path_for_lookup: str) -> bool:
    psql = shutil.which("psql", path=path_for_lookup)
    if psql is None:
        return False
    env = os.environ.copy()
    env.setdefault("PGPASSWORD", os.getenv("POSTGRES_PASSWORD", "password"))
    command = [
        psql,
        "-h",
        os.getenv("POSTGRES_HOST", "localhost"),
        "-p",
        os.getenv("POSTGRES_PORT", "5432"),
        "-U",
        os.getenv("POSTGRES_USERNAME", "postgres"),
        "-d",
        os.getenv("POSTGRES_DATABASE", "postgres"),
        "-w",
        "-c",
        "select 1",
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _mcpmark_subprocess_env(report: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    local_node_bin = Path(str(report.get("local_node_bin", "")))
    mcpmark_python_bin = Path(str(report.get("mcpmark_python", ""))).parent
    path_parts = []
    if mcpmark_python_bin.exists():
        path_parts.append(str(mcpmark_python_bin))
    if local_node_bin.exists():
        path_parts.append(str(local_node_bin))
    if path_parts:
        env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])
    env["PYTHONUNBUFFERED"] = "1"
    env["MCPMARK_REPO"] = str(report.get("mcpmark_repo", ""))
    env["FILESYSTEM_SERVER_PACKAGE"] = MCPMARK_FILESYSTEM_SERVER_PACKAGE
    env["MCPMARK_FILESYSTEM_SERVER_JS"] = str(report.get("filesystem_server_js", ""))
    env["MCPMARK_POSTGRES_MCP_PACKAGE"] = MCPMARK_POSTGRES_MCP_PACKAGE
    postgres_mcp_command = Path(str(report.get("postgres_mcp_command", "")))
    if postgres_mcp_command.exists():
        env.setdefault("MCPMARK_POSTGRES_MCP_COMMAND", str(postgres_mcp_command))
    env.setdefault("POSTGRES_HOST", "localhost")
    env.setdefault("POSTGRES_PORT", "5432")
    env.setdefault("POSTGRES_DATABASE", "postgres")
    env.setdefault("POSTGRES_USERNAME", "postgres")
    env.setdefault("POSTGRES_PASSWORD", "password")
    return env


def _tau2_command(tau_repo: Path, case_id: str, output_root: Path, limits: dict[str, Any] | None = None) -> list[str]:
    limits = limits or {}
    python = tau_repo / ".venv" / "bin" / "python"
    entry = Path(__file__).with_name("tau2_jsonl_entry.py")
    timeout = _limit_int(limits, "case_timeout_sec", int(os.getenv("TAU2_TIMEOUT", "300")))
    agent_args = {
        "student_root": str(_student_release_root()),
        "python": str(_student_release_root() / ".venv" / "bin" / "python") if os.getenv("COURSE_AGENT_PROCESS_COMMAND") else sys.executable,
        "timeout": _limit_int(limits, "case_timeout_sec", int(os.getenv("COURSE_AGENT_PROCESS_TIMEOUT_SEC", "300"))),
        "limits": limits,
    }
    user_llm_args = _json_env("TAU2_USER_LLM_ARGS", {"temperature": 0.0, "timeout": 300})
    return [
        str(python),
        str(entry),
        "run",
        "--domain",
        "airline",
        "--task-ids",
        str(case_id),
        "--num-trials",
        "1",
        "--agent",
        "student_jsonl_agent",
        "--agent-llm",
        "unused",
        "--agent-llm-args",
        json.dumps(agent_args, sort_keys=True),
        "--user",
        os.getenv("TAU2_USER", "user_simulator"),
        "--user-llm",
        os.getenv("TAU2_USER_MODEL", "azure/gpt-4o-mini"),
        "--user-llm-args",
        json.dumps(user_llm_args, sort_keys=True),
        "--max-steps",
        str(_limit_int(limits, "max_environment_steps", int(os.getenv("TAU2_MAX_STEPS", "40")))),
        "--max-concurrency",
        "1",
        "--timeout",
        str(timeout),
        "--save-to",
        str(output_root),
        "--verbose-logs",
        "--llm-log-mode",
        "all",
        "--log-level",
        "INFO",
    ]


def _limit_int(limits: dict[str, Any], name: str, default: int) -> int:
    value = limits.get(name)
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _tau2_subprocess_env(case_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["TAU2_CURRENT_TASK_ID"] = case_id
    course_key = os.getenv("COURSE_API_KEY")
    if course_key:
        env["AZURE_OPENAI_API_KEY"] = course_key
        env["OPENAI_API_KEY"] = course_key
        env["AZURE_API_KEY"] = course_key
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        env["AZURE_API_BASE"] = azure_endpoint
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    if azure_api_version:
        env["AZURE_API_VERSION"] = azure_api_version
    return env


def _load_tau2_agent_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                events.append(
                    {
                        "event": "error",
                        "error_type": "Tau2AgentTrajectoryParseError",
                        "message": str(exc),
                        "path": str(path),
                    }
                )
                continue
            if isinstance(event, dict):
                events.append(event)
    return [
        {
            "event": "tau2_agent_trajectory",
            "path": str(path),
            "agent_event_count": len(events),
        },
        *events,
    ]


def _tau2_llm_env_error() -> str:
    missing: list[str] = []
    placeholders: list[str] = []
    required = {
        "COURSE_API_KEY": os.getenv("COURSE_API_KEY"),
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_API_VERSION": os.getenv("AZURE_OPENAI_API_VERSION"),
    }
    for name, value in required.items():
        if not value:
            missing.append(name)
        elif _looks_like_placeholder(value):
            placeholders.append(name)
    if not missing and not placeholders:
        return ""
    parts = []
    if missing:
        parts.append(f"missing {', '.join(missing)}")
    if placeholders:
        parts.append(f"placeholder values for {', '.join(placeholders)}")
    details = "; ".join(parts)
    return (
        f"tau2 official runs require LLM configuration from env.student.local.sh: {details}. "
        "Copy env.student.sh.example to env.student.local.sh, fill COURSE_API_KEY, "
        "AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_API_VERSION, then source env.student.local.sh."
    )


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        not lowered
        or "replace-with" in lowered
        or "your-" in lowered
        or "example.openai.azure.com" in lowered
    )


def _redact_command(command: list[str]) -> list[str]:
    redacted = list(command)
    for flag in ("--user-llm-args", "--agent-llm-args"):
        if flag not in redacted:
            continue
        index = redacted.index(flag) + 1
        if index >= len(redacted):
            continue
        try:
            payload = json.loads(redacted[index])
        except json.JSONDecodeError:
            redacted[index] = "<redacted-json>"
            continue
        if isinstance(payload, dict):
            redacted[index] = json.dumps(_redact_mapping(payload), sort_keys=True)
        else:
            redacted[index] = "<redacted-json>"
    return redacted


def _redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    secret_terms = ("key", "token", "secret", "password")
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if any(term in key.lower() for term in secret_terms):
            clean[key] = "<redacted>"
        elif isinstance(value, dict):
            clean[key] = _redact_mapping(value)
        else:
            clean[key] = value
    return clean


def _json_env(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _find_results_json(output_root: Path) -> Path:
    direct = output_root / "results.json"
    if direct.exists():
        return direct
    matches = sorted(output_root.rglob("results.json"))
    if not matches:
        raise RuntimeError(f"tau2-bench did not write results.json under {output_root}")
    return matches[0]


def _load_tau2_results(output_root: Path) -> Any:
    return json.loads(_find_results_json(output_root).read_text())


def _extract_tau2_reward(payload: Any) -> float:
    simulation = _first_simulation(payload)
    if isinstance(simulation, dict):
        reward_info = simulation.get("reward_info")
        if isinstance(reward_info, dict) and isinstance(reward_info.get("reward"), (int, float)):
            return float(reward_info["reward"])
        if isinstance(simulation.get("reward"), (int, float)):
            return float(simulation["reward"])
    if isinstance(payload, dict) and isinstance(payload.get("reward"), (int, float)):
        return float(payload["reward"])
    raise RuntimeError("tau2-bench results did not contain a numeric reward")


def _first_simulation(payload: Any) -> Any:
    if isinstance(payload, dict):
        simulations = payload.get("simulations")
        if isinstance(simulations, list) and simulations:
            return simulations[0]
        results = payload.get("results")
        if isinstance(results, list) and results:
            return results[0]
    if isinstance(payload, list) and payload:
        return payload[0]
    return payload
