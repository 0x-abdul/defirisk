from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "compose.py"
SPEC = importlib.util.spec_from_file_location("compose_surfaces", SCRIPT_PATH)
compose = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = compose
SPEC.loader.exec_module(compose)


def test_surface_scores_override_family_and_exclude_deployment_rows() -> None:
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
            "surface_id": "v2-id",
            "deployment_id": None,
        },
        {
            "factor_id": "RD-F-001",
            "score": "red",
            "scope_level": "deployment",
            "family_slug": None,
            "surface_id": "v2-id",
            "deployment_id": "eth-id",
        },
    ]

    effective = compose._effective_surface_scores(scores, "v2-id")

    assert len(effective) == 1
    assert effective[0]["score"] == "yellow"


def test_family_score_is_inherited_when_surface_has_no_override() -> None:
    scores = [
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "scope_level": "family",
            "family_slug": "fixture-family",
            "surface_id": None,
            "deployment_id": None,
        }
    ]

    assert compose._effective_surface_scores(scores, "v3-id")[0]["score"] == "green"


def test_surface_grade_uses_least_privileged_function() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.query = ""
            self.params = ()

        def execute(self, query, params) -> None:
            self.query = query
            self.params = params

    cur = Cursor()
    compose._update_surface_grade(
        cur,
        family_slug="fixture-family",
        surface_id="00000000-0000-0000-0000-000000000001",
        letter="B",
        rubric_version="v1.7.0",
        graded_at="2026-07-17T00:00:00Z",
        risk_score=25.0,
        category_severities={"1": 25.0},
    )

    assert "refresh_update_surface_grade" in cur.query
    assert "%s::numeric" in cur.query
    assert "UPDATE protocol_surfaces" not in cur.query
    assert cur.params[:2] == (
        "fixture-family",
        "00000000-0000-0000-0000-000000000001",
    )


def test_required_nightly_protocols_must_produce_primary_grades() -> None:
    assert compose._missing_required_protocols(
        {"updated", "missing"},
        {"updated"},
    ) == ["missing"]
