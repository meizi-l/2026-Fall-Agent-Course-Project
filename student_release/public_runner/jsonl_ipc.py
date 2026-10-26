"""Bounded JSONL subprocess I/O shared by runner and benchmark adapters."""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from typing import Any


def stop_process(proc: subprocess.Popen, *, owns_process_group: bool = True, force: bool = False) -> None:
    """Stop owned writers, including descendants after their group leader exits."""
    grouped = os.name == "posix" and owns_process_group

    def send(*, kill: bool = False) -> None:
        retry_deadline = time.monotonic() + 1
        while True:
            try:
                if grouped:
                    os.killpg(proc.pid, signal.SIGKILL if kill else signal.SIGTERM)
                elif proc.poll() is None:
                    proc.kill() if kill else proc.terminate()
                return
            except ProcessLookupError:
                return
            except PermissionError:
                # macOS can briefly return EPERM while an orphan group is reaped.
                if not grouped or time.monotonic() >= retry_deadline:
                    raise
                time.sleep(0.02)

    deadline = time.monotonic() + (0 if force else 1)
    send(kill=force)
    if force:
        proc.wait(timeout=5)
        return
    try:
        proc.wait(timeout=max(0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        pass
    if grouped and not force:
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                pass  # Retry during the grace period; persistent denial reaches send().
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    send(kill=True)
    proc.wait(timeout=5)


class JSONLProcess:
    def __init__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout: float,
        env: dict[str, str] | None = None,
        start_new_session: bool = True,
    ) -> None:
        self.timeout = timeout
        self._owns_process_group = start_new_session
        self._closed = False
        self._proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=start_new_session,
        )
        self._responses: queue.Queue[str | None] = queue.Queue(maxsize=16)
        self._stderr: deque[str] = deque(maxlen=16)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    @property
    def pid(self) -> int:
        return self._proc.pid

    def poll(self) -> int | None:
        return self._proc.poll()

    def _read_stdout(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._responses.put(line)
        self._responses.put(None)

    def _read_stderr(self) -> None:
        assert self._proc.stderr is not None
        while chunk := self._proc.stderr.read(4096):
            self._stderr.append(chunk)

    def send(self, request: dict[str, Any]) -> Any:
        if self._proc.stdin is None:
            raise RuntimeError("JSONL process stdin is closed")
        deadline = time.monotonic() + self.timeout
        write_result: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)

        def write() -> None:
            try:
                assert self._proc.stdin is not None
                self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
                write_result.put(None)
            except BaseException as exc:
                write_result.put(exc)

        threading.Thread(target=write, daemon=True).start()
        try:
            write_error = write_result.get(timeout=max(0, deadline - time.monotonic()))
            if write_error is not None:
                raise RuntimeError(f"JSONL process write failed: {write_error}") from write_error
            line = self._responses.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            self.close(force=True)
            raise TimeoutError(f"JSONL process exceeded {self.timeout} seconds") from None
        if line is None:
            self._proc.wait(timeout=5)
            raise RuntimeError(f"JSONL process exited without response: {''.join(self._stderr)[-4000:]}")
        return json.loads(line)

    def close(self, *, force: bool = False) -> None:
        if not self._closed:
            stop_process(self._proc, owns_process_group=self._owns_process_group, force=force)
            self._closed = True
