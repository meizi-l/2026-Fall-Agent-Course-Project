#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
course_root=$(cd -- "$script_dir/.." && pwd)
local_node_bin="$course_root/third_party/.local/node20/bin"
export PATH="$local_node_bin:/opt/homebrew/bin:/usr/local/bin:/opt/homebrew/opt/node@20/bin:/usr/local/opt/node@20/bin:/opt/homebrew/opt/postgresql@17/bin:/usr/local/opt/postgresql@17/bin:$PATH"

usage() {
  cat <<'USAGE'
Usage: bash third_party/check_mcpmark_runtimes.sh [core|filesystem|postgres|all]

Checks system/runtime dependencies for the course MCPMark subset.

This script checks rather than installs. For filesystem tasks, run:

  bash third_party/install_mcpmark_system_deps.sh --local-node --install

For Postgres tasks, install/start Docker or Podman plus PostgreSQL client tools
with the commands printed by:

  bash third_party/install_mcpmark_system_deps.sh --auto --dry-run
USAGE
}

target=${1:-all}

if [[ "$target" == "--help" || "$target" == "-h" ]]; then
  usage
  exit 0
fi

case "$target" in
  core)
    bash "$script_dir/setup_mcpmark.sh" --check-only
    ;;
  filesystem)
    bash "$script_dir/setup_mcpmark.sh" --check-only
    bash "$script_dir/setup_mcpmark.sh" --check-filesystem-runtime
    ;;
  postgres)
    bash "$script_dir/setup_mcpmark.sh" --check-only
    bash "$script_dir/setup_mcpmark.sh" --check-postgres-runtime
    ;;
  all)
    bash "$script_dir/setup_mcpmark.sh" --check-only
    bash "$script_dir/setup_mcpmark.sh" --check-filesystem-runtime
    bash "$script_dir/setup_mcpmark.sh" --check-postgres-runtime
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
