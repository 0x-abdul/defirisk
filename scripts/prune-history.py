#!/usr/bin/env python3
"""Apply retention pruning to daily grade and factor snapshot history."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - CLI dependency guard
    psycopg = None
    dict_row = None

SCRIPT_NAME = "prune-history.py"


def get_connection_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not url:
        print(
            "ERROR: Set DATABASE_URL or LOCAL_DATABASE_URL before running.",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def connect(url: str) -> Any:
    if psycopg is None:
        print("ERROR: psycopg v3 is not installed. Run: pip install 'psycopg[binary]'")
        sys.exit(1)
    try:
        return psycopg.connect(url, connect_timeout=10)
    except psycopg.Error as exc:
        print(f"ERROR: Cannot connect to database: {exc}", file=sys.stderr)
        sys.exit(1)


def create_pipeline_run(cur: Any) -> Any | None:
    try:
        cur.execute(
            """
            INSERT INTO pipeline_runs
                (script_name, cadence_bucket, protocols_touched,
                 fetchers_invoked, success_count, error_count, triggered_by)
            VALUES (%s, 'S', 0, '[]'::jsonb, 0, 0, %s)
            RETURNING id
            """,
            (SCRIPT_NAME, SCRIPT_NAME),
        )
        return cur.fetchone()["id"]
    except Exception:
        return None


def update_pipeline_run(
    cur: Any,
    run_id: Any | None,
    *,
    deleted_protocol_rows: int,
    deleted_factor_rows: int,
    duration_seconds: int,
) -> None:
    if run_id is None:
        return
    deleted_total = deleted_protocol_rows + deleted_factor_rows
    try:
        cur.execute(
            """
            UPDATE pipeline_runs
            SET protocols_touched = 0,
                success_count = %s,
                error_count = 0,
                duration_seconds = %s,
                notes = %s
            WHERE id = %s
            """,
            (
                deleted_total,
                duration_seconds,
                json.dumps(
                    {
                        "deleted_protocol_grade_history": deleted_protocol_rows,
                        "deleted_factor_score_history": deleted_factor_rows,
                    },
                    sort_keys=True,
                ),
                run_id,
            ),
        )
    except Exception:
        pass


def count_protocol_rows_to_prune(cur: Any) -> int:
    cur.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY protocol_slug, date_trunc('month', snapshot_date)
                       ORDER BY snapshot_date ASC, snapshot_at ASC
                   ) AS rn
            FROM protocol_grade_history
            WHERE snapshot_date < CURRENT_DATE - INTERVAL '365 days'
        ),
        keepers AS (
            SELECT id AS keep_id FROM ranked WHERE rn = 1
        )
        SELECT COUNT(*) AS count
        FROM protocol_grade_history pgh
        WHERE pgh.snapshot_date < CURRENT_DATE - INTERVAL '365 days'
          AND pgh.id NOT IN (SELECT keep_id FROM keepers)
        """
    )
    return int(cur.fetchone()["count"])


def count_factor_rows_to_prune(cur: Any) -> int:
    cur.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY protocol_slug, factor_id,
                                    date_trunc('month', snapshot_date)
                       ORDER BY snapshot_date ASC, snapshot_at ASC
                   ) AS rn
            FROM factor_score_history
            WHERE snapshot_date < CURRENT_DATE - INTERVAL '365 days'
        ),
        keepers AS (
            SELECT id AS keep_id FROM ranked WHERE rn = 1
        )
        SELECT COUNT(*) AS count
        FROM factor_score_history fsh
        WHERE fsh.snapshot_date < CURRENT_DATE - INTERVAL '365 days'
          AND fsh.id NOT IN (SELECT keep_id FROM keepers)
        """
    )
    return int(cur.fetchone()["count"])


def prune_protocol_rows(cur: Any) -> int:
    cur.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY protocol_slug, date_trunc('month', snapshot_date)
                       ORDER BY snapshot_date ASC, snapshot_at ASC
                   ) AS rn
            FROM protocol_grade_history
            WHERE snapshot_date < CURRENT_DATE - INTERVAL '365 days'
        ),
        keepers AS (
            SELECT id AS keep_id FROM ranked WHERE rn = 1
        ),
        deleted AS (
            DELETE FROM protocol_grade_history pgh
            WHERE pgh.snapshot_date < CURRENT_DATE - INTERVAL '365 days'
              AND pgh.id NOT IN (SELECT keep_id FROM keepers)
            RETURNING 1
        )
        SELECT COUNT(*) AS count FROM deleted
        """
    )
    return int(cur.fetchone()["count"])


def prune_factor_rows(cur: Any) -> int:
    cur.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY protocol_slug, factor_id,
                                    date_trunc('month', snapshot_date)
                       ORDER BY snapshot_date ASC, snapshot_at ASC
                   ) AS rn
            FROM factor_score_history
            WHERE snapshot_date < CURRENT_DATE - INTERVAL '365 days'
        ),
        keepers AS (
            SELECT id AS keep_id FROM ranked WHERE rn = 1
        ),
        deleted AS (
            DELETE FROM factor_score_history fsh
            WHERE fsh.snapshot_date < CURRENT_DATE - INTERVAL '365 days'
              AND fsh.id NOT IN (SELECT keep_id FROM keepers)
            RETURNING 1
        )
        SELECT COUNT(*) AS count FROM deleted
        """
    )
    return int(cur.fetchone()["count"])


def run(conn_str: str, *, dry_run: bool) -> int:
    started = time.monotonic()
    conn = connect(conn_str)
    with conn:
        with conn.cursor(row_factory=dict_row) as cur:
            run_id = None if dry_run else create_pipeline_run(cur)
            if dry_run:
                deleted_protocol = count_protocol_rows_to_prune(cur)
                deleted_factor = count_factor_rows_to_prune(cur)
            else:
                deleted_protocol = prune_protocol_rows(cur)
                deleted_factor = prune_factor_rows(cur)
                update_pipeline_run(
                    cur,
                    run_id,
                    deleted_protocol_rows=deleted_protocol,
                    deleted_factor_rows=deleted_factor,
                    duration_seconds=int(time.monotonic() - started),
                )

    conn.close()
    suffix = " (dry-run)" if dry_run else ""
    print(
        "Done: "
        f"{deleted_protocol} protocol_grade_history row(s), "
        f"{deleted_factor} factor_score_history row(s) pruned{suffix}."
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune old snapshot history rows")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deletes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(get_connection_url(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
