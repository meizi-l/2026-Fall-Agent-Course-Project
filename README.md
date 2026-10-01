# Course Project: Building an Agentic AI System

## Overview

Students will design and implement an AI agent that can interact with external
environments, use tools, reason over observations, and complete multi-step
tasks.

The main student work is the implementation of a unified `StudentAgent`. The
course provides the runner, benchmark adapters, fixed agent interface, logging,
trajectory format, public development cases, and grading infrastructure.
Students are responsible for the behavior and internal design of their agent.

This repository is organized as follows:

- `student_release/`: student-facing starter package, local smoke tests, public
  runner, submission builder, and public task configs.
- `shared/`: schemas and policy documents shared by student and staff tooling.
- `third_party/`: setup scripts for official public benchmark environments.
- `staff_side/`: staff and grading-server tooling. Hidden cases and private
  verifier material are not part of the public release.

## Benchmarks

Agents are evaluated on three benchmark environments:

- **tau2 Airline**: conversational interaction, policy constraints, state
  tracking, and state-changing actions.
- **MCPMark**: filesystem and PostgreSQL tasks requiring structured tool use and
  environment manipulation.
- **DeepPlanning Shopping**: longer-horizon shopping and planning tasks with
  multiple constraints.

Together, these benchmarks test planning, tool selection, state tracking, error
handling, and effective use of language models.

Students receive **20 public cases** for development and debugging. Final
grading uses **40 hidden cases** from the same benchmarks and task families,
with different task instances. Public cases are for iteration and interface
validation and do not contribute to the final project score.

Details of the public cases, including case identifiers and benchmark-specific
settings, are defined in `student_release/task_configs/public_cases.json`.

The benchmark-specific course baseline completion rates are:

| Benchmark | Course baseline completion rate |
| --- | ---: |
| MCPMark | 31.25% |
| tau2 Airline | 41.67% |
| DeepPlanning Shopping | 16.67% |

## Scoring And Grading

Each hidden case receives binary course credit:

- `1.0` for full task completion.
- `0.0` otherwise.

Benchmark-native partial scores may be recorded for debugging and analysis, but
they are not used directly as the course grading score.

For each benchmark `b`, the grader computes:

```text
n_b = number of hidden cases for benchmark b
c_b = number of fully completed hidden cases for benchmark b
r_b = c_b / n_b
a_b = published course-baseline completion rate for benchmark b
w_b = n_b / 40
```

The completion rate for each benchmark is converted to a benchmark score on a
0-100 scale. Matching the course baseline earns 60, zero completion earns 0,
and full completion earns 100:

```text
if r_b <= a_b:
    benchmark_score_b = 60 * r_b / a_b
else:
    benchmark_score_b = 60 + 40 * (r_b - a_b) / (1 - a_b)
```

The final automated project score weights each benchmark by its proportion of
the 40 hidden cases:

```text
project_score = sum_b w_b * benchmark_score_b
```

The grading report also records the unadjusted hidden-case completion rate:

```text
raw_completion_rate = total fully completed hidden cases / 40
```

Course baseline anchors are measured separately for each benchmark using the
same locked runner, model, budgets, and benchmark settings used for grading.
The anchors are fixed before final grading. Benchmarks are not compared directly
with one another because they have different task formats and difficulty
profiles.

If the submitted agent cannot be loaded, its dependencies cannot be installed,
or it violates the locked interface, all affected cases receive `0.0`. If the
agent crashes, times out, exceeds a limit, or returns an invalid response during
one case, that case receives `0.0`; successfully completed cases retain their
scores. A verified failure of course-controlled grading infrastructure is not
counted against the student and is rerun by course staff.

## System Architecture

The course uses a fixed evaluation pipeline. Public or hidden task configs are
loaded by the course runner. For each task step, the runner provides the current
observation, available tools, and execution limits to the student's
`StudentAgent`.

The agent returns either tool calls or a final answer using the course response
schema. Tool requests are routed through benchmark-specific adapters to the
corresponding task environment. Tool outputs and new observations are returned
to the agent through the same fixed interface.

Throughout execution, the runner records trajectories, tool interactions,
runtime events, model usage when available, and scores. Benchmark environments
and grading infrastructure are course-controlled; the submitted agent controls
only its own reasoning, state, helper code, and responses through the locked
interface.

## What Students May Use

Students must keep the public `StudentAgent` interface expected by the course
runner: the class name, `respond`, `llm_client`, and the benchmark solver method
signatures documented in `student_release/README.md`.

Students do not have to keep the starter strategy or internal implementation.
They may replace solver bodies, add internal state, write helper functions or
classes, add helper modules under
`student_release/src/course_agent/student_tools/`, and use an agentic framework
that complies with the dependency and execution policies below.

During grading, the only student-agent LLM model allowed is `gpt-5-mini`,
accessed through the provided course/HKUST Azure configuration. Students must
not rely on other model providers, private APIs, local model servers, GPUs,
large downloaded model weights, or external services. Benchmark-side
simulators may use separate course-controlled models; those calls are part of
the benchmark environment rather than the submitted student agent.

Additional Python packages are allowed if they are declared in
`student_release/pyproject.toml`, locked in `student_release/uv.lock`, available
from the PyPI registry, and practical on Linux x86_64 and macOS. Git, URL, and
path dependencies are not allowed. Dependencies must not require source-only
builds, undocumented system packages, install-time external services, or large
model downloads. The submission builder enforces the detailed dependency
policy documented in `student_release/README.md`.

## Configuration And Local Development

The course provides pinned student-side dependencies, pinned benchmark
checkouts where practical, and locked runner and protocol interfaces so
students can develop on different laptops while staff grading remains as fair
and reproducible as practical. Exact host-level reproducibility is not
guaranteed because container runtimes and system packages remain self-managed.

Final grading is expected on a staff-controlled server with this baseline:

```text
OS: AlmaLinux 9.8 (Olive Jaguar), x86_64
Family: RHEL/CentOS/Fedora compatible
Container runtime: Podman available for containerized benchmark services
Student package Python: course_project/.python-version, currently Python 3.11
```

Local macOS, Linux, or other reasonable setups are acceptable as long as the
submitted agent works through the locked course interfaces and compatible
benchmark environments.

Local readiness has two separate layers:

1. **Benchmark environment readiness.** The checks under `third_party/`
   validate pinned benchmark checkouts, benchmark-side dependencies, data
   files, and required host services such as containers or PostgreSQL. They do
   not validate the student agent, student LLM credentials, or course runner
   interface. See `third_party/README.md` for setup commands, pinned versions,
   environment variables, and runtime checks.
2. **Student-side readiness.** Follow `student_release/README.md`: configure
   `env.student.local.sh` for LLM-backed runs, run `smoke_local.py` to verify
   that `StudentAgent` loads and follows the locked course JSONL interface, and
   run `public_runner/run_public_tasks.py` to exercise the public task runner.

Official public runs expect benchmark paths compatible with:

```bash
export TAU2_REPO=/absolute/path/to/tau2-bench
export DEEPPLANNING_REPO=/absolute/path/to/qwen-agent
export MCPMARK_REPO=/absolute/path/to/mcpmark
```

For LLM-backed local runs, students configure their own HKUST API key and
endpoint in `env.student.local.sh`. Final grading uses staff/course-owned
credentials injected by grading workers for the school Azure/HKUST endpoint;
student-submitted local env files are ignored during final grading.

Useful references:

- [HKUST API Developer Portal](https://hkust.developer.azure-api.net/)
- [HKUST Azure OpenAI API Service](https://itso.hkust.edu.hk/services/it-infrastructure/azure-openai-api-service)

## Locked And Editable Files

The grading interface is locked. Students should treat these files and
directories as course infrastructure:

- `student_release/public_runner/`
- `student_release/public_runner/envs/`
- `student_release/src/course_agent/protocol.py`
- `student_release/src/course_agent/runtime.py`
- `student_release/src/course_agent/agent_process.py`
- benchmark setup and adapters under `third_party/`

Students implement their agent in:

- `student_release/src/course_agent/student_agent.py`
- `student_release/src/course_agent/student_tools/`, for helper modules created
  by the student

Students may also update `student_release/pyproject.toml` and
`student_release/uv.lock` when they need additional permitted Python packages.
Staff grading installs dependencies from the submitted lock file.

## Submission

Students create `submission.json` from `submission.example.json`, fill in their
student ID, name, and email, and build `submission.zip` with the provided
submission tool:

```bash
cd course_project/student_release
cp submission.example.json submission.json
# Edit student_id, student_name, and email.
uv run --locked python build_submission.py --output submission.zip
```

Before packaging, the submission builder checks that:

- `submission.json` is valid and contains non-placeholder student information.
- `pyproject.toml` and `uv.lock` satisfy the course dependency policy.
- `smoke_local.py` passes, proving that the JSONL agent process can load the
  submitted `StudentAgent` and follow the locked interface.
- The simplified public runner passes, proving that the agent can complete
  local interface cases and write trajectories.

Generated trajectories, caches, local env files, API keys, internal baseline
code, model weights, databases, nested archives, and hidden or private files
must not be included in submissions. Staff grading reruns the submitted agent
in the official grading environment with staff-owned benchmark setup, 40 hidden
task configs, and staff-controlled credentials.
