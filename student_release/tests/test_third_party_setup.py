import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_tau2_setup_script_reports_default_install_path():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_tau2_bench.sh"

    result = subprocess.run(
        ["bash", str(script), "--print-path"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == str(course_root / "third_party" / "tau2-bench")


def test_tau2_setup_script_installs_core_import_compat_packages():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_tau2_bench.sh"
    script_text = script.read_text()

    assert "b7ea9074c1cba482b30687fecdb5c8425fd6f619" in script_text
    assert 'tau2_python_version=${TAU2_PYTHON_VERSION:-"3.12"}' in script_text
    assert "TAU2_PYTHON" in script_text
    assert 'extra_pip_packages="websockets==17.1"' in script_text
    assert "uv sync --locked" in script_text
    assert "uv pip install $extra_pip_packages" in script_text


def test_deepplanning_setup_script_reports_default_install_path():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_deepplanning.sh"

    result = subprocess.run(
        ["bash", str(script), "--print-path"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == str(course_root / "third_party" / "qwen-agent")


def test_deepplanning_setup_script_pins_repo_and_uses_course_python():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_deepplanning.sh"
    script_text = script.read_text()

    assert "31a4d36d123688581a9e9744427272b33ce940e0" in script_text
    assert "Qwen/DeepPlanning" in script_text
    assert "213876c" in script_text
    assert "632a3b5d0db1fa0717474b9361b2d7102aeb7e1f00c32cb842f012ff7adf8000" in script_text
    assert "58b65bff1f5e9eefb580b02202ef1394a87f8d82466a7aff5e1329a812e16d55" in script_text
    assert "eff61a838f55fad677499adc77405b480d08de87b97b409737b67e0abce610e7" in script_text
    assert "DEEPPLANNING_DOWNLOAD_DATA" in script_text
    assert "course_python_version_file" in script_text
    assert ".venv-deepplanning" in script_text
    assert "benchmark/deepplanning/requirements.txt" in script_text
    assert "database_level1.tar.gz" in script_text
    assert "--check-only" in script_text


def test_deepplanning_check_only_rejects_unpinned_git_checkout(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_deepplanning.sh"
    fake_repo = tmp_path / "qwen-agent"
    fake_repo.mkdir()
    (fake_repo / "README.md").write_text("fake qwen-agent\n")
    subprocess.run(["git", "init"], cwd=fake_repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=fake_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fake qwen-agent"],
        cwd=fake_repo,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )

    result = subprocess.run(
        ["bash", str(script), "--check-only"],
        cwd=course_root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "DEEPPLANNING_REPO": str(fake_repo),
            "DEEPPLANNING_REF": "0000000000000000000000000000000000000000",
        },
    )

    assert result.returncode == 2
    assert "DeepPlanning checkout is at" in result.stderr
    assert "0000000000000000000000000000000000000000" in result.stderr


def test_mcpmark_setup_script_reports_default_install_path():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_mcpmark.sh"

    result = subprocess.run(
        ["bash", str(script), "--print-path"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == str(course_root / "third_party" / "mcpmark")


def test_mcpmark_setup_script_pins_repo_and_uses_course_python():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_mcpmark.sh"
    script_text = script.read_text()

    assert "cd45b7f57923b9b3985467f5139927575f83141c" in script_text
    assert "https://github.com/eval-sys/mcpmark.git" in script_text
    assert 'mcpmark_python_version=${MCPMARK_PYTHON_VERSION:-"3.12"}' in script_text
    assert "MCPMARK_PYTHON" in script_text
    assert ".venv-mcpmark" in script_text
    assert 'pip install -r "$pins" -e .' in script_text
    assert "MCPMARK_INSTALL_PLAYWRIGHT_BROWSERS" in script_text
    assert "MCPMARK_NODE_MAJOR" in script_text
    assert "MCPMARK_POSTGRES_DOCKER_IMAGE" in script_text
    assert "pgvector/pgvector:0.8.0-pg17-bookworm" in script_text
    assert "third_party/.local/node20/bin" in script_text
    assert "createdb" in script_text
    assert "tasks/filesystem" in script_text
    assert "--check-only" in script_text
    assert "--check-filesystem-runtime" in script_text
    assert "--check-postgres-runtime" in script_text


def test_mcpmark_runtime_check_script_wraps_all_course_checks():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "check_mcpmark_runtimes.sh"
    script_text = script.read_text()

    assert "setup_mcpmark.sh\" --check-only" in script_text
    assert "setup_mcpmark.sh\" --check-filesystem-runtime" in script_text
    assert "setup_mcpmark.sh\" --check-postgres-runtime" in script_text
    assert "core|filesystem|postgres|all" in script_text


def test_mcpmark_system_dependency_helper_documents_install_paths():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"
    script_text = script.read_text()

    assert "brew install postgresql@17" in script_text
    assert "brew install node@20" in script_text
    assert "Optional system Node fallback" in script_text
    assert "NodeSource" in script_text
    assert "apt.postgresql.org" in script_text
    assert "--dry-run" in script_text
    assert "--install" in script_text
    assert "check_mcpmark_runtimes.sh" in script_text
    assert "Docker Desktop" in script_text
    assert "postgres-docker" in script_text
    assert "MCPMARK_CONTAINER_RUNTIME" in script_text
    assert "\"$runtime\" pull \"$postgres_image\"" in script_text
    assert "Homebrew install failed" in script_text
    assert "Homebrew permissions" in script_text
    assert "chown" not in script_text
    assert "chmod" not in script_text


def test_mcpmark_system_dependency_helper_avoids_sudo_for_ubuntu():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"

    dry_run = subprocess.run(
        ["bash", str(script), "--ubuntu", "--dry-run"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "sudo" not in dry_run.stdout
    assert "Run these commands as root" in dry_run.stdout

    install = subprocess.run(
        ["bash", str(script), "--ubuntu", "--install"],
        cwd=course_root,
        text=True,
        capture_output=True,
    )

    assert install.returncode == 2
    assert "does not run privileged Ubuntu package-manager commands" in install.stderr


def test_mcpmark_system_dependency_helper_supports_local_node_install():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"

    dry_run = subprocess.run(
        ["bash", str(script), "--local-node", "--dry-run"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "NODE_VERSION=v20.18.3" in dry_run.stdout
    assert "third_party/.local/node20" in dry_run.stdout
    assert "node-v20.18.3" in dry_run.stdout
    assert "sudo" not in dry_run.stdout


def test_mcpmark_local_node_dry_run_maps_supported_os_arch_pairs(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        (
            "#!/usr/bin/env bash\n"
            "if [[ \"${1:-}\" == \"-s\" ]]; then echo \"$MCPMARK_TEST_UNAME_S\"; "
            "else echo \"$MCPMARK_TEST_UNAME_M\"; fi\n"
        ),
    )

    cases = [
        ("Darwin", "arm64", "darwin-arm64"),
        ("Darwin", "x86_64", "darwin-x64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Linux", "x86_64", "linux-x64"),
    ]
    for os_name, arch, expected_platform in cases:
        dry_run = subprocess.run(
            ["bash", str(script), "--local-node", "--dry-run"],
            cwd=course_root,
            check=True,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "MCPMARK_TEST_UNAME_S": os_name,
                "MCPMARK_TEST_UNAME_M": arch,
            },
        )

        assert f"node-v20.18.3-{expected_platform}.tar.xz" in dry_run.stdout


def test_mcpmark_system_dependency_auto_detects_ubuntu_linux(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/usr/bin/env bash\nif [[ \"${1:-}\" == \"-s\" ]]; then echo Linux; else echo x86_64; fi\n",
    )
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nID=ubuntu\n')

    dry_run = subprocess.run(
        ["bash", str(script), "--auto", "--dry-run"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MCPMARK_OS_RELEASE_FILE": str(os_release),
        },
    )

    assert "Ubuntu system dependencies" in dry_run.stdout
    assert "apt-get install -y postgresql-client-17" in dry_run.stdout


def test_mcpmark_system_dependency_auto_rejects_non_ubuntu_linux(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/usr/bin/env bash\nif [[ \"${1:-}\" == \"-s\" ]]; then echo Linux; else echo x86_64; fi\n",
    )
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Fedora Linux"\nID=fedora\n')

    dry_run = subprocess.run(
        ["bash", str(script), "--auto", "--dry-run"],
        cwd=course_root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MCPMARK_OS_RELEASE_FILE": str(os_release),
        },
    )

    assert dry_run.returncode == 2
    assert "Unsupported Linux distribution" in dry_run.stderr
    assert "--local-node --install" in dry_run.stderr
    assert "--postgres-docker --install" in dry_run.stderr
    assert "psql, createdb, and pg_restore" in dry_run.stderr
    assert "check_mcpmark_runtimes.sh all" in dry_run.stderr


def test_mcpmark_system_dependency_auto_recognizes_almalinux_without_apt(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/usr/bin/env bash\nif [[ \"${1:-}\" == \"-s\" ]]; then echo Linux; else echo x86_64; fi\n",
    )
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="AlmaLinux"\nID=almalinux\nID_LIKE="rhel centos fedora"\n')

    dry_run = subprocess.run(
        ["bash", str(script), "--auto", "--dry-run"],
        cwd=course_root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MCPMARK_OS_RELEASE_FILE": str(os_release),
        },
    )

    assert dry_run.returncode == 2
    assert "AlmaLinux/course-server environment" in dry_run.stderr
    assert "does not run dnf" in dry_run.stderr
    assert "apt-get" not in dry_run.stdout
    assert "--local-node --install" in dry_run.stderr
    assert "--postgres-docker --install" in dry_run.stderr


def test_mcpmark_system_dependency_helper_prints_postgres_docker_commands():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"

    dry_run = subprocess.run(
        ["bash", str(script), "--postgres-docker", "--dry-run"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "docker pull pgvector/pgvector:0.8.0-pg17-bookworm" in dry_run.stdout
    assert "docker run -d" in dry_run.stdout
    assert "--name mcpmark-postgres" in dry_run.stdout
    assert "POSTGRES_PASSWORD=password" in dry_run.stdout
    assert "sudo" not in dry_run.stdout


def test_mcpmark_system_dependency_helper_prints_podman_commands_when_podman_is_available(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "install_mcpmark_system_deps.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "podman", "#!/usr/bin/env bash\nexit 0\n")

    dry_run = subprocess.run(
        ["bash", str(script), "--postgres-docker", "--dry-run"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MCPMARK_CONTAINER_RUNTIME": "podman",
        },
    )

    assert "CONTAINER_RUNTIME=podman" in dry_run.stdout
    assert "podman pull pgvector/pgvector:0.8.0-pg17-bookworm" in dry_run.stdout
    assert "podman run -d" in dry_run.stdout
    assert "Docker or Podman" in dry_run.stdout


def test_mcpmark_postgres_runtime_rejects_wrong_client_major_version(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_mcpmark.sh"
    fake_repo = tmp_path / "mcpmark"
    fake_postgres_mcp = fake_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    fake_postgres_mcp.parent.mkdir(parents=True)
    _write_executable(fake_postgres_mcp, "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_postgres_mcp.parent / "python",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "docker", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "psql", "#!/usr/bin/env bash\necho 'psql (PostgreSQL) 17.2'\n")
    _write_executable(bin_dir / "createdb", "#!/usr/bin/env bash\necho 'createdb (PostgreSQL) 17.2'\n")
    _write_executable(bin_dir / "pg_restore", "#!/usr/bin/env bash\necho 'pg_restore (PostgreSQL) 17.2'\n")

    result = subprocess.run(
        ["bash", str(script), "--check-postgres-runtime"],
        cwd=course_root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "MCPMARK_REPO": str(fake_repo),
            "MCPMARK_POSTGRES_CLIENT_MAJOR": "99",
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 2
    assert "expected PostgreSQL client major 99" in result.stderr


def test_mcpmark_postgres_runtime_accepts_podman_container_runtime(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_mcpmark.sh"
    fake_repo = tmp_path / "mcpmark"
    fake_postgres_mcp = fake_repo / ".venv-mcpmark-postgres-mcp" / "bin" / "postgres-mcp"
    fake_postgres_mcp.parent.mkdir(parents=True)
    _write_executable(fake_postgres_mcp, "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_postgres_mcp.parent / "python",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "podman", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "psql", "#!/usr/bin/env bash\necho 'psql (PostgreSQL) 17.5'\n")
    _write_executable(bin_dir / "createdb", "#!/usr/bin/env bash\necho 'createdb (PostgreSQL) 17.5'\n")
    _write_executable(bin_dir / "pg_restore", "#!/usr/bin/env bash\necho 'pg_restore (PostgreSQL) 17.5'\n")

    result = subprocess.run(
        ["bash", str(script), "--check-postgres-runtime"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "MCPMARK_REPO": str(fake_repo),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MCPMARK_CONTAINER_RUNTIME": "podman",
        },
    )

    assert "CONTAINER_RUNTIME=podman" in result.stdout
    assert "POSTGRES_MCP_COMMAND=" in result.stdout
    assert "POSTGRES_IMAGE=pgvector/pgvector:0.8.0-pg17-bookworm" in result.stdout


def test_third_party_readme_lists_version_consistency_contracts():
    course_root = Path(__file__).resolve().parents[2]
    readme = (course_root / "third_party" / "README.md").read_text()

    assert "tau2-bench" in readme
    assert "Python 3.12" in readme
    assert "b7ea9074c1cba482b30687fecdb5c8425fd6f619" in readme
    assert "DeepPlanning" in readme
    assert "MCPMark Python env" in readme
    assert "Python 3.12" in readme
    assert "31a4d36d123688581a9e9744427272b33ce940e0" in readme
    assert "PostgreSQL client tools" in readme
    assert "major version 17" in readme
    assert "Docker or Podman" in readme
    assert "Docker or Podman" in readme
    assert "AlmaLinux 9.8" in readme
    assert "RHEL/CentOS/Fedora compatible" in readme
    assert "Docker/Podman itself is not pinned" in readme
    assert "pgvector/pgvector:0.8.0-pg17-bookworm" in readme
    assert "Ubuntu Linux (x86-64 and ARM64)" in readme
    assert "Other Linux distributions may work" in readme
    assert "not silently treated as Ubuntu" in readme
    assert "curl" in readme
    assert ".tar.xz" in readme


def test_third_party_readme_explains_mcpmark_scripts_and_recommended_flow():
    course_root = Path(__file__).resolve().parents[2]
    readme = (course_root / "third_party" / "README.md").read_text()

    assert "MCPMark scripts" in readme
    assert "setup_mcpmark.sh" in readme
    assert "install_mcpmark_system_deps.sh" in readme
    assert "check_mcpmark_runtimes.sh" in readme
    assert "Install pinned project-local Node.js" in readme
    assert "bash third_party/install_mcpmark_system_deps.sh --local-node --install" in readme
    assert "bash third_party/install_mcpmark_system_deps.sh --postgres-docker --install" in readme
    assert "bash third_party/check_mcpmark_runtimes.sh all" in readme
    assert "Host utilities" in readme
    assert "Minimal troubleshooting" in readme
    assert "Running Public Official Cases" not in readme


def test_mcpmark_check_only_rejects_missing_course_subset_task(tmp_path):
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_mcpmark.sh"
    fake_repo = _create_fake_mcpmark_repo(tmp_path, include_postgres_task=False)
    expected_ref = subprocess.run(
        ["git", "-C", str(fake_repo), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    result = subprocess.run(
        ["bash", str(script), "--check-only"],
        cwd=course_root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "MCPMARK_REPO": str(fake_repo),
            "MCPMARK_REF": expected_ref,
            "MCPMARK_PYTHON_VERSION": f"{sys.version_info.major}.{sys.version_info.minor}",
            "MCPMARK_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 2
    assert "missing course MCPMark task file" in result.stderr
    assert "postgres/easy/employees/hiring_year_summary" in result.stderr


def test_mcpmark_filesystem_runtime_reports_pinned_server_package():
    course_root = Path(__file__).resolve().parents[2]
    script = course_root / "third_party" / "setup_mcpmark.sh"
    repo = Path(os.environ.get("MCPMARK_REPO", course_root / "third_party/mcpmark"))
    server_root = Path(os.environ.get("MCPMARK_FILESYSTEM_SERVER_ROOT", course_root / "third_party/.local/mcp-filesystem-server"))
    server = server_root / "node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
    if not (repo / ".venv-mcpmark/bin/python").is_file() or not server.is_file():
        pytest.skip("requires the optional installed MCPMark filesystem runtime")

    result = subprocess.run(
        ["bash", str(script), "--check-filesystem-runtime"],
        cwd=course_root,
        check=True,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    assert "FILESYSTEM_SERVER_PACKAGE=@modelcontextprotocol/server-filesystem@2025.12.18" in result.stdout


def _create_fake_mcpmark_repo(tmp_path: Path, *, include_postgres_task: bool = True) -> Path:
    repo = tmp_path / "mcpmark"
    (repo / "src" / "agents").mkdir(parents=True)
    (repo / ".venv-mcpmark" / "bin").mkdir(parents=True)
    (repo / "pipeline.py").write_text("# fake pipeline\n")
    (repo / "pyproject.toml").write_text("[project]\nname = 'fake-mcpmark'\n")
    (repo / "src" / "__init__.py").write_text("")
    (repo / "src" / "agents" / "__init__.py").write_text("")
    python_path = repo / ".venv-mcpmark" / "bin" / "python"
    python_path.symlink_to(Path(sys.executable))
    _write_task(
        repo / "tasks" / "filesystem" / "standard" / "desktop" / "timeline_extraction",
        service="filesystem",
        category_id="desktop",
        task_id="timeline_extraction",
    )
    if include_postgres_task:
        _write_task(
            repo / "tasks" / "postgres" / "easy" / "employees" / "hiring_year_summary",
            service="postgres",
            category_id="employees",
            task_id="hiring_year_summary",
        )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fake mcpmark"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    return repo


def _write_task(path: Path, *, service: str, category_id: str, task_id: str) -> None:
    path.mkdir(parents=True)
    (path / "description.md").write_text(f"Fake {service} task\n")
    (path / "verify.py").write_text("raise SystemExit(0)\n")
    (path / "meta.json").write_text(
        (
            "{\n"
            f"  \"task_id\": \"{task_id}\",\n"
            f"  \"category_id\": \"{category_id}\",\n"
            f"  \"mcp\": [\"{service}\"]\n"
            "}\n"
        )
    )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)
