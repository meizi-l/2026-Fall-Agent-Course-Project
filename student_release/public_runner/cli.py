from __future__ import annotations

from public_runner.run_public_tasks import main as run_public_tasks_main


def main(argv: list[str] | None = None) -> int:
    """Run public tasks with the same arguments as run_public_tasks.py."""
    return run_public_tasks_main(argv)
