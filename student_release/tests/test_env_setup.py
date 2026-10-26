from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
NAMES = ["COURSE_API_KEY", "OPENAI_BASE_URL", "COURSE_LLM_MODEL", "TAU2_USER_MODEL"]


def _source_env_script(script: Path, names: list[str], stale=False) -> dict[str, str]:
    printf_args = " ".join(f'"${name}"' for name in names)
    command = f"source '{script}'; printf '%s\\n' {printf_args}"
    # Never inherit real credentials or a developer's provider overrides.
    env = {"PATH": os.environ["PATH"]}
    if stale:
        env.update({"OPENAI_BASE_URL": "https://old.invalid", "TAU2_USER_MODEL": "azure/gpt-4o-mini"})
    completed = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", command],
        env=env, check=True, text=True, capture_output=True,
    )
    return dict(zip(names, completed.stdout.splitlines(), strict=True))


def test_env_examples_supply_shared_genai_service_and_distinct_models():
    script = ROOT / "env.student.sh.example"
    names = NAMES + ["COURSE_LLM_TIMEOUT_SEC", "COURSE_LLM_MAX_ATTEMPTS", "TAU2_USER_LLM_ARGS", "TAU2_REPO"]
    values = _source_env_script(script, names)
    assert values["COURSE_API_KEY"] == "replace-with-your-hkust-genai-api-key"
    assert values["OPENAI_BASE_URL"] == "https://hkust.azure-api.net/hkust-genai/v1"
    assert values["COURSE_LLM_MODEL"] == "gpt-5-mini"
    assert values["TAU2_USER_MODEL"] == "openai/gpt-4o-mini"
    assert all(values[name] == "" for name in names[4:])


def test_env_examples_override_stale_provider_selection():
    values = _source_env_script(ROOT / "env.student.sh.example", NAMES, stale=True)
    assert values["OPENAI_BASE_URL"] == "https://hkust.azure-api.net/hkust-genai/v1"
    assert values["TAU2_USER_MODEL"] == "openai/gpt-4o-mini"
