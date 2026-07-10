from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "import-protocol-assessment.py"
SPEC = importlib.util.spec_from_file_location("import_protocol_assessment", SCRIPT_PATH)
importer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = importer
SPEC.loader.exec_module(importer)


def grading() -> dict:
    return {
        "protocol": {
            "slug": "fixture-family",
            "display_name": "Fixture Family",
            "protocol_type": "lending",
            "primary_chain": "ethereum",
            "status": "live",
        },
        "factor_scores": [
            {
                "factor_id": "RD-F-001",
                "score": "green",
                "evidence_summary": "Fixture evidence",
                "collection_mode": "manual",
                "sources": [
                    {
                        "source_type": "docs",
                        "reference": "Fixture documentation",
                    }
                ],
            }
        ],
    }


def db_args(**overrides):
    defaults = {
        "db_url": "postgresql://user:pass@localhost:5432/fixture_staging",
        "expected_database": "fixture_staging",
        "allow_nonlocal": False,
        "i_understand_nonlocal": False,
        "allow_protected_database": False,
        "i_understand_protected_database": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_flat_packet_normalises_to_one_default_surface() -> None:
    packet = grading()
    family = importer.normalise_family(packet, "fixture-family")
    surfaces = importer.normalise_surfaces(packet, family)

    assert importer.validate(packet, "fixture-family") == []
    assert family["family_slug"] == "fixture-family"
    assert len(surfaces) == 1
    assert surfaces[0]["surface_slug"] == "default"
    assert surfaces[0]["is_primary"] is True


def test_family_slug_must_equal_protocol_slug() -> None:
    packet = grading()
    packet["family"] = {
        "family_slug": "different-family",
        "display_name": "Different",
        "protocol_type": "lending",
        "primary_chain": "ethereum",
    }

    assert "family.family_slug must equal protocol.slug" in importer.validate(
        packet, "fixture-family"
    )


def test_apply_requires_exact_database_identity() -> None:
    try:
        importer.resolve_database_url(db_args(expected_database="wrong"))
    except ValueError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("expected database identity guard")


def test_production_database_requires_double_guard() -> None:
    args = db_args(
        db_url="postgresql://user:pass@localhost:5432/risk_dashboard",
        expected_database="risk_dashboard",
    )

    try:
        importer.resolve_database_url(args)
    except ValueError as exc:
        assert "protected database" in str(exc)
    else:
        raise AssertionError("expected protected database guard")


class SurfaceCursor:
    def execute(self, sql, params=None) -> None:
        return None

    def fetchall(self):
        return [
            {"surface_slug": "v2", "legacy_slug": "fixture-v2"},
            {"surface_slug": "v3", "legacy_slug": "fixture-v3"},
        ]


def test_partial_surface_packet_is_blocked() -> None:
    try:
        importer.ensure_surface_set_safe(
            SurfaceCursor(),
            {"family_slug": "fixture-family"},
            [{"surface_slug": "v3"}],
            allow_surface_removal=False,
        )
    except ValueError as exc:
        assert "v2" in str(exc)
    else:
        raise AssertionError("expected partial-family guard")


def test_explicit_zero_surface_tvs_is_preserved() -> None:
    packet = grading()
    packet["surfaces"] = [
        {
            "surface_slug": "core",
            "display_name": "Core",
            "primary_chain": "ethereum",
            "tvs_usd": 0,
            "total_value_secured_usd": 99,
            "is_primary": True,
        }
    ]
    family = importer.normalise_family(packet, "fixture-family")

    assert importer.normalise_surfaces(packet, family)[0]["tvs_usd"] == 0


def test_same_deployment_key_on_different_chains_is_not_a_duplicate() -> None:
    packet = grading()
    packet["surfaces"] = [
        {
            "surface_slug": "core",
            "display_name": "Core",
            "primary_chain": "ethereum",
            "is_primary": True,
        }
    ]
    packet["deployments"] = [
        {"surface_slug": "core", "chain": "ethereum", "deployment_key": "primary"},
        {"surface_slug": "core", "chain": "arbitrum", "deployment_key": "primary"},
    ]
    base = packet["factor_scores"][0]
    packet["factor_scores"] = [
        {**base, "scope_level": "deployment", "surface_slug": "core", "chain": "ethereum"},
        {**base, "scope_level": "deployment", "surface_slug": "core", "chain": "arbitrum"},
    ]

    assert importer.validate(packet, "fixture-family") == []


def test_subprocesses_receive_only_validated_database_url(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod")
    monkeypatch.setenv("LOCAL_DATABASE_URL", "postgresql://other")
    monkeypatch.setattr(importer.subprocess, "call", lambda *args, **kwargs: calls.append(kwargs) or 0)

    staging = "postgresql://user:secret@localhost:5432/fixture_staging"
    assert importer.run_compose("fixture-family", dry_run=False, db_url=staging) == 0
    assert importer.run_dump("fixture-family", db_url=staging) == 0

    assert all(call["env"]["DATABASE_URL"] == staging for call in calls)
    assert all("LOCAL_DATABASE_URL" not in call["env"] for call in calls)


def test_compose_failure_skips_dump_and_propagates(monkeypatch) -> None:
    dumped = []
    monkeypatch.setattr(importer, "run_compose", lambda *args, **kwargs: 7)
    monkeypatch.setattr(importer, "run_dump", lambda *args, **kwargs: dumped.append(True) or 0)

    assert importer.run_post_import(
        "fixture-family",
        "postgresql://staging",
        skip_compose=False,
        run_dump_requested=True,
        skip_dump=False,
    ) == 7
    assert dumped == []


def test_incident_flag_is_preserved_when_packet_omits_it() -> None:
    class Cursor:
        def execute(self, sql, params):
            self.sql = sql
            self.params = params

    cur = Cursor()
    importer.upsert_protocol(cur, grading()["protocol"], "v1.7.0")

    assert cur.params["has_active_incident"] is None
    assert "COALESCE(%(has_active_incident)s, protocols.has_active_incident)" in cur.sql


def test_incident_state_is_inherited_from_legacy_surface() -> None:
    class Cursor:
        def execute(self, sql, params):
            self.sql = sql
            self.params = params

        def fetchone(self):
            return {"has_active_incident": True}

    protocol = grading()["protocol"]
    cur = Cursor()

    inherited = importer.inherit_incident_state(
        cur,
        protocol,
        [{"surface_slug": "v2", "legacy_slug": "legacy-v2"}],
    )

    assert inherited is True
    assert protocol["has_active_incident"] is True
    assert cur.params == (["fixture-family", "legacy-v2"], ["fixture-family", "legacy-v2"])
    assert "active_incidents" in cur.sql
