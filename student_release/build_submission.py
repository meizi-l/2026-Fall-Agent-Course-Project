from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any
import zipfile


SKIP_NAMES = {
    ".env",
    ".envrc",
    "env.local.sh",
    "env.student.local.sh",
}
FORBIDDEN_NAMES = {
    "hidden_final.private.json",
}
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "runs",
    "trajectories",
    "trajectories_smoke",
    "artifacts",
    "results",
}
FORBIDDEN_SUFFIXES = {
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".pt",
    ".pth",
    ".safetensors",
    ".gguf",
    ".sqlite",
    ".db",
    ".log",
}
REQUIRED_FILES = {
    "pyproject.toml",
    "uv.lock",
    "submission.json",
    "src/course_agent/student_agent.py",
}
INTERNAL_ONLY_FILES = {
    "src/course_agent/baseline_agent.py",
}
REQUIRED_METADATA_FIELDS = ("student_id", "student_name", "email")
STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_PACKAGE_COUNT = 150
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_ESTIMATED_DOWNLOAD_BYTES = 300 * 1024 * 1024
PYPI_REGISTRY_URL = "https://pypi.org/simple"


class ForbiddenFileError(RuntimeError):
    """Raised when a submission contains content forbidden by course policy."""


class SubmissionMetadataError(RuntimeError):
    """Raised when submission.json is missing or malformed."""


class DependencyPolicyError(RuntimeError):
    """Raised when pyproject.toml/uv.lock violate course dependency policy."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _is_skipped(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if parts & SKIP_DIRS:
        return True
    if path.name.lower() in SKIP_NAMES:
        return True
    return path.as_posix() in INTERNAL_ONLY_FILES


def _is_forbidden(path: Path) -> bool:
    if path.name.lower() in FORBIDDEN_NAMES:
        return True
    return path.suffix.lower() in FORBIDDEN_SUFFIXES


def validate_submission_metadata(root: Path) -> dict[str, str]:
    path = root / "submission.json"
    if not path.exists():
        raise SubmissionMetadataError("Missing submission.json. Copy submission.example.json and fill in your details.")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SubmissionMetadataError(f"submission.json is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SubmissionMetadataError("submission.json must be a JSON object")

    metadata: dict[str, str] = {}
    missing = [field for field in REQUIRED_METADATA_FIELDS if field not in raw]
    if missing:
        raise SubmissionMetadataError(f"submission.json missing required field(s): {', '.join(missing)}")
    for field in REQUIRED_METADATA_FIELDS:
        value = raw[field]
        if not isinstance(value, str):
            raise SubmissionMetadataError(f"submission.json field {field!r} must be a string")
        stripped = value.strip()
        if not stripped:
            raise SubmissionMetadataError(f"submission.json field {field!r} must be non-empty")
        metadata[field] = stripped

    if not STUDENT_ID_RE.match(metadata["student_id"]):
        raise SubmissionMetadataError("student_id must be 3-64 characters using letters, digits, underscore, dash, or dot")
    if not EMAIL_RE.match(metadata["email"]):
        raise SubmissionMetadataError("email must look like a valid email address")

    example_path = root / "submission.example.json"
    if example_path.exists():
        try:
            example = json.loads(example_path.read_text())
        except json.JSONDecodeError:
            example = {}
        if isinstance(example, dict):
            same_as_example = all(str(example.get(field, "")).strip() == metadata[field] for field in REQUIRED_METADATA_FIELDS)
            if same_as_example:
                raise SubmissionMetadataError("submission.json still matches submission.example.json; fill in your own details")

    _write_json(path, metadata)
    return metadata


def _load_lock(root: Path) -> dict[str, Any]:
    lock_path = root / "uv.lock"
    if not lock_path.exists():
        raise DependencyPolicyError("Missing uv.lock")
    try:
        return tomllib.loads(lock_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise DependencyPolicyError(f"uv.lock is not valid TOML: {exc}") from exc


def validate_dependency_policy(root: Path) -> dict[str, Any]:
    if not (root / "pyproject.toml").exists():
        raise DependencyPolicyError("Missing pyproject.toml")
    lock = _load_lock(root)
    packages = lock.get("package", [])
    if not isinstance(packages, list):
        raise DependencyPolicyError("uv.lock package section is malformed")
    if len(packages) > MAX_PACKAGE_COUNT:
        raise DependencyPolicyError(f"too many locked packages: {len(packages)} > {MAX_PACKAGE_COUNT}")

    estimated_download_bytes = 0
    for package in packages:
        if not isinstance(package, dict):
            raise DependencyPolicyError("uv.lock package entry is malformed")
        name = str(package.get("name", "<unknown>"))
        source = package.get("source", {})
        if not isinstance(source, dict):
            raise DependencyPolicyError(f"{name}: source is malformed")

        if source.get("editable") == ".":
            continue
        if any(key in source for key in ("git", "url", "path", "directory", "editable")):
            raise DependencyPolicyError(f"{name}: git/url/path/editable dependencies are not allowed")
        registry = source.get("registry")
        if registry != PYPI_REGISTRY_URL:
            raise DependencyPolicyError(f"{name}: only PyPI registry dependencies are allowed")

        wheels = package.get("wheels", [])
        if not isinstance(wheels, list) or not wheels:
            raise DependencyPolicyError(f"{name}: no wheel is locked; source-only packages would require compile/install risk")

        wheel_sizes = [_artifact_size(name, wheel) for wheel in wheels]
        sdist = package.get("sdist")
        artifact_sizes = list(wheel_sizes)
        if isinstance(sdist, dict):
            artifact_sizes.append(_artifact_size(name, sdist))
        for size in artifact_sizes:
            if size > MAX_ARTIFACT_BYTES:
                raise DependencyPolicyError(f"{name}: locked artifact exceeds 50 MB")
        estimated_download_bytes += min(wheel_sizes)

    if estimated_download_bytes > MAX_ESTIMATED_DOWNLOAD_BYTES:
        raise DependencyPolicyError(
            f"estimated minimum dependency download exceeds 300 MB: {estimated_download_bytes} bytes"
        )
    return {
        "package_count": len(packages),
        "estimated_min_download_bytes": estimated_download_bytes,
        "limits": {
            "max_package_count": MAX_PACKAGE_COUNT,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES,
            "max_estimated_download_bytes": MAX_ESTIMATED_DOWNLOAD_BYTES,
            "allowed_registry": PYPI_REGISTRY_URL,
        },
    }


def _artifact_size(package_name: str, artifact: dict[str, Any]) -> int:
    size = artifact.get("size")
    if not isinstance(size, int) or size < 0:
        raise DependencyPolicyError(f"{package_name}: locked artifact is missing a non-negative size")
    return size


def collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _is_skipped(relative):
            continue
        if path.is_dir():
            continue
        if relative.name == "submission.zip":
            continue
        if _is_forbidden(relative):
            raise ForbiddenFileError(f"Forbidden submission file: {relative}")
        files.append(relative)
    present = {path.as_posix() for path in files}
    missing = sorted(REQUIRED_FILES - present)
    if missing:
        raise ForbiddenFileError(f"Missing required submission files: {', '.join(missing)}")
    return files


def build_submission(root: Path, output: Path, preflight_log: dict[str, Any] | None = None) -> None:
    metadata = validate_submission_metadata(root)
    validate_dependency_policy(root)
    log = preflight_log or {"steps": []}
    log.setdefault("generated_at", utc_now_iso())
    log.setdefault("status", "passed")
    log["submission"] = metadata
    _write_json(root / "submission_build_log.json", log)

    files = collect_files(root)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            archive.write(root / relative, relative.as_posix())

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    expected = REQUIRED_FILES | {"submission_build_log.json"}
    missing = sorted(expected - names)
    if missing:
        raise ForbiddenFileError(f"submission.zip missing expected file(s): {', '.join(missing)}")
    forbidden = sorted(name for name in names if Path(name).as_posix() in INTERNAL_ONLY_FILES)
    if forbidden:
        raise ForbiddenFileError(f"submission.zip includes internal file(s): {', '.join(forbidden)}")


def run_preflight(root: Path) -> dict[str, Any]:
    log: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "status": "passed",
        "steps": [],
    }
    _record_python_step(log, "validate_submission_json", lambda: validate_submission_metadata(root))
    _record_python_step(log, "dependency_policy", lambda: validate_dependency_policy(root))
    _record_command(log, "uv_lock_check", ["uv", "lock", "--check"], cwd=root)
    _record_command(log, "smoke_local", [sys.executable, "smoke_local.py"], cwd=root)
    with tempfile.TemporaryDirectory(prefix="course_submission_simplified_") as output_root:
        _record_command(
            log,
            "simplified_public_run",
            [
                sys.executable,
                "public_runner/run_public_tasks.py",
                "--backend",
                "simplified",
                "--output-root",
                output_root,
            ],
            cwd=root,
            timeout=120,
        )
    if any(step["status"] != "passed" for step in log["steps"]):
        log["status"] = "failed"
    return log


def _record_python_step(log: dict[str, Any], name: str, fn: Any) -> None:
    started = time.monotonic()
    step: dict[str, Any] = {
        "step": name,
        "kind": "python",
        "started_at": utc_now_iso(),
    }
    try:
        result = fn()
    except Exception as exc:
        step.update({"status": "failed", "error_type": type(exc).__name__, "message": str(exc)})
    else:
        step.update({"status": "passed", "result": result})
    step["duration_sec"] = round(time.monotonic() - started, 3)
    step["ended_at"] = utc_now_iso()
    log["steps"].append(step)


def _record_command(
    log: dict[str, Any],
    name: str,
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 60,
) -> None:
    started = time.monotonic()
    step: dict[str, Any] = {
        "step": name,
        "kind": "command",
        "command": command,
        "started_at": utc_now_iso(),
    }
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        step.update({"status": "failed", "error_type": type(exc).__name__, "message": str(exc), "exit_code": None})
    else:
        step.update(
            {
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            }
        )
    step["duration_sec"] = round(time.monotonic() - started, 3)
    step["ended_at"] = utc_now_iso()
    log["steps"].append(step)


def _tail(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[-limit:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build course agent project submission.zip")
    parser.add_argument("--output", default="submission.zip")
    parser.add_argument("--skip-checks", action="store_true", help="Only package files; intended for tests/debugging.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output

    log = {"generated_at": utc_now_iso(), "status": "passed", "steps": []} if args.skip_checks else run_preflight(root)
    if log.get("status") != "passed":
        _write_json(root / "submission_build_log.json", log)
        print("Submission checks failed. See submission_build_log.json.", file=sys.stderr)
        return 1
    try:
        build_submission(root, output, preflight_log=log)
    except Exception as exc:
        log["status"] = "failed"
        log.setdefault("steps", []).append(
            {
                "step": "write_submission_zip",
                "kind": "python",
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "started_at": utc_now_iso(),
                "ended_at": utc_now_iso(),
                "duration_sec": 0,
            }
        )
        _write_json(root / "submission_build_log.json", log)
        print(f"Submission build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output}")
    print(f"Wrote {root / 'submission_build_log.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
