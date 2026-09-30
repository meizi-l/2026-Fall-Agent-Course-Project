from __future__ import annotations

import argparse
import contextlib
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import uuid


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from course_agent.protocol import AgentResponse
from course_agent.util import append_jsonl, make_run_id, safe_case_id, utc_now_iso, write_json
from public_runner.envs.base import BackendCaseResult, TaskEnvironment
from public_runner.envs.official import OfficialPublicBackend
from public_runner.envs.simplified import SimplifiedBackend
from public_runner.envs.tool_policy import (
    ToolCall,
    ToolCallPolicyError,
    should_stop_after_tool_error,
    terminal_tool_names_for_benchmark,
    validate_tool_batch,
)
from public_runner.jsonl_ipc import JSONLProcess
from public_runner.student_launcher import student_process_launch


class AgentProcessClient:
    def __init__(self) -> None:
        python = str(ROOT / ".venv" / "bin" / "python") if os.getenv("COURSE_AGENT_PROCESS_COMMAND") else sys.executable
        command, env = student_process_launch(ROOT, python)
        self._proc = JSONLProcess(
            command,
            cwd=ROOT, timeout=300, env=env,
        )

    def send(self, request: dict[str, Any]) -> AgentResponse:
        self._proc.timeout = _positive_int(request.get("limits", {}).get("case_timeout_sec"), 300)
        return AgentResponse.from_dict(self._proc.send(request))

    def close(self) -> None:
        self._proc.close()


def _load_assignment(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _case_key(case: dict[str, Any]) -> str:
    return str(case.get("case_key") or safe_case_id(str(case["case_id"])))


def _case_metadata_item(benchmark: str, case: dict[str, Any]) -> dict[str, str]:
    return {
        "benchmark": benchmark,
        "case_id": str(case["case_id"]),
        "case_key": _case_key(case),
    }


def _all_enabled_cases(assignment: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for benchmark, config in assignment["benchmarks"].items():
        if not config.get("enabled", False):
            continue
        for case in config.get("cases", []):
            selected.append({"benchmark": benchmark, "case": case})
    return selected


def _parse_case_selector(selector: str) -> tuple[str, str]:
    if ":" not in selector:
        raise ValueError(f"case selector must be benchmark:case_key, got {selector!r}")
    benchmark, case_selector = selector.split(":", 1)
    if not benchmark or not case_selector:
        raise ValueError(f"case selector must be benchmark:case_key, got {selector!r}")
    return benchmark, case_selector


def _selected_cases(
    assignment: dict[str, Any],
    benchmarks: set[str],
    case_ids: set[str],
    case_selectors: list[str],
) -> list[dict[str, Any]]:
    enabled_benchmarks = {
        benchmark
        for benchmark, config in assignment["benchmarks"].items()
        if config.get("enabled", False)
    }
    unknown_benchmarks = sorted(benchmarks - enabled_benchmarks)
    if unknown_benchmarks:
        raise ValueError(f"unknown benchmark(s): {', '.join(unknown_benchmarks)}")
    if case_selectors and (benchmarks or case_ids):
        raise ValueError("--case cannot be combined with --benchmark or --case-id")
    if case_ids and len(benchmarks) != 1:
        raise ValueError("--case-id can only be used with exactly one --benchmark; use --case benchmark:case_key instead")

    all_cases = _all_enabled_cases(assignment)
    if case_selectors:
        cases_by_selector: dict[tuple[str, str], dict[str, Any]] = {}
        for item in all_cases:
            benchmark = item["benchmark"]
            case = item["case"]
            cases_by_selector[(benchmark, _case_key(case))] = item
            cases_by_selector[(benchmark, str(case["case_id"]))] = item

        selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        missing: list[str] = []
        for raw_selector in case_selectors:
            benchmark, case_selector = _parse_case_selector(raw_selector)
            item = cases_by_selector.get((benchmark, case_selector))
            if item is None:
                missing.append(raw_selector)
                continue
            key = (item["benchmark"], str(item["case"]["case_id"]))
            if key not in seen:
                selected.append(item)
                seen.add(key)
        if missing:
            raise ValueError(f"unknown case selector(s): {', '.join(missing)}")
        return selected

    selected: list[dict[str, Any]] = []
    for item in all_cases:
        benchmark = item["benchmark"]
        case = item["case"]
        if benchmarks and benchmark not in benchmarks:
            continue
        case_id = str(case["case_id"])
        if case_ids and case_id not in case_ids:
            continue
        selected.append(item)
    if case_ids:
        matched_case_ids = {str(item["case"]["case_id"]) for item in selected}
        missing_case_ids = sorted(case_ids - matched_case_ids)
        if missing_case_ids:
            benchmark = next(iter(benchmarks))
            raise ValueError(f"unknown case id(s) for {benchmark}: {', '.join(missing_case_ids)}")
    return selected


def _selected_cases_from_metadata(assignment: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    cases_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for benchmark, config in assignment["benchmarks"].items():
        for case in config.get("cases", []):
            cases_by_key[(benchmark, str(case["case_id"]))] = case

    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in metadata.get("selected_cases", []):
        benchmark = item["benchmark"]
        case_id = str(item["case_id"])
        case = cases_by_key.get((benchmark, case_id))
        if case is None:
            missing.append(f"{benchmark}:{case_id}")
            continue
        selected.append({"benchmark": benchmark, "case": case})
    if missing:
        raise RuntimeError(f"resume metadata references cases not found in assignment: {', '.join(missing)}")
    return selected


def _latest_case_results(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for result in _load_jsonl(path):
        results[(result["benchmark"], str(result["case_id"]))] = result
    return results


def _case_result_history(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    history: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for result in _load_jsonl(path):
        history.setdefault((result["benchmark"], str(result["case_id"])), []).append(result)
    return history


def _is_retryable_result(result: dict[str, Any] | None) -> bool:
    if result is None:
        return True
    status = str(result.get("status", ""))
    return status.endswith("_error") and _positive_int(result.get("attempt"), 1) < 2


def _next_attempt(result: dict[str, Any] | None) -> int:
    if result is None:
        return 1
    return _positive_int(result.get("attempt"), 1) + 1


def _trajectory_relative_path(benchmark: str, case_short_name: str, attempt: int) -> Path:
    filename = "trajectory.jsonl" if attempt == 1 else f"attempt_{attempt}.jsonl"
    return Path("cases") / benchmark / safe_case_id(case_short_name) / filename


def _llm_usage_relative_path(trajectory_relative_path: Path) -> Path:
    return trajectory_relative_path.with_name(f"{trajectory_relative_path.stem}_llm_usage.jsonl")


@contextlib.contextmanager
def _temporary_env(updates: dict[str, str]):
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_llm_usage_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            events.append(
                {
                    "event": "error",
                    "error_type": "LLMUsageParseError",
                    "message": str(exc),
                    "path": str(path),
                }
            )
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _int_usage_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _llm_usage_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "llm_api_call_count": 0,
        "llm_successful_call_count": 0,
        "llm_failed_call_count": 0,
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "llm_total_tokens": 0,
        "llm_estimated_input_tokens": 0,
    }
    for event in events:
        if event.get("event") != "llm_call":
            continue
        summary["llm_api_call_count"] += 1
        status = event.get("status")
        if status == "success":
            summary["llm_successful_call_count"] += 1
        elif status == "error":
            summary["llm_failed_call_count"] += 1
        summary["llm_estimated_input_tokens"] += _int_usage_value(event.get("estimated_input_tokens"))
        usage = event.get("usage")
        if isinstance(usage, dict):
            summary["llm_prompt_tokens"] += _int_usage_value(usage.get("prompt_tokens"))
            summary["llm_completion_tokens"] += _int_usage_value(usage.get("completion_tokens"))
            summary["llm_total_tokens"] += _int_usage_value(usage.get("total_tokens"))
    return summary


def _sum_llm_usage(results: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "llm_api_call_count",
        "llm_successful_call_count",
        "llm_failed_call_count",
        "llm_prompt_tokens",
        "llm_completion_tokens",
        "llm_total_tokens",
        "llm_estimated_input_tokens",
    )
    return {key: sum(_int_usage_value(result.get(key)) for result in results) for key in keys}


def _status_issue_category(status: str) -> str:
    if status == "scored_success":
        return "none"
    if status == "scored_failure":
        return "agent_performance"
    if status == "official_setup_error":
        return "official_setup"
    if status == "official_runtime_error":
        return "official_runtime"
    if status == "student_runtime_error":
        return "student_runtime"
    if status == "runner_error":
        return "runner"
    if status.endswith("_error"):
        return "runtime"
    return "unknown"


def _latest_event(events: list[dict[str, Any]], event_name: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == event_name:
            return event
    return None


def _case_analysis_entry(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status", ""))
    trajectory_path = str(result.get("trajectory_path", ""))
    trajectory_events = _load_jsonl(run_dir / trajectory_path) if trajectory_path else []
    error_event = _latest_event(trajectory_events, "error")
    score_event = _latest_event(trajectory_events, "score")
    issue_category = _status_issue_category(status)
    runtime_issue = status.endswith("_error")
    issue_type: str | None = None
    issue_message: str | None = None

    if error_event is not None:
        issue_type = str(error_event.get("error_type") or status)
        issue_message = str(error_event.get("message") or "")
    elif status == "scored_failure":
        issue_type = "agent_or_task_failure"
        issue_message = "Case completed but did not reach full grading score."

    entry: dict[str, Any] = {
        "case_key": result.get("case_key"),
        "status": status,
        "analysis_score": result.get("analysis_score", result.get("grading_score", result.get("reward", 0.0))),
        "grading_score": result.get("grading_score", result.get("reward", 0.0)),
        "max_score": result.get("max_score", result.get("max_reward", 1.0)),
        "reward": result.get("reward", result.get("grading_score", 0.0)),
        "max_reward": result.get("max_reward", result.get("max_score", 1.0)),
        "runtime_issue": runtime_issue,
        "issue_category": issue_category,
        "issue_type": issue_type,
        "issue_message": issue_message,
        "trajectory_path": trajectory_path,
        "attempt": result.get("attempt", 1),
        "auto_resumed": bool(result.get("auto_resumed", False)),
        "started_at": result.get("started_at"),
        "completed_at": result.get("completed_at"),
        "llm_api_call_count": result.get("llm_api_call_count", 0),
        "llm_successful_call_count": result.get("llm_successful_call_count", 0),
        "llm_failed_call_count": result.get("llm_failed_call_count", 0),
        "llm_prompt_tokens": result.get("llm_prompt_tokens", 0),
        "llm_completion_tokens": result.get("llm_completion_tokens", 0),
        "llm_total_tokens": result.get("llm_total_tokens", 0),
        "llm_estimated_input_tokens": result.get("llm_estimated_input_tokens", 0),
    }
    if "previous_status" in result:
        entry["previous_status"] = result["previous_status"]
    if "llm_usage_path" in result:
        entry["llm_usage_path"] = result["llm_usage_path"]
    if score_event is not None:
        detail_keys = (
            "score_source",
            "matched_count",
            "expected_count",
            "extra_products_count",
            "verification_error",
            "mcpmark_task_name",
            "official_task_path",
            "raw_grading_score",
            "raw_analysis_score",
            "raw_min_score",
            "raw_max_score",
        )
        score_details = {key: score_event[key] for key in detail_keys if key in score_event}
        if score_details:
            entry["score_details"] = score_details
    if error_event is not None and "setup_report" in error_event:
        setup_report = error_event["setup_report"]
        if isinstance(setup_report, dict):
            entry["runtime_details"] = {
                "missing": setup_report.get("missing", []),
                "found": setup_report.get("found", {}),
            }
    return entry


def _case_analysis_document(
    *,
    run_id: str,
    backend_name: str,
    summary_results: list[dict[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    benchmarks: dict[str, dict[str, Any]] = {}
    for result in summary_results:
        benchmark = str(result["benchmark"])
        case_id = str(result["case_id"])
        benchmarks.setdefault(benchmark, {})[case_id] = _case_analysis_entry(run_dir, result)
    return {
        "run_id": run_id,
        "backend": backend_name,
        "generated_at": utc_now_iso(),
        "benchmarks": benchmarks,
    }


def _matching_auto_resume_run(
    output_root: Path,
    *,
    assignment: dict[str, Any],
    assignment_path: Path,
    backend_name: str,
    filters: dict[str, Any],
    selected: list[dict[str, Any]],
) -> Path | None:
    if not output_root.exists():
        return None
    expected_selected = [_case_metadata_item(item["benchmark"], item["case"]) for item in selected]
    candidates: list[Path] = []
    for child in output_root.iterdir():
        metadata_path = child / "run_metadata.json"
        if not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("assignment_id") != assignment.get("assignment_id"):
            continue
        if metadata.get("backend") != backend_name:
            continue
        if metadata.get("split") != assignment.get("split"):
            continue
        if metadata.get("filters") != filters:
            continue
        recorded_assignment_path = Path(str(metadata.get("assignment_path", "")))
        if not recorded_assignment_path.is_absolute():
            recorded_assignment_path = ROOT / recorded_assignment_path
        if recorded_assignment_path != assignment_path:
            continue
        if metadata.get("selected_cases") != expected_selected:
            continue
        history = _case_result_history(child / "case_results.jsonl")
        if any(_is_retryable_result(history.get((item["benchmark"], str(item["case"]["case_id"])), [None])[-1]) for item in selected):
            candidates.append(child)
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def _case_limits(assignment: dict[str, Any], benchmark: str) -> dict[str, Any]:
    raw_limits = assignment.get("limits", {})
    if not isinstance(raw_limits, dict):
        return {}
    limits = {key: value for key, value in raw_limits.items() if key != "benchmarks"}
    benchmark_limits = raw_limits.get("benchmarks", {}).get(benchmark, {})
    if isinstance(benchmark_limits, dict):
        limits.update(benchmark_limits)
    return limits


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _max_agent_turns(limits: dict[str, Any]) -> int:
    return _positive_int(limits.get("max_agent_turns", limits.get("max_model_calls")), 20)


def _default_max_workers(backend_name: str, selected: list[dict[str, Any]]) -> int:
    del selected
    if backend_name == "official":
        return 1
    return 4


def _case_attempt_requires_resource_lock(backend_name: str, benchmark: str) -> bool:
    return backend_name == "official" and benchmark == "mcpmark"


def _case_attempt_resource_lock_path(backend_name: str, benchmark: str) -> Path:
    lock_root = Path(os.getenv("COURSE_RUNNER_LOCK_DIR", tempfile.gettempdir())) / "comp5211_public_runner_locks"
    return lock_root / f"{backend_name}_{benchmark}.lock"


@contextlib.contextmanager
def _case_attempt_resource_lock(*, backend_name: str, benchmark: str, run_dir: Path):
    del run_dir
    if not _case_attempt_requires_resource_lock(backend_name, benchmark):
        yield
        return

    try:
        import fcntl
    except ImportError:
        yield
        return

    lock_path = _case_attempt_resource_lock_path(backend_name, benchmark)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _backend_by_name(name: str) -> SimplifiedBackend | OfficialPublicBackend:
    if name == "simplified":
        return SimplifiedBackend()
    if name == "official":
        return OfficialPublicBackend()
    raise ValueError(f"Unsupported backend: {name}")


def _response_tool_calls(response: AgentResponse) -> list[ToolCall]:
    if response.kind == "tool_call":
        return [ToolCall(response.tool_name or "", response.tool_arguments)]
    if response.kind == "tool_calls":
        return [ToolCall(str(call["tool_name"]), dict(call.get("tool_arguments", {}))) for call in response.tool_call_list]
    return []


def _score_event(score: Any) -> dict[str, Any]:
    grading_score = float(getattr(score, "grading_score", getattr(score, "reward", 0.0)))
    analysis_score = float(getattr(score, "analysis_score", grading_score))
    max_score = float(getattr(score, "max_score", getattr(score, "max_reward", 1.0)))
    min_score = float(getattr(score, "min_score", 0.0))
    reward = float(getattr(score, "reward", grading_score))
    max_reward = float(getattr(score, "max_reward", max_score))
    details = dict(getattr(score, "details", {}) or {})
    return {
        "event": "score",
        **details,
        "grading_score": grading_score,
        "analysis_score": analysis_score,
        "min_score": min_score,
        "max_score": max_score,
        "reward": reward,
        "max_reward": max_reward,
    }


def _run_environment_case(
    env: TaskEnvironment,
    assignment: dict[str, Any],
    run_id: str,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> BackendCaseResult:
    original_cwd = Path.cwd()
    events: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        events.append(event)
        if event_sink is not None:
            event_sink(event)

    limits = _case_limits(assignment, env.benchmark)
    env.configure_limits(limits)

    if hasattr(env, "run"):
        runner = getattr(env, "run")
        if callable(runner):
            try:
                result = runner()
            finally:
                try:
                    env.close()
                finally:
                    os.chdir(original_cwd)
            for event in result.events:
                emit(event)
            return BackendCaseResult(
                status=result.status,
                reward=result.reward,
                max_reward=result.max_reward,
                grading_score=result.grading_score,
                analysis_score=result.analysis_score,
                max_score=result.max_score,
                events=events,
            )

    client = AgentProcessClient()
    try:
        env.start()
        max_turns = _max_agent_turns(limits)
        runner_tool_results: list[dict[str, Any]] = []
        for step in range(max_turns):
            observation = env.observe()
            observation["tool_results"] = list(runner_tool_results)
            tools = env.tools()
            request = {
                "request_id": uuid.uuid4().hex,
                "context_id": f"{run_id}-{env.benchmark}-{safe_case_id(env.case_id)}",
                "benchmark": env.benchmark,
                "case_id": env.case_id,
                "step": step,
                "text": env.case.get("description", "Public local case."),
                "observation": observation,
                "tools": tools,
                "limits": limits,
            }
            emit({"event": "request", "request": request})
            response = client.send(request)
            response_data = response.to_dict()
            emit({"event": "response", "response": response_data})
            if response.kind == "error":
                emit({"event": "error", "error_type": response.error_type, "message": response.message})
                return BackendCaseResult(status="student_runtime_error", reward=0.0, max_reward=1.0, events=events)
            if response.kind in {"tool_call", "tool_calls"}:
                tool_calls = _response_tool_calls(response)
                try:
                    validate_tool_batch(
                        benchmark=env.benchmark,
                        calls=tool_calls,
                        available_tools=tools,
                        limits=limits,
                        terminal_tool_names=terminal_tool_names_for_benchmark(env.benchmark),
                    )
                except ToolCallPolicyError as exc:
                    emit({"event": "error", "error_type": exc.error_type, "message": exc.message})
                    return BackendCaseResult(status="student_runtime_error", reward=0.0, max_reward=1.0, events=events)
                for index, call in enumerate(tool_calls):
                    try:
                        tool_result = env.execute_tool(call.tool_name, call.tool_arguments)
                        if env.benchmark == "mcpmark" and isinstance(tool_result, dict) and tool_result.get("isError") is True:
                            raise RuntimeError(f"MCP tool returned isError: {json.dumps(tool_result, ensure_ascii=False)}")
                    except Exception as exc:
                        indexed_result = {
                            "index": index,
                            "tool_name": call.tool_name,
                            "tool_arguments": call.tool_arguments,
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                        runner_tool_results.append(indexed_result)
                        emit({"event": "tool_result", **indexed_result})
                        if should_stop_after_tool_error(
                            benchmark=env.benchmark,
                            failed_call=call,
                            remaining_calls=tool_calls[index + 1 :],
                            available_tools=tools,
                        ):
                            for skipped_index, skipped_call in enumerate(tool_calls[index + 1 :], start=index + 1):
                                skipped_result = {
                                    "index": skipped_index,
                                    "tool_name": skipped_call.tool_name,
                                    "tool_arguments": skipped_call.tool_arguments,
                                    "ok": False,
                                    "skipped": True,
                                    "reason": "skipped_after_tool_error",
                                }
                                runner_tool_results.append(skipped_result)
                                emit({"event": "tool_result", **skipped_result})
                            break
                        continue
                    indexed_result = {
                        "index": index,
                        "tool_name": call.tool_name,
                        "tool_arguments": call.tool_arguments,
                        "ok": True,
                        "result": tool_result,
                    }
                    runner_tool_results.append(indexed_result)
                    emit({"event": "tool_result", **indexed_result})
                    if env.done:
                        score = env.score("")
                        emit(_score_event(score))
                        return BackendCaseResult(
                            status=score.status,
                            reward=score.reward,
                            max_reward=score.max_reward,
                            grading_score=score.grading_score,
                            analysis_score=score.analysis_score,
                            max_score=score.max_score,
                            events=events,
                        )
                continue
            if response.kind == "final":
                score = env.score(response.content)
                emit(_score_event(score))
                return BackendCaseResult(
                    status=score.status,
                    reward=score.reward,
                    max_reward=score.max_reward,
                    grading_score=score.grading_score,
                    analysis_score=score.analysis_score,
                    max_score=score.max_score,
                    events=events,
                )
        emit({"event": "error", "error_type": "TurnLimitExceeded", "message": f"runner exceeded {max_turns} agent turns"})
        return BackendCaseResult(status="student_runtime_error", reward=0.0, max_reward=1.0, events=events)
    finally:
        try:
            env.close()
        finally:
            try:
                client.close()
            finally:
                os.chdir(original_cwd)


@contextlib.contextmanager
def _case_deadline(seconds: int):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("case deadline requires a main-thread case worker")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def on_timeout(_signum, _frame):
        raise TimeoutError(f"case exceeded {seconds} seconds")

    signal.signal(signal.SIGALRM, on_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, previous_timer[0] - (time.monotonic() - started)), previous_timer[1])


def _run_case_attempt(
    *,
    backend_name: str,
    item: dict[str, Any],
    assignment: dict[str, Any],
    run_id: str,
    started_at: str,
    run_dir: str,
    attempt: int,
    auto_resumed: bool,
    previous_status: str | None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    benchmark = item["benchmark"]
    case = item["case"]
    case_id = str(case["case_id"])
    case_short_name = _case_key(case)
    trajectory_relative_path = _trajectory_relative_path(benchmark, case_short_name, attempt)
    trajectory_path = run_path / trajectory_relative_path
    llm_usage_relative_path = _llm_usage_relative_path(trajectory_relative_path)
    llm_usage_path = run_path / llm_usage_relative_path
    backend = _backend_by_name(backend_name)

    def record_event(event: dict[str, Any]) -> None:
        append_jsonl(trajectory_path, {"time": utc_now_iso(), **event})

    try:
        with _temporary_env({"COURSE_LLM_USAGE_PATH": str(llm_usage_path)}):
            with _case_attempt_resource_lock(backend_name=backend_name, benchmark=benchmark, run_dir=run_path):
                with _case_deadline(_positive_int(_case_limits(assignment, benchmark).get("case_timeout_sec"), 300)):
                    env = backend.create_environment(benchmark, case)
                    backend_result = _run_environment_case(env, assignment, run_id, record_event)
    except Exception as exc:
        error_event = {"event": "error", "error_type": type(exc).__name__, "message": str(exc)}
        record_event(error_event)
        backend_result = BackendCaseResult(status="runner_error", reward=0.0, max_reward=1.0, events=[error_event])
    llm_usage_events = _load_llm_usage_events(llm_usage_path)
    for event in llm_usage_events:
        record_event(event)
    llm_usage_summary = _llm_usage_summary(llm_usage_events)

    result = {
        "run_id": run_id,
        "benchmark": benchmark,
        "case_id": case_id,
        "case_key": case_short_name,
        "status": backend_result.status,
        "grading_score": backend_result.grading_score,
        "analysis_score": backend_result.analysis_score,
        "max_score": backend_result.max_score,
        "reward": backend_result.reward,
        "max_reward": backend_result.max_reward,
        "backend": backend.name,
        "started_at": started_at,
        "completed_at": utc_now_iso(),
        "trajectory_path": str(trajectory_relative_path),
        "attempt": attempt,
        "auto_resumed": auto_resumed,
        **llm_usage_summary,
    }
    if llm_usage_events:
        result["llm_usage_path"] = str(llm_usage_relative_path)
    if previous_status is not None:
        result["previous_status"] = previous_status
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run selected public course agent project cases locally.",
        allow_abbrev=False,
    )
    parser.add_argument("--assignment", default="task_configs/public_cases.json")
    parser.add_argument("--backend", choices=["simplified", "official"], default="simplified")
    parser.add_argument("--benchmark", action="append", default=[])
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--case", action="append", default=[], help="Run one case selected as benchmark:case_key.")
    parser.add_argument("--output-root", default="trajectories")
    parser.add_argument("--resume", help="Resume an existing trajectory batch directory.")
    parser.add_argument("--max-workers", type=int, help="Run up to this many cases concurrently. Defaults are backend-specific.")
    args = parser.parse_args(argv)

    if args.resume:
        run_dir = Path(args.resume)
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        metadata_path = run_dir / "run_metadata.json"
        metadata = json.loads(metadata_path.read_text())
        assignment_path = Path(metadata["assignment_path"])
        if not assignment_path.is_absolute():
            assignment_path = ROOT / assignment_path
        assignment = _load_assignment(assignment_path)
        selected = _selected_cases_from_metadata(assignment, metadata)
        backend_name = metadata["backend"]
        backend = _backend_by_name(backend_name)
        run_id = metadata["run_id"]
        started_at = metadata["started_at"]
        filters = metadata.get("filters", {})
        max_workers = _positive_int(args.max_workers, _default_max_workers(backend.name, selected))
        metadata["last_resumed_at"] = utc_now_iso()
        metadata["resume_count"] = int(metadata.get("resume_count", 0)) + 1
        metadata["max_workers"] = max_workers
        write_json(metadata_path, metadata)
    else:
        assignment_path = Path(args.assignment)
        if not assignment_path.is_absolute():
            assignment_path = ROOT / assignment_path
        assignment = _load_assignment(assignment_path)
        try:
            selected = _selected_cases(assignment, set(args.benchmark), set(args.case_id), args.case)
        except ValueError as exc:
            parser.error(str(exc))
        backend = _backend_by_name(args.backend)
        run_dir = Path(args.output_root)
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        filters = {"benchmarks": args.benchmark, "case_ids": args.case_id, "cases": args.case}
        max_workers = _positive_int(args.max_workers, _default_max_workers(backend.name, selected))
        auto_resume_run = _matching_auto_resume_run(
            run_dir,
            assignment=assignment,
            assignment_path=assignment_path,
            backend_name=backend.name,
            filters=filters,
            selected=selected,
        )
        if auto_resume_run is not None:
            run_dir = auto_resume_run
            metadata_path = run_dir / "run_metadata.json"
            metadata = json.loads(metadata_path.read_text())
            run_id = metadata["run_id"]
            started_at = metadata["started_at"]
            metadata["last_auto_resumed_at"] = utc_now_iso()
            metadata["auto_resume_count"] = int(metadata.get("auto_resume_count", 0)) + 1
            metadata["max_workers"] = max_workers
            write_json(metadata_path, metadata)
        else:
            run_id = make_run_id()
            run_dir = run_dir / run_id
            started_at = utc_now_iso()
            write_json(
                run_dir / "run_metadata.json",
                {
                    "run_id": run_id,
                    "started_at": started_at,
                    "assignment_id": assignment["assignment_id"],
                    "assignment_path": str(assignment_path),
                    "backend": backend.name,
                    "split": assignment["split"],
                    "filters": filters,
                    "selected_case_count": len(selected),
                    "selected_cases": [_case_metadata_item(item["benchmark"], item["case"]) for item in selected],
                    "auto_resume_count": 0,
                    "max_workers": max_workers,
                },
            )

    result_history = _case_result_history(run_dir / "case_results.jsonl")
    latest_results = {key: values[-1] for key, values in result_history.items() if values}
    pending_attempts: list[dict[str, Any]] = []
    for item in selected:
        benchmark = item["benchmark"]
        case = item["case"]
        case_id = str(case["case_id"])
        case_short_name = _case_key(case)
        case_key = (benchmark, case_id)
        previous_result = latest_results.get(case_key)
        if not _is_retryable_result(previous_result):
            continue
        attempt = _next_attempt(previous_result)
        auto_resumed = previous_result is not None or bool(result_history)
        pending_attempts.append(
            {
                "backend_name": backend.name,
                "item": item,
                "assignment": assignment,
                "run_id": run_id,
                "started_at": started_at,
                "run_dir": str(run_dir),
                "attempt": attempt,
                "auto_resumed": auto_resumed,
                "previous_status": previous_result.get("status") if previous_result is not None else None,
            }
        )

    def record_result(result: dict[str, Any]) -> None:
        case_key = (result["benchmark"], str(result["case_id"]))
        append_jsonl(run_dir / "case_results.jsonl", result)
        latest_results[case_key] = result
        result_history.setdefault(case_key, []).append(result)

    def run_attempts(attempts: list[dict[str, Any]]) -> None:
        if max_workers <= 1 or len(attempts) <= 1:
            for attempt_kwargs in attempts:
                record_result(_run_case_attempt(**attempt_kwargs))
        else:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_run_case_attempt, **attempt_kwargs) for attempt_kwargs in attempts]
                for future in as_completed(futures):
                    record_result(future.result())

    run_attempts(pending_attempts)
    retry_attempts = []
    for attempt_kwargs in pending_attempts:
        item = attempt_kwargs["item"]
        case_key = (item["benchmark"], str(item["case"]["case_id"]))
        previous_result = latest_results[case_key]
        if _is_retryable_result(previous_result):
            retry_attempts.append({
                **attempt_kwargs,
                "attempt": _next_attempt(previous_result),
                "auto_resumed": True,
                "previous_status": previous_result["status"],
            })
    run_attempts(retry_attempts)

    selected_keys = [(item["benchmark"], str(item["case"]["case_id"])) for item in selected]
    summary_results = [latest_results[key] for key in selected_keys if key in latest_results]
    total_grading_score = sum(float(result.get("grading_score", result.get("reward", 0.0))) for result in summary_results)
    total_analysis_score = sum(
        float(result.get("analysis_score", result.get("grading_score", result.get("reward", 0.0))))
        for result in summary_results
    )
    total_reward = sum(float(result.get("reward", result.get("grading_score", 0.0))) for result in summary_results)
    llm_usage_totals = _sum_llm_usage(summary_results)
    status_counts: dict[str, int] = {}
    exit_code = 0
    for result in summary_results:
        status = result["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if status.endswith("_error"):
            exit_code = 2
    write_json(
        run_dir / "score_summary.json",
        {
            "run_id": run_id,
            "backend": backend.name,
            "selected_cases": len(selected),
            "completed_cases": len(summary_results),
            "total_grading_score": total_grading_score,
            "average_grading_score": total_grading_score / len(summary_results) if summary_results else 0.0,
            "total_analysis_score": total_analysis_score,
            "average_analysis_score": total_analysis_score / len(summary_results) if summary_results else 0.0,
            "total_reward": total_reward,
            "average_reward": total_reward / len(summary_results) if summary_results else 0.0,
            "status_counts": status_counts,
            **llm_usage_totals,
        },
    )
    write_json(
        run_dir / "case_analysis.json",
        _case_analysis_document(
            run_id=run_id,
            backend_name=backend.name,
            summary_results=summary_results,
            run_dir=run_dir,
        ),
    )
    print(f"Wrote trajectory batch to {run_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
