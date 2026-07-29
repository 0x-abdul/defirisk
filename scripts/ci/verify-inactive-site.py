#!/usr/bin/env python3
"""Run filesystem smoke and exact API-hash checks on an inactive site build."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API_LANDING_ARTIFACT = "index.html"


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


def verify_deployed_api(committed_root: Path, deployed_root: Path) -> int:
    committed = hash_tree(committed_root)
    deployed = hash_tree(deployed_root)
    landing_hash = deployed.pop(API_LANDING_ARTIFACT, None)
    if landing_hash is None:
        raise ValueError("inactive release lacks deterministic API landing artifact")
    if committed != deployed:
        raise ValueError("inactive release API data differs from committed data/api")
    return len(committed)


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
    try:
        api_file_count = verify_deployed_api(ROOT / "data/api", dist / "api")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "OK: inactive route smoke passed, "
        f"{api_file_count} API data files match Git, and the deterministic "
        "API landing artifact is present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
