#!/usr/bin/env python3
"""Validate a public worktree or extracted Git tree before publication."""

from __future__ import annotations

import argparse
from pathlib import Path

from public_boundary import validate_tree


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--skip-manifest", action="store_true")
    args = parser.parse_args()

    failures = validate_tree(args.root, check_manifest=not args.skip_manifest)
    if failures:
        print("Public boundary validation failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("OK: public repository boundary and committed API manifest are valid")


if __name__ == "__main__":
    main()
