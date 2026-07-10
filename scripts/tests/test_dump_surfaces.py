from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "dump.py"
SPEC = importlib.util.spec_from_file_location("dump_surfaces", SCRIPT_PATH)
dump = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = dump
SPEC.loader.exec_module(dump)


def test_surface_payloads_preserve_primary_compatibility_and_overlays() -> None:
    surfaces = [
        {
            "surface_id": "v2-id",
            "surface_slug": "v2",
            "display_name": "Fixture v2",
            "is_primary": True,
        },
        {
            "surface_id": "v3-id",
            "surface_slug": "v3",
            "display_name": "Fixture v3",
            "is_primary": False,
        },
    ]
    scores = [
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "scope_level": "family",
            "family_slug": "fixture-family",
            "surface_id": None,
            "deployment_id": None,
        },
        {
            "factor_id": "RD-F-001",
            "score": "yellow",
            "scope_level": "surface",
            "family_slug": None,
            "surface_id": "v3-id",
            "deployment_id": None,
        },
        {
            "factor_id": "RD-F-001",
            "score": "red",
            "scope_level": "deployment",
            "family_slug": None,
            "surface_id": "v3-id",
            "deployment_id": "base-id",
        },
    ]
    deployments = [
        {"id": "eth-id", "surface_id": "v2-id", "chain": "ethereum"},
        {"id": "base-id", "surface_id": "v3-id", "chain": "base"},
    ]

    payloads = dump.build_surface_payloads(surfaces, scores, deployments, [])
    primary = next(surface for surface in payloads if surface["is_primary"])
    v3 = next(surface for surface in payloads if surface["surface_slug"] == "v3")

    assert primary["factor_scores"][0]["score"] == "green"
    assert primary["deployments"][0]["chain"] == "ethereum"
    assert v3["factor_scores"][0]["score"] == "yellow"
    assert v3["deployment_factor_scores"]["base-id"][0]["score"] == "red"


def test_deployment_only_surface_is_exported() -> None:
    surfaces = [
        {"surface_id": "primary-id", "is_primary": True, "status": "active"},
        {"surface_id": "deployment-only-id", "is_primary": False, "status": "active"},
    ]
    scores = [
        {
            "factor_id": "RD-F-001",
            "scope_level": "deployment",
            "surface_id": "deployment-only-id",
            "deployment_id": "deployment-id",
        }
    ]

    exported = dump._surfaces_with_current_scores(surfaces, scores)

    assert [surface["surface_id"] for surface in exported] == [
        "primary-id",
        "deployment-only-id",
    ]


def test_deployment_category_severity_uses_rubric_weighting() -> None:
    scores = [
        {"factor_id": "RD-F-001", "score": "red"},
        *[
            {"factor_id": f"RD-F-{index:03d}", "score": "green"}
            for index in range(2, 11)
        ],
    ]
    categories = {score["factor_id"]: 1 for score in scores}

    severities = dump._category_severities_for_scores(
        scores,
        categories,
        has_active_incident=False,
    )

    assert severities["1"] == 10.0


def test_active_incident_downgrades_cascade_red_to_yellow() -> None:
    scores = [
        {"factor_id": "RD-F-060", "score": "green"},
        {"factor_id": "RD-F-061", "score": "yellow"},
        {"factor_id": "RD-F-063", "score": "red"},
    ]
    categories = {score["factor_id"]: 4 for score in scores}

    severities = dump._category_severities_for_scores(
        scores,
        categories,
        has_active_incident=True,
    )

    assert severities["4"] == 22.22222222222222


def test_legacy_alias_targets_exclude_same_slug_default_surface() -> None:
    targets = dump._legacy_alias_targets(
        {
            "fixture-family": [
                {"surface_slug": "core", "legacy_slug": "fixture-v2"},
            ],
            "single": [
                {"surface_slug": "default", "legacy_slug": "single"},
            ],
        }
    )

    assert targets == {"fixture-v2": "fixture-family"}
