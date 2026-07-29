#!/usr/bin/env python3
"""Run filesystem smoke and exact API-hash checks on an inactive site build."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def hash_tree(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"unsafe or missing tree: {root}")
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is forbidden: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def main() -> int:
    dist = ROOT / "site/dist"
    required = (
        dist / "index.html",
        dist / "about/index.html",
        dist / "methodology/index.html",
        dist / "data/index.html",
        dist / "changes/index.html",
        dist / "404.html",
    )
    missing = [
        str(path.relative_to(ROOT)) for path in required if not path.is_file()
    ]
    if missing:
        raise SystemExit(f"inactive release lacks required routes: {missing}")
    index = json.loads(
        (ROOT / "data/api/v1.7.0/index.json").read_text(encoding="utf-8")
    )
    protocols = index.get("data", {}).get("protocols")
    if not isinstance(protocols, list):
        raise SystemExit("committed protocol index is invalid")
    missing_protocol_routes: list[str] = []
    for row in protocols:
        slug = row.get("slug") if isinstance(row, dict) else None
        if not isinstance(slug, str) or not slug:
            missing_protocol_routes.append("<invalid-slug>")
            continue
        route = dist / "protocols" / slug / "index.html"
        if not route.is_file():
            missing_protocol_routes.append(str(route.relative_to(ROOT)))
    if missing_protocol_routes:
        raise SystemExit(
            "inactive release lacks protocol routes: "
            f"{missing_protocol_routes}"
        )
    committed = hash_tree(ROOT / "data/api")
    deployed = hash_tree(dist / "api")
    if committed != deployed:
        raise SystemExit("inactive release API tree differs from committed data/api")
    print(
        f"OK: inactive route smoke passed and {len(committed)} API files match Git"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
