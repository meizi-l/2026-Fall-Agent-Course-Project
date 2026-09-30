from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_local_checks_agent_process_and_documents_scope():
    result = subprocess.run(
        [sys.executable, "smoke_local.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )

    assert "Smoke passed" in result.stdout
    assert "agent_process" in result.stdout
    assert "public_runner assignment config" in result.stdout
    assert "does not check official benchmark environments" in result.stdout
