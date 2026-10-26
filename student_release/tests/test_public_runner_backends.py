import json
import sys

import pytest

from public_runner.envs.base import BackendCaseResult, CaseScore, TaskEnvironment
from public_runner.envs.official import (
    OfficialDeepPlanningEnvironment,
    OfficialMCPMarkEnvironment,
    OfficialPublicBackend,
    OfficialTau2AirlineEnvironment,
    _deepplanning_setup_report,
    _mcpmark_postgres_runtime_report,
    _mcpmark_setup_report,
    _redact_command,
    _tau2_setup_report,
    _tau2_command,
    _tau2_subprocess_env,
)
from public_runner.envs.mcpmark_jsonl_entry import normalize_filesystem_tool_arguments
from public_runner.envs.simplified import SimplifiedBackend


@pytest.fixture
def mcpmark_runtime(tmp_path, monkeypatch):
    """Provide preflight assets without borrowing the developer's installation."""
    course_root = tmp_path / "course-layout"
    (course_root / "student_release").mkdir(parents=True)
    node = course_root / "third_party/.local/node20/bin/node"
    node.parent.mkdir(parents=True)
    node.write_text("#!/bin/sh\nexit 0\n")
    node.chmod(0o755)
    server = course_root / "third_party/.local/mcp-filesystem-server/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
    server.parent.mkdir(parents=True)
    server.write_text("// Fixture for setup-report checks; adapter I/O uses its own fake executable.\n")
    monkeypatch.setattr("public_runner.envs.official._course_project_root", lambda: course_root)


def _set_valid_tau2_llm_env(monkeypatch):
    monkeypatch.setenv("COURSE_API_KEY", "test-course-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://hkust.azure-api.net/hkust-genai/v1")
    monkeypatch.setenv("TAU2_USER_MODEL", "openai/gpt-4o-mini")


def test_simplified_backend_routes_all_three_benchmarks():
    backend = SimplifiedBackend()

    for benchmark in ("mcpmark", "tau2_airline", "deepplanning"):
        env = backend.create_environment(benchmark, {"case_id": "case-1", "description": "test"})
        assert isinstance(env, TaskEnvironment)
        assert env.benchmark == benchmark


def test_score_objects_use_binary_grading_and_preserve_analysis_score():
    score = CaseScore(
        status="scored_success",
        reward=75.0,
        max_reward=100.0,
        details={"score_source": "unit"},
        grading_score=75.0,
        analysis_score=125.0,
        max_score=100.0,
    )

    assert score.grading_score == 0.0
    assert score.analysis_score == 125.0
    assert score.max_score == 1.0
    assert score.reward == 0.0
    assert score.max_reward == 1.0
    assert score.details["raw_grading_score"] == 75.0
    assert score.details["raw_analysis_score"] == 125.0
    assert score.details["raw_max_score"] == 100.0

    complete_score = CaseScore(
        status="scored_success",
        reward=100.0,
        max_reward=100.0,
        details={"score_source": "unit"},
        grading_score=100.0,
        analysis_score=0.5,
        max_score=100.0,
    )

    assert complete_score.grading_score == 1.0
    assert complete_score.analysis_score == 0.5
    assert complete_score.reward == 1.0

    result = BackendCaseResult(
        status="scored_success",
        reward=0.8,
        max_reward=1.0,
        grading_score=0.8,
        analysis_score=-0.5,
        max_score=1.0,
        events=[],
    )

    assert result.grading_score == 0.0
    assert result.analysis_score == -0.5
    assert result.max_score == 1.0
    assert result.reward == 0.0
    assert result.max_reward == 1.0


def test_official_backend_routes_all_three_benchmarks_but_reports_setup_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TAU2_REPO", str(tmp_path / "missing-tau2-bench"))
    monkeypatch.setenv("DEEPPLANNING_REPO", str(tmp_path / "missing-qwen-agent"))
    backend = OfficialPublicBackend()

    for benchmark in ("mcpmark", "tau2_airline", "deepplanning"):
        env = backend.create_environment(benchmark, {"case_id": "case-1", "description": "test"})
        assert isinstance(env, TaskEnvironment)
        assert env.benchmark == benchmark
        result = env.run()
        assert result.status == "official_setup_error"
        assert any(event["event"] == "error" for event in result.events)


def test_official_backend_setup_report_uses_course_project_paths_only():
    report = OfficialPublicBackend().setup_report()

    serialized = json.dumps(report)
    assert "experiments/" not in serialized
    assert "course_project" in serialized
    assert "third_party" in serialized
    assert "student_release" in serialized
    assert "staff_side" not in report["found"]


def test_tau2_setup_report_message_reflects_configured_repo(tmp_path, monkeypatch):
    tau_repo = tmp_path / "tau2-bench"
    python = tau_repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python3\n")
    (tau_repo / "pyproject.toml").write_text("[project]\nname = 'fake-tau2'\n")
    monkeypatch.setenv("TAU2_REPO", str(tau_repo))

    report = _tau2_setup_report()

    assert report["missing"] == []
    assert "configured" in report["message"]
    assert "not configured" not in report["message"]


def test_deepplanning_setup_report_message_reflects_configured_repo(tmp_path, monkeypatch):
    qwen_repo = tmp_path / "qwen-agent"
    benchmark_root = qwen_repo / "benchmark" / "deepplanning" / "shoppingplanning"
    python = qwen_repo / ".venv-deepplanning" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python3\n")
    (qwen_repo / ".git").mkdir()
    (qwen_repo / "benchmark" / "deepplanning").mkdir(parents=True)
    (qwen_repo / "benchmark" / "deepplanning" / "requirements.txt").write_text("pytest\n")
    (benchmark_root / "tools").mkdir(parents=True)
    (benchmark_root / "data").mkdir(parents=True)
    (benchmark_root / "database_level1" / "case_12").mkdir(parents=True)
    (benchmark_root / "database_level2" / "case_1").mkdir(parents=True)
    (benchmark_root / "database_level3" / "case_1").mkdir(parents=True)
    (benchmark_root / "tools" / "shopping_tool_schema.json").write_text("[]\n")
    for level in (1, 2, 3):
        (benchmark_root / "data" / f"level_{level}_query_meta.json").write_text("[]\n")
    monkeypatch.setenv("DEEPPLANNING_REPO", str(qwen_repo))

    report = _deepplanning_setup_report()

    assert report["missing"] == []
    assert "configured" in report["message"]
    assert report["deepplanning_repo"] == str(qwen_repo)
    assert report["deepplanning_python"] == str(python)


def test_mcpmark_setup_report_message_reflects_configured_repo(tmp_path, monkeypatch, mcpmark_runtime):
    mcpmark_repo = tmp_path / "mcpmark"
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    public_task = mcpmark_repo / "tasks" / "filesystem" / "standard" / "desktop" / "timeline_extraction"
    postgres_task = mcpmark_repo / "tasks" / "postgres" / "easy" / "employees" / "hiring_year_summary"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python3\n")
    (mcpmark_repo / ".git").mkdir()
    (mcpmark_repo / "pipeline.py").write_text("# fake mcpmark\n")
    (mcpmark_repo / "pyproject.toml").write_text("[project]\nname = 'fake-mcpmark'\n")
    public_task.mkdir(parents=True)
    postgres_task.mkdir(parents=True)
    for filename in ("description.md", "meta.json", "verify.py"):
        (public_task / filename).write_text("{}\n")
        (postgres_task / filename).write_text("{}\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_npx = fake_bin / "npx"
    fake_npx.write_text("#!/usr/bin/env sh\nexit 0\n")
    fake_npx.chmod(0o755)
    monkeypatch.setenv("MCPMARK_REPO", str(mcpmark_repo))
    monkeypatch.setenv("PATH", str(fake_bin))

    report = _mcpmark_setup_report()

    assert report["missing"] == []
    assert "configured" in report["message"]
    assert report["mcpmark_repo"] == str(mcpmark_repo)
    assert report["mcpmark_python"] == str(python)


def test_self_managed_benchmark_repos_satisfy_public_runner_interface(tmp_path, monkeypatch, mcpmark_runtime):
    tau_repo = tmp_path / "tau2-bench"
    tau_python = tau_repo / ".venv" / "bin" / "python"
    tau_python.parent.mkdir(parents=True)
    tau_python.write_text("#!/usr/bin/env python3\n")
    (tau_repo / "pyproject.toml").write_text("[project]\nname = 'fake-tau2'\n")

    qwen_repo = tmp_path / "qwen-agent"
    benchmark_root = qwen_repo / "benchmark" / "deepplanning" / "shoppingplanning"
    deepplanning_python = qwen_repo / ".venv-deepplanning" / "bin" / "python"
    deepplanning_python.parent.mkdir(parents=True)
    deepplanning_python.write_text("#!/usr/bin/env python3\n")
    (qwen_repo / ".git").mkdir()
    (qwen_repo / "benchmark" / "deepplanning").mkdir(parents=True)
    (qwen_repo / "benchmark" / "deepplanning" / "requirements.txt").write_text("pytest\n")
    (benchmark_root / "tools").mkdir(parents=True)
    (benchmark_root / "data").mkdir(parents=True)
    (benchmark_root / "database_level1" / "case_12").mkdir(parents=True)
    (benchmark_root / "database_level2" / "case_1").mkdir(parents=True)
    (benchmark_root / "database_level3" / "case_1").mkdir(parents=True)
    (benchmark_root / "tools" / "shopping_tool_schema.json").write_text("[]\n")
    for level in (1, 2, 3):
        (benchmark_root / "data" / f"level_{level}_query_meta.json").write_text("[]\n")

    mcpmark_repo = tmp_path / "mcpmark"
    mcpmark_python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    filesystem_task = mcpmark_repo / "tasks" / "filesystem" / "standard" / "desktop" / "timeline_extraction"
    postgres_task = mcpmark_repo / "tasks" / "postgres" / "easy" / "employees" / "hiring_year_summary"
    mcpmark_python.parent.mkdir(parents=True)
    mcpmark_python.write_text("#!/usr/bin/env python3\n")
    (mcpmark_repo / ".git").mkdir()
    (mcpmark_repo / "pipeline.py").write_text("# fake mcpmark\n")
    (mcpmark_repo / "pyproject.toml").write_text("[project]\nname = 'fake-mcpmark'\n")
    filesystem_task.mkdir(parents=True)
    postgres_task.mkdir(parents=True)
    for filename in ("description.md", "meta.json", "verify.py"):
        (filesystem_task / filename).write_text("{}\n")
        (postgres_task / filename).write_text("{}\n")
    (filesystem_task / "meta.json").write_text(
        '{"category_id":"desktop","task_id":"timeline_extraction","mcp":["filesystem"]}\n'
    )
    (postgres_task / "meta.json").write_text(
        '{"category_id":"employees","task_id":"hiring_year_summary","mcp":["postgres"]}\n'
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_npx = fake_bin / "npx"
    fake_npx.write_text("#!/usr/bin/env sh\nexit 0\n")
    fake_npx.chmod(0o755)

    monkeypatch.setenv("TAU2_REPO", str(tau_repo))
    monkeypatch.setenv("DEEPPLANNING_REPO", str(qwen_repo))
    monkeypatch.setenv("MCPMARK_REPO", str(mcpmark_repo))
    monkeypatch.setenv("PATH", str(fake_bin))

    backend = OfficialPublicBackend()

    tau_env = backend.create_environment("tau2_airline", {"case_id": "3", "case_key": "tau2_3"})
    deepplanning_env = backend.create_environment(
        "deepplanning",
        {"case_id": "shopping/level_1/case_12", "case_key": "dp_shop_12"},
    )
    mcpmark_env = backend.create_environment(
        "mcpmark",
        {
            "case_id": "filesystem/desktop/timeline_extraction",
            "case_key": "mcp_fs_timeline",
            "official_task_path": "filesystem/standard/desktop/timeline_extraction",
        },
    )

    assert isinstance(tau_env, OfficialTau2AirlineEnvironment)
    assert isinstance(deepplanning_env, OfficialDeepPlanningEnvironment)
    assert isinstance(mcpmark_env, OfficialMCPMarkEnvironment)


def test_mcpmark_postgres_runtime_report_accepts_podman_only(tmp_path, monkeypatch):
    mcpmark_repo = tmp_path / "mcpmark"
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    postgres_mcp = mcpmark_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    python.parent.mkdir(parents=True)
    postgres_mcp.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python3\n")
    postgres_mcp.write_text("#!/usr/bin/env sh\nexit 0\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("podman", "psql", "createdb", "pg_restore"):
        executable = fake_bin / command
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    report = _mcpmark_postgres_runtime_report(
        {
            "mcpmark_repo": str(mcpmark_repo),
            "mcpmark_python": str(python),
            "missing": [],
            "found": {},
        }
    )

    assert report["missing"] == []
    assert report["found"]["mcpmark_postgres_container_runtime"] is True
    assert report["found"]["mcpmark_postgres_container_runtime_name"] == "podman"


def test_mcpmark_postgres_runtime_report_rejects_stopped_container_daemon(tmp_path, monkeypatch):
    mcpmark_repo = tmp_path / "mcpmark"
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    postgres_mcp = mcpmark_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    python.parent.mkdir(parents=True)
    postgres_mcp.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python3\n")
    postgres_mcp.write_text("#!/usr/bin/env sh\nexit 0\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n")
    docker.chmod(0o755)
    for command in ("psql", "createdb", "pg_restore"):
        executable = fake_bin / command
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    report = _mcpmark_postgres_runtime_report(
        {
            "mcpmark_repo": str(mcpmark_repo),
            "mcpmark_python": str(python),
            "missing": [],
            "found": {},
        }
    )

    assert "mcpmark_postgres_container_runtime_ready" in report["missing"]
    assert report["found"]["mcpmark_postgres_container_runtime"] is True
    assert report["found"]["mcpmark_postgres_container_runtime_ready"] is False


def test_mcpmark_postgres_runtime_report_rejects_unreachable_postgres_service(tmp_path, monkeypatch):
    mcpmark_repo = tmp_path / "mcpmark"
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    postgres_mcp = mcpmark_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    python.parent.mkdir(parents=True)
    postgres_mcp.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python3\n")
    postgres_mcp.write_text("#!/bin/sh\nexit 0\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("podman", "createdb", "pg_restore"):
        executable = fake_bin / command
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    psql = fake_bin / "psql"
    psql.write_text("#!/bin/sh\nexit 2\n")
    psql.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    report = _mcpmark_postgres_runtime_report(
        {
            "mcpmark_repo": str(mcpmark_repo),
            "mcpmark_python": str(python),
            "missing": [],
            "found": {},
        }
    )

    assert "mcpmark_postgres_database_connection" in report["missing"]
    assert report["found"]["mcpmark_postgres_database_connection"] is False


def test_mcpmark_filesystem_adapter_normalizes_relative_tool_paths(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()

    normalized = normalize_filesystem_tool_arguments(
        {
            "path": "task.txt",
            "source": "drafts/input.md",
            "destination": "timeline.txt",
            "paths": ["a.txt", str(root / "already_absolute.txt")],
        },
        root,
    )

    assert normalized["path"] == str(root / "task.txt")
    assert normalized["source"] == str(root / "drafts" / "input.md")
    assert normalized["destination"] == str(root / "timeline.txt")
    assert normalized["paths"] == [str(root / "a.txt"), str(root / "already_absolute.txt")]


def test_official_mcpmark_environment_drives_subprocess_adapter(tmp_path, monkeypatch, mcpmark_runtime):
    mcpmark_repo = tmp_path / "mcpmark"
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    public_task = mcpmark_repo / "tasks" / "filesystem" / "standard" / "desktop" / "timeline_extraction"
    postgres_task = mcpmark_repo / "tasks" / "postgres" / "easy" / "employees" / "hiring_year_summary"
    python.parent.mkdir(parents=True)
    python.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json",
                "import sys",
                "for line in sys.stdin:",
                "    request = json.loads(line)",
                "    command = request['command']",
                "    if command == 'start':",
                "        result = {'case_id': request['case_id'], 'official_task_path': request.get('case', {}).get('official_task_path'), 'instruction': 'fake filesystem task', 'test_directory': '/tmp/fake-mcpmark'}",
                "    elif command == 'tools':",
                "        result = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}]",
                "    elif command == 'observe':",
                "        result = {'case_id': 'filesystem/desktop/timeline_extraction', 'instruction': 'fake filesystem task'}",
                "    elif command == 'execute_tool':",
                "        result = {'tool_name': request['tool_name'], 'arguments': request['tool_arguments']}",
                "    elif command == 'score':",
                "        result = {'status': 'scored_success', 'grading_score': 1.0, 'analysis_score': 1.0, 'max_score': 1.0, 'reward': 1.0, 'max_reward': 1.0, 'details': {'score_source': 'fake_mcpmark'}}",
                "    elif command == 'close':",
                "        result = {'closed': True}",
                "    else:",
                "        raise RuntimeError(command)",
                "    print(json.dumps({'ok': True, 'result': result}), flush=True)",
                "    if command == 'close':",
                "        break",
            ]
        )
    )
    python.chmod(0o755)
    (mcpmark_repo / ".git").mkdir()
    (mcpmark_repo / "pipeline.py").write_text("# fake mcpmark\n")
    (mcpmark_repo / "pyproject.toml").write_text("[project]\nname = 'fake-mcpmark'\n")
    public_task.mkdir(parents=True)
    postgres_task.mkdir(parents=True)
    for filename in ("description.md", "meta.json", "verify.py"):
        (public_task / filename).write_text("{}\n")
        (postgres_task / filename).write_text("{}\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_npx = fake_bin / "npx"
    fake_npx.write_text("#!/usr/bin/env sh\nexit 0\n")
    fake_npx.chmod(0o755)
    monkeypatch.setenv("MCPMARK_REPO", str(mcpmark_repo))
    monkeypatch.setenv("PATH", str(fake_bin))

    env = OfficialMCPMarkEnvironment(
        {
            "case_id": "filesystem/legal_document/contract_dates",
            "official_task_path": "filesystem/standard/legal_document/contract_dates",
            "case_key": "mcp_fs_contract_dates",
            "description": "fake",
        }
    )
    env.configure_limits({"case_timeout_sec": 55})
    env.start()
    try:
        assert env.tools()[0]["function"]["name"] == "read_file"
        observation = env.observe()
        assert observation["instruction"] == "fake filesystem task"
        assert env.execute_tool("read_file", {"path": "notes.txt"}) == {
            "tool_name": "read_file",
            "arguments": {"path": "notes.txt"},
        }
        score = env.score("done")
    finally:
        env.close()

    assert score.status == "scored_success"
    assert score.reward == 1.0
    assert score.grading_score == 1.0
    assert score.analysis_score == 1.0
    assert score.details["score_source"] == "fake_mcpmark"


def test_official_mcpmark_environment_drives_postgres_subprocess_adapter(tmp_path, monkeypatch, mcpmark_runtime):
    mcpmark_repo = tmp_path / "mcpmark"
    python = mcpmark_repo / ".venv-mcpmark" / "bin" / "python"
    filesystem_task = mcpmark_repo / "tasks" / "filesystem" / "standard" / "desktop" / "timeline_extraction"
    postgres_task = mcpmark_repo / "tasks" / "postgres" / "easy" / "employees" / "hiring_year_summary"
    python.parent.mkdir(parents=True)
    postgres_mcp = mcpmark_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    postgres_mcp.parent.mkdir(parents=True)
    postgres_mcp.write_text("#!/usr/bin/env sh\nexit 0\n")
    postgres_mcp.chmod(0o755)
    python.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json",
                "import sys",
                "for line in sys.stdin:",
                "    request = json.loads(line)",
                "    command = request['command']",
                "    if command == 'start':",
                "        result = {'case_id': request['case_id'], 'official_task_path': request.get('case', {}).get('official_task_path'), 'instruction': 'fake postgres task', 'database': 'mcpmark_fake'}",
                "    elif command == 'tools':",
                "        result = [{'type': 'function', 'function': {'name': 'query_database', 'parameters': {'type': 'object'}}}]",
                "    elif command == 'observe':",
                "        result = {'case_id': 'postgres/easy/employees/hiring_year_summary', 'instruction': 'fake postgres task', 'database': 'mcpmark_fake'}",
                "    elif command == 'execute_tool':",
                "        result = {'tool_name': request['tool_name'], 'arguments': request['tool_arguments']}",
                "    elif command == 'score':",
                "        result = {'status': 'scored_failure', 'grading_score': 0.0, 'analysis_score': 0.0, 'max_score': 1.0, 'reward': 0.0, 'max_reward': 1.0, 'details': {'score_source': 'fake_mcpmark_pg'}}",
                "    elif command == 'close':",
                "        result = {'closed': True}",
                "    else:",
                "        raise RuntimeError(command)",
                "    print(json.dumps({'ok': True, 'result': result}), flush=True)",
                "    if command == 'close':",
                "        break",
            ]
        )
    )
    python.chmod(0o755)
    (mcpmark_repo / ".git").mkdir()
    (mcpmark_repo / "pipeline.py").write_text("# fake mcpmark\n")
    (mcpmark_repo / "pyproject.toml").write_text("[project]\nname = 'fake-mcpmark'\n")
    filesystem_task.mkdir(parents=True)
    postgres_task.mkdir(parents=True)
    for filename in ("description.md", "meta.json", "verify.py"):
        (filesystem_task / filename).write_text("{}\n")
        (postgres_task / filename).write_text("{}\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("node", "docker", "psql", "createdb", "pg_restore"):
        executable = fake_bin / command
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    monkeypatch.setenv("MCPMARK_REPO", str(mcpmark_repo))
    monkeypatch.setenv("PATH", str(fake_bin))

    env = OfficialMCPMarkEnvironment(
        {
            "case_id": "postgres/easy/employees/hiring_year_summary",
            "official_task_path": "postgres/easy/employees/hiring_year_summary",
            "case_key": "mcp_pg_hiring_year_summary",
            "description": "fake",
        }
    )
    env.configure_limits({"case_timeout_sec": 55})
    env.start()
    try:
        assert env.tools()[0]["function"]["name"] == "query_database"
        assert env.observe()["database"] == "mcpmark_fake"
        assert env.execute_tool("query_database", {"query": "select 1"}) == {
            "tool_name": "query_database",
            "arguments": {"query": "select 1"},
        }
        score = env.score("done")
    finally:
        env.close()

    assert score.status == "scored_failure"
    assert score.grading_score == 0.0
    assert score.details["score_source"] == "fake_mcpmark_pg"


def test_official_deepplanning_environment_drives_subprocess_adapter(tmp_path, monkeypatch):
    qwen_repo = tmp_path / "qwen-agent"
    benchmark_root = qwen_repo / "benchmark" / "deepplanning" / "shoppingplanning"
    python = qwen_repo / ".venv-deepplanning" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "for line in sys.stdin:",
                "    request = json.loads(line)",
                "    command = request['command']",
                "    if command == 'start':",
                "        result = {'case_id': request['case_id'], 'query': 'fake shopping query'}",
                "    elif command == 'tools':",
                "        result = [{'type': 'function', 'function': {'name': 'search_products', 'parameters': {'type': 'object'}}}]",
                "    elif command == 'observe':",
                "        result = {'case_id': 'shopping/level_1/case_12', 'query': 'fake shopping query', 'cart': {'items': []}}",
                "    elif command == 'execute_tool':",
                "        result = {'tool_name': request['tool_name'], 'arguments': request['tool_arguments']}",
                "    elif command == 'score':",
                "        result = {'status': 'scored_success', 'grading_score': 0.5, 'analysis_score': 0.75, 'max_score': 1.0, 'reward': 0.5, 'max_reward': 1.0, 'details': {'score_source': 'fake_deepplanning'}}",
                "    elif command == 'close':",
                "        result = {'closed': True}",
                "    else:",
                "        raise RuntimeError(command)",
                "    print(json.dumps({'ok': True, 'result': result}), flush=True)",
                "    if command == 'close':",
                "        break",
            ]
        )
    )
    python.chmod(0o755)
    (qwen_repo / ".git").mkdir()
    (qwen_repo / "benchmark" / "deepplanning").mkdir(parents=True)
    (qwen_repo / "benchmark" / "deepplanning" / "requirements.txt").write_text("pytest\n")
    (benchmark_root / "tools").mkdir(parents=True)
    (benchmark_root / "data").mkdir(parents=True)
    for level in (1, 2, 3):
        (benchmark_root / "data" / f"level_{level}_query_meta.json").write_text("[]\n")
        (benchmark_root / f"database_level{level}").mkdir(parents=True)
    (benchmark_root / "tools" / "shopping_tool_schema.json").write_text("[]\n")
    monkeypatch.setenv("DEEPPLANNING_REPO", str(qwen_repo))

    env = OfficialDeepPlanningEnvironment(
        {"case_id": "shopping/level_1/case_12", "case_key": "dp_shop_12", "description": "fake"}
    )
    env.configure_limits({"case_timeout_sec": 55})
    env.start()
    try:
        assert env.tools()[0]["function"]["name"] == "search_products"
        assert env.observe()["query"] == "fake shopping query"
        assert env.execute_tool("search_products", {"query": "sneakers"}) == {
            "tool_name": "search_products",
            "arguments": {"query": "sneakers"},
        }
        score = env.score("done")
    finally:
        env.close()

    assert score.status == "scored_failure"
    assert score.reward == 0.0
    assert score.grading_score == 0.0
    assert score.analysis_score == 0.75
    assert score.max_score == 1.0
    assert score.details["score_source"] == "fake_deepplanning"


def test_official_tau2_airline_environment_runs_tau_repo_command(tmp_path, monkeypatch):
    _set_valid_tau2_llm_env(monkeypatch)
    tau_repo = tmp_path / "tau2-bench"
    bin_dir = tau_repo / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (tau_repo / "pyproject.toml").write_text("[project]\nname = 'fake-tau2'\n")
    fake_python = bin_dir / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import pathlib",
                "import sys",
                "save_to = pathlib.Path(sys.argv[sys.argv.index('--save-to') + 1])",
                "save_to.mkdir(parents=True, exist_ok=True)",
                "agent_events = pathlib.Path(__import__('os').environ['COURSE_TAU2_AGENT_TRAJECTORY'])",
                "agent_events.write_text('\\n'.join([",
                "    json.dumps({'event': 'request', 'request': {'benchmark': 'tau2_airline', 'case_id': '3'}}),",
                "    json.dumps({'event': 'response', 'response': {'kind': 'final', 'content': 'done'}}),",
                "]) + '\\n')",
                "(save_to / 'results.json').write_text(json.dumps({",
                "    'simulations': [{",
                "        'task_id': '3',",
                "        'reward_info': {'reward': 1.0},",
                "        'termination_reason': 'USER_STOP',",
                "    }],",
                "}))",
                "print(json.dumps({'argv': sys.argv}))",
            ]
        )
    )
    fake_python.chmod(0o755)
    monkeypatch.setenv("TAU2_REPO", str(tau_repo))
    monkeypatch.setenv("TAU2_USER_MODEL", "openai/fake-user")
    monkeypatch.setenv("TAU2_MAX_STEPS", "12")

    env = OfficialTau2AirlineEnvironment({"case_id": "3", "case_key": "tau2_3", "description": "fake"})
    env.configure_limits({"max_environment_steps": 123, "case_timeout_sec": 55})
    result = env.run()

    assert result.status == "scored_success"
    assert result.reward == 1.0
    assert result.grading_score == 1.0
    assert result.analysis_score == 1.0
    assert result.max_score == 1.0
    command_events = [event for event in result.events if event["event"] == "official_command"]
    assert command_events
    command = command_events[0]["command"]
    assert "--agent" in command
    assert "student_jsonl_agent" in command
    assert "--task-ids" in command
    assert "3" in command
    assert "--user-llm" in command
    assert "openai/fake-user" in command
    assert command[command.index("--max-steps") + 1] == "123"
    assert command[command.index("--timeout") + 1] == "55"
    assert any(
        event["event"] == "score"
        and event["reward"] == 1.0
        and event["grading_score"] == 1.0
        and event["analysis_score"] == 1.0
        for event in result.events
    )
    assert any(event["event"] == "tau2_agent_trajectory" and event["agent_event_count"] == 2 for event in result.events)
    assert any(
        event["event"] == "request" and event["request"]["benchmark"] == "tau2_airline"
        for event in result.events
    )
    assert any(
        event["event"] == "response" and event["response"]["content"] == "done"
        for event in result.events
    )


def test_official_tau2_partial_reward_is_analysis_only_not_grading(tmp_path, monkeypatch):
    _set_valid_tau2_llm_env(monkeypatch)
    tau_repo = tmp_path / "tau2-bench"
    bin_dir = tau_repo / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (tau_repo / "pyproject.toml").write_text("[project]\nname = 'fake-tau2'\n")
    fake_python = bin_dir / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import pathlib",
                "import sys",
                "save_to = pathlib.Path(sys.argv[sys.argv.index('--save-to') + 1])",
                "save_to.mkdir(parents=True, exist_ok=True)",
                "(save_to / 'results.json').write_text(json.dumps({",
                "    'simulations': [{",
                "        'task_id': '3',",
                "        'reward_info': {'reward': 0.5},",
                "    }],",
                "}))",
            ]
        )
    )
    fake_python.chmod(0o755)
    monkeypatch.setenv("TAU2_REPO", str(tau_repo))

    result = OfficialTau2AirlineEnvironment({"case_id": "3", "case_key": "tau2_3"}).run()

    assert result.status == "scored_failure"
    assert result.grading_score == 0.0
    assert result.reward == 0.0
    assert result.analysis_score == 0.5


def test_tau2_subprocess_env_uses_shared_course_key_for_user_simulator_and_agent(monkeypatch):
    monkeypatch.setenv("COURSE_API_KEY", "shared-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-02-01-preview")
    monkeypatch.setenv("OPENAI_API_KEY", "stale-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://hkust.azure-api.net/hkust-genai/v1")
    monkeypatch.setenv("AZURE_API_KEY", "stale-azure-key")
    monkeypatch.delenv("AZURE_API_BASE", raising=False)
    monkeypatch.delenv("AZURE_API_VERSION", raising=False)

    env = _tau2_subprocess_env("3")

    assert env["TAU2_CURRENT_TASK_ID"] == "3"
    assert env["OPENAI_API_KEY"] == "shared-key"
    assert env["OPENAI_BASE_URL"] == "https://hkust.azure-api.net/hkust-genai/v1"
    assert {"AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_API_KEY",
            "AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"}.isdisjoint(env)


def test_official_tau2_reports_missing_llm_env_before_subprocess(tmp_path, monkeypatch):
    tau_repo = tmp_path / "tau2-bench"
    python = tau_repo / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("# This test must fail before launching Python.\n")
    (tau_repo / "pyproject.toml").write_text("[project]\nname = 'fake-tau2'\n")
    monkeypatch.setenv("TAU2_REPO", str(tau_repo))
    monkeypatch.setenv("COURSE_API_KEY", "replace-with-your-course-api-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = OfficialTau2AirlineEnvironment({"case_id": "3", "case_key": "tau2_3"}).run()

    assert result.status == "official_setup_error"
    errors = [event for event in result.events if event["event"] == "error"]
    assert errors[-1]["error_type"] == "Tau2LLMEnvironmentError"
    assert "source env.student.local.sh" in errors[-1]["message"]
    assert "COURSE_API_KEY" in errors[-1]["message"]
    assert "OPENAI_BASE_URL" in errors[-1]["message"]


def test_tau2_default_user_simulator_model_is_4o_mini(tmp_path, monkeypatch):
    monkeypatch.delenv("TAU2_USER_MODEL", raising=False)

    argv = _tau2_command(tmp_path / "tau2-bench", "3", tmp_path / "out")

    assert argv[argv.index("--user-llm") + 1] == "openai/gpt-4o-mini"


def test_tau2_genai_preflight_rejects_stale_azure_model(monkeypatch):
    from public_runner.envs.official import _tau2_llm_env_error

    _set_valid_tau2_llm_env(monkeypatch)
    monkeypatch.setenv("TAU2_USER_MODEL", "azure/gpt-4o-mini")
    assert "TAU2_USER_MODEL" in _tau2_llm_env_error()
    assert "openai/" in _tau2_llm_env_error()


def test_tau2_task_limits_survive_minimal_env(tmp_path, monkeypatch):
    for name in ("TAU2_USER", "TAU2_MAX_STEPS", "TAU2_TIMEOUT", "TAU2_USER_LLM_ARGS"):
        monkeypatch.delenv(name, raising=False)
    limits = {"case_timeout_sec": 90, "max_environment_steps": 200, "llm_max_attempts": 2}
    argv = _tau2_command(tmp_path / "tau2-bench", "3", tmp_path / "out", limits)
    assert argv[argv.index("--user") + 1] == "user_simulator"
    assert argv[argv.index("--timeout") + 1] == "90"
    assert argv[argv.index("--max-steps") + 1] == "200"
    assert json.loads(argv[argv.index("--agent-llm-args") + 1])["limits"] == limits
    assert json.loads(argv[argv.index("--user-llm-args") + 1]) == {"temperature": 0.0, "timeout": 300}


def test_tau2_command_defaults_to_course_timeout(tmp_path, monkeypatch):
    monkeypatch.delenv("TAU2_TIMEOUT", raising=False)
    monkeypatch.delenv("COURSE_AGENT_PROCESS_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("TAU2_USER_LLM_ARGS", raising=False)

    argv = _tau2_command(tmp_path / "tau2-bench", "3", tmp_path / "out")

    assert argv[argv.index("--timeout") + 1] == "300"
    agent_args = json.loads(argv[argv.index("--agent-llm-args") + 1])
    user_args = json.loads(argv[argv.index("--user-llm-args") + 1])
    assert agent_args["timeout"] == 300
    assert user_args["timeout"] == 300


def test_tau2_command_event_redacts_llm_args_secrets():
    command = [
        "python",
        "entry.py",
        "--user-llm-args",
        '{"api_key":"secret","temperature":0}',
        "--agent-llm-args",
        '{"timeout":10}',
    ]

    redacted = _redact_command(command)

    assert "secret" not in json.dumps(redacted)
    assert '"api_key": "<redacted>"' in redacted[redacted.index("--user-llm-args") + 1]
    assert '"temperature": 0' in redacted[redacted.index("--user-llm-args") + 1]


def test_official_tau2_airline_environment_preserves_process_events_on_result_parse_error(tmp_path, monkeypatch):
    _set_valid_tau2_llm_env(monkeypatch)
    tau_repo = tmp_path / "tau2-bench"
    bin_dir = tau_repo / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (tau_repo / "pyproject.toml").write_text("[project]\nname = 'fake-tau2'\n")
    fake_python = bin_dir / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import pathlib",
                "import sys",
                "save_to = pathlib.Path(sys.argv[sys.argv.index('--save-to') + 1])",
                "save_to.mkdir(parents=True, exist_ok=True)",
                "(save_to / 'results.json').write_text(json.dumps({'simulations': [{'task_id': '3'}]}))",
            ]
        )
    )
    fake_python.chmod(0o755)
    monkeypatch.setenv("TAU2_REPO", str(tau_repo))

    env = OfficialTau2AirlineEnvironment({"case_id": "3", "case_key": "tau2_3", "description": "fake"})
    result = env.run()

    assert result.status == "official_runtime_error"
    assert any(event["event"] == "official_process" and event["returncode"] == 0 for event in result.events)
    assert any(event["event"] == "error" and event["error_type"] == "OfficialTau2ResultError" for event in result.events)
