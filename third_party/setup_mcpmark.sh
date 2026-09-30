#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export LANG=C

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
course_root=$(cd -- "$script_dir/.." && pwd)
local_node_bin="$course_root/third_party/.local/node20/bin"
export PATH="$local_node_bin:$PATH:/opt/homebrew/bin:/usr/local/bin:/opt/homebrew/opt/node@20/bin:/usr/local/opt/node@20/bin:/opt/homebrew/opt/postgresql@17/bin:/usr/local/opt/postgresql@17/bin"
course_python_version_file="$course_root/.python-version"
target=${MCPMARK_REPO:-"$course_root/third_party/mcpmark"}
repo_url=${MCPMARK_REPO_URL:-"https://github.com/eval-sys/mcpmark.git"}
ref=${MCPMARK_REF:-"cd45b7f57923b9b3985467f5139927575f83141c"}
mcpmark_python_version=${MCPMARK_PYTHON_VERSION:-"3.12"}
venv_dir="$target/.venv-mcpmark"
venv_python="$venv_dir/bin/python"
postgres_mcp_venv_dir=${MCPMARK_POSTGRES_MCP_VENV:-"$target/.venv-mcpmark-postgres-mcp"}
postgres_mcp_python="$postgres_mcp_venv_dir/bin/python"
install_playwright_browsers=${MCPMARK_INSTALL_PLAYWRIGHT_BROWSERS:-"0"}
node_major=${MCPMARK_NODE_MAJOR:-"20"}
postgres_client_major=${MCPMARK_POSTGRES_CLIENT_MAJOR:-"17"}
postgres_image=${MCPMARK_POSTGRES_DOCKER_IMAGE:-"pgvector/pgvector:0.8.0-pg17-bookworm"}
container_runtime_override=${MCPMARK_CONTAINER_RUNTIME:-""}
filesystem_server_package=${MCPMARK_FILESYSTEM_SERVER_PACKAGE:-"@modelcontextprotocol/server-filesystem@2025.12.18"}
filesystem_server_root=${MCPMARK_FILESYSTEM_SERVER_ROOT:-"$course_root/third_party/.local/mcp-filesystem-server"}
filesystem_server_js="$filesystem_server_root/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
postgres_mcp_package=${MCPMARK_POSTGRES_MCP_PACKAGE:-"postgres-mcp==0.3.0"}
pins="$course_root/third_party/locks/mcpmark-python.txt"
postgres_pins="$course_root/third_party/locks/postgres-mcp-python.txt"
course_filesystem_task="filesystem/standard/desktop/timeline_extraction"
course_postgres_task="postgres/easy/employees/hiring_year_summary"
case_config=${MCPMARK_CASE_CONFIG:-"$course_root/student_release/task_configs/public_cases.json"}

usage() {
  cat <<'USAGE'
Usage: bash third_party/setup_mcpmark.sh [--print-path] [--print-python] [--check-only] [--check-filesystem-runtime] [--check-postgres-runtime]

Downloads and verifies MCPMark for the course project.

Environment variables:
  MCPMARK_REPO       Install/use this MCPMark checkout path.
  MCPMARK_CASE_CONFIG
                     Assignment JSON whose MCPMark task files are checked.
                     Defaults to student_release/task_configs/public_cases.json.
  MCPMARK_REPO_URL   Git URL to clone. Defaults to the official upstream.
  MCPMARK_REF        Commit, tag, or branch to checkout. Defaults to the
                     course-pinned audited commit.
  MCPMARK_PYTHON_VERSION
                     Expected Python minor version for MCPMark. Defaults to
                     3.12 because postgres-mcp==0.3.0 requires Python >=3.12.
  MCPMARK_PYTHON     Python executable used to create the MCPMark venv.
  MCPMARK_INSTALL_PLAYWRIGHT_BROWSERS
                     Set to 1 to install Chromium for Playwright tasks.
                     Defaults to 0; filesystem checks do not need browsers.
  MCPMARK_NODE_MAJOR Expected Node.js major version for filesystem MCP runtime.
                     Defaults to 20.
  MCPMARK_POSTGRES_DOCKER_IMAGE
                     Expected Postgres container image for course Postgres tasks.
                     Defaults to pgvector/pgvector:0.8.0-pg17-bookworm.
  MCPMARK_CONTAINER_RUNTIME
                     Optional container CLI override: docker or podman.
  MCPMARK_POSTGRES_CLIENT_MAJOR
                     Expected PostgreSQL client major version for psql,
                     createdb, and pg_restore. Defaults to 17.
  MCPMARK_FILESYSTEM_SERVER_PACKAGE
                     Expected npm MCP filesystem server package.
                     Defaults to @modelcontextprotocol/server-filesystem@2025.12.18.
  MCPMARK_FILESYSTEM_SERVER_ROOT
                     Project-local npm install prefix for the filesystem MCP
                     server package. Defaults to
                     course_project/third_party/.local/mcp-filesystem-server.
  MCPMARK_POSTGRES_MCP_PACKAGE
                     Expected Postgres MCP package installed in the
                     separate Postgres MCP venv.
                     Defaults to postgres-mcp==0.3.0.
  MCPMARK_POSTGRES_MCP_VENV
                     Separate venv path for the Postgres MCP server.
                     Defaults to MCPMark checkout/.venv-mcpmark-postgres-mcp.

This script installs MCPMark itself and verifies a no-account filesystem task
fixture. The course MCPMark subset only uses filesystem and postgres. Use
--check-filesystem-runtime before filesystem adapter tests, and
--check-postgres-runtime after installing Docker or Podman plus Postgres
client tools.
USAGE
}

resolve_course_python() {
  if [[ -n "${MCPMARK_PYTHON:-}" ]]; then
    printf '%s\n' "$MCPMARK_PYTHON"
    return 0
  fi
  if command -v "python$mcpmark_python_version" >/dev/null 2>&1; then
    command -v "python$mcpmark_python_version"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    uv python find "$mcpmark_python_version"
    return 0
  fi
  echo "Could not find MCPMark Python $mcpmark_python_version. Set MCPMARK_PYTHON to a matching interpreter." >&2
  return 2
}

require_course_python() {
  local python_cmd=$1
  "$python_cmd" - "$mcpmark_python_version" <<'PY'
import sys
expected = tuple(int(part) for part in sys.argv[1].split(".")[:2])
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]} at {sys.executable}")
PY
}

check_filesystem_runtime() {
  local missing=0
  local cmd
  for cmd in node npm npx; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "missing runtime command: $cmd" >&2
      missing=1
    fi
  done
  if [[ $missing -ne 0 ]]; then
    echo "Install Node.js $node_major.x LTS with npm/npx before running MCPMark filesystem adapter tests." >&2
    return 2
  fi

  node - "$node_major" <<'NODE'
const expectedMajor = Number(process.argv[2]);
const actual = process.versions.node.split(".").map(Number);
if (actual[0] !== expectedMajor) {
  throw new Error(`expected Node.js ${expectedMajor}.x, got ${process.versions.node}`);
}
NODE

  echo "MCPMark filesystem runtime is ready."
  echo "NODE=$(command -v node)"
  echo "NPM=$(command -v npm)"
  echo "NPX=$(command -v npx)"
  echo "FILESYSTEM_SERVER_PACKAGE=$filesystem_server_package"
  if [[ ! -f "$filesystem_server_js" ]]; then
    echo "missing project-local filesystem MCP server: $filesystem_server_js" >&2
    echo "Run: bash third_party/install_mcpmark_system_deps.sh --local-node --install" >&2
    return 2
  fi
  local probe_parent
  local probe_dir
  probe_parent="$course_root/third_party/.local/tmp"
  mkdir -p "$probe_parent"
  probe_dir=$(mktemp -d "$probe_parent/course_mcp_fs_probe.XXXXXX")
  "$venv_python" - "$filesystem_server_js" "$probe_dir" <<'PY'
import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_js, probe_dir = sys.argv[1], sys.argv[2]

async def main() -> None:
    params = StdioServerParameters(
        command="node",
        args=[server_js, probe_dir],
        env=os.environ.copy(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=15)
            tools = await asyncio.wait_for(session.list_tools(), timeout=15)
            if not any(tool.name == "read_file" for tool in tools.tools):
                raise SystemExit("filesystem MCP server did not expose read_file")

asyncio.run(main())
PY
  rm -rf "$probe_dir"
  echo "FILESYSTEM_SERVER_JS=$filesystem_server_js"
}

check_postgres_runtime() {
  local missing=0
  local cmd
  local container_runtime
  if ! container_runtime=$(resolve_container_runtime); then
    missing=1
  fi
  for cmd in psql createdb pg_restore; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "missing postgres runtime command: $cmd" >&2
      missing=1
    fi
  done
  if [[ ! -x "$postgres_mcp_venv_dir/bin/postgres-mcp" ]]; then
    echo "missing Postgres MCP server: $postgres_mcp_venv_dir/bin/postgres-mcp" >&2
    missing=1
  fi
  if [[ $missing -ne 0 ]]; then
    echo "Install/start Docker or Podman, install PostgreSQL 17 client tools, and run setup_mcpmark.sh before Postgres adapter tests." >&2
    return 2
  fi

  for cmd in psql createdb pg_restore; do
    check_postgres_client_major "$cmd"
  done

  "$container_runtime" version >/dev/null
  PGPASSWORD="${POSTGRES_PASSWORD:-password}" PGCONNECT_TIMEOUT=5 \
    psql -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" \
      -U "${POSTGRES_USERNAME:-postgres}" -d "${POSTGRES_DATABASE:-postgres}" \
      -w -Atq -c 'select 1' >/dev/null
  echo "MCPMark postgres runtime commands are available."
  echo "CONTAINER_RUNTIME=$container_runtime"
  echo "CONTAINER_RUNTIME_PATH=$(command -v "$container_runtime")"
  echo "PSQL=$(command -v psql)"
  echo "CREATEDB=$(command -v createdb)"
  echo "PG_RESTORE=$(command -v pg_restore)"
  "$postgres_mcp_python" - "$postgres_mcp_package" <<'PY'
import importlib.metadata
import sys

expected = sys.argv[1].split("==", 1)[1]
actual = importlib.metadata.version("postgres-mcp")
mcp_version = importlib.metadata.version("mcp")
if actual != expected:
    raise SystemExit(f"postgres-mcp version {actual}; expected {expected}")
if int(mcp_version.split(".", 1)[0]) >= 2:
    raise SystemExit(f"mcp SDK version {mcp_version}; expected <2 for postgres-mcp compatibility")
PY
  "$postgres_mcp_python" "$script_dir/check_python_pins.py" "$postgres_pins"

  echo "POSTGRES_MCP_COMMAND=$postgres_mcp_venv_dir/bin/postgres-mcp"
  echo "POSTGRES_CLIENT_MAJOR=$postgres_client_major"
  echo "POSTGRES_IMAGE=$postgres_image"
  echo "POSTGRES_MCP_PACKAGE=$postgres_mcp_package"
}

resolve_container_runtime() {
  local runtime
  if [[ -n "$container_runtime_override" ]]; then
    runtime="$container_runtime_override"
    if [[ "$runtime" != "docker" && "$runtime" != "podman" ]]; then
      echo "MCPMARK_CONTAINER_RUNTIME must be docker or podman, got: $runtime" >&2
      return 2
    fi
    if ! command -v "$runtime" >/dev/null 2>&1; then
      echo "missing postgres runtime command: $runtime" >&2
      return 2
    fi
    printf '%s\n' "$runtime"
    return 0
  fi
  for runtime in docker podman; do
    if command -v "$runtime" >/dev/null 2>&1; then
      printf '%s\n' "$runtime"
      return 0
    fi
  done
  echo "missing postgres runtime command: docker or podman" >&2
  return 2
}

check_postgres_client_major() {
  local cmd=$1
  local output
  local major
  output=$("$cmd" --version 2>&1 || true)
  major=$(printf '%s\n' "$output" | sed -n 's/.*PostgreSQL[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n 1)
  if [[ -z "$major" ]]; then
    echo "could not parse PostgreSQL client version from $cmd --version: $output" >&2
    return 2
  fi
  if [[ "$major" != "$postgres_client_major" ]]; then
    echo "$cmd reports PostgreSQL client major $major; expected PostgreSQL client major $postgres_client_major" >&2
    return 2
  fi
}

check_mcpmark() {
  local missing=0
  local path
  local required_paths=(
    "$target/.git"
    "$target/pyproject.toml"
    "$target/pipeline.py"
    "$target/src"
    "$target/tasks/filesystem"
    "$target/tasks/postgres"
    "$venv_python"
  )
  local course_task_files=(
    "$target/tasks/$course_filesystem_task/description.md"
    "$target/tasks/$course_filesystem_task/meta.json"
    "$target/tasks/$course_filesystem_task/verify.py"
    "$target/tasks/$course_postgres_task/description.md"
    "$target/tasks/$course_postgres_task/meta.json"
    "$target/tasks/$course_postgres_task/verify.py"
  )

  for path in "${required_paths[@]}"; do
    if [[ ! -e "$path" ]]; then
      echo "missing: $path" >&2
      missing=1
    fi
  done

  for path in "${course_task_files[@]}"; do
    if [[ ! -e "$path" ]]; then
      echo "missing course MCPMark task file: $path" >&2
      missing=1
    fi
  done

  if [[ $missing -ne 0 ]]; then
    echo "MCPMark is not fully configured. See course_project/third_party/README.md." >&2
    return 2
  fi

  cd "$target"
  actual_ref=$(git rev-parse HEAD)
  if [[ "$actual_ref" != "$ref" ]]; then
    echo "MCPMark checkout is at $actual_ref, expected $ref" >&2
    return 2
  fi

  "$venv_python" - "$mcpmark_python_version" "$target" <<'PY'
import json
import sys
from pathlib import Path

expected = tuple(int(part) for part in sys.argv[1].split(".")[:2])
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]} at {sys.executable}")

root = Path(sys.argv[2])
sys.path.insert(0, str(root))

import pipeline  # noqa: F401
import src.agents  # noqa: F401

course_tasks = [
    ("filesystem", "standard", "desktop", "timeline_extraction"),
    ("postgres", "easy", "employees", "hiring_year_summary"),
]
for service, suite, category, task_id in course_tasks:
    task_dir = root / "tasks" / service / suite / category / task_id
    meta_path = task_dir / "meta.json"
    description_path = task_dir / "description.md"
    verify_path = task_dir / "verify.py"
    for required in (meta_path, description_path, verify_path):
        if not required.exists():
            raise SystemExit(f"missing course MCPMark task file: {required}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise SystemExit(f"{meta_path} must contain a JSON object")
    if metadata.get("category_id") != category:
        raise SystemExit(f"{meta_path} category_id must be {category!r}")
    if metadata.get("task_id") != task_id:
        raise SystemExit(f"{meta_path} task_id must be {task_id!r}")
    mcp_services = metadata.get("mcp")
    if not isinstance(mcp_services, list) or service not in mcp_services:
        raise SystemExit(f"{meta_path} must list MCP service {service!r}")
PY
  "$venv_python" "$script_dir/check_python_pins.py" "$pins"

  "$venv_python" - "$target" "$case_config" "$course_root/student_release" <<'PY'
import json
import sys
from pathlib import Path

repo, config_path, student_release = map(Path, sys.argv[1:])
sys.path.insert(0, str(student_release))
from public_runner.envs.mcpmark_case_config import validate_mcpmark_task_files

config = json.loads(config_path.read_text(encoding="utf-8"))
for case in config.get("benchmarks", {}).get("mcpmark", {}).get("cases", []):
    validate_mcpmark_task_files(repo, case)
PY

  echo "MCPMark is ready."
  echo "MCPMARK_REPO=$target"
  echo "MCPMARK_PYTHON=$venv_python"
  echo "MCPMARK_REF=$actual_ref"
  echo "MCPMARK_COURSE_SERVICES=filesystem,postgres"
  echo "MCPMARK_PUBLIC_FILESYSTEM_TASK=$course_filesystem_task"
  echo "MCPMARK_PUBLIC_POSTGRES_TASK=$course_postgres_task"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--print-path" ]]; then
  printf '%s\n' "$target"
  exit 0
fi

if [[ "${1:-}" == "--print-python" ]]; then
  printf '%s\n' "$venv_python"
  exit 0
fi

if [[ "${1:-}" == "--check-only" ]]; then
  check_mcpmark
  exit $?
fi

if [[ "${1:-}" == "--check-filesystem-runtime" ]]; then
  check_filesystem_runtime
  exit $?
fi

if [[ "${1:-}" == "--check-postgres-runtime" ]]; then
  check_postgres_runtime
  exit $?
fi

python_cmd=$(resolve_course_python)
require_course_python "$python_cmd"

mkdir -p "$(dirname "$target")"
if [[ ! -d "$target/.git" ]]; then
  git clone "$repo_url" "$target"
fi

cd "$target"
git fetch --tags --prune
git checkout "$ref"

actual_ref=$(git rev-parse HEAD)
if [[ "$actual_ref" != "$ref" ]]; then
  echo "MCPMark checkout is at $actual_ref, expected $ref" >&2
  exit 2
fi

if [[ ! -x "$venv_python" ]]; then
  "$python_cmd" -m venv "$venv_dir"
fi

"$venv_python" -m pip install --upgrade pip
"$venv_python" -m pip install -r "$pins" -e .
"$venv_python" -m pip freeze > "$target/.course_mcpmark.freeze.txt"

if [[ ! -x "$postgres_mcp_python" ]]; then
  "$python_cmd" -m venv "$postgres_mcp_venv_dir"
fi
"$postgres_mcp_python" -m pip install --upgrade pip
"$postgres_mcp_python" -m pip install -r "$postgres_pins" "$postgres_mcp_package" "mcp<2"
"$postgres_mcp_python" -m pip freeze > "$target/.course_postgres_mcp.freeze.txt"

if [[ "$install_playwright_browsers" == "1" ]]; then
  "$venv_python" -m playwright install chromium
fi

check_mcpmark
