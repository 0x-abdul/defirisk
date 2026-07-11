from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_public.output import verify_output_isolation


def write_json(root, relative: str, value: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def api_fixture(root, *, target_grade: str, other_grade: str = "B", generated_at: str) -> None:
    write_json(
        root,
        "index.json",
        {
            "generated_at": generated_at,
            "data": {
                "protocols": [
                    {"slug": "fixture-family", "headline_grade": target_grade},
                    {"slug": "other-family", "headline_grade": other_grade},
                ]
            },
        },
    )
    write_json(
        root,
        "factors/RD-F-001.json",
        {
            "generated_at": generated_at,
            "data": {
                "scored_protocols": [
                    {"protocol_slug": "fixture-family", "score": "green"},
                    {"protocol_slug": "other-family", "score": "yellow"},
                ]
            },
        },
    )
    write_json(
        root,
        "protocols/fixture-family.json",
        {"data": {"protocol_slug": "fixture-family", "headline_grade": target_grade}},
    )
    write_json(
        root,
        "protocols/other-family.json",
        {"data": {"protocol_slug": "other-family", "headline_grade": other_grade}},
    )


def test_target_and_generated_at_changes_are_isolated(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="before")
    api_fixture(after, target_grade="A", generated_at="after")

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is True
    assert report["unrelated_changed_files"] == []
    assert "index.json" in report["target_changed_files"]
    assert "protocols/fixture-family.json" in report["target_changed_files"]


def test_unrelated_protocol_change_fails(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="A", other_grade="F", generated_at="same")

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "index.json" in report["unrelated_changed_files"]
    assert "protocols/other-family.json" in report["unrelated_changed_files"]


def test_unrelated_file_addition_fails(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    write_json(after, "protocols/new-family.json", {"data": {"slug": "new-family"}})

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert report["unrelated_changed_files"] == ["protocols/new-family.json"]


def test_target_pipeline_runs_and_nested_data_as_of_are_isolated(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="before")
    api_fixture(after, target_grade="B", generated_at="after")
    write_json(
        before,
        "status.json",
        {
            "data_as_of": "before",
            "data": {"fleet": {"data_as_of": "before"}, "runs": []},
        },
    )
    write_json(
        after,
        "status.json",
        {
            "data_as_of": "after",
            "data": {
                "fleet": {"data_as_of": "after"},
                "runs": [
                    {
                        "script_name": "compose.py",
                        "triggered_by": "compose.py:fixture-family",
                        "notes": None,
                    },
                    {
                        "script_name": "apply-protocol-refresh.py",
                        "triggered_by": "protocol-refresh:refresh-1",
                        "notes": json.dumps({"family_slug": "fixture-family"}),
                    },
                ],
            },
        },
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is True
    assert report["unrelated_changed_files"] == []
    assert "status.json" in report["target_changed_files"]


def test_unrelated_pipeline_run_still_fails(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    write_json(before, "status.json", {"data": {"runs": []}})
    write_json(
        after,
        "status.json",
        {
            "data": {
                "runs": [
                    {
                        "script_name": "compose.py",
                        "triggered_by": "compose.py:other-family",
                        "notes": json.dumps({"family_slug": "other-family"}),
                    }
                ]
            }
        },
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


def test_pipeline_run_ownership_does_not_substring_match(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    write_json(before, "status.json", {"data": {"runs": []}})
    write_json(
        after,
        "status.json",
        {
            "data": {
                "runs": [
                    {
                        "script_name": "compose.py",
                        "triggered_by": "compose.py:fixture-family-extra",
                        "notes": json.dumps(
                            {
                                "family_slug": "fixture-family-extra",
                                "message": "refresh fixture-family",
                            }
                        ),
                    }
                ]
            }
        },
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]
