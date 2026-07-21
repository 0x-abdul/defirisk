#!/usr/bin/env python3
"""Export a public-safe proof for one compensated failed refresh attempt.

This command is deliberately read-only.  It verifies the failed pipeline audit
and matching compensation audit in production, then writes a minimal proof
without database locations, run IDs, exception text, backup paths, or local
research material.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from protocol_refresh_public.compensation import build_compensation_proof
from protocol_refresh_public.contracts import ContractError, load_json_strict, verify_public_handoff


SCRIPT_NAME = "apply-protocol-refresh.py"


def _read_json_object(value: object, label: str) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a JSON object")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ContractError(f"{label} must be a JSON object")
    return parsed


def _write_new_json(path: Path, value: dict) -> None:
    if path.suffix.casefold() != ".json":
        raise ContractError("compensation proof output must be a .json file")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ContractError(f"refusing to overwrite compensation proof: {path}") from exc


def export_compensation_proof(*, db_url: str, prior_handoff_path: Path, output_path: Path) -> dict:
    prior = load_json_strict(prior_handoff_path)
    errors = verify_public_handoff(prior)
    if errors:
        raise ContractError("prior handoff is invalid: " + "; ".join(errors))
    refresh_id = prior["refresh_id"]
    family_slug = prior["family_slug"]
    artifact_sha256 = prior["integrity"]["artifact_sha256"]
    try:
        import psycopg
    except ImportError as exc:
        raise ContractError("psycopg v3 is required to export a compensation proof") from exc
    try:
        conn = psycopg.connect(db_url, connect_timeout=10, options="-c default_transaction_read_only=on")
    except Exception as exc:  # driver diagnostics are intentionally not exported
        raise ContractError(f"cannot open read-only compensation-proof connection: {exc.__class__.__name__}") from exc
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                """
                SELECT success_count, error_count, notes
                FROM pipeline_runs
                WHERE script_name = %s AND triggered_by = %s
                """,
                (SCRIPT_NAME, f"protocol-refresh:{refresh_id}"),
            )
            pipeline_rows = cur.fetchall()
            if len(pipeline_rows) != 1:
                raise ContractError("expected exactly one failed refresh pipeline audit row")
            success_count, error_count, notes = pipeline_rows[0]
            if success_count != 0 or error_count != 1:
                raise ContractError("refresh pipeline audit is not a failed, uncompleted attempt")
            note = _read_json_object(notes, "refresh pipeline notes")
            if note.get("family_slug") != family_slug or note.get("artifact_sha256") != artifact_sha256:
                raise ContractError("refresh pipeline audit does not match the prior handoff")
            cur.execute(
                """
                SELECT diff
                FROM change_log
                WHERE changed_by = %s
                  AND entity_type = 'protocol_refresh_compensation'
                  AND entity_id = %s
                  AND diff ->> 'refresh_id' = %s
                  AND diff ->> 'artifact_sha256' = %s
                """,
                (SCRIPT_NAME, family_slug, refresh_id, artifact_sha256),
            )
            compensation_rows = cur.fetchall()
            if len(compensation_rows) != 1:
                raise ContractError("expected exactly one matching compensation audit row")
            diff = _read_json_object(compensation_rows[0][0], "compensation audit diff")
            if diff.get("refresh_id") != refresh_id or diff.get("artifact_sha256") != artifact_sha256:
                raise ContractError("compensation audit does not match the prior handoff")
            restored_target_sha256 = diff.get("restored_target_sha256")
            proof = build_compensation_proof(
                prior_refresh_id=refresh_id,
                family_slug=family_slug,
                prior_artifact_sha256=artifact_sha256,
                restored_target_sha256=restored_target_sha256,
            )
        conn.rollback()
    finally:
        conn.close()
    _write_new_json(output_path, proof)
    return proof


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-handoff", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--db-url", help="PostgreSQL URL; otherwise DATABASE_URL is used")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print(json.dumps({"ok": False, "errors": ["--db-url or DATABASE_URL is required"]}), file=sys.stderr)
        return 2
    try:
        proof = export_compensation_proof(
            db_url=db_url,
            prior_handoff_path=args.prior_handoff,
            output_path=args.output,
        )
    except ContractError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "proof_sha256": proof["integrity"]["proof_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
