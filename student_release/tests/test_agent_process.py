import json
import os
import subprocess
import sys
from io import StringIO
import inspect

from course_agent.agent_process import handle_line, run_jsonl

def _env():
    env = os.environ.copy()
    src = os.path.abspath("src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_agent_process_returns_one_json_response_per_request():
    request = {
        "request_id": "req-1",
        "context_id": "ctx-1",
        "benchmark": "mcpmark",
        "case_id": "filesystem/desktop/timeline_extraction",
        "step": 0,
        "text": "contract ping",
        "observation": {},
        "tools": [],
        "limits": {},
    }

    proc = subprocess.run(
        [sys.executable, "-m", "course_agent.agent_process"],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        env=_env(),
        timeout=10,
        check=False,
    )

    assert proc.returncode == 0
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    response = json.loads(lines[0])
    assert response["request_id"] == "req-1"
    assert response["kind"] == "final"
    assert isinstance(response["content"], str)


def test_agent_process_reports_malformed_json_as_error():
    proc = subprocess.run(
        [sys.executable, "-m", "course_agent.agent_process"],
        input="{bad json}\n",
        text=True,
        capture_output=True,
        env=_env(),
        timeout=10,
        check=False,
    )

    assert proc.returncode == 0
    response = json.loads(proc.stdout)
    assert response["request_id"] is None
    assert response["kind"] == "error"
    assert response["error_type"] == "JSONDecodeError"


def test_agent_process_handlers_are_synchronous():
    assert not inspect.iscoroutinefunction(handle_line)
    assert not inspect.iscoroutinefunction(run_jsonl)


def test_run_jsonl_processes_requests_synchronously():
    request = {
        "request_id": "req-sync",
        "context_id": "ctx-1",
        "benchmark": "deepplanning",
        "case_id": "shopping/level_1/case_12",
        "step": 0,
        "text": "contract ping",
        "observation": {},
        "tools": [],
        "limits": {},
    }
    stdout = StringIO()

    exit_code = run_jsonl(StringIO(json.dumps(request) + "\n"), stdout)

    assert exit_code == 0
    response = json.loads(stdout.getvalue())
    assert response["request_id"] == "req-sync"
    assert response["kind"] == "final"
