import contextlib
import json
import time

import pytest

from course_agent.protocol import AgentResponse
import public_runner.run_public_tasks as run_public_tasks
from public_runner.envs.base import TaskEnvironment
from public_runner.run_public_tasks import main


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_public_runner_records_timestamped_simplified_batch(tmp_path):
    output_root = tmp_path / "trajectories"

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--benchmark",
            "tau2_airline",
            "--case-id",
            "49",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    runs = list(output_root.iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    summary = json.loads((run_dir / "score_summary.json").read_text())
    case_analysis = json.loads((run_dir / "case_analysis.json").read_text())
    case_results = [
        json.loads(line)
        for line in (run_dir / "case_results.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert metadata["backend"] == "simplified"
    assert metadata["filters"]["benchmarks"] == ["tau2_airline"]
    assert metadata["selected_case_count"] == 1
    assert summary["backend"] == "simplified"
    assert summary["completed_cases"] == 1
    assert summary["total_grading_score"] == 1.0
    assert summary["average_grading_score"] == 1.0
    assert summary["total_analysis_score"] == 1.0
    assert summary["average_analysis_score"] == 1.0
    assert summary["total_reward"] == 1.0
    assert case_results[0]["benchmark"] == "tau2_airline"
    assert case_results[0]["case_key"] == "tau2_49"
    assert case_results[0]["grading_score"] == 1.0
    assert case_results[0]["analysis_score"] == 1.0
    assert case_results[0]["max_score"] == 1.0
    assert case_results[0]["reward"] == 1.0
    assert case_results[0]["backend"] == "simplified"
    assert (run_dir / case_results[0]["trajectory_path"]).exists()
    case_entry = case_analysis["benchmarks"]["tau2_airline"]["49"]
    assert case_entry["case_key"] == "tau2_49"
    assert case_entry["status"] == "scored_success"
    assert case_entry["grading_score"] == 1.0
    assert case_entry["analysis_score"] == 1.0
    assert case_entry["runtime_issue"] is False
    assert case_entry["issue_category"] == "none"
    assert case_entry["trajectory_path"] == case_results[0]["trajectory_path"]


def test_public_runner_records_official_setup_error_trajectory(tmp_path, monkeypatch):
    monkeypatch.setenv("MCPMARK_REPO", str(tmp_path / "missing-mcpmark"))
    output_root = tmp_path / "trajectories"

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "official",
            "--benchmark",
            "mcpmark",
            "--case-id",
            "filesystem/file_context/pattern_matching",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 2
    run_dir = next(output_root.iterdir())
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    summary = json.loads((run_dir / "score_summary.json").read_text())
    case_analysis = json.loads((run_dir / "case_analysis.json").read_text())
    result = json.loads((run_dir / "case_results.jsonl").read_text().splitlines()[0])

    assert metadata["backend"] == "official"
    assert summary["status_counts"] == {"official_setup_error": 1}
    assert summary["total_grading_score"] == 0.0
    assert summary["average_grading_score"] == 0.0
    assert result["backend"] == "official"
    assert result["case_key"] == "mcp_filesystem_file_context_pattern_matching"
    assert result["status"] == "official_setup_error"
    assert result["grading_score"] == 0.0
    assert result["analysis_score"] == 0.0
    assert result["reward"] == result["grading_score"]
    assert (run_dir / result["trajectory_path"]).exists()
    case_entry = case_analysis["benchmarks"]["mcpmark"]["filesystem/file_context/pattern_matching"]
    assert case_entry["status"] == "official_setup_error"
    assert case_entry["runtime_issue"] is True
    assert case_entry["issue_category"] == "official_setup"
    assert case_entry["issue_type"] == "OfficialSetupError"
    assert "MCPMark is not configured" in case_entry["issue_message"]


def test_public_runner_accepts_official_benchmark_scoped_case_selector(tmp_path, monkeypatch):
    monkeypatch.setenv("TAU2_REPO", str(tmp_path / "missing-tau2-bench"))
    output_root = tmp_path / "trajectories"

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "official",
            "--case",
            "tau2_airline:tau2_49",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 2
    run_dir = next(output_root.iterdir())
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    result = json.loads((run_dir / "case_results.jsonl").read_text().splitlines()[0])
    assert metadata["filters"]["cases"] == ["tau2_airline:tau2_49"]
    assert result["benchmark"] == "tau2_airline"
    assert result["case_key"] == "tau2_49"
    assert result["status"] == "official_setup_error"


def test_public_runner_selects_benchmark_scoped_case_keys(tmp_path):
    output_root = tmp_path / "trajectories"

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--case",
            "mcpmark:mcp_filesystem_file_context_pattern_matching",
            "--case",
            "tau2_airline:tau2_49",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    run_dir = next(output_root.iterdir())
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    case_results = _read_jsonl(run_dir / "case_results.jsonl")

    assert metadata["filters"]["cases"] == ["mcpmark:mcp_filesystem_file_context_pattern_matching", "tau2_airline:tau2_49"]
    assert metadata["selected_cases"] == [
        {
            "benchmark": "mcpmark",
            "case_id": "filesystem/file_context/pattern_matching",
            "case_key": "mcp_filesystem_file_context_pattern_matching",
        },
        {"benchmark": "tau2_airline", "case_id": "49", "case_key": "tau2_49"},
    ]
    assert [
        (result["benchmark"], result["case_id"], result["case_key"], result["trajectory_path"])
        for result in sorted(case_results, key=lambda result: result["benchmark"])
    ] == [
        ("mcpmark", "filesystem/file_context/pattern_matching", "mcp_filesystem_file_context_pattern_matching", "cases/mcpmark/mcp_filesystem_file_context_pattern_matching/trajectory.jsonl"),
        ("tau2_airline", "49", "tau2_49", "cases/tau2_airline/tau2_49/trajectory.jsonl"),
    ]


def test_public_runner_default_worker_policy_is_conservative_for_official():
    selected = [
        {"benchmark": "tau2_airline", "case": {"case_id": "49"}},
        {"benchmark": "deepplanning", "case": {"case_id": "shopping/level_1/case_10"}},
    ]

    assert run_public_tasks._default_max_workers("simplified", selected) == 4
    assert run_public_tasks._default_max_workers("official", selected) == 1


def test_public_runner_resource_lock_policy_targets_official_mcpmark_only():
    assert run_public_tasks._case_attempt_requires_resource_lock("official", "mcpmark") is True
    assert run_public_tasks._case_attempt_requires_resource_lock("official", "tau2_airline") is False
    assert run_public_tasks._case_attempt_requires_resource_lock("official", "deepplanning") is False
    assert run_public_tasks._case_attempt_requires_resource_lock("simplified", "mcpmark") is False


def test_public_runner_resource_lock_path_can_be_host_level(tmp_path, monkeypatch):
    lock_root = tmp_path / "runner-locks"
    monkeypatch.setenv("COURSE_RUNNER_LOCK_DIR", str(lock_root))

    assert run_public_tasks._case_attempt_resource_lock_path("official", "mcpmark") == (
        lock_root / "comp5211_public_runner_locks" / "official_mcpmark.lock"
    )


def test_public_runner_wraps_case_attempt_in_resource_lock(tmp_path, monkeypatch):
    calls = []

    class FakeBackend:
        name = "official"

        def create_environment(self, benchmark, case):
            return TaskEnvironment(benchmark, case)

    @contextlib.contextmanager
    def fake_resource_lock(*, backend_name, benchmark, run_dir):
        calls.append((backend_name, benchmark, run_dir))
        yield

    monkeypatch.setattr(run_public_tasks, "_backend_by_name", lambda _name: FakeBackend())
    monkeypatch.setattr(run_public_tasks, "_case_attempt_resource_lock", fake_resource_lock)
    monkeypatch.setattr(
        run_public_tasks,
        "_run_environment_case",
        lambda _env, _assignment, _run_id, _record_event: run_public_tasks.BackendCaseResult(
            status="scored_success",
            reward=1.0,
            max_reward=1.0,
            events=[],
        ),
    )

    result = run_public_tasks._run_case_attempt(
        backend_name="official",
        item={"benchmark": "mcpmark", "case": {"case_id": "filesystem/file_context/pattern_matching"}},
        assignment={},
        run_id="run",
        started_at="2026-09-29T00:00:00Z",
        run_dir=str(tmp_path),
        attempt=1,
        auto_resumed=False,
        previous_status=None,
    )

    assert calls == [("official", "mcpmark", tmp_path)]
    assert result["status"] == "scored_success"


def test_public_runner_collects_case_llm_usage(tmp_path, monkeypatch):
    class FakeBackend:
        name = "official"

        def create_environment(self, benchmark, case):
            return TaskEnvironment(benchmark, case)

    def fake_run_environment_case(_env, _assignment, _run_id, _record_event):
        usage_path = run_public_tasks.Path(run_public_tasks.os.environ["COURSE_LLM_USAGE_PATH"])
        run_public_tasks.append_jsonl(
            usage_path,
            {
                "event": "llm_call",
                "status": "success",
                "model": "gpt-5-mini",
                "deployment": "gpt-5-mini",
                "attempt": 1,
                "estimated_input_tokens": 9,
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            },
        )
        return run_public_tasks.BackendCaseResult(status="scored_success", reward=1.0, max_reward=1.0, events=[])

    monkeypatch.delenv("COURSE_LLM_USAGE_PATH", raising=False)
    monkeypatch.setattr(run_public_tasks, "_backend_by_name", lambda _name: FakeBackend())
    monkeypatch.setattr(run_public_tasks, "_run_environment_case", fake_run_environment_case)

    result = run_public_tasks._run_case_attempt(
        backend_name="official",
        item={"benchmark": "tau2_airline", "case": {"case_id": "49", "case_key": "tau2_49"}},
        assignment={},
        run_id="run",
        started_at="2026-09-29T00:00:00Z",
        run_dir=str(tmp_path),
        attempt=1,
        auto_resumed=False,
        previous_status=None,
    )

    assert "COURSE_LLM_USAGE_PATH" not in run_public_tasks.os.environ
    assert result["llm_api_call_count"] == 1
    assert result["llm_successful_call_count"] == 1
    assert result["llm_failed_call_count"] == 0
    assert result["llm_prompt_tokens"] == 7
    assert result["llm_completion_tokens"] == 5
    assert result["llm_total_tokens"] == 12
    assert result["llm_estimated_input_tokens"] == 9
    assert result["llm_usage_path"] == "cases/tau2_airline/tau2_49/trajectory_llm_usage.jsonl"
    trajectory_events = _read_jsonl(tmp_path / result["trajectory_path"])
    assert trajectory_events[-1]["event"] == "llm_call"
    assert trajectory_events[-1]["usage"]["total_tokens"] == 12


def test_public_runner_summarizes_llm_usage_from_latest_results(tmp_path, monkeypatch):
    def fake_run_case_attempt(**kwargs):
        return {
            "run_id": kwargs["run_id"],
            "benchmark": "tau2_airline",
            "case_id": "49",
            "case_key": "tau2_49",
            "status": "scored_success",
            "grading_score": 1.0,
            "analysis_score": 1.0,
            "max_score": 1.0,
            "reward": 1.0,
            "max_reward": 1.0,
            "backend": "simplified",
            "started_at": kwargs["started_at"],
            "completed_at": "2026-09-29T00:00:01Z",
            "trajectory_path": "cases/tau2_airline/tau2_49/trajectory.jsonl",
            "attempt": kwargs["attempt"],
            "auto_resumed": kwargs["auto_resumed"],
            "llm_api_call_count": 2,
            "llm_successful_call_count": 1,
            "llm_failed_call_count": 1,
            "llm_prompt_tokens": 13,
            "llm_completion_tokens": 8,
            "llm_total_tokens": 21,
            "llm_estimated_input_tokens": 15,
        }

    output_root = tmp_path / "trajectories"
    monkeypatch.setattr(run_public_tasks, "_run_case_attempt", fake_run_case_attempt)

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--case",
            "tau2_airline:tau2_49",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    run_dir = next(output_root.iterdir())
    summary = json.loads((run_dir / "score_summary.json").read_text())
    case_analysis = json.loads((run_dir / "case_analysis.json").read_text())
    assert summary["llm_api_call_count"] == 2
    assert summary["llm_successful_call_count"] == 1
    assert summary["llm_failed_call_count"] == 1
    assert summary["llm_prompt_tokens"] == 13
    assert summary["llm_completion_tokens"] == 8
    assert summary["llm_total_tokens"] == 21
    assert summary["llm_estimated_input_tokens"] == 15
    case_entry = case_analysis["benchmarks"]["tau2_airline"]["49"]
    assert case_entry["llm_total_tokens"] == 21


def test_public_runner_retries_runtime_error_in_same_invocation(tmp_path, monkeypatch):
    def fake_attempt(**kwargs):
        return {
            "run_id": kwargs["run_id"], "benchmark": "tau2_airline", "case_id": "49",
            "case_key": "tau2_49", "status": "runner_error" if kwargs["attempt"] == 1 else "scored_success",
            "grading_score": 0.0 if kwargs["attempt"] == 1 else 1.0,
            "analysis_score": 0.0 if kwargs["attempt"] == 1 else 1.0,
            "max_score": 1.0, "reward": 0.0 if kwargs["attempt"] == 1 else 1.0,
            "max_reward": 1.0, "backend": "simplified", "started_at": kwargs["started_at"],
            "completed_at": "2026-09-29T00:00:01Z", "trajectory_path": "trajectory.jsonl",
            "attempt": kwargs["attempt"], "auto_resumed": kwargs["auto_resumed"],
        }

    monkeypatch.setattr(run_public_tasks, "_run_case_attempt", fake_attempt)
    output_root = tmp_path / "trajectories"
    assert main(["--backend", "simplified", "--case", "tau2_airline:tau2_49", "--output-root", str(output_root)]) == 0
    run_dir = next(output_root.iterdir())
    rows = _read_jsonl(run_dir / "case_results.jsonl")
    assert [(row["status"], row["attempt"]) for row in rows] == [("runner_error", 1), ("scored_success", 2)]
    assert json.loads((run_dir / "score_summary.json").read_text())["total_grading_score"] == 1.0


def test_public_runner_checkpoints_before_later_case_crashes(tmp_path, monkeypatch):
    real_attempt = run_public_tasks._run_case_attempt
    count = 0

    def attempt_then_crash(**kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt
        return real_attempt(**kwargs)

    monkeypatch.setattr(run_public_tasks, "_run_case_attempt", attempt_then_crash)
    output_root = tmp_path / "trajectories"
    with pytest.raises(KeyboardInterrupt):
        main(["--backend", "simplified", "--case", "tau2_airline:tau2_49",
              "--case", "tau2_airline:tau2_40", "--max-workers", "1", "--output-root", str(output_root)])
    rows = _read_jsonl(next(output_root.iterdir()) / "case_results.jsonl")
    assert len(rows) == 1


def test_case_attempt_enforces_total_case_timeout(tmp_path, monkeypatch):
    class HangingEnvironment(TaskEnvironment):
        def run(self):
            time.sleep(10)

    class Backend:
        name = "simplified"

        def create_environment(self, benchmark, case):
            return HangingEnvironment(benchmark, case)

    monkeypatch.setattr(run_public_tasks, "_backend_by_name", lambda name: Backend())
    started = time.monotonic()
    result = run_public_tasks._run_case_attempt(
        backend_name="simplified", item={"benchmark": "tau2_airline", "case": {"case_id": "49", "case_key": "tau2_49"}},
        assignment={"limits": {"case_timeout_sec": 1}}, run_id="run-1", started_at="now", run_dir=str(tmp_path),
        attempt=1, auto_resumed=False, previous_status=None,
    )
    assert time.monotonic() - started < 3
    assert result["status"] == "runner_error"
    assert _read_jsonl(tmp_path / result["trajectory_path"])[-1]["error_type"] == "TimeoutError"


def test_public_runner_runs_selected_cases_with_explicit_process_workers(tmp_path):
    output_root = tmp_path / "trajectories"

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--case",
            "mcpmark:mcp_filesystem_file_context_pattern_matching",
            "--case",
            "tau2_airline:tau2_49",
            "--max-workers",
            "2",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    run_dir = next(output_root.iterdir())
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    case_results = _read_jsonl(run_dir / "case_results.jsonl")

    assert metadata["max_workers"] == 2
    assert sorted((result["benchmark"], result["case_key"]) for result in case_results) == [
        ("mcpmark", "mcp_filesystem_file_context_pattern_matching"),
        ("tau2_airline", "tau2_49"),
    ]


def test_public_runner_rejects_unscoped_case_ids_without_single_benchmark(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--assignment",
                "task_configs/public_cases.json",
                "--backend",
                "simplified",
                "--case-id",
                "49",
                "--output-root",
                str(tmp_path / "trajectories"),
            ]
        )

    assert exc_info.value.code == 2


def test_public_runner_rejects_unknown_benchmark(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--assignment",
                "task_configs/public_cases.json",
                "--backend",
                "simplified",
                "--benchmark",
                "missing_benchmark",
                "--output-root",
                str(tmp_path / "trajectories"),
            ]
        )

    assert exc_info.value.code == 2


def test_public_runner_rejects_unknown_legacy_case_id(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--assignment",
                "task_configs/public_cases.json",
                "--backend",
                "simplified",
                "--benchmark",
                "tau2_airline",
                "--case-id",
                "9999",
                "--output-root",
                str(tmp_path / "trajectories"),
            ]
        )

    assert exc_info.value.code == 2


def test_public_runner_resume_skips_completed_cases_and_finishes_batch(tmp_path):
    output_root = tmp_path / "trajectories"

    first_exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--benchmark",
            "tau2_airline",
            "--case-id",
            "49",
            "--output-root",
            str(output_root),
        ]
    )
    assert first_exit_code == 0
    run_dir = next(output_root.iterdir())
    metadata_path = run_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["selected_case_count"] = 2
    metadata["selected_cases"] = [
        {"benchmark": "tau2_airline", "case_id": "49"},
        {"benchmark": "tau2_airline", "case_id": "40"},
    ]
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    original_case_3_trajectory = (run_dir / "cases" / "tau2_airline" / "tau2_49" / "trajectory.jsonl").read_text()

    resume_exit_code = main(["--resume", str(run_dir)])

    assert resume_exit_code == 0
    assert list(output_root.iterdir()) == [run_dir]
    resumed_results = _read_jsonl(run_dir / "case_results.jsonl")
    assert [(result["benchmark"], result["case_id"]) for result in resumed_results] == [
        ("tau2_airline", "49"),
        ("tau2_airline", "40"),
    ]
    assert (run_dir / "cases" / "tau2_airline" / "tau2_49" / "trajectory.jsonl").read_text() == original_case_3_trajectory
    assert (run_dir / "cases" / "tau2_airline" / "tau2_40" / "trajectory.jsonl").exists()
    summary = json.loads((run_dir / "score_summary.json").read_text())
    assert summary["selected_cases"] == 2
    assert summary["completed_cases"] == 2
    assert summary["total_grading_score"] == 2.0
    assert summary["average_grading_score"] == 1.0
    assert summary["total_reward"] == 2.0
    assert summary["status_counts"] == {"scored_success": 2}


def test_public_runner_auto_resumes_incomplete_matching_batch(tmp_path):
    output_root = tmp_path / "trajectories"
    run_dir = output_root / "run-existing"
    assignment_path = run_public_tasks.ROOT / "task_configs" / "public_cases.json"
    selected_cases = [
        {"benchmark": "tau2_airline", "case_id": "49", "case_key": "tau2_49"},
        {"benchmark": "tau2_airline", "case_id": "40", "case_key": "tau2_40"},
    ]
    run_public_tasks.write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-existing",
            "started_at": "2026-09-27T00:00:00Z",
            "assignment_id": json.loads(assignment_path.read_text())["assignment_id"],
            "assignment_path": str(assignment_path),
            "backend": "simplified",
            "split": "public",
            "filters": {
                "benchmarks": [],
                "case_ids": [],
                "cases": ["tau2_airline:tau2_49", "tau2_airline:tau2_40"],
            },
            "selected_case_count": 2,
            "selected_cases": selected_cases,
        },
    )
    run_public_tasks.append_jsonl(
        run_dir / "case_results.jsonl",
        {
            "run_id": "run-existing",
            "benchmark": "tau2_airline",
            "case_id": "49",
            "case_key": "tau2_49",
            "status": "scored_success",
            "grading_score": 1.0,
            "analysis_score": 1.0,
            "max_score": 1.0,
            "reward": 1.0,
            "max_reward": 1.0,
            "backend": "simplified",
            "started_at": "2026-09-27T00:00:00Z",
            "completed_at": "2026-09-27T00:00:01Z",
            "trajectory_path": "cases/tau2_airline/tau2_49/trajectory.jsonl",
            "attempt": 1,
            "auto_resumed": False,
        },
    )

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--case",
            "tau2_airline:tau2_49",
            "--case",
            "tau2_airline:tau2_40",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    assert list(output_root.iterdir()) == [run_dir]
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    results = _read_jsonl(run_dir / "case_results.jsonl")
    assert metadata["auto_resume_count"] == 1
    assert [(result["case_id"], result["attempt"], result["auto_resumed"]) for result in results] == [
        ("49", 1, False),
        ("40", 1, True),
    ]
    assert (run_dir / "cases" / "tau2_airline" / "tau2_40" / "trajectory.jsonl").exists()


def test_public_runner_auto_retries_error_case_once(tmp_path):
    output_root = tmp_path / "trajectories"
    run_dir = output_root / "run-existing"
    assignment_path = run_public_tasks.ROOT / "task_configs" / "public_cases.json"
    run_public_tasks.write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-existing",
            "started_at": "2026-09-27T00:00:00Z",
            "assignment_id": json.loads(assignment_path.read_text())["assignment_id"],
            "assignment_path": str(assignment_path),
            "backend": "simplified",
            "split": "public",
            "filters": {"benchmarks": ["tau2_airline"], "case_ids": ["49"], "cases": []},
            "selected_case_count": 1,
            "selected_cases": [{"benchmark": "tau2_airline", "case_id": "49", "case_key": "tau2_49"}],
        },
    )
    run_public_tasks.append_jsonl(
        run_dir / "case_results.jsonl",
        {
            "run_id": "run-existing",
            "benchmark": "tau2_airline",
            "case_id": "49",
            "case_key": "tau2_49",
            "status": "runner_error",
            "grading_score": 0.0,
            "analysis_score": 0.0,
            "max_score": 1.0,
            "reward": 0.0,
            "max_reward": 1.0,
            "backend": "simplified",
            "started_at": "2026-09-27T00:00:00Z",
            "completed_at": "2026-09-27T00:00:01Z",
            "trajectory_path": "cases/tau2_airline/tau2_49/attempt_1.jsonl",
            "attempt": 1,
            "auto_resumed": False,
        },
    )

    exit_code = main(
        [
            "--assignment",
            "task_configs/public_cases.json",
            "--backend",
            "simplified",
            "--benchmark",
            "tau2_airline",
            "--case-id",
            "49",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    results = _read_jsonl(run_dir / "case_results.jsonl")
    assert [(result["status"], result["attempt"], result["auto_resumed"]) for result in results] == [
        ("runner_error", 1, False),
        ("scored_success", 2, True),
    ]
    assert results[1]["previous_status"] == "runner_error"
    assert results[1]["trajectory_path"] == "cases/tau2_airline/tau2_49/attempt_2.jsonl"


def test_case_analysis_classifies_scored_failure_as_agent_performance(tmp_path):
    run_dir = tmp_path / "run"
    trajectory = run_dir / "cases" / "deepplanning" / "dp_level_1_case_10" / "trajectory.jsonl"
    run_public_tasks.append_jsonl(
        trajectory,
        {
            "event": "score",
            "grading_score": 0.0,
            "analysis_score": 0.6666666667,
            "score_source": "deepplanning_official",
            "matched_count": 2,
            "expected_count": 3,
            "extra_products_count": 1,
        },
    )
    result = {
        "benchmark": "deepplanning",
        "case_id": "shopping/level_1/case_10",
        "case_key": "dp_level_1_case_10",
        "status": "scored_failure",
        "grading_score": 0.0,
        "analysis_score": 0.6666666667,
        "max_score": 1.0,
        "reward": 0.0,
        "max_reward": 1.0,
        "trajectory_path": "cases/deepplanning/dp_level_1_case_10/trajectory.jsonl",
        "attempt": 1,
        "auto_resumed": False,
    }

    analysis = run_public_tasks._case_analysis_document(
        run_id="run",
        backend_name="official",
        summary_results=[result],
        run_dir=run_dir,
    )

    case_entry = analysis["benchmarks"]["deepplanning"]["shopping/level_1/case_10"]
    assert case_entry["runtime_issue"] is False
    assert case_entry["issue_category"] == "agent_performance"
    assert case_entry["issue_type"] == "agent_or_task_failure"
    assert case_entry["score_details"] == {
        "score_source": "deepplanning_official",
        "matched_count": 2,
        "expected_count": 3,
        "extra_products_count": 1,
    }


def test_environment_case_uses_assignment_max_agent_turns(monkeypatch):
    class NeverDoneEnvironment(TaskEnvironment):
        def tools(self):
            return [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]

        def execute_tool(self, name, arguments):
            return {"ok": True}

    class ToolCallingClient:
        def send(self, request):
            return AgentResponse.tool_call(request["request_id"], "noop", {})

        def close(self):
            return None

    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", ToolCallingClient)
    env = NeverDoneEnvironment("tau2_airline", {"case_id": "49", "description": "limit test"})
    assignment = {"limits": {"benchmarks": {"tau2_airline": {"max_agent_turns": 3}}}}

    result = run_public_tasks._run_environment_case(env, assignment, "run-1")

    requests = [event for event in result.events if event["event"] == "request"]
    assert len(requests) == 3
    assert requests[-1]["request"]["limits"]["max_agent_turns"] == 3
    assert result.status == "student_runtime_error"
    errors = [event for event in result.events if event["event"] == "error"]
    assert any(event["error_type"] == "TurnLimitExceeded" for event in errors)


def test_environment_case_rejects_too_many_tool_calls_in_one_turn(monkeypatch):
    class NeverCalledEnvironment(TaskEnvironment):
        def tools(self):
            return [
                {"type": "function", "function": {"name": "read_a", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "read_b", "parameters": {"type": "object"}}},
            ]

        def execute_tool(self, name, arguments):
            raise AssertionError(f"{name} should not run after batch validation fails")

    class TooManyToolCallsClient:
        def send(self, request):
            return AgentResponse.tool_calls(
                request["request_id"],
                [
                    {"tool_name": "read_a", "tool_arguments": {}},
                    {"tool_name": "read_b", "tool_arguments": {}},
                ],
            )

        def close(self):
            return None

    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", TooManyToolCallsClient)
    env = NeverCalledEnvironment("mcpmark", {"case_id": "case-1", "description": "limit test"})
    assignment = {"limits": {"benchmarks": {"mcpmark": {"max_tool_calls_per_turn": 1}}}}

    result = run_public_tasks._run_environment_case(env, assignment, "run-1")

    assert result.status == "student_runtime_error"
    errors = [event for event in result.events if event["event"] == "error"]
    assert errors[-1]["error_type"] == "ToolCallLimitExceeded"
    assert "2 > 1" in errors[-1]["message"]


def test_environment_case_rejects_mutating_tool_before_read(monkeypatch):
    class NeverCalledEnvironment(TaskEnvironment):
        def tools(self):
            return [
                {"type": "function", "function": {"name": "add_product_to_cart", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "get_cart_info", "parameters": {"type": "object"}}},
            ]

        def execute_tool(self, name, arguments):
            raise AssertionError(f"{name} should not run after ordering validation fails")

    class WriteBeforeReadClient:
        def send(self, request):
            return AgentResponse.tool_calls(
                request["request_id"],
                [
                    {"tool_name": "add_product_to_cart", "tool_arguments": {"product_id": "p1"}},
                    {"tool_name": "get_cart_info", "tool_arguments": {}},
                ],
            )

        def close(self):
            return None

    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", WriteBeforeReadClient)
    env = NeverCalledEnvironment("deepplanning", {"case_id": "shopping/level_1/case_1", "description": "limit test"})
    assignment = {"limits": {"benchmarks": {"deepplanning": {"max_tool_calls_per_turn": 5, "max_mutating_tool_calls_per_turn": 3}}}}

    result = run_public_tasks._run_environment_case(env, assignment, "run-1")

    assert result.status == "student_runtime_error"
    errors = [event for event in result.events if event["event"] == "error"]
    assert errors[-1]["error_type"] == "ToolCallOrderError"
    assert "mutating tool calls must come after read-only tool calls" in errors[-1]["message"]


def test_environment_case_rejects_tau2_terminal_tool_combined_with_other_tools(monkeypatch):
    class NeverCalledEnvironment(TaskEnvironment):
        def tools(self):
            return [
                {"type": "function", "function": {"name": "respond_to_user", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "lookup_reservation", "parameters": {"type": "object"}}},
            ]

        def execute_tool(self, name, arguments):
            raise AssertionError(f"{name} should not run after terminal validation fails")

    class MixedTerminalClient:
        def send(self, request):
            return AgentResponse.tool_calls(
                request["request_id"],
                [
                    {"tool_name": "respond_to_user", "tool_arguments": {"content": "hello"}},
                    {"tool_name": "lookup_reservation", "tool_arguments": {"confirmation": "ABC123"}},
                ],
            )

        def close(self):
            return None

    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", MixedTerminalClient)
    env = NeverCalledEnvironment("tau2_airline", {"case_id": "49", "description": "limit test"})
    assignment = {"limits": {"benchmarks": {"tau2_airline": {"max_tool_calls_per_turn": 3}}}}

    result = run_public_tasks._run_environment_case(env, assignment, "run-1")

    assert result.status == "student_runtime_error"
    errors = [event for event in result.events if event["event"] == "error"]
    assert errors[-1]["error_type"] == "ToolCallOrderError"
    assert "respond_to_user cannot be combined" in errors[-1]["message"]


def test_environment_case_rejects_deepplanning_terminal_tool_combined_with_other_tools(monkeypatch):
    class NeverCalledEnvironment(TaskEnvironment):
        def tools(self):
            return [
                {"type": "function", "function": {"name": "search_products", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "submit_plan", "parameters": {"type": "object"}}},
            ]

        def execute_tool(self, name, arguments):
            raise AssertionError(f"{name} should not run after terminal validation fails")

    class MixedTerminalClient:
        def send(self, request):
            return AgentResponse.tool_calls(
                request["request_id"],
                [
                    {"tool_name": "search_products", "tool_arguments": {"query": "shirt"}},
                    {"tool_name": "submit_plan", "tool_arguments": {"plan": {"items": ["baseline-item"]}}},
                ],
            )

        def close(self):
            return None

    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", MixedTerminalClient)
    env = NeverCalledEnvironment("deepplanning", {"case_id": "shopping/level_1/case_1", "description": "limit test"})
    assignment = {"limits": {"benchmarks": {"deepplanning": {"max_tool_calls_per_turn": 5}}}}

    result = run_public_tasks._run_environment_case(env, assignment, "run-1")

    assert result.status == "student_runtime_error"
    errors = [event for event in result.events if event["event"] == "error"]
    assert errors[-1]["error_type"] == "ToolCallOrderError"
    assert "submit_plan cannot be combined" in errors[-1]["message"]


def test_environment_case_returns_indexed_results_and_skips_after_write_error(monkeypatch):
    class ErrorAfterWriteEnvironment(TaskEnvironment):
        def tools(self):
            return [
                {"type": "function", "function": {"name": "search_products", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "add_product_to_cart", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "add_coupon_to_cart", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "delete_coupon_from_cart", "parameters": {"type": "object"}}},
            ]

        def execute_tool(self, name, arguments):
            if name == "search_products":
                self._tool_results.append({"tool_name": name, "result": {"ids": ["p1"]}})
                return {"ids": ["p1"]}
            if name == "add_product_to_cart":
                self._tool_results.append({"tool_name": name, "result": {"cart": ["p1"]}})
                return {"cart": ["p1"]}
            raise RuntimeError("coupon not owned")

    class BatchThenFinalClient:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return AgentResponse.tool_calls(
                    request["request_id"],
                    [
                        {"tool_name": "search_products", "tool_arguments": {"query": "shirt"}},
                        {"tool_name": "add_product_to_cart", "tool_arguments": {"product_id": "p1"}},
                        {"tool_name": "add_coupon_to_cart", "tool_arguments": {"coupon_name": "bad"}},
                        {"tool_name": "delete_coupon_from_cart", "tool_arguments": {"coupon_name": "bad"}},
                    ],
                )
            return AgentResponse.final(request["request_id"], "done")

        def close(self):
            return None

    client = BatchThenFinalClient()
    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", lambda: client)
    env = ErrorAfterWriteEnvironment("deepplanning", {"case_id": "shopping/level_1/case_1", "description": "limit test"})
    assignment = {"limits": {"benchmarks": {"deepplanning": {"max_agent_turns": 2, "max_tool_calls_per_turn": 5, "max_mutating_tool_calls_per_turn": 3}}}}

    result = run_public_tasks._run_environment_case(env, assignment, "run-1")

    assert result.status == "scored_success"
    tool_results = client.requests[1]["observation"]["tool_results"]
    assert [item["index"] for item in tool_results] == [0, 1, 2, 3]
    assert [item["ok"] for item in tool_results] == [True, True, False, False]
    assert tool_results[2]["error_type"] == "RuntimeError"
    assert tool_results[2]["error"] == "coupon not owned"
    assert tool_results[3]["skipped"] is True
    assert tool_results[3]["reason"] == "skipped_after_tool_error"


def test_mcpmark_tool_is_error_stops_batch_and_reaches_agent(monkeypatch):
    class MCPErrorEnvironment(TaskEnvironment):
        def tools(self):
            return [{"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
                    for name in ("read_file", "list_directory")]

        def execute_tool(self, name, arguments):
            if name == "read_file":
                return {"isError": True, "content": [{"type": "text", "text": "missing file"}]}
            raise AssertionError("second tool must not run")

    class Client:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return AgentResponse.tool_calls(request["request_id"], [
                    {"tool_name": "read_file", "tool_arguments": {}},
                    {"tool_name": "list_directory", "tool_arguments": {}},
                ])
            return AgentResponse.final(request["request_id"], "done")

        def close(self):
            pass

    client = Client()
    monkeypatch.setattr(run_public_tasks, "AgentProcessClient", lambda: client)
    env = MCPErrorEnvironment("mcpmark", {"case_id": "case", "description": "test"})
    result = run_public_tasks._run_environment_case(env, {"limits": {}}, "run-1")

    assert result.status == "scored_success"
    tool_results = client.requests[1]["observation"]["tool_results"]
    assert tool_results[0]["ok"] is False
    assert "missing file" in tool_results[0]["error"]
    assert tool_results[1]["skipped"] is True
