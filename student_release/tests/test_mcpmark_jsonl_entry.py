from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_entry():
    spec = importlib.util.spec_from_file_location(
        "mcpmark_jsonl_entry_under_test",
        ROOT / "public_runner" / "envs" / "mcpmark_jsonl_entry.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mcpmark_entry_uses_configured_official_task_path_for_arbitrary_case_id():
    module = _load_entry()

    parsed = module.resolve_public_case(
        "staff-hidden-case-001",
        {"official_task_path": "filesystem/standard/legal_document/contract_dates"},
    )

    assert parsed.service == "filesystem"
    assert parsed.task_suite == "standard"
    assert parsed.task_filter == "legal_document/contract_dates"
    assert parsed.official_task_path == "filesystem/standard/legal_document/contract_dates"


def test_mcpmark_entry_requires_configured_official_task_path():
    module = _load_entry()

    try:
        module.resolve_public_case("postgres/easy/chinook/top_customers")
    except ValueError as exc:
        assert "official_task_path" in str(exc)
    else:
        raise AssertionError("expected missing official_task_path to fail")


def test_mcpmark_entry_rejects_non_course_service():
    module = _load_entry()

    try:
        module.resolve_public_case(
            "staff-hidden-github-case",
            {"official_task_path": "github/verified/issues/task"},
        )
    except ValueError as exc:
        assert "only enables filesystem and postgres" in str(exc)
    else:
        raise AssertionError("expected unsupported MCPMark service to fail")


def test_selected_mcpmark_task_files_are_checked(tmp_path):
    from public_runner.envs.mcpmark_case_config import validate_mcpmark_task_files

    case = {"case_id": "staff-case", "official_task_path": "filesystem/standard/docs/one"}
    try:
        validate_mcpmark_task_files(tmp_path, case)
    except ValueError as exc:
        assert "description.md" in str(exc)
    else:
        raise AssertionError("missing selected task files must fail")

    task = tmp_path / "tasks" / "filesystem" / "standard" / "docs" / "one"
    task.mkdir(parents=True)
    (task / "description.md").write_text("task")
    (task / "verify.py").write_text("pass\n")
    (task / "meta.json").write_text('{"category_id":"docs","task_id":"one","mcp":["filesystem"]}')
    validate_mcpmark_task_files(tmp_path, case)
