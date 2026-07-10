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
    first_factor = scores[0]["factor_id"]
    primary_history = copy.deepcopy(source_detail.get("grade_history", []))
    secondary_history = copy.deepcopy(primary_history)

    primary_deployments = copy.deepcopy(source_detail["deployments"][:2])
    secondary_deployments = copy.deepcopy(source_detail["deployments"][2:4])
    for deployment in primary_deployments:
        deployment["protocol_slug"] = FAMILY_SLUG
        deployment["surface_id"] = "00000000-0000-4000-8000-000000000001"
        deployment["deployment_key"] = deployment.get("deployment_key") or "primary"
    for deployment in secondary_deployments:
        deployment["protocol_slug"] = FAMILY_SLUG
        deployment["surface_id"] = "00000000-0000-4000-8000-000000000002"
        deployment["deployment_key"] = deployment.get("deployment_key") or "primary"

    primary_surface = {
        "surface_id": "00000000-0000-4000-8000-000000000001",
        "family_slug": FAMILY_SLUG,
        "surface_slug": "core",
        "display_name": "Core markets",
        "surface_type": "version",
        "status": "active",
        "is_primary": True,
        "legacy_slug": None,
        "headline_grade": source_protocol.get("headline_grade"),
        "risk_score": source_protocol.get("risk_score"),
        "graded_at": source_protocol.get("graded_at"),
        "tvs_usd": source_protocol.get("total_value_secured_usd"),
        "category_severities": source_protocol.get("category_severities"),
        "cap_applied": source_protocol.get("cap_applied"),
        "cap_reason": source_protocol.get("cap_reason"),
        "deployments": primary_deployments,
        "factor_scores": copy.deepcopy(scores),
        "deployment_factor_scores": {},
        "deployment_category_severities": {},
        "grade_history": primary_history,
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
        "headline_grade": source_protocol.get("headline_grade"),
        "risk_score": source_protocol.get("risk_score"),
        "graded_at": source_protocol.get("graded_at"),
        "tvs_usd": 1000000,
        "category_severities": source_protocol.get("category_severities"),
        "cap_applied": source_protocol.get("cap_applied"),
        "cap_reason": source_protocol.get("cap_reason"),
        "deployments": secondary_deployments,
        "factor_scores": secondary_scores,
        "deployment_factor_scores": {},
        "deployment_category_severities": {},
        "grade_history": secondary_history,
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
