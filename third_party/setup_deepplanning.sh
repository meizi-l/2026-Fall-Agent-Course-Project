#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export LANG=C

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
course_root=$(cd -- "$script_dir/.." && pwd)
course_python_version_file="$course_root/.python-version"
target=${DEEPPLANNING_REPO:-"$course_root/third_party/qwen-agent"}
repo_url=${DEEPPLANNING_REPO_URL:-"https://github.com/QwenLM/Qwen-Agent.git"}
ref=${DEEPPLANNING_REF:-"31a4d36d123688581a9e9744427272b33ce940e0"}
course_python_version=${COURSE_PYTHON_VERSION:-$(tr -d '[:space:]' < "$course_python_version_file")}
dataset_repo=${DEEPPLANNING_DATASET_REPO:-"Qwen/DeepPlanning"}
dataset_ref=${DEEPPLANNING_DATASET_REF:-"213876c"}
download_data=${DEEPPLANNING_DOWNLOAD_DATA:-"1"}
venv_python="$target/.venv-deepplanning/bin/python"
benchmark_root="$target/benchmark/deepplanning/shoppingplanning"
requirements="$target/benchmark/deepplanning/requirements.txt"
pins="$course_root/third_party/locks/deepplanning-python.txt"

expected_database_level1_sha256="632a3b5d0db1fa0717474b9361b2d7102aeb7e1f00c32cb842f012ff7adf8000"
expected_database_level2_sha256="58b65bff1f5e9eefb580b02202ef1394a87f8d82466a7aff5e1329a812e16d55"
expected_database_level3_sha256="eff61a838f55fad677499adc77405b480d08de87b97b409737b67e0abce610e7"

usage() {
  cat <<'USAGE'
Usage: bash third_party/setup_deepplanning.sh [--print-path] [--check-only] [--print-data-sha256]

Downloads and verifies Qwen-Agent DeepPlanning Shopping for the course project.

Environment variables:
  DEEPPLANNING_REPO       Install/use this Qwen-Agent checkout path.
  DEEPPLANNING_REPO_URL   Git URL to clone. Defaults to the official upstream.
  DEEPPLANNING_REF        Commit, tag, or branch to checkout. Defaults to the
                          course-pinned audited commit.
  COURSE_PYTHON_VERSION   Expected Python minor version. Defaults to
                          course_project/.python-version.
  COURSE_PYTHON           Python executable used to create the DeepPlanning venv.
  DEEPPLANNING_DATASET_REPO
                          HuggingFace dataset repo. Defaults to Qwen/DeepPlanning.
  DEEPPLANNING_DATASET_REF
                          HuggingFace dataset revision. Defaults to the
                          course-pinned v1.1 revision, 213876c.
  DEEPPLANNING_DOWNLOAD_DATA
                          Set to 0 to skip automatic Shopping data download.

DeepPlanning Shopping data:
  By default this script downloads database_level1.tar.gz,
  database_level2.tar.gz, and database_level3.tar.gz from HuggingFace into:
    third_party/qwen-agent/benchmark/deepplanning/shoppingplanning/database_zip/

  The script extracts those archives when present and --check-only verifies the
  extracted database_level1/2/3 directories. If automatic download fails, place
  the same files in database_zip/ manually and rerun this script.
USAGE
}

resolve_course_python() {
  if [[ -n "${COURSE_PYTHON:-}" ]]; then
    printf '%s\n' "$COURSE_PYTHON"
    return 0
  fi
  if [[ -x "$course_root/.venv/bin/python" ]]; then
    printf '%s\n' "$course_root/.venv/bin/python"
    return 0
  fi
  if [[ -x "$course_root/student_release/.venv/bin/python" ]]; then
    printf '%s\n' "$course_root/student_release/.venv/bin/python"
    return 0
  fi
  if command -v "python$course_python_version" >/dev/null 2>&1; then
    command -v "python$course_python_version"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    uv python find "$course_python_version"
    return 0
  fi
  echo "Could not find course Python $course_python_version. Set COURSE_PYTHON to a matching interpreter." >&2
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

require_course_python() {
  local python_cmd=$1
  "$python_cmd" - "$course_python_version" <<'PY'
import sys
expected = tuple(int(part) for part in sys.argv[1].split(".")[:2])
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]} at {sys.executable}")
PY
}

print_data_sha256() {
  local data_zip="$benchmark_root/database_zip"
  local archive
  for archive in database_level1.tar.gz database_level2.tar.gz database_level3.tar.gz; do
    if [[ -f "$data_zip/$archive" ]]; then
      shasum -a 256 "$data_zip/$archive"
    else
      echo "missing: $data_zip/$archive" >&2
    fi
  done
}

verify_git_ref() {
  if [[ ! -d "$target/.git" ]]; then
    echo "missing: $target/.git" >&2
    return 2
  fi

  local actual_ref expected_ref
  actual_ref=$(git -C "$target" rev-parse HEAD)
  expected_ref=$(git -C "$target" rev-parse "${ref}^{commit}" 2>/dev/null || printf '%s' "$ref")
  if [[ "$actual_ref" != "$expected_ref" ]]; then
    echo "DeepPlanning checkout is at $actual_ref, expected $expected_ref ($ref)" >&2
    return 2
  fi
}

verify_data_sha256() {
  local data_zip="$benchmark_root/database_zip"
  local archive expected actual
  for archive in database_level1.tar.gz database_level2.tar.gz database_level3.tar.gz; do
    case "$archive" in
      database_level1.tar.gz) expected="$expected_database_level1_sha256" ;;
      database_level2.tar.gz) expected="$expected_database_level2_sha256" ;;
      database_level3.tar.gz) expected="$expected_database_level3_sha256" ;;
    esac
    if [[ ! -f "$data_zip/$archive" ]]; then
      echo "missing: $data_zip/$archive" >&2
      return 2
    fi
    actual=$(shasum -a 256 "$data_zip/$archive" | awk '{print $1}')
    if [[ "$actual" != "$expected" ]]; then
      echo "sha256 mismatch for $data_zip/$archive: expected $expected, got $actual" >&2
      return 2
    fi
  done
}

download_deepplanning_data() {
  local python_cmd=$1
  local data_zip="$benchmark_root/database_zip"
  mkdir -p "$data_zip"
  "$python_cmd" - "$dataset_repo" "$dataset_ref" "$data_zip" <<'PY'
import os
import sys
import urllib.request
from pathlib import Path

repo, revision, output_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
archives = ["database_level1.tar.gz", "database_level2.tar.gz", "database_level3.tar.gz"]
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
headers = {}
if token:
    headers["Authorization"] = f"Bearer {token}"

for archive in archives:
    target = output_dir / archive
    if target.exists() and target.stat().st_size > 0:
        continue
    url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{archive}"
    tmp = target.with_suffix(target.suffix + ".partial")
    request = urllib.request.Request(url, headers=headers)
    print(f"Downloading {url} -> {target}", flush=True)
    try:
        with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        raise SystemExit(f"failed to download {archive}: {exc}") from exc
    tmp.replace(target)
PY
}

check_deepplanning() {
  local missing=0
  local path
  local required_paths=(
    "$target/.git"
    "$requirements"
    "$venv_python"
    "$benchmark_root/tools/shopping_tool_schema.json"
    "$benchmark_root/data/level_1_query_meta.json"
    "$benchmark_root/data/level_2_query_meta.json"
    "$benchmark_root/data/level_3_query_meta.json"
    "$benchmark_root/database_level1"
    "$benchmark_root/database_level2"
    "$benchmark_root/database_level3"
  )

  for path in "${required_paths[@]}"; do
    if [[ ! -e "$path" ]]; then
      echo "missing: $path" >&2
      missing=1
    fi
  done

  verify_git_ref

  if [[ $missing -ne 0 ]]; then
    echo "DeepPlanning is not fully configured. See course_project/third_party/README.md." >&2
    return 2
  fi

  verify_data_sha256
  "$venv_python" "$script_dir/check_python_pins.py" "$pins"

  "$venv_python" - "$course_python_version" "$benchmark_root" <<'PY'
import json
import sys
from pathlib import Path

expected = tuple(int(part) for part in sys.argv[1].split(".")[:2])
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]} at {sys.executable}")

root = Path(sys.argv[2])
schema = json.loads((root / "tools" / "shopping_tool_schema.json").read_text(encoding="utf-8"))
if not isinstance(schema, list) or not schema:
    raise SystemExit("shopping_tool_schema.json must contain a non-empty JSON list")

for level in (1, 2, 3):
    metadata = json.loads((root / "data" / f"level_{level}_query_meta.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, list) or not metadata:
        raise SystemExit(f"level_{level}_query_meta.json must contain a non-empty JSON list")
PY

  echo "DeepPlanning Shopping is ready."
  echo "DEEPPLANNING_REPO=$target"
  echo "DEEPPLANNING_PYTHON=$venv_python"
}

if [[ "${1:-}" == "--print-data-sha256" ]]; then
  print_data_sha256
  exit 0
fi

if [[ "${1:-}" == "--check-only" ]]; then
  check_deepplanning
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

verify_git_ref

if [[ ! -x "$venv_python" ]]; then
  "$python_cmd" -m venv "$target/.venv-deepplanning"
fi

"$venv_python" -m pip install --upgrade pip
"$venv_python" -m pip install -r "$pins" -r "$requirements"
"$venv_python" -m pip freeze > "$target/.course_deepplanning.freeze.txt"

data_zip="$benchmark_root/database_zip"
if [[ "$download_data" != "0" ]]; then
  download_deepplanning_data "$python_cmd"
fi

verify_data_sha256

for level in 1 2 3; do
  archive="$data_zip/database_level${level}.tar.gz"
  output_dir="$benchmark_root/database_level${level}"
  if [[ -f "$archive" && ! -d "$output_dir" ]]; then
    tar -xzf "$archive" -C "$benchmark_root"
  fi
done

check_deepplanning
