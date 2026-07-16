from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_public.contracts import ContractError
from protocol_refresh_public.output import resolve_protocol_output, verify_output_isolation


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
        {
            "data": {
                "protocol_data": {
                    "protocol": {
                        "slug": "fixture-family",
                        "headline_grade": target_grade,
                    }
                }
            }
        },
    )
    write_json(
        root,
        "protocols/other-family.json",
        {
            "data": {
                "protocol_data": {
                    "protocol": {
                        "slug": "other-family",
                        "headline_grade": other_grade,
                    }
                }
            }
        },
    )


def move_target_to_unpublished(root: Path, token: str) -> Path:
    source = root / "protocols/fixture-family.json"
    target = root / "unpublished" / f"fixture-family-{token}" / "index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)
    return target.parent


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


def _status_run(identifier: str, family_slug: str | None = None) -> dict:
    if family_slug is None:
        return {
            "id": identifier,
            "script_name": "compose.py",
            "triggered_by": f"compose.py:{identifier}",
            "notes": json.dumps({"family_slug": identifier}),
        }
    return {
        "id": identifier,
        "script_name": "apply-protocol-refresh.py",
        "triggered_by": f"protocol-refresh:{identifier}",
        "notes": json.dumps({"family_slug": family_slug}),
    }


def test_target_runs_may_evict_only_unrelated_status_tail_rows(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    unrelated = [_status_run(f"other-{index}") for index in range(28)]
    before_runs = [
        _status_run("target-old-1", "fixture-family"),
        _status_run("target-old-2", "fixture-family"),
        *unrelated,
    ]
    after_runs = [
        _status_run("target-new-1", "fixture-family"),
        _status_run("target-new-2", "fixture-family"),
        *before_runs[:2],
        *unrelated[:26],
    ]
    write_json(
        before,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": before_runs}},
    )
    write_json(
        after,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": after_runs}},
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is True
    assert report["unrelated_changed_files"] == []
    assert "status.json" in report["target_changed_files"]


def test_status_window_rejects_tail_eviction_before_declared_window_is_full(
    tmp_path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    before_runs = [_status_run("other-1"), _status_run("other-2")]
    after_runs = [_status_run("target-new", "fixture-family"), before_runs[0]]
    write_json(
        before,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": before_runs}},
    )
    write_json(
        after,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": after_runs}},
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


def test_status_window_allows_target_insertion_to_fill_window_without_eviction(
    tmp_path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    before_runs = [_status_run(f"other-{index}") for index in range(29)]
    after_runs = [_status_run("target-new", "fixture-family"), *before_runs]
    write_json(
        before,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": before_runs}},
    )
    write_json(
        after,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": after_runs}},
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is True
    assert "status.json" in report["target_changed_files"]


def test_status_window_rejects_duplicate_run_id_with_tail_eviction(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    unrelated = [_status_run(f"other-{index}") for index in range(29)]
    target = _status_run("target-existing", "fixture-family")
    before_runs = [target, *unrelated]
    after_runs = [target, target, *unrelated[:28]]
    write_json(
        before,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": before_runs}},
    )
    write_json(
        after,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": after_runs}},
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


def test_status_window_rejects_mutated_existing_target_id_with_tail_eviction(
    tmp_path,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    unrelated = [_status_run(f"other-{index}") for index in range(29)]
    before_runs = [_status_run("target-existing", "fixture-family"), *unrelated]
    mutated_target = dict(before_runs[0])
    mutated_target["triggered_by"] = "protocol-refresh:mutated"
    after_runs = [mutated_target, *unrelated[:28]]
    write_json(
        before,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": before_runs}},
    )
    write_json(
        after,
        "status.json",
        {"data": {"meta": {"runs_window": 30}, "runs": after_runs}},
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


def test_status_window_rejects_middle_or_excess_unrelated_eviction(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    unrelated = [_status_run(f"other-{index}") for index in range(4)]
    before_runs = [_status_run("target-old", "fixture-family"), *unrelated]
    after_runs = [
        _status_run("target-new", "fixture-family"),
        before_runs[0],
        unrelated[0],
        unrelated[2],
    ]
    write_json(before, "status.json", {"data": {"runs": before_runs}})
    write_json(after, "status.json", {"data": {"runs": after_runs}})

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


def test_status_window_rejects_unrelated_run_insertion(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    before_runs = [_status_run("other-1"), _status_run("other-2")]
    after_runs = [
        _status_run("target-new", "fixture-family"),
        _status_run("other-added"),
        *before_runs,
    ]
    write_json(before, "status.json", {"data": {"runs": before_runs}})
    write_json(after, "status.json", {"data": {"runs": after_runs}})

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


def test_status_window_rejects_non_run_status_change(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    before_runs = [_status_run("other-1"), _status_run("other-2")]
    after_runs = [_status_run("target-new", "fixture-family"), *before_runs]
    write_json(
        before,
        "status.json",
        {"data": {"runs": before_runs, "bucket_freshness": {"C": {"count": 1}}}},
    )
    write_json(
        after,
        "status.json",
        {"data": {"runs": after_runs, "bucket_freshness": {"C": {"count": 2}}}},
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "status.json" in report["unrelated_changed_files"]


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


def test_unpublished_target_detail_and_history_changes_are_isolated(tmp_path) -> None:
    token = "secret-review-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="before")
    api_fixture(after, target_grade="A", generated_at="after")
    before_target = move_target_to_unpublished(before, token)
    after_target = move_target_to_unpublished(after, token)
    write_json(
        before_target,
        "history.json",
        {
            "data": {
                "protocol_slug": "fixture-family",
                "series": [{"grade": "B"}],
            }
        },
    )
    write_json(
        after_target,
        "history.json",
        {
            "data": {
                "protocol_slug": "fixture-family",
                "series": [{"grade": "A"}],
            }
        },
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is True
    assert report["unrelated_changed_files"] == []
    assert "unpublished/<review>/index.json" in report["target_changed_files"]
    assert "unpublished/<review>/history.json" in report["target_changed_files"]
    assert token not in json.dumps(report)


def test_unrelated_unpublished_protocol_change_fails_without_token_disclosure(tmp_path) -> None:
    target_token = "target-secret-token"
    other_token = "other-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    move_target_to_unpublished(before, target_token)
    move_target_to_unpublished(after, target_token)
    other_relative = f"unpublished/other-family-{other_token}/index.json"
    before_other = {
        "data": {
            "protocol_data": {
                "protocol": {"slug": "other-family", "headline_grade": "B"}
            }
        }
    }
    after_other = json.loads(json.dumps(before_other))
    after_other["data"]["protocol_data"]["protocol"]["headline_grade"] = "F"
    write_json(before, other_relative, before_other)
    write_json(after, other_relative, after_other)

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    rendered = json.dumps(report)
    assert target_token not in rendered
    assert other_token not in rendered
    assert "unpublished/<review>/index.json" in report["unrelated_changed_files"]


def test_unpublished_slug_prefix_collision_is_unrelated(tmp_path) -> None:
    token = "prefix-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    relative = f"unpublished/fixture-family-extra-{token}/index.json"
    write_json(
        before,
        relative,
        {
            "data": {
                "protocol_data": {
                    "protocol": {"slug": "fixture-family-extra", "headline_grade": "B"}
                }
            }
        },
    )
    write_json(
        after,
        relative,
        {
            "data": {
                "protocol_data": {
                    "protocol": {"slug": "fixture-family-extra", "headline_grade": "F"}
                }
            }
        },
    )

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert token not in json.dumps(report)


def test_publication_location_change_is_not_isolated(tmp_path) -> None:
    token = "new-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="A", generated_at="same")
    move_target_to_unpublished(after, token)

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "target-publication-location" in report["unrelated_changed_files"]
    assert token not in json.dumps(report)


def test_duplicate_target_outputs_are_rejected_without_token_disclosure(tmp_path) -> None:
    token = "duplicate-secret-token"
    api_fixture(tmp_path, target_grade="B", generated_at="same")
    published = json.loads(
        (tmp_path / "protocols/fixture-family.json").read_text(encoding="utf-8")
    )
    write_json(tmp_path, f"unpublished/fixture-family-{token}/index.json", published)

    with pytest.raises(ContractError, match="exactly one") as exc_info:
        resolve_protocol_output(tmp_path, "fixture-family")

    assert token not in str(exc_info.value)


def test_malformed_unpublished_output_error_redacts_token(tmp_path) -> None:
    token = "malformed-secret-token"
    api_fixture(tmp_path, target_grade="B", generated_at="same")
    malformed = tmp_path / "unpublished" / f"other-family-{token}" / "index.json"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text("{", encoding="utf-8")

    with pytest.raises(ContractError, match=r"unpublished/<review>/index.json") as exc_info:
        resolve_protocol_output(tmp_path, "fixture-family")

    assert token not in str(exc_info.value)


@pytest.mark.parametrize(
    "unexpected_relative",
    [
        "unpublished/fixture-family-secret-token/unexpected.json",
        "protocols/fixture-family/unexpected.json",
    ],
)
def test_unexpected_nested_target_file_change_is_unrelated(
    tmp_path,
    unexpected_relative: str,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    if unexpected_relative.startswith("unpublished/"):
        move_target_to_unpublished(before, "secret-token")
        move_target_to_unpublished(after, "secret-token")
    write_json(before, unexpected_relative, {"data": {"value": "before"}})
    write_json(after, unexpected_relative, {"data": {"value": "after"}})

    report = verify_output_isolation(before, after, "fixture-family")

    assert report["isolated"] is False
    assert "secret-token" not in json.dumps(report)


def test_target_history_with_wrong_identity_is_rejected(tmp_path) -> None:
    token = "history-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    api_fixture(before, target_grade="B", generated_at="same")
    api_fixture(after, target_grade="B", generated_at="same")
    before_target = move_target_to_unpublished(before, token)
    after_target = move_target_to_unpublished(after, token)
    write_json(
        before_target,
        "history.json",
        {"data": {"protocol_slug": "other-family", "series": []}},
    )
    write_json(
        after_target,
        "history.json",
        {"data": {"protocol_slug": "other-family", "series": []}},
    )

    with pytest.raises(ContractError, match="target history") as exc_info:
        verify_output_isolation(before, after, "fixture-family")

    assert token not in str(exc_info.value)


def test_duplicate_published_target_outputs_are_rejected(tmp_path) -> None:
    api_fixture(tmp_path, target_grade="B", generated_at="same")
    published = json.loads(
        (tmp_path / "protocols/fixture-family.json").read_text(encoding="utf-8")
    )
    write_json(tmp_path, "protocols/alias-copy.json", published)

    with pytest.raises(ContractError, match="found 2"):
        resolve_protocol_output(tmp_path, "fixture-family")


def test_mislocated_published_target_output_is_rejected(tmp_path) -> None:
    api_fixture(tmp_path, target_grade="B", generated_at="same")
    canonical = tmp_path / "protocols/fixture-family.json"
    mislocated = tmp_path / "protocols/alias-copy.json"
    canonical.replace(mislocated)

    with pytest.raises(ContractError, match="canonical published path"):
        resolve_protocol_output(tmp_path, "fixture-family")
