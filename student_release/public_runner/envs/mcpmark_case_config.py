from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


MCPMARK_ALLOWED_SERVICES = {"filesystem", "postgres"}


@dataclass(frozen=True)
class MCPMarkCase:
    service: str
    task_suite: str
    task_filter: str
    official_task_path: str


def resolve_mcpmark_case(case_id: str, case_config: dict[str, Any] | None = None) -> MCPMarkCase:
    official_task_path = mcpmark_official_task_path(case_id, case_config)
    parts = official_task_path.split("/")
    if len(parts) < 4:
        raise ValueError(
            "MCPMark official_task_path must be service/suite/category/task_id, "
            f"got: {official_task_path!r}"
        )
    service = parts[0]
    if service not in MCPMARK_ALLOWED_SERVICES:
        raise ValueError(
            f"Unsupported MCPMark service {service!r}. "
            "The course release only enables filesystem and postgres."
        )
    return MCPMarkCase(
        service=service,
        task_suite=parts[1],
        task_filter="/".join(parts[2:]),
        official_task_path=official_task_path,
    )


def mcpmark_case_service(case: dict[str, Any]) -> str:
    return resolve_mcpmark_case(str(case.get("case_id", "")), case).service


def mcpmark_official_task_path(case_id: str, case_config: dict[str, Any] | None = None) -> str:
    case_config = case_config or {}
    for key in ("official_task_path", "mcpmark_task_path", "task_path"):
        value = case_config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().strip("/")
    raise ValueError(
        "MCPMark case config must provide official_task_path. "
        f"case_id is only a runner identifier and cannot select an official MCPMark task: {case_id!r}"
    )


def validate_mcpmark_task_files(repo_root: Path, case: dict[str, Any]) -> None:
    selected = resolve_mcpmark_case(str(case.get("case_id", "")), case)
    parts = selected.official_task_path.split("/")
    if len(parts) != 4 or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid MCPMark official_task_path: {selected.official_task_path!r}")
    task_dir = repo_root / "tasks" / Path(*parts)
    for filename in ("description.md", "meta.json", "verify.py"):
        path = task_dir / filename
        if not path.is_file():
            raise ValueError(f"missing selected MCPMark task file: {path}")
    metadata = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("category_id") != parts[2] or metadata.get("task_id") != parts[3]:
        raise ValueError(f"invalid selected MCPMark task metadata: {task_dir / 'meta.json'}")
    if not isinstance(metadata.get("mcp"), list) or parts[0] not in metadata["mcp"]:
        raise ValueError(f"selected MCPMark task does not enable {parts[0]}: {task_dir / 'meta.json'}")
