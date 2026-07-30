from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from lean_protocol_refresh.contracts import (
    CANONICAL_FACTOR_IDS,
    ContractError,
    RUBRIC_VERSION,
    validate_change_set,
)


def _semantic_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _factor(factor_id: str, score: str = "green") -> dict:
    return {
        "factor_id": factor_id,
        "score": score,
        "evidence_summary": f"Public evidence supports {factor_id}.",
        "sources": [
            {
                "source_type": "docs",
                "url": f"https://example.org/evidence/{factor_id}",
                "reference": f"Public evidence for {factor_id}",
            }
        ],
    }


def _standard_change_set() -> dict:
    return {
        "schema_version": "lean-protocol-refresh/v1",
        "batch_id": "portable-contract-fixture",
        "refresh_date": "2026-07-30",
        "rubric_version": RUBRIC_VERSION,
        "protocols": [
            {
                "family_slug": "example",
                "surface_slugs": ["default"],
                "topology": {
                    "mode": "preserve",
                    "family_slug": "example",
                    "surface_slugs": ["default"],
                    "deployment_targets": [],
                },
                "outcome": "changed",
                "last_refreshed": "2026-07-30",
                "resulting_grade": "B",
                "rubric_version": RUBRIC_VERSION,
                "changes": [
                    {
                        "factor_id": "RD-F-001",
                        "old_value": _factor("RD-F-001", "yellow"),
                        "new_value": _factor("RD-F-001", "green"),
                        "evidence": [
                            {
                                "source_type": "docs",
                                "url": "https://example.org/evidence/RD-F-001",
                                "reference": "Public evidence for RD-F-001",
                            }
                        ],
                        "resulting_score": "green",
                        "resulting_grade": "B",
                    }
                ],
            }
        ],
    }


def _mixed_change_set() -> dict:
    document = _standard_change_set()
    protocol = document["protocols"][0]
    changed = protocol["changes"][0]["new_value"]
    projection = []
    for factor_id in sorted(CANONICAL_FACTOR_IDS):
        value = (
            copy.deepcopy(changed)
            if factor_id == "RD-F-001"
            else _factor(factor_id)
        )
        value["factor_id"] = factor_id
        projection.append(
            {
                "factor_id": factor_id,
                "scope_level": "surface",
                "target": "default",
                "value": value,
            }
        )
    ordinary_hash = _semantic_sha256(protocol)
    protocol["mixed_recovery"] = {
        "schema_version": "lean-protocol-refresh/mixed-recovery/v1",
        "source_rubric_version": "v1.5.0",
        "target_rubric_version": RUBRIC_VERSION,
        "selection_policy": "prefer_target_then_source",
        "full_target_projection": projection,
        "full_target_projection_semantic_sha256": _semantic_sha256(projection),
        "protocol_change_semantic_sha256": ordinary_hash,
    }
    return document


def test_standard_change_set_is_accepted() -> None:
    parsed = validate_change_set(_standard_change_set())
    assert parsed.protocols[0].changes[0].factor_id == "RD-F-001"


def test_hash_bound_historical_old_remediation_is_accepted() -> None:
    document = _standard_change_set()
    change = document["protocols"][0]["changes"][0]
    change["old_value"] = {
        "factor_id": "RD-F-001",
        "scope_level": "surface",
        "surface_slug": "default",
        "score": "yellow",
        "collection_mode": "manual",
        "gap_reason": None,
        "sources": [],
    }
    change["historical_old_remediation"] = {
        "schema_version": "lean-protocol-refresh/historical-old-remediation/v1",
        "mode": "historical_evidence_unavailable",
        "specialist": "code-security-analyst",
        "baseline_fragment_semantic_sha256": "1" * 64,
        "baseline_row_semantic_sha256": "2" * 64,
        "explanation": (
            "The retained score is immutable historical state and is not "
            "presented as a publicly substantiated claim."
        ),
        "evidence_summary": (
            "No public-safe evidence can substantiate the retained historical "
            "score; it is shown only as immutable baseline state."
        ),
        "evidence_detail": None,
        "notes": None,
        "sources": [],
    }

    parsed = validate_change_set(document)
    assert (
        parsed.protocols[0].changes[0].historical_old_remediation["mode"]
        == "historical_evidence_unavailable"
    )

    document["protocols"][0]["changes"][0]["historical_old_remediation"][
        "baseline_row_semantic_sha256"
    ] = "not-a-hash"
    with pytest.raises(ContractError):
        validate_change_set(document)


def test_mixed_recovery_hashes_and_projection_are_enforced() -> None:
    document = _mixed_change_set()
    parsed = validate_change_set(document)
    assert len(
        parsed.protocols[0].mixed_recovery.full_target_projection
    ) == len(CANONICAL_FACTOR_IDS)

    document["protocols"][0]["mixed_recovery"][
        "full_target_projection_semantic_sha256"
    ] = "0" * 64
    with pytest.raises(ContractError):
        validate_change_set(document)


def test_private_source_is_rejected_in_every_environment() -> None:
    document = _standard_change_set()
    document["protocols"][0]["changes"][0]["new_value"]["sources"][0][
        "url"
    ] = "https://10.0.0.1/private"

    with pytest.raises(ContractError):
        validate_change_set(document)
