#!/usr/bin/env python3
"""Detect daily grade transitions and populate grade_changes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - CLI dependency guard
    psycopg = None
    dict_row = None

SCRIPT_NAME = "detect-grade-changes.py"
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}


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


def is_upgrade(from_grade: str, to_grade: str) -> bool:
    return GRADE_ORDER.get(to_grade, 99) < GRADE_ORDER.get(from_grade, 99)


def create_pipeline_run(cur: Any) -> Any | None:
    try:
        cur.execute(
            """
            INSERT INTO pipeline_runs
                (script_name, cadence_bucket, protocols_touched,
                 fetchers_invoked, success_count, error_count, triggered_by)
            VALUES (%s, 'C', 0, '[]'::jsonb, 0, 0, %s)
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
    changes_inserted: int,
    duration_seconds: int,
) -> None:
    if run_id is None:
        return
    try:
        cur.execute(
            """
            UPDATE pipeline_runs
            SET protocols_touched = %s,
                success_count = %s,
                error_count = 0,
                duration_seconds = %s,
                notes = %s
            WHERE id = %s
            """,
            (
                changes_inserted,
                changes_inserted,
                duration_seconds,
                json.dumps({"grade_changes_inserted": changes_inserted}),
                run_id,
            ),
        )
    except Exception:
        pass


def default_snapshot_date() -> str:
    """Return the UTC date used by compose.py snapshot rows."""
    return datetime.now(tz=timezone.utc).date().isoformat()


def find_grade_changes(
    cur: Any,
    *,
    snapshot_date: str | None,
    backfill: bool,
) -> list[dict[str, Any]]:
    date_filter = ""
    params: tuple[str, ...] | None = None
    if not backfill:
        date_filter = "AND snapshot_date = %s"
        params = (snapshot_date or default_snapshot_date(),)

    cur.execute(
        f"""
        WITH ordered AS (
            SELECT
                pgh.*,
                LAG(grade_letter) OVER w AS previous_grade,
                LAG(snapshot_date) OVER w AS previous_snapshot_date
            FROM protocol_grade_history pgh
            WINDOW w AS (
                PARTITION BY protocol_slug
                ORDER BY snapshot_date ASC, snapshot_at ASC
            )
        )
        SELECT
            protocol_slug,
            previous_grade AS from_grade,
            grade_letter AS to_grade,
            rubric_version,
            previous_snapshot_date AS snapshot_date_before,
            snapshot_date AS snapshot_date_after,
            source_run_id
        FROM ordered
        WHERE previous_grade IS NOT NULL
          AND previous_grade <> grade_letter
          {date_filter}
        ORDER BY snapshot_date_after ASC, protocol_slug ASC
        """,
        params,
    )
    return cur.fetchall()


def insert_grade_changes(cur: Any, rows: list[dict[str, Any]], dry_run: bool) -> int:
    inserted = 0
    for row in rows:
        reason = (
            f"Grade changed from {row['from_grade']} to {row['to_grade']} "
            f"between {row['snapshot_date_before']} and {row['snapshot_date_after']}."
        )
        if dry_run:
            print(f"[dry-run] {row['protocol_slug']}: {reason}")
            inserted += 1
            continue
        cur.execute(
            """
            INSERT INTO grade_changes
                (protocol_slug, from_grade, to_grade, rubric_version,
                 snapshot_date_before, snapshot_date_after, reason,
                 is_upgrade, source_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (protocol_slug, snapshot_date_before, snapshot_date_after)
            DO NOTHING
            RETURNING id
            """,
            (
                row["protocol_slug"],
                row["from_grade"],
                row["to_grade"],
                row["rubric_version"],
                row["snapshot_date_before"],
                row["snapshot_date_after"],
                reason,
                is_upgrade(row["from_grade"], row["to_grade"]),
                row["source_run_id"],
            ),
        )
        if cur.fetchone() is not None:
            inserted += 1
    return inserted


def run(
    conn_str: str,
    *,
    dry_run: bool,
    snapshot_date: str | None,
    backfill: bool,
) -> int:
    started = time.monotonic()
    conn = connect(conn_str)
    with conn:
        with conn.cursor(row_factory=dict_row) as cur:
            run_id = None if dry_run else create_pipeline_run(cur)
            rows = find_grade_changes(
                cur,
                snapshot_date=snapshot_date,
                backfill=backfill,
            )
            inserted = insert_grade_changes(cur, rows, dry_run)
            if not dry_run:
                update_pipeline_run(
                    cur,
                    run_id,
                    changes_inserted=inserted,
                    duration_seconds=int(time.monotonic() - started),
                )

    conn.close()
    suffix = " (dry-run)" if dry_run else ""
    print(f"Done: {inserted} grade change(s) detected{suffix}.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect protocol grade changes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writes")
    parser.add_argument(
        "--snapshot-date",
        default=default_snapshot_date(),
        help=(
            "Only detect transitions whose new snapshot has this UTC date "
            "(default: today). Ignored with --backfill."
        ),
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Scan all historical snapshots instead of only today's new snapshots.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(
        get_connection_url(),
        dry_run=args.dry_run,
        snapshot_date=args.snapshot_date,
        backfill=args.backfill,
    )


if __name__ == "__main__":
    raise SystemExit(main())
