#!/usr/bin/env python3
"""Prove that a family-aware dump preserves the legacy JSON contract.

The pre-migration dump is treated as a recursive subset of the post-migration
dump: existing files, keys, list order, and values must remain intact, while
new family/surface fields may be added. Envelope generation time is expected
to change between runs and is the sole ignored legacy value.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _assert_subset(before: Any, after: Any, path: str, errors: list[str]) -> None:
    if isinstance(before, dict):
        if not isinstance(after, dict):
            errors.append(f"{path}: expected object, found {type(after).__name__}")
            return
        for key, before_value in before.items():
            child_path = f"{path}.{key}"
            if key == "generated_at":
                continue
            if key not in after:
                errors.append(f"{child_path}: legacy key is missing")
                continue
            _assert_subset(before_value, after[key], child_path, errors)
        return

    if isinstance(before, list):
        if not isinstance(after, list):
            errors.append(f"{path}: expected array, found {type(after).__name__}")
            return
        if len(before) != len(after):
            errors.append(f"{path}: array length changed from {len(before)} to {len(after)}")
            return
        for index, (before_value, after_value) in enumerate(zip(before, after, strict=True)):
            _assert_subset(before_value, after_value, f"{path}[{index}]", errors)
        return

    if before != after:
        errors.append(f"{path}: value changed from {before!r} to {after!r}")


def compare(before_root: Path, after_root: Path) -> list[str]:
    errors: list[str] = []
    before_files = {
        path.relative_to(before_root)
        for path in before_root.rglob("*.json")
    }
    after_files = {
        path.relative_to(after_root)
        for path in after_root.rglob("*.json")
    }

    for missing in sorted(before_files - after_files):
        errors.append(f"{missing.as_posix()}: legacy file is missing")

    for relative_path in sorted(before_files & after_files):
        before = json.loads((before_root / relative_path).read_text(encoding="utf-8"))
        after = json.loads((after_root / relative_path).read_text(encoding="utf-8"))
        _assert_subset(before, after, relative_path.as_posix(), errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare legacy and family-aware single-surface API dumps"
    )
    parser.add_argument("before", type=Path, help="Pre-migration api/v1.7.0 directory")
    parser.add_argument("after", type=Path, help="Post-migration api/v1.7.0 directory")
    args = parser.parse_args()

    errors = compare(args.before.resolve(), args.after.resolve())
    if errors:
        print(f"FAIL: {len(errors)} legacy compatibility difference(s)")
        for error in errors[:100]:
            print(f"  {error}")
        if len(errors) > 100:
            print(f"  ... {len(errors) - 100} additional difference(s)")
        return 1

    file_count = sum(1 for _ in args.before.rglob("*.json"))
    print(f"PASS: {file_count} legacy JSON files are preserved as recursive subsets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
