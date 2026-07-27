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
    header_path = api_root / "protocols" / "fixture-header-family.json"
    alias_path = api_root / "protocols" / "fixture-v2.json"
    alias_history_path = api_root / "protocols" / "fixture-v2" / "history.json"
    for path in (canonical_path, header_path, alias_path, alias_history_path):
        require_file(path)

    canonical = read_json(canonical_path)["data"]["protocol_data"]
    header = read_json(header_path)["data"]["protocol_data"]
    alias = read_json(alias_path)["data"]["protocol_data"]
    surfaces = {surface["surface_slug"]: surface for surface in canonical["surfaces"]}

    assert canonical["protocol"]["slug"] == "fixture-family"
    assert set(surfaces) == {"core", "v2"}
    assert canonical["surfaces"][0]["surface_slug"] == "core"
    assert surfaces["core"]["is_primary"] is True
    assert surfaces["v2"]["is_primary"] is False
    assert surfaces["v2"]["tvs_usd"] > surfaces["core"]["tvs_usd"]
    assert surfaces["v2"]["headline_grade"] is None
    assert surfaces["v2"]["risk_score"] is None
    assert surfaces["v2"]["cap_applied"] == "none"
    assert surfaces["core"]["headline_grade"] == "D"
    assert surfaces["core"]["cap_applied"] == "D"
    assert canonical["protocol"]["headline_grade"] == "A"
    secondary_overrides = surfaces["v2"]["deployment_overrides"]
    assert len(secondary_overrides) == 1
    partial_override = next(iter(secondary_overrides.values()))
    assert 0 < len(partial_override) < len(surfaces["v2"]["factor_scores"])
    assert partial_override[0]["evidence_summary"] == (
        "Synthetic partial deployment-scoped override."
    )
    effective_scores = next(
        iter(surfaces["v2"]["deployment_factor_scores"].values())
    )
    assert len(effective_scores) == len(surfaces["v2"]["factor_scores"])
    effective_severities = next(
        iter(surfaces["v2"]["deployment_category_severities"].values())
    )
    assert effective_severities["1"] == 88
    assert "13" not in effective_severities
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

    header_surfaces = {surface["surface_slug"]: surface for surface in header["surfaces"]}
    assert set(header_surfaces) == {"legacy", "secure"}
    assert header_surfaces["secure"]["tvs_usd"] > header_surfaces["legacy"]["tvs_usd"]
    assert header_surfaces["secure"]["headline_grade"] == "C"
    assert header_surfaces["secure"]["risk_score"] == 42.7
    assert header_surfaces["secure"]["cap_applied"] == "D"
    assert header_surfaces["secure"]["graded_at"] == "2026-06-15T00:00:00Z"
    assert header["protocol"]["headline_grade"] == "A"
    header_overrides = header_surfaces["secure"]["deployment_overrides"]
    assert len(header_overrides) == 1
    assert len(next(iter(header_overrides.values()))) < len(header_surfaces["secure"]["factor_scores"])
    assert len(next(iter(header_surfaces["secure"]["deployment_factor_scores"].values()))) == len(
        header_surfaces["secure"]["factor_scores"]
    )

    if dist_root is None:
        return

    family_page = dist_root / "protocols" / "fixture-family" / "index.html"
    header_page = dist_root / "protocols" / "fixture-header-family" / "index.html"
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
        header_page,
        alias_page,
        surface_factor_page,
        alias_factor_page,
        copied_alias,
        copied_history,
    ):
        require_file(path)

    family_html = family_page.read_text(encoding="utf-8")
    header_html = header_page.read_text(encoding="utf-8")
    alias_html = alias_page.read_text(encoding="utf-8")
    alias_factor_html = alias_factor_page.read_text(encoding="utf-8")
    assert "Core markets" in family_html and "Version 2" in family_html
    assert "Surface grade · Version 2" in family_html
    assert "Risk profile at a glance" in family_html
    assert "Categories &amp; evidence" in family_html
    assert family_html.count('href="#cat-') == 13
    assert "Family overview" not in family_html
    assert "Secure markets" in header_html
    assert "42.7" in header_html
    assert "Grade capped to D" in header_html
    assert "2026-06-15" in header_html
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
