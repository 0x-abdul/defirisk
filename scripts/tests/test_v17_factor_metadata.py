from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V17_API = ROOT / "data" / "api" / "v1.7.0"

CURRENT_CRITICAL_RULE = (
    "Critical-factor treatment in rubric v1.7.0: a red result on this factor "
    "blocks an A grade and adds 5 points to the protocol risk score, up to a "
    "15-point cap across all critical reds. Two or more critical reds force D "
    "or worse. Three or more force F. Risk-score bands and core-five caps can "
    "lower the grade further."
)

OBSOLETE_V15_MARKER = re.compile(
    r"(?i)(?:this factor is critical under rubric v1\.5:"
    r"|this factor alone is sufficient to trigger[^\r\n]*rubric v1\.5"
    r"|is alone sufficient to trigger[^\r\n]*rubric v1\.5)"
)
OBSOLETE_SINGLE_RED_CLAIM = re.compile(
    r"(?i)(?:"
    r"single\s+(?:critical[- ]flag\s+)?red"
    r"|one\s+(?:critical[- ]flag\s+)?red"
    r"|\balone(?:\s+is)?\s+sufficient"
    r")"
)


CRITICAL_IDS = (
    "RD-F-001", "RD-F-022", "RD-F-027", "RD-F-028", "RD-F-036",
    "RD-F-039", "RD-F-041", "RD-F-042", "RD-F-043", "RD-F-046",
    "RD-F-053", "RD-F-070", "RD-F-123", "RD-F-124", "RD-F-125",
    "RD-F-139", "RD-F-143", "RD-F-151", "RD-F-154", "RD-F-180",
)

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _v17_factor_index() -> list[dict]:
    return _read_json(V17_API / "factors.json")["data"]["factors"]


def _v17_factor_detail(factor_id: str) -> dict:
    return _read_json(V17_API / "factors" / f"{factor_id}.json")["data"][
        "factor_data"
    ]["factor"]


def test_v17_factor_names_are_consistent_in_index_and_detail_records() -> None:
    expected_names = {
        "RD-F-126": "Is a fork of",
        "RD-F-170": "Solc version used (versions with known bugs flagged)",
    }
    index_by_id = {factor["id"]: factor for factor in _v17_factor_index()}

    for factor_id, expected_name in expected_names.items():
        assert index_by_id[factor_id]["name"] == expected_name
        assert _v17_factor_detail(factor_id)["name"] == expected_name


def test_v17_active_critical_details_use_current_rule_language() -> None:
    active_critical_ids = [
        factor["id"]
        for factor in _v17_factor_index()
        if factor.get("is_critical") is True
        and factor.get("deprecated_in_rubric") is None
    ]
    assert tuple(active_critical_ids) == CRITICAL_IDS

    for factor_id in active_critical_ids:
        detail = _v17_factor_detail(factor_id)
        assert detail["is_critical"] is True, factor_id
        methodology = detail["scoring_methodology"]
        assert CURRENT_CRITICAL_RULE in methodology, factor_id
        assert not OBSOLETE_V15_MARKER.search(methodology), factor_id
        assert not OBSOLETE_SINGLE_RED_CLAIM.search(methodology), factor_id

def test_historical_factor_names_remain_unchanged() -> None:
    for version in ("v1.5.0", "v1.6.0"):
        payload = _read_json(ROOT / "data" / "api" / version / "factors.json")
        names = {factor["id"]: factor["name"] for factor in payload["data"]["factors"]}
        assert names["RD-F-126"] == "Is-a-fork-of"
        assert names["RD-F-170"] == "Solc version used (known-bug versions flagged)"
