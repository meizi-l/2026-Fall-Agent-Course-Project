"""Select the local or staff-configured JSONL student process launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path


STUDENT_ENV_KEYS = frozenset({
    "PATH", "LANG", "LC_ALL", "TZ", "PYTHONUNBUFFERED", "COURSE_LLM_USAGE_PATH",
    "COURSE_LLM_MODEL", "COURSE_LLM_TIMEOUT_SEC", "COURSE_LLM_MAX_INPUT_TOKENS",
    "COURSE_LLM_MAX_OUTPUT_TOKENS", "COURSE_LLM_MAX_ATTEMPTS",
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_DEPLOYMENT",
    "OPENAI_BASE_URL", "AZURE_API_BASE", "AZURE_API_VERSION",
})


def student_launcher_env(student_root: Path) -> dict[str, str]:
    token = os.environ.get("COURSE_STUDENT_API_KEY")
    if not token:
        raise RuntimeError("COURSE_STUDENT_API_KEY is required for isolated student execution")
    env = {key: value for key in STUDENT_ENV_KEYS if (value := os.environ.get(key)) is not None}
    env["PYTHONPATH"] = str(student_root / "src")
    for key in ("COURSE_API_KEY", "AZURE_OPENAI_API_KEY", "OPENAI_API_KEY", "AZURE_API_KEY"):
        env[key] = token
    return env


def configured_launcher_command(setting: str, student_root: Path, python: str) -> list[str]:
    try:
        command = json.loads(setting)
    except json.JSONDecodeError as exc:
        raise ValueError("student launcher command must be a JSON array") from exc
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg for arg in command):
        raise ValueError("student launcher command must be a non-empty JSON string array")
    return [arg.replace("{student_root}", str(student_root)).replace("{python}", python) for arg in command]


def student_process_launch(student_root: Path, python: str) -> tuple[list[str], dict[str, str]]:
    setting = os.environ.get("COURSE_AGENT_PROCESS_COMMAND")
    if setting:
        return configured_launcher_command(setting, student_root, python), student_launcher_env(student_root)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(student_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return [python, "-m", "course_agent.agent_process"], env
