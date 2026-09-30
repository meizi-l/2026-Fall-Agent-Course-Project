from datetime import UTC, datetime
import json

from course_agent.util import append_jsonl, make_run_id, safe_case_id, write_json


def test_util_writes_jsonl_and_safe_ids(tmp_path):
    assert safe_case_id("filesystem/desktop/timeline extraction") == "filesystem_desktop_timeline_extraction"
    assert make_run_id(datetime(2026, 9, 25, 1, 2, 3, tzinfo=UTC)).startswith("20260925T010203Z-")

    json_path = tmp_path / "nested" / "data.json"
    write_json(json_path, {"b": 1})
    assert json.loads(json_path.read_text()) == {"b": 1}

    jsonl_path = tmp_path / "nested" / "events.jsonl"
    append_jsonl(jsonl_path, {"event": "one"})
    append_jsonl(jsonl_path, {"event": "two"})
    assert [json.loads(line)["event"] for line in jsonl_path.read_text().splitlines()] == ["one", "two"]
