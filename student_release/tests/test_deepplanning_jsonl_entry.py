from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_entry():
    spec = importlib.util.spec_from_file_location(
        "deepplanning_jsonl_entry_under_test",
        ROOT / "public_runner" / "envs" / "deepplanning_jsonl_entry.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_deepplanning_entry_parses_public_shopping_case_id():
    module = _load_entry()

    parsed = module.parse_shopping_case_id("shopping/level_1/case_12")

    assert parsed.level == 1
    assert parsed.sample_id == "12"
    assert parsed.case_dir_name == "case_12"


def test_deepplanning_entry_rejects_non_shopping_case_id():
    module = _load_entry()

    try:
        module.parse_shopping_case_id("travel/level_1/case_12")
    except ValueError as exc:
        assert "shopping/level_<1|2|3>/case_<id>" in str(exc)
    else:
        raise AssertionError("expected ValueError")
