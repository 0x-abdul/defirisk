#!/usr/bin/env python3
"""Export an approved internal refresh as a non-authorizing public JSON handoff."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

from protocol_refresh_public.contracts import (
    ContractError,
    build_public_handoff,
    canonical_sha256,
    load_json_strict,
    verify_public_handoff,
    write_json,
)
from protocol_refresh_apply.db import normalize_snapshot
from protocol_refresh_public.compensation import verify_compensation_proof


def _result_row(value: object, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    grade = value.get("headline_grade")
    risk = value.get("risk_score")
    if grade not in {"A", "B", "C", "D", "F"}:
        raise ContractError(f"{label}.headline_grade is invalid")
    if isinstance(risk, bool) or not isinstance(risk, (int, float)):
        raise ContractError(f"{label}.risk_score is invalid")
    cap = value.get("cap_applied")
    if cap not in {None, "none", False, "cap", True}:
        raise ContractError(f"{label}.cap_applied is invalid")
    return {
        "headline_grade": grade,
        "risk_score": f"{risk:.2f}",
        "cap_state": "none" if cap in {None, "none", False} else "cap",
    }


def _expected_result_from_local_after(accepted: dict, snapshot: dict) -> dict:
    """Derive a public verification assertion from the record's local receipt.

    This supports pre-assertion internal records without weakening the public
    payload contract: the raw source bytes remain checksum-bound through
    ``source_approval`` and every asserted result must come from the matching
    verified local-after snapshot.
    """
    family = accepted.get("family_slug")
    surfaces = accepted.get("surface_slugs")
    if snapshot.get("family_slug") != family or not isinstance(surfaces, list):
        raise ContractError("local-after snapshot identity does not match accepted changes")
    family_rows = snapshot.get("families")
    if not isinstance(family_rows, list):
        raise ContractError("local-after snapshot has no family result")
    matching_family = [row for row in family_rows if isinstance(row, dict) and row.get("family_slug") == family]
    if len(matching_family) != 1:
        raise ContractError("local-after snapshot must contain exactly one matching family result")
    surface_rows = snapshot.get("surfaces")
    if not isinstance(surface_rows, list):
        raise ContractError("local-after snapshot has no surface results")
    by_surface = {
        row.get("surface_slug"): row
        for row in surface_rows
        if isinstance(row, dict) and isinstance(row.get("surface_slug"), str)
    }
    if set(by_surface) != set(surfaces) or len(by_surface) != len(surface_rows):
        raise ContractError("local-after snapshot surface results do not exactly match accepted scope")
    scores = snapshot.get("current_factor_scores")
    if not isinstance(scores, list):
        raise ContractError("local-after snapshot has no current factor scores")
    active_ids: set[str] = set()
    for index, score in enumerate(scores):
        if not isinstance(score, dict) or score.get("rubric_version") != accepted.get("rubric_version") or score.get("is_current") is not True:
            raise ContractError(f"local-after snapshot factor score {index} is not an active-rubric current row")
        score_id = score.get("id")
        if not isinstance(score_id, str) or not score_id or score_id in active_ids:
            raise ContractError("local-after snapshot factor score IDs must be unique")
        active_ids.add(score_id)
    return {
        **_result_row(matching_family[0], label="local-after family result"),
        "active_factor_count": len(active_ids),
        "surface_results": {
            slug: _result_row(by_surface[slug], label=f"local-after surface result {slug}")
            for slug in sorted(by_surface)
        },
    }


def _enrich_current_factor_baseline(accepted: dict, accepted_path: Path) -> dict:
    """Bind the retained factor state without exposing local research rows."""
    baseline = accepted.get("baseline")
    if not isinstance(baseline, dict):
        raise ContractError("accepted changes baseline must be an object")
    existing = baseline.get("current_factor_scores_sha256")
    if existing is not None:
        if not isinstance(existing, str) or len(existing) != 64:
            raise ContractError("accepted changes current-factor baseline fingerprint is invalid")
        return accepted
    before = load_json_strict(accepted_path.parent / "local-db-before.json")
    if before.get("family_slug") != accepted.get("family_slug") or before.get("target") is not True:
        raise ContractError("local-before snapshot identity does not match accepted changes")
    if canonical_sha256(before) != baseline.get("target_sha256"):
        raise ContractError("local-before snapshot does not match the sealed accepted baseline")
    normalized = normalize_snapshot(before)
    factors = normalized.get("current_factor_scores")
    if not isinstance(factors, list) or not factors:
        raise ContractError("local-before snapshot has no current factor scores")
    result = deepcopy(accepted)
    result["baseline"]["current_factor_scores_sha256"] = canonical_sha256(factors)
    return result


def _enriched_accepted(accepted_path: Path) -> tuple[dict, dict]:
    accepted = load_json_strict(accepted_path)
    source_accepted = accepted
    accepted = _enrich_current_factor_baseline(accepted, accepted_path)
    if "expected_result" not in accepted:
        local_after = load_json_strict(accepted_path.parent / "local-db-after.json")
        accepted = deepcopy(accepted)
        accepted["expected_result"] = _expected_result_from_local_after(
            accepted, local_after
        )
    return accepted, source_accepted


def _verify_prior_reissue_lineage(
    *,
    prior: dict,
    original: dict,
) -> None:
    """Require an immediate prior handoff to retain the sealed source payload.

    A failed post-commit attempt consumes its own idempotency key.  Chained
    reissues are allowed only when every public payload field other than the
    refresh identifier remains exactly equal to the immutable approved source.
    """
    if prior.get("family_slug") != original.get("family_slug"):
        raise ContractError("prior handoff family_slug does not match the approved source")
    if prior.get("surface_slugs") != original.get("surface_slugs"):
        raise ContractError("prior handoff surface scope does not match the approved source")
    prior_source = prior.get("source_approval")
    original_source = original.get("source_approval")
    if not isinstance(prior_source, dict) or not isinstance(original_source, dict):
        raise ContractError("prior handoff source approval is invalid")
    for name in ("approval_state", "accepted_changes_sha256", "status_sha256"):
        if prior_source.get(name) != original_source.get(name):
            raise ContractError("prior handoff source approval does not match the approved source")
    expected_payload = deepcopy(original["payload"])
    expected_payload["refresh_id"] = prior["refresh_id"]
    legacy_expected_payload = deepcopy(expected_payload)
    legacy_expected_payload["baseline"].pop("current_factor_scores_sha256", None)
    if (
        prior.get("payload") != expected_payload
        and prior.get("payload") != legacy_expected_payload
    ):
        raise ContractError("prior handoff payload drifted from the approved source")


def export_handoff(
    accepted_path: Path,
    status_path: Path,
    output_path: Path,
    *,
    reissue_refresh_id: str | None = None,
    prior_handoff_path: Path | None = None,
    compensation_proof_path: Path | None = None,
    correction_record_paths: list[Path] | None = None,
) -> dict:
    if output_path.suffix.casefold() != ".json":
        raise ContractError("public handoff output must be a .json file")
    status = load_json_strict(status_path)
    accepted, source_accepted = _enriched_accepted(accepted_path)
    corrections: list[tuple[dict, dict]] = []
    for record_path in correction_record_paths or []:
        correction_accepted_path = record_path / "accepted-changes.json"
        correction_status_path = record_path / "status.json"
        if not correction_accepted_path.is_file() or not correction_status_path.is_file():
            raise ContractError("correction record must contain accepted-changes.json and status.json")
        corrections.append(
            (
                load_json_strict(correction_accepted_path),
                load_json_strict(correction_status_path),
            )
        )
    reissue_values = (reissue_refresh_id, prior_handoff_path, compensation_proof_path)
    if any(value is not None for value in reissue_values) and not all(
        value is not None for value in reissue_values
    ):
        raise ContractError(
            "reissue requires reissue_refresh_id, prior_handoff_path, and compensation_proof_path"
        )
    if reissue_refresh_id is not None and output_path.exists():
        raise ContractError(f"refusing to overwrite reissue handoff: {output_path}")
    if reissue_refresh_id is None:
        handoff = build_public_handoff(
            accepted, status, source_document=source_accepted, corrections=corrections
        )
    else:
        prior = load_json_strict(prior_handoff_path)
        prior_errors = verify_public_handoff(prior)
        if prior_errors:
            raise ContractError("prior handoff is invalid: " + "; ".join(prior_errors))
        proof = verify_compensation_proof(load_json_strict(compensation_proof_path))
        original = build_public_handoff(
            accepted, status, source_document=source_accepted, corrections=corrections
        )
        _verify_prior_reissue_lineage(prior=prior, original=original)
        if proof["prior_refresh_id"] != prior["refresh_id"]:
            raise ContractError("compensation proof prior_refresh_id does not match prior handoff")
        if proof["family_slug"] != prior["family_slug"]:
            raise ContractError("compensation proof family_slug does not match prior handoff")
        if proof["prior_artifact_sha256"] != prior["integrity"]["artifact_sha256"]:
            raise ContractError("compensation proof artifact hash does not match prior handoff")
        reissued = deepcopy(accepted)
        reissued["refresh_id"] = reissue_refresh_id
        handoff = build_public_handoff(
            reissued,
            status,
            source_document=source_accepted,
            reissue={
                "reason": "compensated_production_attempt",
                "prior_refresh_id": prior["refresh_id"],
                "prior_artifact_sha256": prior["integrity"]["artifact_sha256"],
                "compensation_proof_sha256": proof["integrity"]["proof_sha256"],
            },
            corrections=corrections,
        )
    write_json(output_path, handoff)
    return handoff


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "refresh_dir",
        nargs="?",
        type=Path,
        help="directory containing accepted-changes.json and status.json",
    )
    parser.add_argument("--accepted-changes", type=Path)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reissue-refresh-id")
    parser.add_argument("--prior-handoff", type=Path)
    parser.add_argument("--compensation-proof", type=Path)
    parser.add_argument(
        "--correction-record",
        action="append",
        type=Path,
        default=[],
        help="separately approved factor-only correction record to bind into the public handoff",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    accepted = args.accepted_changes
    status = args.status
    if args.refresh_dir is not None:
        accepted = accepted or args.refresh_dir / "accepted-changes.json"
        status = status or args.refresh_dir / "status.json"
    if accepted is None or status is None:
        print(
            json.dumps({"ok": False, "errors": ["provide refresh_dir or both input paths"]}),
            file=sys.stderr,
        )
        return 2
    try:
        handoff = export_handoff(
            accepted,
            status,
            args.output,
            reissue_refresh_id=args.reissue_refresh_id,
            prior_handoff_path=args.prior_handoff,
            compensation_proof_path=args.compensation_proof,
            correction_record_paths=args.correction_record,
        )
    except ContractError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output),
                "artifact_sha256": handoff["integrity"]["artifact_sha256"],
                "production_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
