from __future__ import annotations

import contextlib
import json
import sys
import traceback
from typing import TextIO

from course_agent.protocol import AgentRequest, AgentResponse
from course_agent.student_agent import StudentAgent


def handle_line(agent: StudentAgent, line: str) -> AgentResponse:
    request_id: str | None = None
    try:
        raw = json.loads(line)
        if isinstance(raw, dict):
            candidate = raw.get("request_id")
            request_id = candidate if isinstance(candidate, str) else None
        request = AgentRequest.from_dict(raw)
        return agent.respond(request)
    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr)
        return AgentResponse.error(request_id, type(exc).__name__, str(exc) or type(exc).__name__)


def run_jsonl(stdin: TextIO, stdout: TextIO) -> int:
    agent = StudentAgent()
    for line in stdin:
        if not line.strip():
            continue
        with contextlib.redirect_stdout(sys.stderr):
            response = handle_line(agent, line)
        stdout.write(json.dumps(response.to_dict(), separators=(",", ":")) + "\n")
        stdout.flush()
    return 0


def main() -> None:
    raise SystemExit(run_jsonl(sys.stdin, sys.stdout))


if __name__ == "__main__":
    main()
