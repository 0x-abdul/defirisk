#!/usr/bin/env python3
"""Fail unless two complete build trees are byte-identical."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def hash_tree(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"build tree is not a safe directory: {root}")
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is not permitted in build output: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    if not result:
        raise ValueError(f"build tree is empty: {root}")
    return result


def compare(first: Path, second: Path) -> dict[str, object]:
    first_hashes = hash_tree(first)
    second_hashes = hash_tree(second)
    first_paths = set(first_hashes)
    second_paths = set(second_hashes)
    changed = sorted(
        path
        for path in first_paths & second_paths
        if first_hashes[path] != second_hashes[path]
    )
    return {
        "ok": first_hashes == second_hashes,
        "file_count": len(first_hashes),
        "missing_from_first": sorted(second_paths - first_paths),
        "missing_from_second": sorted(first_paths - second_paths),
        "changed": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.first.resolve(), args.second.resolve())
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
