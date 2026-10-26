from __future__ import annotations

import sys
import time
import os
import subprocess

import pytest


def test_jsonl_process_times_out_and_reaps_hung_child(tmp_path):
    from public_runner.jsonl_ipc import JSONLProcess

    process = JSONLProcess(
        [sys.executable, "-u", "-c", "import sys,time; sys.stdin.readline(); time.sleep(10)"],
        cwd=tmp_path,
        timeout=0.2,
    )
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        process.send({"request_id": "one"})
    assert time.monotonic() - started < 3
    assert process.pid is not None
    assert process.poll() is not None


def test_jsonl_process_drains_large_stderr(tmp_path):
    from public_runner.jsonl_ipc import JSONLProcess

    process = JSONLProcess(
        [sys.executable, "-u", "-c", "import sys,json; sys.stdin.readline(); sys.stderr.write('x'*200000); print(json.dumps({'ok':True}))"],
        cwd=tmp_path,
        timeout=2,
    )
    try:
        assert process.send({"request_id": "one"}) == {"ok": True}
    finally:
        process.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_jsonl_child_can_share_case_group_and_close_without_killing_parent(tmp_path):
    from public_runner.jsonl_ipc import JSONLProcess

    process = JSONLProcess(
        [sys.executable, "-u", "-c", "import json,os,sys,time; sys.stdin.readline(); print(json.dumps({'group':os.getpgrp()})); time.sleep(10)"],
        cwd=tmp_path, timeout=2, start_new_session=False,
    )
    try:
        assert process.send({})["group"] == os.getpgrp()
    finally:
        process.close()
    assert process.poll() is not None


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_group_cleanup_reaps_writers_after_leader_already_exited(tmp_path):
    from public_runner.jsonl_ipc import stop_process

    output = tmp_path / "late.txt"
    child = f"import time,pathlib; time.sleep(1.5); pathlib.Path({str(output)!r}).write_text('late')"
    leader = subprocess.Popen(
        [sys.executable, "-c", f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child!r}])"],
        start_new_session=True,
    )
    try:
        leader.wait(timeout=2)
        stop_process(leader)
        time.sleep(1.6)
        assert not output.exists()
    finally:
        stop_process(leader, force=True)
