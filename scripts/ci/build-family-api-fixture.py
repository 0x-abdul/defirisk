#!/usr/bin/env python3
"""Build a disposable multi-surface API fixture from committed public data."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "data" / "api" / "v1.7.0"
DEFAULT_OUTPUT = REPO_ROOT / "_local" / "family-api-fixture" / "v1.7.0"
FAMILY_SLUG = "fixture-family"
ALIAS_SLUG = "fixture-v2"
HEADER_FAMILY_SLUG = "fixture-header-family"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_fixture(source: Path, output: Path) -> str:
    local_root = (REPO_ROOT / "_local").resolve()
    try:
        output.resolve().relative_to(local_root)
    except ValueError as exc:
        raise ValueError(f"fixture output must stay under {local_root}") from exc
    if output.resolve() == local_root:
        raise ValueError("fixture output must be a child of _local, not _local itself")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)

    source_envelope = read_json(source / "protocols" / "aave-v3.json")
    source_detail = source_envelope["data"]["protocol_data"]
    source_protocol = source_detail["protocol"]
    scores = copy.deepcopy(source_detail["factor_scores"])
    factor_rows = read_json(source / "factors.json")["data"]["factors"]
    category_thirteen_ids = {
        factor["id"] for factor in factor_rows if factor["category_id"] == 13
    }
    first_factor = scores[0]["factor_id"]
    primary_history = copy.deepcopy(source_detail.get("grade_history", []))
    secondary_history = copy.deepcopy(primary_history)

    primary_deployments = copy.deepcopy(source_detail["deployments"][:2])
    secondary_deployments = copy.deepcopy(source_detail["deployments"][2:4])
    for index, deployment in enumerate(primary_deployments):
        deployment["protocol_slug"] = FAMILY_SLUG
        deployment["surface_id"] = "00000000-0000-4000-8000-000000000001"
        deployment["deployment_key"] = f"core-{index + 1}"
        deployment["selector"] = {"surface": "core", "chain": deployment.get("chain"), "deployment_key": deployment["deployment_key"]}
        deployment["factor_counts"] = {"rubric_total": 184, "assessed": 160, "severity_rated": 160, "pending": 12, "not_applicable": 6, "unscored": 6}
    # Long labels and unavailable deployment TVS are deliberate UI regression
    # states; consumers must not substitute a surface-wide value.
    if len(primary_deployments) > 1:
        primary_deployments[1]["display_name"] = "Long-label fixture deployment for responsive selector verification"
        primary_deployments[1]["tvs_usd"] = None
    for index, deployment in enumerate(secondary_deployments):
        deployment["protocol_slug"] = FAMILY_SLUG
        deployment["surface_id"] = "00000000-0000-4000-8000-000000000002"
        deployment["deployment_key"] = f"v2-{index + 1}"
        deployment["selector"] = {"surface": "v2", "chain": deployment.get("chain"), "deployment_key": deployment["deployment_key"]}

    primary_surface = {
        "surface_id": "00000000-0000-4000-8000-000000000001",
        "family_slug": FAMILY_SLUG,
        "surface_slug": "core",
        "display_name": "Core markets",
        "surface_type": "version",
        "status": "active",
        "is_primary": True,
        "legacy_slug": None,
        # The primary surface is deliberately assessed and capped while the
        # highest-TVL surface below is not.  This keeps the queryless route
        # honest: it must not inherit a primary-surface assessment.
        "headline_grade": "D",
        "risk_score": 73.4,
        "graded_at": "2026-04-10T12:00:00Z",
        "tvs_usd": 1000000,
        "category_severities": source_protocol.get("category_severities"),
        "cap_applied": "D",
        "cap_reason": "Synthetic alternate-surface cap.",
        "deployments": primary_deployments,
        "factor_scores": copy.deepcopy(scores),
        "deployment_overrides": {},
        "deployment_factor_scores": {},
        "deployment_category_severities": {},
        "grade_history": primary_history,
        "deployment_count": len(primary_deployments),
        "factor_counts": {"rubric_total": 184, "assessed": 160, "severity_rated": 160, "pending": 12, "not_applicable": 6, "unscored": 6},
    }
    secondary_scores = copy.deepcopy(scores)
    secondary_scores[0]["score"] = "yellow"
    secondary_scores[0]["evidence_summary"] = "Synthetic family-route fixture evidence."
    secondary_surface = {
        "surface_id": "00000000-0000-4000-8000-000000000002",
        "family_slug": FAMILY_SLUG,
        "surface_slug": "v2",
        "display_name": "Version 2",
        "surface_type": "version",
        "status": "active",
        "is_primary": False,
        "legacy_slug": ALIAS_SLUG,
        "headline_grade": None,
        "risk_score": None,
        "graded_at": None,
        # Deliberately larger than the first, primary surface so queryless
        # selection cannot accidentally rely on payload order or is_primary.
        "tvs_usd": 2000000,
        # Raw category payload intentionally disagrees with the effective
        # factor score below.  The UI must render its category light from the
        # effective factor model, not this stale raw value.
        "category_severities": {**(source_protocol.get("category_severities") or {}), "1": 99},
        "cap_applied": "none",
        "cap_reason": None,
        "deployments": secondary_deployments,
        "factor_scores": secondary_scores,
        "deployment_overrides": {},
        "deployment_factor_scores": {},
        "deployment_category_severities": {},
        "grade_history": secondary_history,
        "deployment_count": len(secondary_deployments),
        "factor_counts": {"rubric_total": 184, "assessed": 140, "severity_rated": 140, "pending": 22, "not_applicable": 12, "unscored": 10},
    }
    # A deliberately partial override on the queryless default surface
    # exercises per-factor fallback without exposing an internal UUID in its
    # public URL selector.
    secondary_override = copy.deepcopy(
        [
            secondary_scores[0],
            *[
                score
                for score in secondary_scores[1:]
                if score["factor_id"] in category_thirteen_ids
            ],
        ]
    )
    secondary_override[0]["score"] = "red"
    secondary_override[0]["evidence_summary"] = "Synthetic partial deployment-scoped override."
    for score in secondary_override[1:]:
        score["score"] = "not_assessed"
        score["evidence_summary"] = "Synthetic deployment-unassessed category."
    secondary_effective_scores = copy.deepcopy(secondary_scores)
    overrides_by_factor = {
        score["factor_id"]: score for score in secondary_override
    }
    secondary_effective_scores = [
        copy.deepcopy(overrides_by_factor.get(score["factor_id"], score))
        for score in secondary_effective_scores
    ]
    secondary_surface["deployment_overrides"] = {
        secondary_deployments[0]["id"]: secondary_override
    }
    secondary_surface["deployment_factor_scores"] = {
        secondary_deployments[0]["id"]: secondary_effective_scores
    }
    effective_secondary_severities = {
        key: value
        for key, value in (secondary_surface["category_severities"] or {}).items()
        if str(key) != "13"
    }
    effective_secondary_severities["1"] = 88
    secondary_surface["deployment_category_severities"] = {
        secondary_deployments[0]["id"]: {
            **effective_secondary_severities,
        }
    }

    protocol = copy.deepcopy(source_protocol)
    protocol.update(
        {
            "slug": FAMILY_SLUG,
            "display_name": "Fixture Family",
            "description": "Synthetic multi-surface payload used only by build checks.",
            "surface_count": 2,
            "primary_surface_slug": "core",
            "legacy_caveat": "Legacy links select the corresponding surface.",
            # Family-level storage is intentionally not the selected default
            # surface's grade.  Detail pages must take assessment headers
            # from their selected surface.
            "headline_grade": "A",
            "risk_score": 2.1,
            "graded_at": "2026-01-01T00:00:00Z",
        }
    )
    family = {
        "family_slug": FAMILY_SLUG,
        "display_name": "Fixture Family",
        "description": protocol["description"],
        "homepage_url": protocol.get("homepage_url"),
        "protocol_type": protocol.get("protocol_type"),
        "primary_chain": protocol.get("primary_chain"),
        "primary_surface_id": primary_surface["surface_id"],
        "is_published": True,
        "legacy_caveat": protocol["legacy_caveat"],
    }
    family_detail = {
        "protocol": protocol,
        "family": family,
        "surfaces": [primary_surface, secondary_surface],
        "deployments": primary_deployments,
        "factor_scores": copy.deepcopy(scores),
        "grade_history": primary_history,
    }
    family_envelope = copy.deepcopy(source_envelope)
    family_envelope["data"]["protocol_data"] = family_detail
    write_json(output / "protocols" / f"{FAMILY_SLUG}.json", family_envelope)

    alias_protocol = copy.deepcopy(protocol)
    alias_protocol.update(
        {
            "slug": ALIAS_SLUG,
            "display_name": "Fixture Family Version 2",
            "canonical_family_slug": FAMILY_SLUG,
            "selected_surface_slug": "v2",
        }
    )
    alias_detail = copy.deepcopy(family_detail)
    alias_detail["protocol"] = alias_protocol
    alias_detail["deployments"] = secondary_deployments
    alias_detail["factor_scores"] = copy.deepcopy(secondary_scores)
    alias_detail["grade_history"] = secondary_history
    alias_envelope = copy.deepcopy(family_envelope)
    alias_envelope["data"]["protocol_data"] = alias_detail
    write_json(output / "protocols" / f"{ALIAS_SLUG}.json", alias_envelope)

    # A second independent family supplies the complementary header state:
    # its greatest-TVL default surface is graded, capped, risk-scored, and
    # carries a stable provenance date.  Keep factor data intentionally
    # equivalent to the first family so DOM parity assertions can isolate
    # the presentation contract from assessment-header state.
    header_primary = copy.deepcopy(primary_surface)
    header_primary.update(
        {
            "surface_id": "00000000-0000-4000-8000-000000000011",
            "family_slug": HEADER_FAMILY_SLUG,
            "surface_slug": "legacy",
            "display_name": "Legacy markets",
            "is_primary": True,
            "tvs_usd": 900000,
            "headline_grade": None,
            "risk_score": None,
            "graded_at": None,
            "cap_applied": "none",
            "cap_reason": None,
        }
    )
    header_primary["deployments"] = copy.deepcopy(primary_deployments)
    for deployment in header_primary["deployments"]:
        deployment["protocol_slug"] = HEADER_FAMILY_SLUG
        deployment["surface_id"] = header_primary["surface_id"]
        deployment["deployment_key"] = f"legacy-{deployment['deployment_key']}"

    header_default = copy.deepcopy(secondary_surface)
    header_default.update(
        {
            "surface_id": "00000000-0000-4000-8000-000000000012",
            "family_slug": HEADER_FAMILY_SLUG,
            "surface_slug": "secure",
            "display_name": "Secure markets",
            "is_primary": False,
            "tvs_usd": 3000000,
            "headline_grade": "C",
            "risk_score": 42.7,
            "graded_at": "2026-06-15T00:00:00Z",
            "cap_applied": "D",
            "cap_reason": "Synthetic default-surface cap.",
        }
    )
    header_default["deployments"] = copy.deepcopy(secondary_deployments)
    for deployment in header_default["deployments"]:
        deployment["protocol_slug"] = HEADER_FAMILY_SLUG
        deployment["surface_id"] = header_default["surface_id"]
        deployment["deployment_key"] = f"secure-{deployment['deployment_key']}"
    header_override = copy.deepcopy(header_default["factor_scores"][:1])
    header_override[0]["score"] = "red"
    header_override[0]["evidence_summary"] = "Synthetic header-family partial override."
    header_effective = copy.deepcopy(header_default["factor_scores"])
    header_effective[0] = copy.deepcopy(header_override[0])
    header_default["deployment_overrides"] = {
        header_default["deployments"][0]["id"]: header_override
    }
    header_default["deployment_factor_scores"] = {
        header_default["deployments"][0]["id"]: header_effective
    }
    header_default["deployment_category_severities"] = {
        header_default["deployments"][0]["id"]: {
            **(header_default["category_severities"] or {}),
            "1": 88,
        }
    }

    header_protocol = copy.deepcopy(protocol)
    header_protocol.update(
        {
            "slug": HEADER_FAMILY_SLUG,
            "display_name": "Fixture Header Family",
            "description": "Synthetic header-selection fixture used only by build checks.",
            "primary_surface_slug": "legacy",
            # Explicit stored-vs-derived disagreement: the selected surface
            # says C/D while the family record says A/no cap.
            "headline_grade": "A",
            "risk_score": 1.0,
            "graded_at": "2026-01-01T00:00:00Z",
            "cap_applied": "none",
            "cap_reason": None,
        }
    )
    header_family = copy.deepcopy(family)
    header_family.update(
        {
            "family_slug": HEADER_FAMILY_SLUG,
            "display_name": header_protocol["display_name"],
            "description": header_protocol["description"],
            "primary_surface_id": header_primary["surface_id"],
        }
    )
    header_detail = {
        "protocol": header_protocol,
        "family": header_family,
        "surfaces": [header_primary, header_default],
        "deployments": header_primary["deployments"],
        "factor_scores": copy.deepcopy(header_primary["factor_scores"]),
        "grade_history": primary_history,
    }
    header_envelope = copy.deepcopy(source_envelope)
    header_envelope["data"]["protocol_data"] = header_detail
    write_json(output / "protocols" / f"{HEADER_FAMILY_SLUG}.json", header_envelope)

    index_envelope = read_json(output / "index.json")
    protocols = index_envelope["data"]["protocols"]
    protocols.append(
        {
            "slug": FAMILY_SLUG,
            "display_name": protocol["display_name"],
            "protocol_type": protocol["protocol_type"],
            "primary_chain": protocol["primary_chain"],
            "surface_count": 2,
            "primary_surface_slug": "core",
            "legacy_caveat": protocol["legacy_caveat"],
            "headline_grade": protocol.get("headline_grade"),
            "total_value_secured_usd": protocol.get("total_value_secured_usd"),
            "graded_at": protocol.get("graded_at"),
            "rubric_version": protocol.get("rubric_version"),
            "status": protocol["status"],
            "has_active_incident": protocol["has_active_incident"],
            "risk_score": protocol.get("risk_score"),
            "category_severities": protocol.get("category_severities"),
            "cap_applied": protocol.get("cap_applied"),
            "cap_reason": protocol.get("cap_reason"),
        }
    )
    protocols.append(
        {
            "slug": HEADER_FAMILY_SLUG,
            "display_name": header_protocol["display_name"],
            "protocol_type": header_protocol["protocol_type"],
            "primary_chain": header_protocol["primary_chain"],
            "surface_count": 2,
            "primary_surface_slug": "legacy",
            "legacy_caveat": header_protocol["legacy_caveat"],
            "headline_grade": header_protocol["headline_grade"],
            "total_value_secured_usd": header_protocol.get("total_value_secured_usd"),
            "graded_at": header_protocol["graded_at"],
            "rubric_version": header_protocol.get("rubric_version"),
            "status": header_protocol["status"],
            "has_active_incident": header_protocol["has_active_incident"],
            "risk_score": header_protocol["risk_score"],
            "category_severities": header_protocol.get("category_severities"),
            "cap_applied": header_protocol["cap_applied"],
            "cap_reason": header_protocol["cap_reason"],
        }
    )
    write_json(output / "index.json", index_envelope)

    source_history = source / "protocols" / "aave-v3" / "history.json"
    if source_history.exists():
        history_envelope = read_json(source_history)
        history_data = history_envelope.get("data", {})
        history_data["protocol_slug"] = ALIAS_SLUG
        history_data["canonical_family_slug"] = FAMILY_SLUG
        history_data["selected_surface_slug"] = "v2"
        write_json(output / "protocols" / ALIAS_SLUG / "history.json", history_envelope)

    return first_factor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    first_factor = build_fixture(args.source.resolve(), args.output.resolve())
    print(f"fixture_root={args.output.resolve()}")
    print(f"first_factor={first_factor}")


if __name__ == "__main__":
    main()
