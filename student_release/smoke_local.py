from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


BENCHMARK_CASES = {
    "mcpmark": "filesystem/file_context/pattern_matching",
    "tau2_airline": "49",
    "deepplanning": "shopping/level_1/case_10",
}


def _request(benchmark: str, case_id: str) -> dict[str, object]:
    return {
        "request_id": uuid.uuid4().hex,
        "context_id": f"smoke-{benchmark}-{uuid.uuid4().hex}",
        "benchmark": benchmark,
        "case_id": case_id,
        "step": 0,
        "text": "Course contract smoke request.",
        "observation": {},
        "tools": [],
        "limits": {"case_timeout_sec": 30, "max_agent_turns": 1},
    }


def main() -> int:
    root = Path(__file__).resolve().parent
    assignment_path = root / "task_configs" / "public_cases.json"
    assignment = json.loads(assignment_path.read_text())
    missing_benchmarks = sorted(set(BENCHMARK_CASES) - set(assignment.get("benchmarks", {})))
    if missing_benchmarks:
        print(f"Missing benchmarks in public assignment config: {missing_benchmarks}", file=sys.stderr)
        return 1
    env = os.environ.copy()
    src = str(root / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    requests = [_request(benchmark, case_id) for benchmark, case_id in BENCHMARK_CASES.items()]
    payload = "".join(json.dumps(request) + "\n" for request in requests)
    proc = subprocess.run(
        [sys.executable, "-m", "course_agent.agent_process"],
        cwd=root,
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != len(requests):
        print(f"Expected {len(requests)} responses, got {len(lines)}", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return 1
    for request, line in zip(requests, lines, strict=True):
        response = json.loads(line)
        if response.get("request_id") != request["request_id"]:
            print(f"Wrong request_id in response: {response}", file=sys.stderr)
            return 1
        if response.get("kind") not in {"tool_call", "tool_calls", "final"}:
            print(f"Unexpected response kind: {response}", file=sys.stderr)
            return 1
    print("Smoke passed for mcpmark, tau2_airline, and deepplanning.")
    print("Checked: course_agent.agent_process JSONL protocol and public_runner assignment config.")
    print("This does not check official benchmark environments; run third_party setup checks for those.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
