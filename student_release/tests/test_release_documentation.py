from pathlib import Path


COURSE_ROOT = Path(__file__).resolve().parents[2]


def test_course_readme_documents_grading_baseline_and_locked_interfaces():
    readme = (COURSE_ROOT / "README.md").read_text()
    student_readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "AlmaLinux 9.8" in readme
    assert "tested on a macOS MacBook" in readme
    assert "macOS MacBook" in student_readme
    assert "student_release/public_runner/" in readme
    assert "src/course_agent/student_agent.py" in readme
    assert "student_tools" in readme
    assert "COURSE_API_KEY" in readme
    assert "HKUST GenAI" in readme
    assert "student_release/README.md" in readme
    assert "export TAU2_REPO=/absolute/path/to/tau2-bench" in readme
    assert "export DEEPPLANNING_REPO=/absolute/path/to/qwen-agent" in readme
    assert "export MCPMARK_REPO=/absolute/path/to/mcpmark" in readme
    assert "uv run --locked" in readme
    assert ".venv/bin/python" in student_readme
    assert "third_party/README.md" in readme
    assert "locked runner and protocol interfaces" in readme
    assert "bash third_party/setup_tau2_bench.sh" not in readme
    assert "bash third_party/setup_deepplanning.sh" not in readme


def test_student_readme_documents_dependency_lock_constraints():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "macOS MacBook" in readme
    assert "uv.lock" in readme
    assert "pyproject.toml" in readme
    assert "pure-Python or prebuilt wheels" in readme
    assert "large model weights" in readme
    assert "compile native extensions" in readme
    assert "`build_submission.py` checks this policy" in readme
    assert "build_submission.py" in readme
    assert "src/course_agent/student_agent.py" in readme
    assert "src/course_agent/student_tools/" in readme
    assert "public_runner/" in readme
    assert "baseline_agent.py" not in readme
    assert "only `student_agent.py` and files you add under" in readme


def test_student_readme_documents_student_agent_template_contract():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "Keep the class name" in readme
    assert "`respond`" in readme
    assert "`llm_client`" in readme
    assert "solve_mcpmark(self, request)" in readme
    assert "solve_tau2_airline(self, request)" in readme
    assert "solve_deepplanning(self, request)" in readme
    assert "public runner imports `course_agent.student_agent.StudentAgent`" in readme
    assert "tool_call" in readme and "tool_calls" in readme and "final" in readme
    assert "##### LOCKED COURSE INTERFACE" in readme
    assert "##### STUDENT-DESIGNED BENCHMARK LOGIC" in readme


def test_student_readme_explains_local_smoke_scope():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "smoke_local.py" in readme
    assert "does not check official benchmark environments" in readme
    assert "agent_process" in readme
    assert "task_configs/public_cases.json" in readme


def test_internal_baseline_agent_is_not_student_facing_documentation():
    assert not (COURSE_ROOT / "student_release" / "src" / "course_agent" / "baseline_agent.py").exists()
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()
    assert "baseline_agent.py" not in readme


def test_student_readme_documents_template_llm_interaction_scope():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "starter template does not implement benchmark strategy" in readme
    assert "CourseLLMClient" in readme
    assert "schema-valid placeholder" in readme
    assert "LLM" in readme and "connection failures" in readme
    assert "runtime/error events" in readme


def test_student_readme_documents_task_config_and_trajectory_contracts():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "public_cases.json and hidden_cases.json use the same schema" in readme
    assert "request, response, tool_result, score, and" in readme
    assert "error events" in readme
    assert "sidecar JSONL of StudentAgent request/response/error events" in readme
    assert "tau2 agent event count of" in readme
    assert "`0`" in readme
    assert "case_analysis.json" in readme
    assert "runtime_issue" in readme
    assert "issue_category" in readme
    assert "case_results.jsonl" in readme
    assert "score_summary.json" in readme
    assert "trajectory_llm_usage.jsonl" in readme
    assert "CourseLLMClient" in readme
    assert "benchmark-side user" in readme
    assert "simulator LLM is not counted" in readme
    assert "By default, each run writes a new batch under" in readme
    assert "`trajectories/<run_id>/` inside `student_release/`" in readme
    assert "Use `--output-root` to write" in readme
    assert "See `../shared/trajectory_schema.md`" in readme
    assert "Automatic resume is triggered when you rerun the same assignment" in readme
    assert "Students usually do not need a resume flag" in readme


def test_student_readme_documents_public_runner_usage_and_workers():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "public_runner/run_public_tasks.py" in readme
    assert "run-tasks" in readme
    assert ".venv/bin/python cli.py --help" in readme
    assert "--backend simplified" in readme
    assert "--backend official" in readme
    assert "--benchmark tau2_airline" in readme
    assert "--case tau2_airline:tau2_49" in readme
    assert "benchmark:case_key" in readme
    assert "--max-workers 2" in readme
    assert "MCPMark cases take an internal runner lock" in readme
    assert "tau2 and DeepPlanning cases may still run concurrently" in readme
    assert "COURSE_RUNNER_LOCK_DIR" in readme
    assert "Keep `--max-workers 1`" in readme
    assert "LLM/API throttling" in readme


def test_student_readme_documents_tool_call_policy():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "does not reorder calls for you" in readme
    assert "Read-only tool calls must come before mutating tool calls" in readme
    assert "Terminal tools cannot be combined" in readme
    assert "ToolCallLimitExceeded" in readme
    assert "student_runtime_error" in readme
    assert "splitting" in readme and "work across later turns" in readme
    assert "respond_to_user" in readme
    assert "submit_plan" in readme
    assert "readOnlyHint" in readme


def test_student_readme_documents_binary_grading_and_analysis_score():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "`grading_score` | `0.0` or `1.0`" in readme
    assert "binary `grading_score`" in readme
    assert "`analysis_score` keeps the benchmark's own feedback value" in readme
    assert "`total_grading_score` is the sum of binary per-case `grading_score` values" in readme
    assert "`average_grading_score` is `total_grading_score / completed_cases`" in readme
    assert "`scoring.baseline_anchors`" in readme
    assert "reference-only benchmark-level average scores" in readme
    assert "comparable public/hidden case sets" in readme
    assert "contextualize baseline difficulty" in readme
    assert "tau2 official `reward_info.reward`" in readme
    assert "DeepPlanning Shopping official `score`" in readme


def test_shared_trajectory_schema_matches_runner_outputs():
    schema = (COURSE_ROOT / "shared" / "trajectory_schema.md").read_text()

    assert "case_analysis.json" in schema
    assert "one JSON object per case attempt" in schema
    assert "a retried case can have multiple rows" in schema
    assert "skips" in schema and "latest result is not retryable" in schema
    assert "resume counters, and max worker count" in schema
    assert "run-tasks --output-root <path>" in schema
    assert "relative paths are resolved from `course_project/student_release/`" in schema
    assert "attempt_2.jsonl" in schema
    assert "`grading_score` is the course grading value and is binary" in schema
    assert "`analysis_score` is feedback-only diagnostic information" in schema
    assert "`runtime_issue` is `true` only for statuses ending in `_error`" in schema
    assert "`score_summary.json` includes `selected_cases`, `completed_cases`" in schema
    assert "trajectory_llm_usage.jsonl" in schema
    assert "`attempt_{n}_llm_usage.jsonl`" in schema
    assert "`llm_total_tokens`" in schema
    assert "tau2's" in schema and "benchmark-side user simulator LLM" in schema
    assert "cost estimates require an external model price" in schema
    assert "table" in schema
    assert "single automatic retry" in schema
    assert "runtime/setup errors" in schema
    assert "`total_grading_score` is the sum of binary per-case `grading_score` values" in schema
    assert "`average_grading_score` is `total_grading_score / completed_cases`" in schema
    assert "`scoring.baseline_anchors`" in schema
    assert "contextualize" in schema and "baseline difficulty" in schema


def test_student_facing_docs_do_not_promise_preview_service():
    student_readme = (COURSE_ROOT / "student_release" / "README.md").read_text()
    key_policy = (COURSE_ROOT / "shared" / "key_ownership_policy.md").read_text()

    combined = f"{student_readme}\n{key_policy}"
    forbidden = [
        "Preview jobs",
        "School Preview",
        "preview service",
        "student-owned preview",
        "preview credential",
        "HTTP/HTTPS",
    ]
    for phrase in forbidden:
        assert phrase not in combined
    assert not (COURSE_ROOT / "shared" / "key_and_preview_policy.md").exists()


def test_student_readme_documents_tau2_llm_env_preflight():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "## Experiment Setup" in readme
    assert "Replace only the API key" in readme
    assert "export COURSE_API_KEY=..." in readme
    assert "OPENAI_BASE_URL=https://hkust.azure-api.net/hkust-genai/v1" in readme
    assert "TAU2_USER_MODEL=openai/gpt-4o-mini" in readme
    assert "the runner finds them automatically" in readme
    assert "No benchmark path\nexports are required" in readme
    assert "export TAU2_REPO=/absolute/path/to/tau2-bench" in readme
    assert "export DEEPPLANNING_REPO=/absolute/path/to/qwen-agent" in readme
    assert "export MCPMARK_REPO=/absolute/path/to/mcpmark" in readme
    assert "Tau2LLMEnvironmentError" in readme
    assert "COURSE_API_KEY" in readme
    assert "api-key" in readme
    assert "limits=request.limits" in readme
    assert "For official public runs, set up benchmark environments from the course root" in readme
    assert "bash third_party/setup_tau2_bench.sh" in readme
    assert "bash third_party/setup_deepplanning.sh" in readme
    assert "bash third_party/setup_mcpmark.sh" in readme
    assert "MCPMark" in readme and "`filesystem`/`postgres` subset" in readme
    assert "`../third_party/README.md` for pinned versions" in readme


def test_student_readme_documents_submission_build_checks():
    readme = (COURSE_ROOT / "student_release" / "README.md").read_text()

    assert "cp submission.example.json submission.json" in readme
    assert "student_id" in readme and "student_name" in readme and "email" in readme
    assert "submission_build_log.json" in readme
    assert "uv lock --check" in readme
    assert "smoke_local.py" in readme
    assert "--backend simplified" in readme
    assert "50 MB" in readme
    assert "300 MB" in readme
    assert "git/url/path" in readme
    assert "source-only packages" in readme
    assert "submission.zip" in readme


def test_third_party_readme_documents_cross_platform_version_policy():
    readme = (COURSE_ROOT / "third_party" / "README.md").read_text()

    assert "tested on a macOS MacBook" in readme
    assert "virtualenv paths, data files, services, and environment" in readme
    assert "Benchmark version policy" in readme
    assert "Host utilities are self-managed" in readme
    assert "AlmaLinux 9.8 (Olive Jaguar)" in readme
    assert "Podman" in readme
    assert "public_runner" in readme
    assert "TAU2_REPO" in readme
    assert "DEEPPLANNING_REPO" in readme
    assert "MCPMARK_REPO" in readme
    assert "Course-Provided Setup Scripts" in readme
    assert "Self-Managed Minimum Contract" in readme
    assert "Do not patch benchmark APIs" in readme
    assert "Benchmark-side readiness checks" in readme
    assert "do not validate student LLM credentials" in readme
    assert "For full local readiness" in readme
    assert "export TAU2_REPO=" in readme
    assert "export DEEPPLANNING_REPO=/absolute/path/to/qwen-agent" in readme
    assert "export MCPMARK_REPO=/absolute/path/to/mcpmark" in readme
    assert "export POSTGRES_HOST=localhost" in readme
    assert "export MCPMARK_CONTAINER_RUNTIME=docker" in readme
    assert "you do not" in readme
    assert "need to export the variables below" in readme
    assert "Override them only when your self-managed Postgres" in readme
    assert "service differs" in readme
    assert "Hostname used by the runner and MCPMark Postgres state manager" in readme
    assert "also used as `PGPASSWORD` during runner preflight" in readme
    assert "You do not need to restart Docker, Podman, or the Postgres container for every" in readme
    assert "per-case temporary database" in readme
    assert "leftover `mcpmark_%` databases" in readme
    assert "serializes official MCPMark cases with a host-level" in readme
    assert "bypass `public_runner`" in readme
    assert "bash third_party/setup_tau2_bench.sh --check-only" in readme
    assert "bash third_party/check_mcpmark_runtimes.sh all" in readme
    assert "Docker or Podman daemon is running" in readme
    assert "Running Public Official Cases" not in readme
