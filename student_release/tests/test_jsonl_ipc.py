from __future__ import annotations

import sys
import time

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
