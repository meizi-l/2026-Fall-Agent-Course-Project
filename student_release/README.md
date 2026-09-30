# Course Agent Project Student Release

This package is the student-facing starter for the course agent project.

The release has been tested on a macOS MacBook during development. Students may
use other machines, but official benchmark runs require benchmark environments
that match the paths, data layout, and environment variables expected by the
locked `public_runner` and `course_agent` interface.

## What You Build

Implement `StudentAgent` in `src/course_agent/student_agent.py`. The runner
calls your agent once per step with the current observation, available tools,
and limits.

The starter template is separated into sections such as
`##### LOCKED COURSE INTERFACE`, `##### RESPONSE SCHEMA REQUIREMENTS`,
`##### OPTIONAL COURSE HELPERS`, `##### STUDENT-DESIGNED BENCHMARK LOGIC`, and
`##### ADD YOUR OWN HELPERS`. Keep the class name `StudentAgent`, `respond`,
`llm_client`, and the three solver method signatures:

- `solve_mcpmark(self, request)`
- `solve_tau2_airline(self, request)`
- `solve_deepplanning(self, request)`

You may replace the solver bodies, add state in `__init__`, add helper methods,
and add helper modules under `src/course_agent/student_tools/`. Return only the
course response schema from `course_agent.protocol.AgentResponse`: `tool_call`,
`tool_calls`, or `final`.

The starter template does not implement benchmark strategy. It returns
schema-valid placeholder responses so smoke tests can load the course JSONL
interface. Your submitted behavior should live in `student_agent.py` and any
helpers you add. The public runner imports `course_agent.student_agent.StudentAgent`.

You may edit:

- `src/course_agent/student_agent.py`
- `src/course_agent/student_tools/`, if you add helper code for your agent
- `pyproject.toml` and `uv.lock`, if you need extra Python dependencies

Do not modify `cli.py`, `public_runner/`, `public_runner/envs/`, protocol/runtime files
under `src/course_agent/`, or benchmark setup code. Staff grading uses the
locked course runner and hidden task configs to call your submitted agent.
Under `src/course_agent/`, only `student_agent.py` and files you add under
`student_tools/` are intended for student changes.

## Install

Install `uv` first; the course release uses `uv.lock` so student and staff
machines resolve the same student-side dependencies.

```bash
uv --version
uv sync --locked
```

The tested student runtime uses Python `3.11` from `course_project/.python-version`.
When experimenting, use either `uv run --locked ...` or the created
`.venv/bin/python` directly.

If you add packages, update both `pyproject.toml` and `uv.lock` before
submitting. Staff grading installs from your submitted lock file, so dependencies
must be practical on the grading server. Prefer pure-Python or prebuilt wheels
for Linux x86_64 and macOS. Avoid dependencies that compile native extensions
during grading, require system package installs, download large model weights,
need GPUs, or contact external services at install time. If `uv sync --locked`
is slow, fragile, or host-specific on a clean machine, it is risky for grading.
`build_submission.py` checks this policy before writing `submission.zip`: it
requires `uv.lock` to match `pyproject.toml`, rejects git/url/path dependencies,
rejects source-only packages without wheels, rejects any locked artifact over
50 MB, and rejects dependency sets whose estimated minimum download exceeds
300 MB.

## Experiment Setup

For real LLM-backed runs, copy and edit the local environment file:

```bash
cp env.student.sh.example env.student.local.sh
```

At minimum, replace these required values:

```bash
export COURSE_API_KEY=...
export AZURE_OPENAI_ENDPOINT=...
export AZURE_OPENAI_API_VERSION=...
```

Then source the file before running official public cases:

```bash
source env.student.local.sh
```

Do not submit `env.student.local.sh`. Final grading uses staff/course-owned
credentials.

The starter includes `course_agent.runtime.CourseLLMClient`, a synchronous
OpenAI SDK wrapper. It reads `COURSE_API_KEY`, `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_API_VERSION`, `COURSE_LLM_MODEL`, timeout/token limits, and
`COURSE_LLM_MAX_ATTEMPTS` from the environment before making chat-completion
calls. The starter template itself does not implement benchmark strategy or make
LLM calls by default; after you design your agent, real LLM connection failures
are recorded as runtime/error events.

The template also configures tau2's LLM user simulator:

- `TAU2_REPO` points to the tau2-bench checkout.
- `TAU2_USER_MODEL=azure/gpt-4o-mini` uses the school Azure gateway through
  LiteLLM's Azure provider form.
- `TAU2_USER_LLM_ARGS` holds non-secret simulator settings such as temperature
  and timeout. Do not put API keys in this value because command arguments are
  recorded in trajectories.
- `TAU2_MAX_STEPS` and `TAU2_TIMEOUT` bound tau2 simulator runs.

Tau2 official runs check the LLM environment before starting the simulator. If
`COURSE_API_KEY`, `AZURE_OPENAI_ENDPOINT`, or `AZURE_OPENAI_API_VERSION` is
missing or still uses the template placeholder, the run records
`Tau2LLMEnvironmentError`.

For benchmark environments, the course-managed defaults are:

```bash
export TAU2_REPO=../third_party/tau2-bench
export DEEPPLANNING_REPO=../third_party/qwen-agent
export MCPMARK_REPO=../third_party/mcpmark
```

If you self-manage benchmark checkouts elsewhere, set those variables to
absolute paths. The checkouts must keep the pinned versions, virtualenv paths,
data files, and services described in `../third_party/README.md`; do not patch
`public_runner` or `course_agent` to make a local benchmark setup work.

For official public runs, set up benchmark environments from the course root:

```bash
cd ..
bash third_party/setup_tau2_bench.sh
bash third_party/setup_deepplanning.sh
bash third_party/setup_mcpmark.sh
bash third_party/install_mcpmark_system_deps.sh --local-node --install
bash third_party/check_mcpmark_runtimes.sh all
cd student_release
```

This course uses tau2 Airline, DeepPlanning Shopping, and the MCPMark
`filesystem`/`postgres` subset. The commands above are the course-provided setup
path; self-managed environments are also acceptable when they expose the same
repo paths, virtualenv paths, data files, and services. See
`../third_party/README.md` for pinned versions, host utilities, Postgres/Docker
or Podman notes, and benchmark-side readiness checks.

## Smoke Test

```bash
uv run --locked python smoke_local.py
```

This checks that `course_agent.agent_process` can load your `StudentAgent`,
handle the course JSONL protocol, return valid responses for the three benchmark
names, and read `task_configs/public_cases.json`. It does not require an API key
and does not check official benchmark environments. To validate tau2,
DeepPlanning, or MCPMark installations, run the `third_party` setup checks from
the course root.

## LLM And Runtime Limits

Limits live in the assignment JSON under `limits`. Top-level limits apply to
every benchmark; entries under `limits.benchmarks.<benchmark>` override or add
benchmark-specific limits. Staff hidden configs use the same schema as
`task_configs/public_cases.json`.

Current public defaults:

| Limit | Default | Implemented by | Meaning |
| --- | ---: | --- | --- |
| `model_input_tokens` | `64000` | `CourseLLMClient` | Rejects an LLM request before the API call if the estimated prompt plus tool schema payload is too large. |
| `model_output_tokens` | `4096` | `CourseLLMClient` | Sent to the chat-completions API as `max_tokens`. |
| `case_timeout_sec` | `300` | `CourseLLMClient`, official adapters, tau2 subprocess adapter | Per-case wall-clock timeout used for LLM calls and official benchmark subprocesses. Official adapters add a small cleanup buffer internally. |
| `llm_max_attempts` | `2` | `CourseLLMClient` | Maximum SDK attempts for one logical LLM call. Failed attempts are retried up to this count. |
| `max_model_calls` | benchmark-specific | `CourseLLMClient`, runner turn loop fallback | Maximum actual LLM SDK attempts in a student-agent process. Retries count as attempts. For benchmarks without `max_agent_turns`, the runner also uses this as the agent turn cap. |
| `max_agent_turns` | benchmark-specific | `run_public_tasks.py`, tau2 JSONL adapter | Maximum student-agent turns for runner-driven environments; tau2 enforces it inside the JSONL adapter. |
| `max_environment_steps` | benchmark-specific | tau2 official command | Passed to tau2 as `--max-steps`. |
| `max_tool_calls_per_turn` | benchmark-specific | `tool_policy.py`, runner, tau2 JSONL adapter | Rejects responses that request too many tool calls in one turn. |
| `max_mutating_tool_calls_per_turn` | benchmark-specific | `tool_policy.py`, runner, tau2 JSONL adapter | Rejects responses with too many state-changing tool calls in one turn. |
| `allow_multi_tool_calls` | `true` when omitted | `tool_policy.py` | If set false, any multi-tool response is rejected. |

The LLM client retries only the SDK call itself. Validation failures such as
oversized input or exhausted `max_model_calls` fail immediately. `calls_made`
counts actual SDK attempts, so one logical response may consume two calls when
the first attempt fails and the retry succeeds.

When your agent calls the provided `CourseLLMClient`, the runner records LLM
usage events from the API response: API call count, successful/failed call
count, prompt tokens, completion tokens, total tokens, and estimated input
tokens. These fields are aggregated into `case_results.jsonl`,
`case_analysis.json`, and `score_summary.json`. Direct API calls that bypass
`CourseLLMClient` are not guaranteed to be captured. Tau2's benchmark-side user
simulator LLM is not counted as student-agent LLM usage.

## Tool Call Limits

Your agent may return either one `tool_call`, multiple `tool_calls`, or a `final` answer. Multiple tool calls are executed sequentially, not in parallel. The runner validates the order you return; it does not reorder calls for you. The next request's `observation["tool_results"]` contains one indexed result per attempted tool call, including errors and skipped calls.

Single-turn tool-call limits for the public assignment are:

| Benchmark | Max tool calls per turn | Max mutating tool calls per turn |
| --- | ---: | ---: |
| `mcpmark` | 4 | 1 |
| `tau2_airline` | 3 | 1 |
| `deepplanning` | 5 | 3 |

If a trajectory records `ToolCallLimitExceeded`, the student agent returned too
many tool calls in one turn. This is classified as `student_runtime_error`
because the response violates the course protocol, not because the benchmark
environment crashed. Fix it in your agent by selecting fewer tools, splitting
work across later turns after observing tool results, or returning a final
answer when no further tool use is allowed.

Read-only tool calls must come before mutating tool calls in the same response. The mutating lists are benchmark-specific: tau2 airline reservation update/cancel/book/send tools plus `respond_to_user`; DeepPlanning cart update tools plus the simplified `submit_plan`; MCPMark uses MCP `readOnlyHint` when present and otherwise classifies common read prefixes such as `read`, `list`, `search`, `query`, `select`, and `get` as read-only. Anything else is treated as mutating.

Terminal tools cannot be combined with any other tool call in the same response. For tau2 airline this is `respond_to_user`; for the simplified DeepPlanning smoke environment this is `submit_plan`.

If a mutating tool fails, the runner records that error and skips the remaining calls in that response. If a read-only tool fails and later calls would mutate state, those later calls are skipped as well. Successful mutating calls are not rolled back.

## Scores

Each public case writes one result row to `case_results.jsonl` and detailed
events to that case's `trajectory.jsonl`.
The runner also writes `case_analysis.json`, a benchmark/case-id indexed summary
that combines per-case scores with the latest runtime/setup/agent-performance
diagnosis for export and staff review.

Per-case score fields:

| Field | Range | Used for grading? | Meaning |
| --- | ---: | --- | --- |
| `grading_score` | `0.0` or `1.0` | Yes | Course grading score: `1.0` only when the case is fully completed. |
| `analysis_score` | benchmark-specific | No | Official benchmark feedback score for debugging partial progress. |
| `max_score` | `1.0` | Yes | Maximum possible `grading_score` for the case. |
| `reward` | `0.0` to `1.0` | Legacy alias | Kept for compatibility; currently equals `grading_score`. |
| `max_reward` | `1.0` | Legacy alias | Kept for compatibility; currently equals `max_score`. |

The runner does not use partial credit for course grading. Raw completion scores
are converted to binary `grading_score`: full completion is `1.0`; anything less
is `0.0`. `analysis_score` keeps the benchmark's own feedback value so you can
compare partial progress across runs. When raw grading values differ from the
binary field, the score event includes `raw_grading_score`, `raw_analysis_score`,
`raw_min_score`, and `raw_max_score`.

Benchmark sources:

| Benchmark | `grading_score` source | `analysis_score` source |
| --- | --- | --- |
| `tau2_airline` | `1.0` only when tau2 official `reward_info.reward` reaches full reward. | tau2 official `reward_info.reward`. |
| `deepplanning` | DeepPlanning Shopping official `case_score`: `1.0` only when all expected products/coupons are matched, otherwise `0.0`. | DeepPlanning Shopping official `score`: `matched_count / expected_count`. Extra products are reported as `extra_products_count`. |
| `mcpmark` | MCPMark official verifier result for the enabled filesystem/postgres public cases; `1.0` when verification passes, otherwise `0.0`. | Same value as `grading_score` for MCPMark public cases. |

`case_analysis.json` is organized as
`benchmarks.<benchmark>.<case_id>` and includes `status`, `analysis_score`,
`grading_score`, `runtime_issue`, `issue_category`, `issue_type`,
`issue_message`, `trajectory_path`, and selected score/runtime details.

`score_summary.json` aggregates `total_grading_score`,
`average_grading_score`, `total_analysis_score`, and
`average_analysis_score`. With the current runner, every case has weight `1.0`:
`total_grading_score` is the sum of binary per-case `grading_score` values, so
it equals the number of completed cases when all selected cases finish.
`average_grading_score` is `total_grading_score / completed_cases`.
Course grading should use `grading_score`; use `analysis_score` only to
understand what happened during development.

`task_configs/public_cases.json` also includes `scoring.baseline_anchors`.
Those anchors are reference-only benchmark-level average scores measured from
TA baseline-agent runs on comparable public/hidden case sets. They are provided
to contextualize baseline difficulty.

## Public Runs

Use `run-tasks` to run local public cases. It is a short CLI wrapper around
`public_runner/run_public_tasks.py`, and accepts the same parameters and flags.
Prefer either `uv run --locked` or `.venv/bin/python`; both use the submitted
lock file. The long form remains equivalent when you want to call the runner
module directly:

```bash
uv run --locked run-tasks --help
.venv/bin/python cli.py --help
uv run --locked python public_runner/run_public_tasks.py --help
```

By default, each run writes a new batch under
`trajectories/<run_id>/` inside `student_release/`. Use `--output-root` to write
somewhere else; relative paths are resolved from `student_release/`, and
absolute paths are used as given:

```bash
uv run --locked run-tasks --backend simplified --output-root trajectories_smoke
uv run --locked run-tasks --backend official --output-root /tmp/course-agent-runs
```

Each batch contains `run_metadata.json`, `case_results.jsonl`,
`case_analysis.json`, `score_summary.json`, and per-case trajectory JSONL files
under `cases/`. See `../shared/trajectory_schema.md` for the full artifact
schema. If your agent uses `CourseLLMClient`, per-case usage sidecars named
`trajectory_llm_usage.jsonl` or `attempt_<n>_llm_usage.jsonl` may also appear
under the case directory.

Run deterministic interface tests with the simplified backend:

```bash
uv run --locked run-tasks --backend simplified
```

Use `simplified` for quick protocol checks. It does not require official
benchmark repositories or API credentials and is the fastest way to see whether
your `StudentAgent` still speaks the course JSONL protocol.

Run official public environments after benchmark setup:

```bash
uv run --locked run-tasks --backend official
```

Use `official` when you want benchmark-real tools, scoring, trajectories, and
failure modes. Official runs require the relevant `third_party` benchmark setup;
tau2 and the starter LLM baseline also require `env.student.local.sh`.

`task_configs/public_cases.json` selects public development cases. Staff
configs follow the same rule: public_cases.json and hidden_cases.json use the same schema.
Hidden configs add private case entries but keep the same benchmark names,
limits, scoring fields, and runner protocol.

Run one benchmark:

```bash
uv run --locked run-tasks \
  --backend simplified \
  --benchmark tau2_airline
```

Run selected cases by public case key:

```bash
uv run --locked run-tasks \
  --backend official \
  --case mcpmark:mcp_filesystem_file_context_pattern_matching \
  --case deepplanning:dp_level_1_case_10
```

`--case` uses `benchmark:case_key`; case keys are listed in
`task_configs/public_cases.json`. `--case-id` is kept only for compatibility and
must be scoped by exactly one `--benchmark`.

Useful command patterns:

```bash
# all simplified public cases
uv run --locked run-tasks --backend simplified

# one official benchmark
uv run --locked run-tasks \
  --backend official \
  --benchmark mcpmark

# one official public case
uv run --locked run-tasks \
  --backend official \
  --case tau2_airline:tau2_49
```

## Checkpoints And Resume

The runner checkpoints every case attempt. `case_results.jsonl` records one row
per attempt, trajectory files record request, response, tool_result, score, and
error events, and `case_analysis.json` summarizes the latest result with
`runtime_issue` and `issue_category`.

Automatic resume is triggered when you rerun the same assignment, backend,
filters, selected cases, and `--output-root`. Instead of creating a new batch,
the runner reuses the latest matching incomplete batch:

- completed non-error cases are skipped;
- missing cases are run;
- cases whose latest status ends in `_error` are retried once;
- failed retries are recorded as final and are not retried again automatically.

First attempts use `trajectory.jsonl`; retry attempts use `attempt_2.jsonl`.
Each result row records `attempt`, `auto_resumed`, and, for retries,
`previous_status`. `score_summary.json` is rewritten from the latest result for
each selected case after all attempts finish.

Students usually do not need a resume flag. Use explicit resume only when you
want to continue a specific old batch:

```bash
uv run --locked run-tasks --resume trajectories/<run_id>
```

Explicit resume uses that batch's original `run_metadata.json`, applies the
same skip/retry rules, and rewrites `score_summary.json`.

For tau2 official runs, the trajectory also includes subprocess events and a
sidecar JSONL of StudentAgent request/response/error events. If tau2 fails
before the first agent turn, the trajectory records a tau2 agent event count of
`0`.

## Case-Level Concurrency

The runner supports bounded case-level concurrency:

```bash
uv run --locked run-tasks \
  --backend simplified \
  --case mcpmark:mcp_filesystem_file_context_pattern_matching \
  --case tau2_airline:tau2_49 \
  --max-workers 2
```

Concurrency is only across cases. A single case's agent/tool loop remains
ordered and synchronous so trajectory events stay understandable and benchmark
state is not interleaved inside one case. Each concurrent case runs in a
separate Python process; the parent process is the only writer to
`case_results.jsonl`, `case_analysis.json`, and `score_summary.json`.

For official runs, MCPMark cases take an internal runner lock. This means only
one MCPMark case runs against the shared MCPMark/Docker/Postgres runtime at a
time, while tau2 and DeepPlanning cases may still run concurrently when
`--max-workers` is greater than `1`. The lock is shared by runner processes on
the same host; advanced users may set `COURSE_RUNNER_LOCK_DIR` to choose the
lock parent directory.

Default worker policy:

| Backend | Default `max_workers` | Rationale |
| --- | ---: | --- |
| `simplified` | `4` | Local deterministic smoke cases are lightweight and isolated. |
| `official` | `1` | Official environments may use external subprocesses, databases, containers, or benchmark state. |

You may raise `--max-workers` when the selected cases are isolated and your
machine has enough CPU, memory, API quota, and container/database capacity. Good
candidates are lightweight simplified runs, or official cases that do not share
mutable services. Keep `--max-workers 1` for first-time official setup checks
and debugging. Higher worker counts can make LLM/API throttling, container
contention, and trajectory diagnosis harder to interpret, even though official
MCPMark cases are serialized by the runner lock.

## Submission

Create `submission.json` from `submission.example.json`, then edit it with your
own identity:

```bash
cp submission.example.json submission.json
# edit student_id, student_name, and email
uv run --locked python build_submission.py --output submission.zip
```

The submission builder records every check in `submission_build_log.json` and
then includes that log inside `submission.zip`. Review the log before submitting.
The required checks are:

- `submission.json` exists, is valid JSON, and has non-placeholder
  `student_id`, `student_name`, and `email` values. String values are stripped
  before packaging.
- Dependency policy passes: `uv lock --check`, PyPI-only registry packages,
  no git/url/path dependencies, no source-only packages, no artifact over 50 MB,
  and no estimated dependency download over 300 MB.
- `smoke_local.py` passes, proving the JSONL agent protocol loads your
  `StudentAgent`.
- `public_runner/run_public_tasks.py --backend simplified` passes, proving the
  runner can complete local interface cases and write trajectories.

Generated trajectories, caches, local env files, internal baseline code, and
archives are excluded from submissions. Model weights, databases, nested
archives, and hidden/private files cause the build to fail. The local simplified
score is only a packaging/interface check; staff grading reruns your submitted
agent in the official grading environment with staff-owned benchmark setup and
task configs.
