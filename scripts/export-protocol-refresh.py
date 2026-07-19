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
    load_json_strict,
    write_json,
)


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


def export_handoff(accepted_path: Path, status_path: Path, output_path: Path) -> dict:
    if output_path.suffix.casefold() != ".json":
        raise ContractError("public handoff output must be a .json file")
    accepted = load_json_strict(accepted_path)
    status = load_json_strict(status_path)
    source_accepted = accepted
    if "expected_result" not in accepted:
        local_after = load_json_strict(accepted_path.parent / "local-db-after.json")
        accepted = deepcopy(accepted)
        accepted["expected_result"] = _expected_result_from_local_after(
            accepted, local_after
        )
    handoff = build_public_handoff(
        accepted, status, source_document=source_accepted
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
        handoff = export_handoff(accepted, status, args.output)
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
