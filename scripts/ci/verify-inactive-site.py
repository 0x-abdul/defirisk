#!/usr/bin/env python3
"""Run filesystem smoke and exact API-hash checks on an inactive site build."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate_boundary import BoundaryError, hash_public_tree, load_json, validate_output_tree


ROOT = Path(__file__).resolve().parents[2]
API_LANDING_ARTIFACT = "index.html"


def hash_tree(root: Path) -> dict[str, str]:
    return hash_public_tree(root)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--api-root", type=Path, help="Complete validated candidate API tree")
    parser.add_argument("--curator-root", type=Path, help="Trusted frozen base for logical data/curator source inputs")
    parser.add_argument("--build-receipt", "--expected-output-manifest", dest="build_receipt", type=Path, help="Frozen external private build receipt (required)")
    args = parser.parse_args()
    root = args.root
    dist = args.dist or root / "site/dist"
    api_root = args.api_root or root / "data/api"
    failures = validate_output_tree(root, dist, api_root=api_root, build_receipt=args.build_receipt, require_build_receipt=True, curator_root=args.curator_root)
    if failures:
        print("Inactive output boundary validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    required = (
        dist / "index.html",
        dist / "about/index.html",
        dist / "methodology/index.html",
        dist / "data/index.html",
        dist / "changes/index.html",
        dist / "404.html",
    )
    missing = [
        f"site/dist/{path.relative_to(dist).as_posix()}" for path in required if not path.is_file()
    ]
    if missing:
        raise SystemExit(f"inactive release lacks required routes: {missing}")
    try:
        baseline = load_json(api_root / "publication-baseline.json")
        index = load_json(api_root / baseline["current_api_version"] / "index.json")
    except (BoundaryError, KeyError):
        raise SystemExit("invalid committed public API publication binding") from None
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
            missing_protocol_routes.append(f"site/dist/{route.relative_to(dist).as_posix()}")
    if missing_protocol_routes:
        raise SystemExit(
            "inactive release lacks protocol routes: "
            f"{missing_protocol_routes}"
        )
    try:
        api_file_count = verify_deployed_api(api_root, dist / "api")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "OK: inactive route smoke passed, "
        f"{api_file_count} API data files match the validated input, and every "
        "emitted text artifact passed the public boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
