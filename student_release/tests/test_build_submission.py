import json
import zipfile
from pathlib import Path

import pytest

from build_submission import (
    DependencyPolicyError,
    ForbiddenFileError,
    SubmissionMetadataError,
    build_submission,
    collect_files,
    validate_dependency_policy,
    validate_submission_metadata,
)


def _minimal_tree(root: Path) -> None:
    (root / "src/course_agent").mkdir(parents=True)
    (root / "src/course_agent/student_agent.py").write_text("class StudentAgent: pass\n")
    (root / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    (root / "uv.lock").write_text(
        """
version = 1
revision = 3
requires-python = ">=3.11"

[[package]]
name = "x"
version = "0"
source = { editable = "." }

[[package]]
name = "pure-wheel"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [
  { url = "https://files.pythonhosted.org/packages/pure-wheel.whl", hash = "sha256:0", size = 1024 },
]
""".strip()
        + "\n"
    )
    (root / "submission.json").write_text(
        json.dumps({"student_id": " 20901234 ", "student_name": " Alice Chan ", "email": " alice@example.com "})
    )


def test_collect_files_excludes_env_case_insensitively(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / ".ENV").write_text("SECRET=1\n")

    assert Path(".ENV") not in collect_files(tmp_path)


def test_collect_files_excludes_local_env_shell_file(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "env.student.local.sh").write_text("export COURSE_API_KEY=SECRET\n")

    assert Path("env.student.local.sh") not in collect_files(tmp_path)


def test_collect_files_rejects_nested_archive(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "notes.Zip").write_text("not really a zip")

    with pytest.raises(ForbiddenFileError, match="notes.Zip"):
        collect_files(tmp_path)


def test_collect_files_excludes_trajectories(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "trajectories/run-1").mkdir(parents=True)
    (tmp_path / "trajectories/run-1/score_summary.json").write_text("{}")

    assert all("trajectories" not in path.parts for path in collect_files(tmp_path))


def test_collect_files_excludes_trajectory_smoke_outputs(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "trajectories_smoke/run-1").mkdir(parents=True)
    (tmp_path / "trajectories_smoke/run-1/score_summary.json").write_text("{}")

    assert all("trajectories_smoke" not in path.parts for path in collect_files(tmp_path))


def test_build_submission_writes_expected_files(tmp_path):
    _minimal_tree(tmp_path)
    output = tmp_path / "submission.zip"

    build_submission(tmp_path, output, preflight_log={"steps": []})

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        submission = json.loads(archive.read("submission.json"))
        build_log = json.loads(archive.read("submission_build_log.json"))
    assert "src/course_agent/student_agent.py" in names
    assert "pyproject.toml" in names
    assert "uv.lock" in names
    assert "submission.json" in names
    assert "submission_build_log.json" in names
    assert submission == {
        "student_id": "20901234",
        "student_name": "Alice Chan",
        "email": "alice@example.com",
    }
    assert build_log["steps"] == []


def test_build_submission_omits_internal_baseline_agent(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "src/course_agent/baseline_agent.py").write_text("class BaselineAgent: pass\n")
    output = tmp_path / "submission.zip"

    build_submission(tmp_path, output, preflight_log={"steps": []})

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "src/course_agent/student_agent.py" in names
    assert "src/course_agent/baseline_agent.py" not in names


def test_submission_metadata_requires_student_identity(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "submission.json").write_text(json.dumps({"student_id": "20901234", "email": "bad"}))

    with pytest.raises(SubmissionMetadataError, match="student_name"):
        validate_submission_metadata(tmp_path)


def test_submission_metadata_normalizes_strings(tmp_path):
    _minimal_tree(tmp_path)

    metadata = validate_submission_metadata(tmp_path)

    assert metadata == {
        "student_id": "20901234",
        "student_name": "Alice Chan",
        "email": "alice@example.com",
    }
    assert json.loads((tmp_path / "submission.json").read_text()) == metadata


def test_dependency_policy_rejects_git_sources(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "bad"
version = "1.0"
source = { git = "https://example.invalid/repo.git" }
""".strip()
        + "\n"
    )

    with pytest.raises(DependencyPolicyError, match="git/url/path"):
        validate_dependency_policy(tmp_path)


def test_dependency_policy_rejects_packages_without_wheels(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "sdist-only"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/sdist-only.tar.gz", hash = "sha256:0", size = 1024 }
""".strip()
        + "\n"
    )

    with pytest.raises(DependencyPolicyError, match="no wheel"):
        validate_dependency_policy(tmp_path)


def test_dependency_policy_rejects_large_artifacts(tmp_path):
    _minimal_tree(tmp_path)
    (tmp_path / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "large-wheel"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [
  { url = "https://files.pythonhosted.org/packages/large.whl", hash = "sha256:0", size = 52428801 },
]
""".strip()
        + "\n"
    )

    with pytest.raises(DependencyPolicyError, match="exceeds 50 MB"):
        validate_dependency_policy(tmp_path)
