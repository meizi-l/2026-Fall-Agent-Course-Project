import json
from pathlib import Path


def test_public_cases_example_has_expected_final_public_cases():
    data = json.loads(Path("task_configs/public_cases.json").read_text())

    assert data["schema_version"] == "1.0"
    assert data["assignment_id"] == "course-agent-project-2026-public-handbook-v1"
    assert set(data["benchmarks"]) == {"mcpmark", "tau2_airline", "deepplanning"}
    expected_counts = {"mcpmark": 8, "tau2_airline": 6, "deepplanning": 6}
    seen_case_keys = set()
    for name, benchmark in data["benchmarks"].items():
        assert benchmark["enabled"] is True
        assert benchmark["runner"] == name
        assert len(benchmark["cases"]) == expected_counts[name]
        for case in benchmark["cases"]:
            assert "case_key" in case
            assert "tags" not in case
            assert case["case_key"] not in seen_case_keys
            seen_case_keys.add(case["case_key"])

    mcpmark_case_ids = {case["case_id"] for case in data["benchmarks"]["mcpmark"]["cases"]}
    assert mcpmark_case_ids == {
        "filesystem/file_context/pattern_matching",
        "filesystem/threestudio/requirements_completion",
        "postgres/employees/management_structure_analysis",
        "postgres/dvdrental/customer_analysis_fix",
        "filesystem/folder_structure/structure_analysis",
        "postgres/lego/transactional_inventory_transfer",
        "postgres/chinook/employee_hierarchy_management",
        "postgres/sports/team_roster_management",
    }
    mcpmark_services = {case["official_task_path"].split("/", 1)[0] for case in data["benchmarks"]["mcpmark"]["cases"]}
    assert mcpmark_services == {"filesystem", "postgres"}

    deepplanning_case_ids = {case["case_id"] for case in data["benchmarks"]["deepplanning"]["cases"]}
    assert deepplanning_case_ids == {
        "shopping/level_1/case_10",
        "shopping/level_1/case_15",
        "shopping/level_2/case_18",
        "shopping/level_2/case_33",
        "shopping/level_3/case_18",
        "shopping/level_3/case_14",
    }


def test_public_cases_scoring_metadata_matches_runner_contract():
    data = json.loads(Path("task_configs/public_cases.json").read_text())

    assert data["scoring"]["method"] == "binary_case_count_average"
    assert data["scoring"]["weights"] == {"per_case": 1.0}
    assert "Reference only" in data["scoring"]["baseline_anchors_note"]
    assert "benchmark-level average scores" in data["scoring"]["baseline_anchors_note"]
    assert "contextualize baseline difficulty" in data["scoring"]["baseline_anchors_note"]
    assert set(data["scoring"]["baseline_anchors"]) == {"mcpmark", "tau2_airline", "deepplanning"}
    assert data["selection_source"]["selection_manifest"] == "short_output_iid_manifest.json"


def test_public_cases_limits_match_course_defaults():
    data = json.loads(Path("task_configs/public_cases.json").read_text())

    assert data["limits"]["model_input_tokens"] == 64000
    assert data["limits"]["model_output_tokens"] == 4096
    assert data["limits"]["case_timeout_sec"] == 300
    assert data["limits"]["llm_max_attempts"] == 2
    assert data["limits"]["benchmarks"]["mcpmark"]["max_agent_turns"] == 80
    assert data["limits"]["benchmarks"]["tau2_airline"]["max_environment_steps"] == 200
    assert data["limits"]["benchmarks"]["deepplanning"]["max_model_calls"] == 100
