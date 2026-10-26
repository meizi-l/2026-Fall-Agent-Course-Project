import json
import os
from pathlib import Path
import sys
import time

import pytest

from public_runner.envs import official
from public_runner import run_public_tasks as runner


@pytest.mark.skipif(os.name != "posix", reason="Course case deadlines use POSIX signals")
def test_tau2_timeout_preserves_attempt_events_and_stops_usage_writers(tmp_path, monkeypatch):
    monkeypatch.setattr(official, "_tau2_setup_report", lambda: {"missing": [], "tau2_repo": str(tmp_path)})
    monkeypatch.setattr(official, "_tau2_llm_env_error", lambda: "")
    child_code = """
import json, os, pathlib, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
p = pathlib.Path(os.environ['COURSE_LLM_USAGE_PATH'])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({'event':'llm_call_started','call_id':'pending'})+'\\n')
pathlib.Path(os.environ['COURSE_TAU2_AGENT_TRAJECTORY']).write_text(
    json.dumps({'event':'request','request':{'request_id':'one'}})+'\\n'+
    json.dumps({'event':'response','request_id':'one','response':{'kind':'final','content':'hello'}})+'\\n'+
    json.dumps({'event':'request','request':{'request_id':'two'}})+'\\n')
time.sleep(3)
with p.open('a') as f:
    f.write(json.dumps({'event':'llm_call','call_id':'pending','status':'success','usage':{'total_tokens':99}})+'\\n')
"""
    benchmark_code = (
        "import os, subprocess, sys, time; "
        f"p=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(10)"
    )
    monkeypatch.setattr(official, "_tau2_command", lambda *args: [sys.executable, "-c", benchmark_code])
    results = []
    for attempt in (1, 2):
        result = runner._run_case_attempt(
            backend_name="official", item={"benchmark": "tau2_airline", "case": {"case_id": "49", "case_key": "tau2_49"}},
            assignment={"limits": {"case_timeout_sec": 1}}, run_id="test", started_at="now", run_dir=str(tmp_path),
            attempt=attempt, auto_resumed=attempt == 2, previous_status="runner_error" if attempt == 2 else None,
        )
        results.append(result)
    try:
        assert all(result["status"] == "runner_error" for result in results)
        output_dirs = []
        for result in results:
            events = [json.loads(line) for line in (tmp_path / result["trajectory_path"]).read_text().splitlines()]
            commands = [event for event in events if event["event"] == "official_command"]
            assert len(commands) == 1
            output_dirs.append(Path(commands[0]["output_dir"]))
            assert output_dirs[-1].is_relative_to(tmp_path)
            assert sum(event["event"] == "request" for event in events) == 2
            assert sum(event["event"] == "response" for event in events) == 1
            assert any(event["event"] == "request_interrupted" and event["request_id"] == "two" for event in events)
            assert any(event.get("error_type") == "TimeoutError" for event in events)
            assert result["llm_interrupted_call_count"] == 1
            assert result["llm_usage_complete"] is False
        assert output_dirs[0] != output_dirs[1]
        snapshots = [(tmp_path / result["llm_usage_path"]).read_bytes() for result in results]
        time.sleep(1.2)
        assert [(tmp_path / result["llm_usage_path"]).read_bytes() for result in results] == snapshots
    finally:
        # Old implementations leave children alive briefly; let this finite fixture finish.
        time.sleep(0.1)


def test_usage_summary_marks_unfinished_calls_without_double_counting():
    summary = runner._llm_usage_summary([
        {"event": "llm_call_started", "call_id": "done"},
        {"event": "llm_call", "call_id": "done", "status": "success", "usage": {"total_tokens": 5}},
        {"event": "llm_call_started", "call_id": "interrupted"},
    ])
    assert summary["llm_api_call_count"] == 2
    assert summary["llm_successful_call_count"] == 1
    assert summary["llm_interrupted_call_count"] == 1
    assert summary["llm_total_tokens"] == 5
    assert summary["llm_usage_complete"] is False
    totals = runner._sum_llm_usage([summary, runner._llm_usage_summary([])])
    assert totals["llm_api_call_count"] == 2
    assert totals["llm_interrupted_call_count"] == 1
    assert totals["llm_usage_complete"] is False


def test_truncated_utf8_sidecars_preserve_complete_events(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"event":"request","request":{"request_id":"one"}}\n{"text":"\xe4')
    events = official._load_tau2_agent_events(path)
    assert sum(event["event"] == "request" for event in events) == 1
    assert any(event.get("error_type") == "Tau2AgentTrajectoryParseError" for event in events)
    usage = runner._load_llm_usage_events(path)
    assert any(event.get("error_type") == "LLMUsageParseError" for event in usage)


def test_invalid_student_response_does_not_hide_recorded_request(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"event":"request","request":{"request_id":"one"}}\n{"event":"response","response":null}\n')
    events = official._load_tau2_agent_events(path)
    assert any(event["event"] == "request" for event in events)
    assert any(event["event"] == "response" and event["response"] is None for event in events)


@pytest.mark.parametrize("reward,exit_code,status", [(1.0, 0, "scored_success"), (0.0, 0, "scored_failure"), (0.0, 2, "official_runtime_error")])
def test_tau2_completed_attempt_emits_events_once_and_keeps_native_verdict(tmp_path, monkeypatch, reward, exit_code, status):
    monkeypatch.setattr(official, "_tau2_setup_report", lambda: {"missing": [], "tau2_repo": str(tmp_path)})
    monkeypatch.setattr(official, "_tau2_llm_env_error", lambda: "")
    code = f"""
import json, os, pathlib, sys
p = pathlib.Path(os.environ['COURSE_TAU2_AGENT_TRAJECTORY'])
p.write_text(json.dumps({{'event':'request','request':{{'request_id':'one'}}}})+'\\n'+
    json.dumps({{'event':'response','response':{{'request_id':'one','kind':'final','content':'done'}}}})+'\\n')
(p.parent / 'results.json').write_text(json.dumps({{'simulations':[{{'task_id':'49','reward_info':{{'reward':{reward}}}}}]}}))
sys.exit({exit_code})
"""
    monkeypatch.setattr(official, "_tau2_command", lambda *args: [sys.executable, "-c", code])
    result = runner._run_case_attempt(
        backend_name="official", item={"benchmark": "tau2_airline", "case": {"case_id": "49", "case_key": "tau2_49"}},
        assignment={"limits": {"case_timeout_sec": 10}}, run_id="test", started_at="now", run_dir=str(tmp_path),
        attempt=1, auto_resumed=False, previous_status=None,
    )
    events = [json.loads(line) for line in (tmp_path / result["trajectory_path"]).read_text().splitlines()]
    assert result["status"] == status
    assert result["grading_score"] == reward
    assert sum(event["event"] == "official_command" for event in events) == 1
    assert sum(event["event"] == "request" for event in events) == 1
    assert sum(event["event"] == "response" for event in events) == 1
    assert not any(event["event"] == "request_interrupted" for event in events)
    assert sum(event["event"] == "score" for event in events) == (1 if exit_code == 0 else 0)
