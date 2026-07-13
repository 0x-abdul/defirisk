from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_apply.contracts import ContractError
from protocol_refresh_apply.runners import CommandResult, make_semantic_verifier


RUBRIC_VERSION = "v1.7.0"
FAMILY_SLUG = "fixture-family"
SURFACE_SLUG = "default"


def write_protocol_output(
    out_root: Path,
    *,
    last_refreshed: str,
    grade: str,
    token: str | None = None,
    family_slug: str = FAMILY_SLUG,
) -> None:
    api_root = out_root / "api" / RUBRIC_VERSION
    if token is None:
        target = api_root / "protocols" / f"{FAMILY_SLUG}.json"
    else:
        target = api_root / "unpublished" / f"{FAMILY_SLUG}-{token}" / "index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "data": {
                    "protocol_data": {
                        "protocol": {
                            "slug": family_slug,
                            "last_refreshed": last_refreshed,
                            "headline_grade": grade,
                        },
                        "surfaces": [{"surface_slug": SURFACE_SLUG}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def result(out_root: Path) -> CommandResult:
    return CommandResult(0, "", "", out_root)


def verifier():
    return make_semantic_verifier(
        rubric_version=RUBRIC_VERSION,
        expected_surfaces=(SURFACE_SLUG,),
        effective_refresh_date="2026-07-13",
    )


@pytest.mark.parametrize("token", [None, "same-secret-token"])
def test_semantic_verifier_supports_published_and_unpublished_targets(
    tmp_path: Path,
    token: str | None,
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_protocol_output(before, last_refreshed="2026-05-01", grade="B", token=token)
    write_protocol_output(after, last_refreshed="2026-07-13", grade="A", token=token)

    assert verifier()(
        db_url="postgresql://db.example/risk",
        family_slug=FAMILY_SLUG,
        before_dump_result=result(before),
        dump_result=result(after),
    )


def test_semantic_verifier_rejects_review_token_rotation_without_disclosure(
    tmp_path: Path,
) -> None:
    before_token = "before-secret-token"
    after_token = "after-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_protocol_output(
        before,
        last_refreshed="2026-05-01",
        grade="B",
        token=before_token,
    )
    write_protocol_output(
        after,
        last_refreshed="2026-07-13",
        grade="A",
        token=after_token,
    )

    with pytest.raises(ContractError, match="publication location") as exc_info:
        verifier()(
            db_url="postgresql://db.example/risk",
            family_slug=FAMILY_SLUG,
            before_dump_result=result(before),
            dump_result=result(after),
        )

    rendered = str(exc_info.value)
    assert before_token not in rendered
    assert after_token not in rendered


def test_semantic_verifier_rejects_wrong_target_identity(tmp_path: Path) -> None:
    token = "identity-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_protocol_output(
        before,
        last_refreshed="2026-05-01",
        grade="B",
        token=token,
        family_slug="other-family",
    )
    write_protocol_output(
        after,
        last_refreshed="2026-07-13",
        grade="A",
        token=token,
        family_slug="other-family",
    )

    with pytest.raises(ContractError, match="found 0") as exc_info:
        verifier()(
            db_url="postgresql://db.example/risk",
            family_slug=FAMILY_SLUG,
            before_dump_result=result(before),
            dump_result=result(after),
        )

    assert token not in str(exc_info.value)


def test_semantic_verifier_rejects_duplicate_target_identity(tmp_path: Path) -> None:
    token = "duplicate-secret-token"
    before = tmp_path / "before"
    after = tmp_path / "after"
    for root, refresh_date, grade in (
        (before, "2026-05-01", "B"),
        (after, "2026-07-13", "A"),
    ):
        write_protocol_output(root, last_refreshed=refresh_date, grade=grade)
        published = (
            root / "api" / RUBRIC_VERSION / "protocols" / f"{FAMILY_SLUG}.json"
        )
        unpublished = (
            root
            / "api"
            / RUBRIC_VERSION
            / "unpublished"
            / f"{FAMILY_SLUG}-{token}"
            / "index.json"
        )
        unpublished.parent.mkdir(parents=True, exist_ok=True)
        unpublished.write_text(published.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ContractError, match="found 2") as exc_info:
        verifier()(
            db_url="postgresql://db.example/risk",
            family_slug=FAMILY_SLUG,
            before_dump_result=result(before),
            dump_result=result(after),
        )

    assert token not in str(exc_info.value)
