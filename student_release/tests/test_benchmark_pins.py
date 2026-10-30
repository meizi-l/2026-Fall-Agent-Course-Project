from __future__ import annotations

import importlib.metadata
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile


COURSE_ROOT = Path(__file__).resolve().parents[2]


def _locked_package_versions(path: Path) -> dict[str, str]:
    versions = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        versions[name.lower()] = version
    return versions


def test_mcpmark_task_runner_lock_excludes_postgres_tool_server_packages():
    versions = _locked_package_versions(COURSE_ROOT / "third_party" / "locks" / "mcpmark-python.txt")

    assert "postgres-mcp" not in versions
    assert "pglast" not in versions
    assert "instructor" not in versions


def test_postgres_mcp_lock_uses_course_server_and_supported_pglast():
    versions = _locked_package_versions(COURSE_ROOT / "third_party" / "locks" / "postgres-mcp-python.txt")

    assert versions["postgres-mcp"] == "0.3.0+course1"
    assert versions["pglast"] == "7.21"
    assert versions["instructor"] == "1.17.0"
    assert versions["click"] == "8.5.0"
    assert versions["openai"] == "3.3.0"
    assert versions["mcp"] == "1.30.0"


def test_course_postgres_mcp_wheel_has_expected_metadata_and_checksum():
    wheel = COURSE_ROOT / "third_party" / "wheels" / "postgres_mcp-0.3.0+course1-py3-none-any.whl"
    checksums = COURSE_ROOT / "third_party" / "wheels" / "SHA256SUMS"

    expected_hash, expected_name = checksums.read_text(encoding="utf-8").strip().split()
    assert expected_name == wheel.name
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == expected_hash

    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")

    assert "Version: 0.3.0+course1\n" in metadata
    assert "Requires-Dist: pglast==7.21\n" in metadata
    assert "Requires-Python: >=3.12\n" in metadata


def test_course_postgres_mcp_build_inputs_pin_upstream_and_metadata_only_patch():
    build_script = (COURSE_ROOT / "third_party" / "build_postgres_mcp_wheel.sh").read_text(encoding="utf-8")
    patch = (COURSE_ROOT / "third_party" / "patches" / "postgres-mcp-0.3.0-course1.patch").read_text(
        encoding="utf-8"
    )

    assert "7179ab0336396f819e23b0b012a9c284be10fac3" in build_script
    assert 'version = "0.3.0+course1"' in patch
    assert '"pglast==7.21"' in patch
    assert "src/postgres_mcp" not in patch


def test_pin_checker_rejects_installed_version_drift(tmp_path):
    checker = COURSE_ROOT / "third_party" / "check_python_pins.py"
    expected = tmp_path / "pins.txt"
    actual_version = importlib.metadata.version("pytest")
    expected.write_text(f"pytest=={actual_version}\n")
    result = subprocess.run([sys.executable, str(checker), str(expected)], capture_output=True, text=True)
    assert result.returncode == 0

    expected.write_text("pytest==0.0.0\n")
    result = subprocess.run([sys.executable, str(checker), str(expected)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "pytest" in result.stderr


def test_tau2_lock_checker_rejects_version_drift(tmp_path):
    checker = COURSE_ROOT / "third_party" / "check_tau2_lock.py"
    lock = tmp_path / "uv.lock"
    actual_version = importlib.metadata.version("pytest")
    lock.write_text(f'[[package]]\nname = "pytest"\nversion = "{actual_version}"\n')
    result = subprocess.run([sys.executable, str(checker), str(lock)], capture_output=True, text=True)
    assert result.returncode == 0
    lock.write_text('[[package]]\nname = "pytest"\nversion = "0.0.0"\n')
    result = subprocess.run([sys.executable, str(checker), str(lock)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "pytest" in result.stderr
