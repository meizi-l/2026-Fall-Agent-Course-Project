"""Check a standalone checkout without the private parent repository."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("configured", [False, True])
def test_official_paths_follow_standalone_checkout_and_keep_repo_overrides(tmp_path, configured):
    checkout = tmp_path / "2026-Fall-Agent-Course-Project"
    release = checkout / "student_release"
    shutil.copytree(ROOT / "public_runner", release / "public_runner", ignore=shutil.ignore_patterns("__pycache__"))
    (checkout / "third_party").mkdir()
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(release)}
    variables = {"tau2_repo": "TAU2_REPO", "mcpmark_repo": "MCPMARK_REPO", "deepplanning_repo": "DEEPPLANNING_REPO"}
    if configured:
        env.update({name: str(tmp_path / "external" / name) for name in variables.values()})
    code = """
import json
from public_runner.envs.official import OfficialPublicBackend, _tau2_setup_report, _mcpmark_setup_report, _deepplanning_setup_report
print(json.dumps({'backend':OfficialPublicBackend().setup_report(), 'tau2':_tau2_setup_report(), 'mcpmark':_mcpmark_setup_report(), 'deepplanning':_deepplanning_setup_report()}))
"""
    completed = subprocess.run([sys.executable, "-c", code], cwd=release, env=env, capture_output=True, text=True, check=True)
    reports = json.loads(completed.stdout)
    assert reports["backend"]["course_project_root"] == str(checkout)
    assert "staff_side" not in reports["backend"]["found"]
    defaults = {"tau2_repo": "tau2-bench", "mcpmark_repo": "mcpmark", "deepplanning_repo": "qwen-agent"}
    for report_name, key in (("tau2", "tau2_repo"), ("mcpmark", "mcpmark_repo"), ("deepplanning", "deepplanning_repo")):
        expected = env[variables[key]] if configured else str(checkout / "third_party" / defaults[key])
        assert reports[report_name][key] == expected
    assert reports["mcpmark"]["local_node_bin"] == str(checkout / "third_party/.local/node20/bin")
