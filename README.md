# Course Agent Project Release

This directory contains the release-path course project code.

- `student_release/`: student-facing starter package and local smoke tools.
- `staff_side/`: staff and grading-server tooling. Hidden cases and private verifier material do not live in Git.
- `shared/`: schemas and policy documents shared by student and staff tooling.
- `third_party/`: setup scripts for official public benchmark environments. Downloaded checkouts such as `tau2-bench/` are local and gitignored.

The release path uses a course-owned local runner. Students implement the
provided `StudentAgent` hooks; they do not need to run an A2A server.
Public and hidden task configs use the same JSON schema; staff hidden configs
swap in private cases while keeping the same locked runner/protocol interface.

## Grading Baseline And Local Development

The course is designed so students can develop on different laptops while staff
grading remains fair and reproducible. We test the release on macOS, and final
grading is expected on a staff-controlled server with this baseline:

```text
OS: AlmaLinux 9.8 (Olive Jaguar), x86_64
Family: RHEL/CentOS/Fedora compatible
Container runtime: Podman available for containerized benchmark services
Student package Python: course_project/.python-version, currently Python 3.11
```

We have tested the current release path on a macOS MacBook during development.
Students do not need to run AlmaLinux locally. Local macOS, Linux, or other
reasonable setups are acceptable as long as the submitted agent works through
the locked course interfaces and `third_party` checks described below.

Benchmark environments are intentionally separated from the student agent code.
The course pins benchmark checkouts and benchmark-side dependencies where that
is practical, while host utilities such as container runtimes and system
packages remain self-managed. A local or self-managed benchmark setup is usable
only if it stays compatible with the locked `student_release/public_runner`,
`course_agent` protocol, and task config schema. See `third_party/README.md` for
the concrete setup commands, pinned versions, environment variables, and runtime
checks. Those checks validate the benchmark environments only; full local
readiness also requires the student env file, `smoke_local.py`, and
`public_runner/run_public_tasks.py` commands documented in
`student_release/README.md`.

At minimum, official public runs expect benchmark paths compatible with:

```bash
export TAU2_REPO=/absolute/path/to/tau2-bench
export DEEPPLANNING_REPO=/absolute/path/to/qwen-agent
export MCPMARK_REPO=/absolute/path/to/mcpmark
```

LLM-backed runs also require the student env file to provide:

```bash
export COURSE_API_KEY=...
export AZURE_OPENAI_ENDPOINT=...
export AZURE_OPENAI_API_VERSION=...
```

## Locked And Editable Files

The grading interface is locked. Students should treat these files and
directories as course infrastructure:

- `student_release/public_runner/`
- `student_release/public_runner/envs/`
- `student_release/src/course_agent/protocol.py`
- `student_release/src/course_agent/runtime.py`
- `student_release/src/course_agent/agent_process.py`
- benchmark setup/adapters under `third_party/`

Students implement their agent in:

- `student_release/src/course_agent/student_agent.py`
- `student_release/src/course_agent/student_tools/`, when helper tools are
  provided or created by the student

Students may update `student_release/pyproject.toml` and `student_release/uv.lock`
when they need extra Python packages, but staff grading installs from the
submitted lock file. Recommended experiment commands are:

```bash
cd course_project/student_release
uv run --locked python public_runner/run_public_tasks.py --backend simplified
.venv/bin/python public_runner/run_public_tasks.py --backend simplified
```

From `course_project`, the same venv interpreter is
`student_release/.venv/bin/python`.

Dependency additions should be lightweight and grading-friendly: prefer
pure-Python packages or prebuilt wheels for Linux x86_64/macOS, avoid packages
that compile native extensions during grading, and do not require large model
weights, external services, GPUs, or system packages not documented by the
course. If a dependency is large or hard to install, vendor-free alternatives or
standard-library code are safer.

Install the student package with `uv`:

```bash
cd course_project/student_release
uv sync --locked
```
