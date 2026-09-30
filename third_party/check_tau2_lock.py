"""Check installed tau2 package versions against the pinned upstream uv.lock."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
import re
import sys
import tomllib


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> int:
    lock = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    allowed: dict[str, set[str]] = {}
    for package in lock["package"]:
        allowed.setdefault(normalized(package["name"]), set()).add(str(package["version"]))
    allowed.setdefault("websockets", set()).add("17.1")
    errors = []
    checked = 0
    for distribution in importlib.metadata.distributions():
        name = normalized(distribution.metadata["Name"])
        versions = allowed.get(name)
        if versions is None:
            continue
        checked += 1
        if distribution.version not in versions:
            errors.append(f"{name}=={distribution.version}; lock allows {', '.join(sorted(versions))}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    print(f"Verified {checked} installed tau2 packages against {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
