"""Optional pinned-environment integration; no API key or network is required."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_pinned_tau2_airline_policy_reaches_student_python_subprocess(tmp_path):
    repo = Path(os.environ.get("TAU2_REPO", ROOT.parent / "third_party" / "tau2-bench")).resolve()
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        pytest.skip("requires the optional pinned tau2 environment")
    code = textwrap.dedent('''
        import json
        import os
        import sys
        from pathlib import Path
        from tau2.domains.airline.environment import get_environment
        from tau2.data_model.message import UserMessage
        from public_runner.envs.tau2_jsonl_entry import create_student_jsonl_agent

        root, student_python, sidecar = sys.argv[1:]
        child = "\\n".join([
            "import json, sys",
            "from course_agent.protocol import AgentRequest, AgentResponse",
            "for line in sys.stdin:",
            "    request = AgentRequest.from_dict(json.loads(line))",
            "    response = AgentResponse.final(request.request_id, json.dumps(request.to_dict()))",
            "    print(json.dumps(response.to_dict()), flush=True)",
        ])
        os.environ["COURSE_AGENT_PROCESS_COMMAND"] = json.dumps(["{python}", "-u", "-c", child])
        os.environ["COURSE_STUDENT_API_KEY"] = "test-ipc-token"
        os.environ["COURSE_TAU2_AGENT_TRAJECTORY"] = sidecar
        os.environ["TAU2_CURRENT_TASK_ID"] = "49"
        env = get_environment()
        policy = env.get_policy()
        assert policy and "Cancel flight" in policy
        limits = {"case_timeout_sec": 300, "max_agent_turns": 100, "max_tool_calls_per_turn": 3}
        agent = create_student_jsonl_agent(
            tools=env.get_tools(), domain_policy=policy,
            llm_args={"student_root": root, "python": student_python, "timeout": 5, "limits": limits},
        )
        try:
            state = agent.get_init_state()
            response, state = agent.generate_next_message(
                UserMessage(role="user", content="Please cancel my reservation."), state,
            )
            request = json.loads(response.content)
            assert request["observation"]["domain_policy"] == policy
            assert request["observation"]["content"] == "Please cancel my reservation."
            assert request["limits"] == limits
            assert request["tools"][0] == env.get_tools()[0].openai_schema
            assert request["tools"][-1]["function"]["name"] == "respond_to_user"
            assert request["case_id"] == "49" and state.step == 1
            assert os.getpgid(agent.client._proc.pid) == os.getpgrp()
        finally:
            agent.close()
        events = [json.loads(line) for line in Path(sidecar).read_text().splitlines()]
        assert events[0]["request"]["observation"]["domain_policy"] == policy
        assert events[1]["response"]["request_id"] == request["request_id"]
        print("Native airline policy -> tau2 adapter -> student Python JSONL -> AgentRequest passed.")
    ''')
    env = {
        "PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT),
        "TAU2_DATA_DIR": str(repo / "data"), "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "COURSE_TAU2_OWNED_PROCESS_GROUP": "1",
    }
    completed = subprocess.run(
        [str(python), "-c", code, str(ROOT), sys.executable, str(tmp_path / "events.jsonl")],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_pinned_tau2_user_simulator_genai_transport_and_logs(tmp_path):
    repo = Path(os.environ.get("TAU2_REPO", ROOT.parent / "third_party" / "tau2-bench")).resolve()
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        pytest.skip("requires the optional pinned tau2 environment")
    code = textwrap.dedent('''
        import asyncio
        import json
        import sys
        from pathlib import Path
        import httpx
        from tau2.utils import llm_utils
        from tau2.user.user_simulator import UserSimulator
        from tau2.data_model.message import AssistantMessage
        from public_runner.envs.tau2_jsonl_entry import _configure_user_llm_transport

        requests = []
        def handle(request):
            requests.append(request)
            assert str(request.url) == "https://hkust.azure-api.net/hkust-genai/v1/chat/completions"
            assert request.headers["api-key"] == "test-simulator-secret"
            body = json.loads(request.content)
            assert body["model"] == "gpt-4o-mini"
            assert body["temperature"] == 0.0
            assert body["messages"]
            return httpx.Response(200, json={
                "id": "test-user", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": "I need to check my flight.",
                }}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            })

        llm_utils.litellm.client_session.close()
        asyncio.run(llm_utils.litellm.aclient_session.aclose())
        llm_utils.litellm.client_session = httpx.Client(transport=httpx.MockTransport(handle))
        llm_utils.litellm.aclient_session = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        llm_utils.litellm.telemetry = False
        _configure_user_llm_transport()
        log_dir = Path(sys.argv[1])
        llm_utils.set_llm_log_dir(log_dir)
        llm_utils.set_llm_log_mode("all")
        simulator = UserSimulator(
            llm="openai/gpt-4o-mini", instructions="Ask about your flight.",
            llm_args={"temperature": 0.0, "timeout": 300},
        )
        message, state = simulator.generate_next_message(
            AssistantMessage(role="assistant", content="How can I help?"), simulator.get_init_state(),
        )
        assert message.content == "I need to check my flight."
        assert message.usage["prompt_tokens"] == 10
        assert len(requests) == 1
        logs = list(log_dir.glob("*.json"))
        assert logs, "tau2 should record the simulator request and response"
        for path in logs:
            text = path.read_text()
            assert "test-simulator-secret" not in text
            assert "api-key" not in text
            assert json.loads(text)["request"]["model"] == "openai/gpt-4o-mini"
        llm_utils.litellm.client_session.close()
        asyncio.run(llm_utils.litellm.aclient_session.aclose())
        print("Pinned tau2 simulator, LiteLLM, authentication and logs passed.")
    ''')
    env = {
        "PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT),
        "TAU2_DATA_DIR": str(repo / "data"), "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "COURSE_API_KEY": "test-simulator-secret",
        "OPENAI_API_KEY": "stale-test-key", "OPENAI_BASE_URL": "https://hkust.azure-api.net/hkust-genai/v1",
    }
    completed = subprocess.run(
        [str(python), "-c", code, str(tmp_path)], env=env, cwd=ROOT,
        capture_output=True, text=True, timeout=60,
    )
    output = completed.stdout + completed.stderr
    assert "test-simulator-secret" not in output
    assert completed.returncode == 0, output
