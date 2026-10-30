#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_repo=${POSTGRES_MCP_SOURCE_REPO:-"https://github.com/crystaldba/postgres-mcp.git"}
source_ref="7179ab0336396f819e23b0b012a9c284be10fac3"
source_date_epoch="1747406582"
patch_file="$script_dir/patches/postgres-mcp-0.3.0-course1.patch"
output_dir=${POSTGRES_MCP_WHEEL_OUTPUT_DIR:-"$script_dir/wheels"}
python_cmd=${POSTGRES_MCP_BUILD_PYTHON:-"python3.12"}
expected_wheel="postgres_mcp-0.3.0+course1-py3-none-any.whl"

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/course-postgres-mcp-build.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT

git clone --quiet "$source_repo" "$work_dir/source"
git -C "$work_dir/source" checkout --quiet "$source_ref"
actual_ref=$(git -C "$work_dir/source" rev-parse HEAD)
if [[ "$actual_ref" != "$source_ref" ]]; then
  echo "postgres-mcp checkout is at $actual_ref, expected $source_ref" >&2
  exit 2
fi
git -C "$work_dir/source" apply "$patch_file"

"$python_cmd" -m venv "$work_dir/build-venv"
"$work_dir/build-venv/bin/python" -m pip install --quiet "hatchling==1.27.0"
mkdir -p "$output_dir"
SOURCE_DATE_EPOCH="$source_date_epoch" \
  "$work_dir/build-venv/bin/python" -m pip wheel \
    --quiet --no-deps --no-build-isolation --wheel-dir "$output_dir" "$work_dir/source"

wheel="$output_dir/$expected_wheel"
if [[ ! -f "$wheel" ]]; then
  echo "expected wheel was not built: $wheel" >&2
  exit 2
fi

(
  cd "$output_dir"
  shasum -a 256 "$expected_wheel" > SHA256SUMS
)
echo "Built $wheel from postgres-mcp $source_ref"
