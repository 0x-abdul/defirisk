#!/usr/bin/env python3
"""Fail when runtime tables or managed grants drift from repository policy."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "db" / "runtime-role-policy.json"


def validate_policy(policy: dict[str, Any], tables: set[str], grants: dict[str, set[str]]) -> list[str]:
    errors: list[str] = []
    known = policy.get("known_public_tables")
    managed = policy.get("managed_table_privileges")
    role = policy.get("runtime_role")
    if policy.get("schema_version") != "1.0" or not isinstance(role, str) or not role:
        return ["runtime role policy identity is invalid"]
    if not isinstance(known, list) or sorted(set(known)) != known:
        errors.append("known_public_tables must be a sorted unique array")
        known_set: set[str] = set()
    else:
        known_set = set(known)
    if known_set != tables:
        errors.append(
            f"public table classification drift: added={sorted(tables-known_set)}, "
            f"removed={sorted(known_set-tables)}"
        )
    if not isinstance(managed, dict):
        return errors + ["managed_table_privileges must be an object"]
    for table, expected in managed.items():
        if table not in known_set or not isinstance(expected, list):
            errors.append(f"invalid managed privilege declaration for {table}")
            continue
        actual = grants.get(table, set())
        if set(expected) != actual:
            errors.append(
                f"runtime grants for {table} differ: expected={sorted(expected)}, actual={sorted(actual)}"
            )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", help="Postgres URL; otherwise DATABASE_URL/LOCAL_DATABASE_URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_url = args.db_url or os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not db_url:
        print("runtime grant verification failed: database URL is required", file=sys.stderr)
        return 1
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT table_name FROM information_schema.tables
                       WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"""
                )
                tables = {row[0] for row in cur.fetchall()}
                cur.execute(
                    """SELECT table_name, privilege_type
                       FROM information_schema.role_table_grants
                       WHERE grantee = %s AND table_schema = 'public'""",
                    (policy["runtime_role"],),
                )
                grants: dict[str, set[str]] = {}
                for table, privilege in cur.fetchall():
                    grants.setdefault(table, set()).add(privilege)
            conn.rollback()
    except (OSError, ValueError) as exc:
        print(f"runtime grant verification failed: {exc}", file=sys.stderr)
        return 1
    errors = validate_policy(policy, tables, grants)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"runtime grant policy OK for {len(tables)} public tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
