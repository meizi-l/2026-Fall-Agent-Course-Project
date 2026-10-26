from __future__ import annotations

import importlib.metadata
from pathlib import Path
import subprocess
import sys


COURSE_ROOT = Path(__file__).resolve().parents[2]


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
