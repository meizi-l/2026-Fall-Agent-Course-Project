"""Verify benchmark environment packages against course-owned exact versions."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
import sys


def main() -> int:
    pins = Path(sys.argv[1])
    errors = []
    count = 0
    for line in pins.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            errors.append(f"invalid exact pin: {line}")
            continue
        name, expected = line.split("==", 1)
        if not name or not expected:
            errors.append(f"invalid exact pin: {line}")
            continue
        count += 1
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"missing pinned package: {name}=={expected}")
            continue
        if actual != expected:
            errors.append(f"{name}=={actual}; expected {expected}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    print(f"Verified {count} exact Python package pins from {pins}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
