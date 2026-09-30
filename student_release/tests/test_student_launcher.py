from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


def test_isolated_student_launch_uses_separate_token_and_allowlist(tmp_path, monkeypatch):
    from public_runner.student_launcher import student_process_launch

    monkeypatch.setenv("COURSE_AGENT_PROCESS_COMMAND", json.dumps(["sandbox", "{student_root}", "{python}"]))
    monkeypatch.setenv("COURSE_STUDENT_API_KEY", "student-token")
    monkeypatch.setenv("COURSE_API_KEY", "staff-token")
    monkeypatch.setenv("STAFF_HIDDEN_PATH", "/secret/cases.json")
    argv, env = student_process_launch(tmp_path, sys.executable)

    assert argv == ["sandbox", str(tmp_path), sys.executable]
    assert env["COURSE_API_KEY"] == "student-token"
    assert env["AZURE_OPENAI_API_KEY"] == "student-token"
    assert env["OPENAI_API_KEY"] == "student-token"
    assert "STAFF_HIDDEN_PATH" not in env
    assert "staff-token" not in env.values()


def test_isolated_student_launch_requires_student_token(tmp_path, monkeypatch):
    from public_runner.student_launcher import student_process_launch

    monkeypatch.setenv("COURSE_AGENT_PROCESS_COMMAND", '["sandbox"]')
    monkeypatch.delenv("COURSE_STUDENT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="COURSE_STUDENT_API_KEY"):
        student_process_launch(tmp_path, sys.executable)


def test_public_runner_uses_configured_student_launcher(monkeypatch):
    import public_runner.run_public_tasks as runner

    captured = {}

    class FakeProcess:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["env"] = kwargs["env"]

        def close(self):
            pass

    monkeypatch.setattr(runner, "JSONLProcess", FakeProcess)
    monkeypatch.setenv("COURSE_AGENT_PROCESS_COMMAND", '["sandbox", "{student_root}", "{python}"]')
    monkeypatch.setenv("COURSE_STUDENT_API_KEY", "student-token")
    monkeypatch.setenv("COURSE_API_KEY", "staff-token")
    runner.AgentProcessClient().close()
    assert captured["argv"][0] == "sandbox"
    assert captured["env"]["COURSE_API_KEY"] == "student-token"
