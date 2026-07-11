from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "dump.py"
SPEC = importlib.util.spec_from_file_location("dump_surfaces", SCRIPT_PATH)
dump = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = dump
SPEC.loader.exec_module(dump)


def test_fetch_protocols_selects_last_refreshed_for_detail_export() -> None:
    class Cursor:
        query = ""

        def execute(self, query: str) -> None:
            self.query = query

        def fetchall(self):
            return [
                {
                    "slug": "fixture-family",
                    "last_refreshed": date(2026, 7, 11),
                }
            ]

    cursor = Cursor()
    protocols = dump.fetch_protocols(cursor)
    protocol_dict = dict(protocols[0])

    assert "last_refreshed" in cursor.query
    assert protocol_dict["last_refreshed"] == date(2026, 7, 11)


def test_write_json_does_not_log_tokenized_path(tmp_path, capsys) -> None:
    fake_token = "deadbeef"
    target = (
        tmp_path
        / "api"
        / "v1.7.0"
        / "unpublished"
        / f"fixture-family-{fake_token}"
        / "index.json"
    )

    dump.write_json(target, {"data": {"slug": "fixture-family"}}, dry_run=False)

    captured = capsys.readouterr()
    assert target.exists()
    assert fake_token not in captured.out
    assert fake_token not in captured.err


def test_write_json_failure_does_not_expose_tokenized_path(tmp_path, monkeypatch) -> None:
    fake_token = "deadbeef"
    target = tmp_path / "unpublished" / f"fixture-family-{fake_token}" / "index.json"

    def fail_write(*_args, **_kwargs):
        raise OSError(f"cannot write {target}")

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(RuntimeError) as exc_info:
        dump.write_json(target, {"data": {}}, dry_run=False)

    assert str(exc_info.value) == "failed to write generated JSON output"
    assert fake_token not in str(exc_info.value)


def test_write_json_dry_run_is_silent_and_writes_nothing(tmp_path, capsys) -> None:
    target = tmp_path / "unpublished" / "fixture-family-deadbeef" / "index.json"

    dump.write_json(target, {"data": {}}, dry_run=True)

    captured = capsys.readouterr()
    assert not target.exists()
    assert captured.out == ""
    assert captured.err == ""


def test_prune_failure_does_not_expose_tokenized_path(tmp_path, monkeypatch) -> None:
    fake_token = "deadbeef"
    tokenized_path = tmp_path / "unpublished" / f"fixture-family-{fake_token}"

    def fail_prune(*_args, **_kwargs):
        raise OSError(f"cannot remove {tokenized_path}")

    (tmp_path / "unpublished").mkdir()
    monkeypatch.setattr(dump.shutil, "rmtree", fail_prune)

    with pytest.raises(RuntimeError) as exc_info:
        dump.prune_generated_output(tmp_path)

    assert str(exc_info.value) == "failed to prune generated API output"
    assert fake_token not in str(exc_info.value)


def test_prune_generated_output_removes_both_directories(tmp_path, capsys) -> None:
    protocols = tmp_path / "protocols"
    unpublished = tmp_path / "unpublished"
    protocols.mkdir()
    (unpublished / "fixture-family-deadbeef").mkdir(parents=True)
    (protocols / "fixture.json").write_text("{}", encoding="utf-8")
    (unpublished / "fixture-family-deadbeef" / "index.json").write_text(
        "{}", encoding="utf-8"
    )

    dump.prune_generated_output(tmp_path)

    captured = capsys.readouterr()
    assert not protocols.exists()
    assert not unpublished.exists()
    assert captured.out == ""
    assert captured.err == ""


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
