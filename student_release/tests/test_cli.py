from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import tomllib

import public_runner.cli as runner_cli


ROOT = Path(__file__).resolve().parents[1]


def test_cli_delegates_arguments_to_public_runner(monkeypatch):
    captured: dict[str, list[str] | None] = {}

    def fake_main(argv: list[str] | None = None) -> int:
        captured["argv"] = argv
        return 7

    monkeypatch.setattr(runner_cli, "run_public_tasks_main", fake_main)

    exit_code = runner_cli.main(["--backend", "simplified", "--benchmark", "tau2_airline"])

    assert exit_code == 7
    assert captured["argv"] == ["--backend", "simplified", "--benchmark", "tau2_airline"]


def test_root_cli_runs_simplified_case(tmp_path):
    output_root = tmp_path / "trajectories"

    result = subprocess.run(
        [
            sys.executable,
            "cli.py",
            "--backend",
            "simplified",
            "--benchmark",
            "tau2_airline",
            "--case-id",
            "49",
            "--output-root",
            str(output_root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )

    assert "Wrote trajectory batch" in result.stdout
    run_dir = next(output_root.iterdir())
    summary = json.loads((run_dir / "score_summary.json").read_text())
    assert summary["backend"] == "simplified"
    assert summary["completed_cases"] == 1


def test_run_tasks_console_script_is_declared():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["run-tasks"] == "public_runner.cli:main"
    assert "public_runner" in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
