#!/usr/bin/env python3
"""Plan or explicitly apply the refresh-owned database migrations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from protocol_refresh_apply.contracts import ContractError
from protocol_refresh_migrations import (
    REPO_ROOT,
    apply_pending_migrations,
    connected_database_identity,
    inspect_migrations,
    plan_document,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", help="Postgres URL; otherwise DATABASE_URL/LOCAL_DATABASE_URL")
    parser.add_argument("--expected-database", required=True, help="Exact connected database name")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Read-only migration plan")
    mode.add_argument("--apply", action="store_true", help="Apply the exact authorized plan")
    parser.add_argument("--plan-out", type=Path, help="Optional new JSON path for the plan")
    parser.add_argument("--backup-receipt", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--receipt-out", type=Path)
    return parser.parse_args(argv)


def _write_new(path: Path, value: dict) -> None:
    if path.exists():
        raise ContractError(f"refusing to overwrite receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_url = args.db_url or os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not db_url:
        print("migration operation failed: database URL is required", file=sys.stderr)
        return 1
    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                database = cur.fetchone()[0]
            if database != args.expected_database:
                raise ContractError(
                    f"database name mismatch: {database!r} != {args.expected_database!r}"
                )
            if args.plan:
                result = plan_document(
                    connected_database_identity(conn),
                    inspect_migrations(conn, REPO_ROOT),
                )
                conn.rollback()
                if args.plan_out:
                    _write_new(args.plan_out, result)
            else:
                if not args.backup_receipt or not args.authorization or not args.receipt_out:
                    raise ContractError(
                        "--apply requires --backup-receipt, --authorization, and --receipt-out"
                    )
                result = apply_pending_migrations(
                    conn,
                    repo_root=REPO_ROOT,
                    expected_database=args.expected_database,
                    backup_receipt_path=args.backup_receipt,
                    authorization_path=args.authorization,
                )
                _write_new(args.receipt_out, result)
    except (ContractError, OSError, ValueError) as exc:
        print(f"migration operation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
