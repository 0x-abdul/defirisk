#!/usr/bin/env python3
"""Assert synthetic family API compatibility and generated dashboard routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_file(path: Path) -> None:
    if not path.is_file():
        raise AssertionError(f"missing generated file: {path}")


def score_signature(rows: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [(row.get("factor_id"), row.get("score")) for row in rows]


def history_signature(rows: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [(row.get("letter"), row.get("graded_at")) for row in rows]


def assert_build(api_root: Path, dist_root: Path | None) -> None:
    canonical_path = api_root / "protocols" / "fixture-family.json"
    alias_path = api_root / "protocols" / "fixture-v2.json"
    alias_history_path = api_root / "protocols" / "fixture-v2" / "history.json"
    for path in (canonical_path, alias_path, alias_history_path):
        require_file(path)

    canonical = read_json(canonical_path)["data"]["protocol_data"]
    alias = read_json(alias_path)["data"]["protocol_data"]
    surfaces = {surface["surface_slug"]: surface for surface in canonical["surfaces"]}

    assert canonical["protocol"]["slug"] == "fixture-family"
    assert set(surfaces) == {"core", "v2"}
    assert all(
        dep["surface_id"] == surfaces["core"]["surface_id"]
        for dep in canonical["deployments"]
    )
    assert score_signature(canonical["factor_scores"]) == score_signature(
        surfaces["core"]["factor_scores"]
    )
    assert history_signature(canonical["grade_history"]) == history_signature(
        surfaces["core"]["grade_history"]
    )

    assert alias["protocol"]["canonical_family_slug"] == "fixture-family"
    assert alias["protocol"]["selected_surface_slug"] == "v2"
    assert all(
        dep["surface_id"] == surfaces["v2"]["surface_id"]
        for dep in alias["deployments"]
    )
    assert score_signature(alias["factor_scores"]) == score_signature(
        surfaces["v2"]["factor_scores"]
    )
    assert history_signature(alias["grade_history"]) == history_signature(
        surfaces["v2"]["grade_history"]
    )

    if dist_root is None:
        return

    family_page = dist_root / "protocols" / "fixture-family" / "index.html"
    alias_page = dist_root / "protocols" / "fixture-v2" / "index.html"
    surface_factor_page = (
        dist_root
        / "protocols"
        / "fixture-family"
        / "surfaces"
        / "core"
        / "factors"
        / "RD-F-001"
        / "index.html"
    )
    alias_factor_page = (
        dist_root / "protocols" / "fixture-v2" / "factors" / "RD-F-001" / "index.html"
    )
    copied_alias = dist_root / "api" / "v1.7.0" / "protocols" / "fixture-v2.json"
    copied_history = (
        dist_root / "api" / "v1.7.0" / "protocols" / "fixture-v2" / "history.json"
    )
    for path in (
        family_page,
        alias_page,
        surface_factor_page,
        alias_factor_page,
        copied_alias,
        copied_history,
    ):
        require_file(path)

    family_html = family_page.read_text(encoding="utf-8")
    alias_html = alias_page.read_text(encoding="utf-8")
    alias_factor_html = alias_factor_page.read_text(encoding="utf-8")
    assert "Core markets" in family_html and "Version 2" in family_html
    assert "/protocols/fixture-family/?surface=v2" in alias_html
    assert (
        "/protocols/fixture-family/surfaces/v2/factors/RD-F-001/"
        in alias_factor_html
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--dist-root", type=Path)
    args = parser.parse_args()
    dist_root = args.dist_root.resolve() if args.dist_root else None
    assert_build(args.api_root.resolve(), dist_root)
    print("family build assertions passed")


if __name__ == "__main__":
    main()
