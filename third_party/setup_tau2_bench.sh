#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
course_root=$(cd -- "$script_dir/.." && pwd)
target=${TAU2_REPO:-"$course_root/third_party/tau2-bench"}
repo_url=${TAU2_REPO_URL:-"https://github.com/sierra-research/tau2-bench.git"}
ref=${TAU2_REF:-"b7ea9074c1cba482b30687fecdb5c8425fd6f619"}
sync_args=${TAU2_UV_SYNC_ARGS:-"--extra dev"}
extra_pip_packages="websockets==17.1"
tau2_python_version=${TAU2_PYTHON_VERSION:-"3.12"}

usage() {
  cat <<'USAGE'
Usage: bash third_party/setup_tau2_bench.sh [--print-path] [--check-only]

Downloads and verifies tau2-bench for the course project.

Environment variables:
  TAU2_REPO       Install/use this tau2-bench path.
  TAU2_REPO_URL   Git URL to clone. Defaults to the official upstream.
  TAU2_REF        Branch, tag, or commit to checkout. Defaults to the
                  course-pinned commit.
  TAU2_UV_SYNC_ARGS
                  Arguments passed to `uv sync`. Defaults to `--extra dev`.
  The course installs websockets==17.1 after sync because tau2 imports it
  through the current runner path.
  TAU2_PYTHON_VERSION
                  Expected tau2-bench Python minor version. Defaults to 3.12,
                  matching tau2-bench's upstream requires-python.
  TAU2_PYTHON     Python executable used by uv for the tau2-bench environment.
USAGE
}

resolve_tau2_python() {
  if [[ -n "${TAU2_PYTHON:-}" ]]; then
    printf '%s\n' "$TAU2_PYTHON"
    return 0
  fi
  if command -v "python$tau2_python_version" >/dev/null 2>&1; then
    command -v "python$tau2_python_version"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    uv python find "$tau2_python_version"
    return 0
  fi
  echo "Could not find tau2 Python $tau2_python_version. Set TAU2_PYTHON to a matching interpreter." >&2
  return 2
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--print-path" ]]; then
  printf '%s\n' "$target"
  exit 0
fi

if [[ "${1:-}" == "--check-only" ]]; then
  if [[ ! -d "$target/.git" ]]; then
    echo "tau2-bench is not installed at $target" >&2
    exit 2
  fi
  cd "$target"
  actual_ref=$(git rev-parse HEAD)
  if [[ "$actual_ref" != "$ref" ]]; then
    echo "tau2-bench is at $actual_ref, expected $ref" >&2
    exit 2
  fi
  .venv/bin/python - "$tau2_python_version" <<'PY'
import sys
expected = tuple(int(part) for part in sys.argv[1].split(".")[:2])
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]} at {sys.executable}")
PY
  .venv/bin/tau2 check-data
  .venv/bin/python "$script_dir/check_tau2_lock.py" "$target/uv.lock"
  .venv/bin/python - <<'PY'
import importlib.metadata
version = importlib.metadata.version("websockets")
if version != "17.1":
    raise SystemExit(f"websockets=={version}; expected 17.1")
PY
  exit 0
fi

python_cmd=$(resolve_tau2_python)
"$python_cmd" - "$tau2_python_version" <<'PY'
import sys
expected = tuple(int(part) for part in sys.argv[1].split(".")[:2])
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]} at {sys.executable}")
PY

mkdir -p "$(dirname "$target")"
if [[ ! -d "$target/.git" ]]; then
  git clone "$repo_url" "$target"
fi

cd "$target"
git fetch --tags --prune
git checkout "$ref"

actual_ref=$(git rev-parse HEAD)
if [[ "$actual_ref" != "$ref" ]]; then
  echo "tau2-bench checkout is at $actual_ref, expected $ref" >&2
  exit 2
fi

# Intentional word splitting: TAU2_UV_SYNC_ARGS is a small admin-facing escape
# hatch for frozen installs or extra groups.
# shellcheck disable=SC2086
UV_PYTHON="$python_cmd" uv sync --locked $sync_args
# Intentional word splitting: package specs are shell-style admin input.
# shellcheck disable=SC2086
uv pip install $extra_pip_packages
.venv/bin/tau2 check-data
bash "$script_dir/setup_tau2_bench.sh" --check-only

cat <<EOF
tau2-bench is ready.
TAU2_REPO=$target
EOF
