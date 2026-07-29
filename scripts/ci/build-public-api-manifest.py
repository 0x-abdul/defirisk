#!/usr/bin/env python3
"""Write or verify the deterministic manifest for every committed API file."""

from __future__ import annotations

import argparse
from pathlib import Path

from public_boundary import MANIFEST_RELATIVE, file_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / MANIFEST_RELATIVE
    generated = file_manifest(root)
    if args.check:
        if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != generated:
            raise SystemExit("committed data/api manifest is stale")
        print("OK: committed data/api manifest matches every API file")
        return
    manifest_path.write_text(generated, encoding="utf-8")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
