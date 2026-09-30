# Third-Party Benchmark Environments

This directory contains setup scripts for official public benchmark
environments. Downloaded checkouts and data are local only and are not committed.

The setup scripts below are the scripts we use to configure the benchmark
environment during course development. They have been tested on a macOS MacBook.
Final staff grading is expected on the staff server environment. Students on
other systems may self-manage host utilities, but the resulting benchmark
checkouts, virtualenv paths, data files, services, and environment variables
must match the interface consumed by `student_release/public_runner` and
`course_agent`.

## Course-Provided Setup Scripts

For the default course-managed layout, run these commands from `course_project`:

```bash
bash third_party/setup_tau2_bench.sh
bash third_party/setup_tau2_bench.sh --check-only

bash third_party/setup_deepplanning.sh
bash third_party/setup_deepplanning.sh --check-only

bash third_party/setup_mcpmark.sh
bash third_party/install_mcpmark_system_deps.sh --local-node --install
bash third_party/check_mcpmark_runtimes.sh all
```

These scripts create or check the paths used by `public_runner`. The course
runner starts separate subprocesses. Each subprocess uses its own
fixed interpreter path:

```text
student agent / public runner:  course_project/student_release/.venv/bin/python
tau2 task environment:          course_project/third_party/tau2-bench/.venv/bin/python
DeepPlanning task environment:  course_project/third_party/qwen-agent/.venv-deepplanning/bin/python
MCPMark task environment:       course_project/third_party/mcpmark/.venv-mcpmark/bin/python
```

The course runner coordinates these environments automatically, so they do not
need to share one virtualenv.

## Self-Managed Minimum Contract

If students install benchmark environments themselves, they must keep them
compatible with the locked course runner. Do not patch benchmark APIs, task
formats, `student_release/public_runner`, or the `course_agent` protocol to make
a local checkout work.

At minimum, self-managed checkouts must expose these repository paths before
running official public cases:

```bash
export TAU2_REPO=/absolute/path/to/tau2-bench
export DEEPPLANNING_REPO=/absolute/path/to/qwen-agent
export MCPMARK_REPO=/absolute/path/to/mcpmark
```

| Variable | Used by | Purpose |
| --- | --- | --- |
| `TAU2_REPO` | `OfficialTau2AirlineEnvironment` | Location of the pinned tau2-bench checkout; must contain `.venv/bin/python` and pass `tau2 check-data`. |
| `DEEPPLANNING_REPO` | `OfficialDeepPlanningEnvironment` | Location of the pinned Qwen-Agent checkout; must contain `.venv-deepplanning/bin/python` and the Shopping data/schema files. |
| `MCPMARK_REPO` | `OfficialMCPMarkEnvironment` | Location of the pinned MCPMark checkout; must contain `.venv-mcpmark/bin/python`, filesystem/postgres tasks, and the Postgres MCP venv for Postgres cases. |

MCPMark only needs the course subset: `filesystem` and `postgres`. Students and
staff do not need MCPMark Notion, GitHub, Playwright, or Playwright-WebArena for
this course project.

MCPMark Postgres additionally needs a reachable Postgres service, Docker or
Podman, and PostgreSQL 17 client tools (`psql`, `createdb`, `pg_restore`). If
you use our `--postgres-docker --install` helper with default values, you do not
need to export the variables below. The script and `public_runner` both default
to the same local settings. Override them only when your self-managed Postgres
service differs:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DATABASE=postgres
export POSTGRES_USERNAME=postgres
export POSTGRES_PASSWORD=password
export MCPMARK_CONTAINER_RUNTIME=docker  # or podman
```

| Variable | Purpose |
| --- | --- |
| `POSTGRES_HOST` | Hostname used by the runner and MCPMark Postgres state manager. |
| `POSTGRES_PORT` | Host port mapped to the Postgres server; our helper maps this to container port `5432`. |
| `POSTGRES_DATABASE` | Database used for initial connectivity checks; MCPMark creates task-specific databases during setup. |
| `POSTGRES_USERNAME` | Postgres user for connectivity checks and MCPMark state setup. |
| `POSTGRES_PASSWORD` | Password for the Postgres user; also used as `PGPASSWORD` during runner preflight. |
| `MCPMARK_CONTAINER_RUNTIME` | Forces `docker` or `podman` when both are installed or when the host requires one. |

### Benchmark-side readiness checks

These commands are the final benchmark-environment checks before running
official public cases. They do not validate student LLM credentials, the student
agent implementation, or trajectory writing. For full local readiness, follow
`student_release/README.md`: source `env.student.local.sh`, run
`smoke_local.py`, then run `public_runner/run_public_tasks.py`.

```bash
bash third_party/setup_tau2_bench.sh --check-only
bash third_party/setup_deepplanning.sh --check-only
bash third_party/setup_mcpmark.sh --check-only
bash third_party/check_mcpmark_runtimes.sh all  # use "filesystem" for filesystem-only MCPMark runs
```

## Benchmark version policy

The course pins benchmark code, benchmark data, and benchmark-side service
versions wherever that can be done cross-platform. Host utilities are self-managed
because macOS, Ubuntu, AlmaLinux, and other Linux distributions use different
package managers and container runtimes. A local setup is acceptable when it
passes the same `--check-only` or runtime check commands used by staff.
Python package versions are recorded in `third_party/locks/`. DeepPlanning and
MCPMark setup install these exact versions, and `--check-only` compares the
installed versions. Tau2 setup uses its upstream `uv.lock` plus
`websockets==17.1`. The lock resolutions were tested on macOS; staff must run
the same checks on AlmaLinux before grading.

Final staff grading is expected on AlmaLinux 9.8 (Olive Jaguar):

```text
NAME="AlmaLinux"
VERSION="9.8 (Olive Jaguar)"
ID="almalinux"
ID_LIKE="rhel centos fedora"
VERSION_ID="9.8"
Platform: x86_64
Container runtime: Podman
```

Students do not need AlmaLinux locally. The public runner and benchmark adapters
are the compatibility boundary: self-managed environments must work with the
same `student_release/public_runner` interface used by staff.

| Benchmark | Course-pinned pieces | Self-managed host utilities |
| --- | --- | --- |
| `tau2_airline` | tau2-bench commit, Python 3.12 venv, tau2 data check | `git`, `uv`, a Python 3.12 interpreter |
| `deepplanning` | Qwen-Agent commit, Shopping data revision, SHA256-verified database archives, `.venv-deepplanning` | `git`, `uv`, network or a staff-provided data cache |
| `mcpmark` filesystem | MCPMark commit, Python 3.12 venv, project-local Node.js, filesystem MCP server package | `git`, `uv`, `curl`, `tar`, `.tar.xz` extraction support |
| `mcpmark` postgres | MCPMark commit, Postgres MCP server package, pinned Postgres container image | Docker or Podman, PostgreSQL 17 client tools |

## tau2 Airline

Install or repair:

```bash
cd course_project
bash third_party/setup_tau2_bench.sh
```

Smoke check:

```bash
bash third_party/setup_tau2_bench.sh --check-only
```

Expected install path:

```bash
bash third_party/setup_tau2_bench.sh --print-path
```

The script pins tau2-bench to:

```text
tau2-bench:  b7ea9074c1cba482b30687fecdb5c8425fd6f619
Python:      Python 3.12 in course_project/third_party/tau2-bench/.venv
```

tau2 does not require Docker, Node.js, or PostgreSQL client tools. Version
consistency is enforced by the pinned tau2 checkout, the `TAU2_PYTHON_VERSION`
check, `uv sync --locked` against tau2's lock data, the exact `websockets`
check, and `tau2 check-data`.

## DeepPlanning Shopping

Install or repair:

```bash
cd course_project
bash third_party/setup_deepplanning.sh
```

The script clones pinned Qwen-Agent, creates `.venv-deepplanning`, downloads the
pinned Shopping databases from HuggingFace, verifies SHA256 digests, and extracts
the data.

Smoke check:

```bash
bash third_party/setup_deepplanning.sh --check-only
```

The check verifies the pinned Qwen-Agent checkout commit, `.venv-deepplanning`,
Shopping schema/data files, extracted database directories, and SHA256 digests
for the pinned database archives.

Expected install path:

```bash
bash third_party/setup_deepplanning.sh --print-path
```

Staff data audit:

```bash
bash third_party/setup_deepplanning.sh --print-data-sha256
```

Pinned versions:

```text
Qwen-Agent:              31a4d36d123688581a9e9744427272b33ce940e0
Qwen/DeepPlanning data:  213876c
Python:                  course_project/.python-version in .venv-deepplanning
```

DeepPlanning does not require Docker, Node.js, or PostgreSQL client tools.
Version consistency is enforced by the pinned Qwen-Agent checkout, the course
Python minor version, the upstream `benchmark/deepplanning/requirements.txt`,
the pinned HuggingFace dataset revision, and the SHA256 checks below.

Expected Shopping data digests:

```text
database_level1.tar.gz  632a3b5d0db1fa0717474b9361b2d7102aeb7e1f00c32cb842f012ff7adf8000
database_level2.tar.gz  58b65bff1f5e9eefb580b02202ef1394a87f8d82466a7aff5e1329a812e16d55
database_level3.tar.gz  eff61a838f55fad677499adc77405b480d08de87b97b409737b67e0abce610e7
```

## MCPMark

The course MCPMark subset uses only:

```text
filesystem
postgres
```

Students and staff do not need to configure MCPMark Notion, GitHub,
Playwright, or Playwright-WebArena for this course project.

Supported local setup platforms with explicit helper commands are macOS (Apple
Silicon and Intel) and Ubuntu Linux (x86-64 and ARM64). Students may install
host utilities in another reasonable way, but their setup must pass the same
check commands. Other Linux distributions may work using the project-local
runtime plus Docker or Podman, with host utilities installed manually, but their
system package setup is not handled by the course installer.

The expected final course grading server is AlmaLinux 9.8 on x86_64
(RHEL/CentOS/Fedora compatible) with Podman available as the container runtime.
Students do not need to use AlmaLinux locally. Teaching staff/admins must prepare
server-level host utilities such as PostgreSQL 17 client tools before final
grading.

### MCPMark scripts

There are three MCPMark bash files under `third_party`:

| Script | What it does | When students use it |
| --- | --- | --- |
| `setup_mcpmark.sh` | Clones/checks the pinned MCPMark repo, creates `.venv-mcpmark` with Python 3.12, installs MCPMark Python dependencies, and verifies the two course task definitions exist. | Run once first, then use `--check-only` when debugging. |
| `install_mcpmark_system_deps.sh` | Installs or prints commands for runtime dependencies outside the MCPMark repo: project-local Node.js, filesystem MCP server, macOS/Linux host utilities, and the pinned Postgres container through Docker or Podman. | Run the specific mode shown in the steps below. |
| `check_mcpmark_runtimes.sh` | Wrapper that checks `core`, `filesystem`, `postgres`, or `all` by calling the setup/runtime checks. It does not install anything. | Run after setup to verify the machine is ready. |

### Recommended setup flow

Run from `course_project`.

1. Install/check MCPMark core:

```bash
bash third_party/setup_mcpmark.sh
bash third_party/setup_mcpmark.sh --check-only
```

2. Install pinned project-local Node.js plus the pinned filesystem MCP server:

```bash
bash third_party/install_mcpmark_system_deps.sh --local-node --install
bash third_party/check_mcpmark_runtimes.sh filesystem
```

3. For Postgres, install host utilities and start Docker or Podman yourself.

macOS:

```bash
bash third_party/install_mcpmark_system_deps.sh --macos --install
```

Linux:

```bash
bash third_party/install_mcpmark_system_deps.sh --ubuntu --dry-run
```

On Ubuntu Linux, copy the printed commands into a root/admin shell or ask
staff/admins to prepare the image. The script intentionally does not run
privileged commands. On AlmaLinux/RHEL/CentOS/Fedora-compatible systems, install
PostgreSQL 17 client tools (`psql`, `createdb`, `pg_restore`) through the
approved `dnf`/system package process. On other Linux distributions, use that
distribution's package manager. Docker Desktop/Engine or Podman must be
installed and running before the next command.

4. Start the pinned PostgreSQL runtime container:

```bash
bash third_party/install_mcpmark_system_deps.sh --postgres-docker --install
```

If the machine has both Docker and Podman, or if the grading server should use
Podman explicitly, set:

```bash
MCPMARK_CONTAINER_RUNTIME=podman bash third_party/install_mcpmark_system_deps.sh --postgres-docker --install
```

You do not need to restart Docker, Podman, or the Postgres container for every
new case. The container is a persistent service. MCPMark Postgres case isolation
comes from a per-case temporary database created by `PostgresStateManager` and
dropped during runner cleanup. If a run is interrupted or force-killed, cleanup
may not run; remove leftover `mcpmark_%` databases before important batches.
The course `public_runner` serializes official MCPMark cases with a host-level
runner lock, so tau2 and DeepPlanning cases can still run concurrently without
starting two MCPMark cases at the same time. If you bypass `public_runner`, you
must provide equivalent isolation yourself.

5. Verify the complete MCPMark runtime:

```bash
bash third_party/check_mcpmark_runtimes.sh all
```

### Dependency model

Pinned/reproducible runtime:

- Node.js: exact `v20.18.3`, installed project-locally by `--local-node`.
- Filesystem MCP server: exact `@modelcontextprotocol/server-filesystem@2025.12.18`, installed under `third_party/.local`.
- PostgreSQL server: exact `pgvector/pgvector:0.8.0-pg17-bookworm` container image.
- Postgres MCP server: exact `postgres-mcp==0.3.0` in `third_party/mcpmark/.venv-mcpmark-postgres-mcp`, with MCP SDK `<2` for compatibility.

Host utilities:

- Docker or Podman container runtime. Docker/Podman itself is not pinned; it only needs to run the pinned Postgres image.
- PostgreSQL client tools: `psql`, `createdb`, `pg_restore`; checked for major version 17, patch versions may differ across macOS/Linux.
- Homebrew, Ubuntu apt, AlmaLinux/RHEL-family dnf, or equivalent package manager, depending on the host.

The recommended cross-platform runtime is project-local Node.js plus the pinned
Postgres container image. Homebrew/apt/dnf are only used for host utilities such
as PostgreSQL client tools, or as a system Node fallback.

### Versions 

| Item | Pin |
| --- | --- |
| MCPMark | `cd45b7f57923b9b3985467f5139927575f83141c` |
| MCPMark Python env | Python 3.12 at `course_project/third_party/mcpmark/.venv-mcpmark` |
| Postgres MCP Python env | Python 3.12 at `course_project/third_party/mcpmark/.venv-mcpmark-postgres-mcp` |
| Project-local Node.js | `v20.18.3` at `course_project/third_party/.local/node20` |
| Filesystem MCP server | `@modelcontextprotocol/server-filesystem@2025.12.18` at `course_project/third_party/.local/mcp-filesystem-server` |
| Postgres container image | `pgvector/pgvector:0.8.0-pg17-bookworm` |
| PostgreSQL client tools | major version 17 for `psql`, `createdb`, `pg_restore` |
| Postgres MCP server | `postgres-mcp==0.3.0` with `mcp<2` |


### Minimal troubleshooting

If a benchmark-side check fails, rerun only the relevant check:

```bash
bash third_party/setup_tau2_bench.sh --check-only
bash third_party/setup_deepplanning.sh --check-only
bash third_party/setup_mcpmark.sh --check-only
bash third_party/check_mcpmark_runtimes.sh filesystem
bash third_party/check_mcpmark_runtimes.sh all
```

Then verify only the matching prerequisite:

- `filesystem`: project-local Node.js and filesystem MCP server were installed
  by `install_mcpmark_system_deps.sh --local-node --install`.
- `postgres`: Docker or Podman daemon is running, PostgreSQL 17 client tools
  are on `PATH`, and the pinned Postgres container is running and reachable at
  `POSTGRES_HOST:POSTGRES_PORT` (defaults: `localhost:5432`). The container is
  not restarted per case; case isolation uses temporary `mcpmark_%` databases
  that are dropped during normal cleanup.
- self-managed checkouts: `TAU2_REPO`, `DEEPPLANNING_REPO`, and `MCPMARK_REPO`
  point to compatible pinned repositories with the expected virtualenv paths.
- first MCPMark filesystem run: network may be needed once to populate the
  official `desktop.zip` test environment under `third_party/mcpmark`.

Use `MCPMARK_CONTAINER_RUNTIME=docker` or `MCPMARK_CONTAINER_RUNTIME=podman` to
force one container runtime when both are installed. Host package-manager,
permission, container, or PostgreSQL client issues are local system
administration problems; the course scripts pin benchmark-side versions but do
not repair host machines.

Platform helpers only run for their named platform; other Linux distributions
are not silently treated as Ubuntu.
