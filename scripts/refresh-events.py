#!/usr/bin/env python3
"""Refresh episodic-cadence state derived from curated event tables."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - CLI dependency guard
    psycopg = None
    dict_row = None

SCRIPT_NAME = "refresh-events.py"


@dataclass(frozen=True)
class EventResult:
    slug: str
    status: str
    db_updates: int = 0
    error: str | None = None


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


class EventRepository:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def fetch_protocols(self, slug: str | None) -> list[dict[str, Any]]:
        where = "WHERE p.slug = %s" if slug else ""
        params = (slug,) if slug else ()
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    p.slug,
                    p.has_active_incident,
                    (
                        EXISTS (
                            SELECT 1
                            FROM active_incidents ai
                            WHERE ai.protocol_slug = p.slug
                              AND ai.status = 'open'
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM hacks h
                            WHERE h.protocol_slug = p.slug
                              AND (h.is_active = true OR h.status = 'open')
                        )
                    ) AS computed_has_active_incident
                FROM protocols p
                {where}
                ORDER BY p.slug
                """,
                params,
            )
            return cur.fetchall()

    def update_protocol_incident_flag(self, slug: str, has_active_incident: bool) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE protocols
                SET has_active_incident = %s, updated_at = now()
                WHERE slug = %s
                """,
                (has_active_incident, slug),
            )

    def create_pipeline_run(self, triggered_by: str) -> Any | None:
        try:
            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs
                        (script_name, cadence_bucket, protocols_touched,
                         fetchers_invoked, success_count, error_count, triggered_by)
                    VALUES (%s, 'E', 0, '[]'::jsonb, 0, 0, %s)
                    RETURNING id
                    """,
                    (SCRIPT_NAME, triggered_by),
                )
                return cur.fetchone()["id"]
        except Exception:
            return None

    def update_pipeline_run(
        self,
        run_id: Any | None,
        results: list[EventResult],
        duration_seconds: int,
    ) -> None:
        if run_id is None:
            return
        errors = [
            {"protocol": result.slug, "error": result.error}
            for result in results
            if result.error is not None
        ]
        notes = {
            "protocol_incident_flag_updates": sum(
                result.db_updates for result in results
            )
        }
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pipeline_runs
                SET protocols_touched = %s,
                    success_count = %s,
                    error_count = %s,
                    duration_seconds = %s,
                    error_summary = %s::jsonb,
                    notes = %s
                WHERE id = %s
                """,
                (
                    len(results),
                    sum(1 for result in results if result.error is None),
                    len(errors),
                    duration_seconds,
                    json.dumps(errors) if errors else None,
                    json.dumps(notes, sort_keys=True),
                    run_id,
                ),
            )


def refresh_protocol(
    repo: Any,
    row: dict[str, Any],
    *,
    dry_run: bool,
) -> EventResult:
    slug = str(row["slug"])
    current = bool(row["has_active_incident"])
    desired = bool(row["computed_has_active_incident"])
    if current == desired:
        return EventResult(slug=slug, status="unchanged")

    if not dry_run:
        repo.update_protocol_incident_flag(slug, desired)
    return EventResult(slug=slug, status="updated", db_updates=1)


def process_protocols(
    repo: Any,
    rows: list[dict[str, Any]],
    *,
    dry_run: bool,
    all_protocols: bool,
) -> list[EventResult]:
    results: list[EventResult] = []
    for row in rows:
        try:
            result = refresh_protocol(repo, row, dry_run=dry_run)
        except Exception as exc:
            result = EventResult(
                slug=str(row.get("slug", "<unknown>")),
                status="error",
                error=str(exc),
            )
            results.append(result)
            if not all_protocols:
                break
            continue
        results.append(result)
    return results


def _run_subprocess(args: list[str], *, dry_run: bool) -> int:
    cmd = [sys.executable, *args]
    printable = " ".join(str(part) for part in cmd)
    if dry_run:
        print(f"[dry-run] would run: {printable}")
        return 0
    print(f"Running: {printable}")
    return subprocess.run(cmd, check=False).returncode


def _post_refresh_steps(changed_slugs: list[str], *, dry_run: bool) -> int:
    if not changed_slugs:
        print("No event-derived DB updates were made; compose.py and dump.py are not needed.")
        return 0

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    for slug in changed_slugs:
        code = _run_subprocess(
            [os.path.join(scripts_dir, "compose.py"), "--protocol", slug],
            dry_run=dry_run,
        )
        if code != 0:
            return code

    detector = os.path.join(scripts_dir, "detect-grade-changes.py")
    if os.path.exists(detector):
        code = _run_subprocess([detector], dry_run=dry_run)
        if code != 0:
            return code

    return _run_subprocess([os.path.join(scripts_dir, "dump.py")], dry_run=dry_run)


def print_summary(results: list[EventResult]) -> None:
    failures = [result for result in results if result.error is not None]
    updates = [result for result in results if result.db_updates > 0]
    print("\nEvent refresh summary")
    print(f"  protocols processed : {len(results)}")
    print(f"  updated flags       : {len(updates)}")
    print(f"  failures            : {len(failures)}")
    if failures:
        print("\nFailures:")
        for result in failures:
            print(f"  {result.slug}: {result.error}")


def run(
    *,
    conn_str: str,
    all_protocols: bool,
    protocol_slug: str | None,
    dry_run: bool,
) -> int:
    started = time.monotonic()
    conn = connect(conn_str)
    results: list[EventResult] = []
    with conn:
        repo = EventRepository(conn)
        rows = repo.fetch_protocols(None if all_protocols else protocol_slug)
        if not rows:
            target = protocol_slug or "all protocols"
            print(f"ERROR: no protocols found for {target}", file=sys.stderr)
            return 1

        run_id = None if dry_run else repo.create_pipeline_run(
            f"{SCRIPT_NAME}:{'all' if all_protocols else protocol_slug}"
        )
        results = process_protocols(
            repo,
            rows,
            dry_run=dry_run,
            all_protocols=all_protocols,
        )
        if not dry_run:
            repo.update_pipeline_run(
                run_id,
                results,
                int(time.monotonic() - started),
            )

    conn.close()
    print_summary(results)

    failures = [result for result in results if result.error is not None]
    successes = [result for result in results if result.error is None]
    if failures and not all_protocols:
        return 1
    if failures and not successes:
        return 1

    changed_slugs = [result.slug for result in successes if result.db_updates > 0]
    return _post_refresh_steps(changed_slugs, dry_run=dry_run)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh episodic-cadence DeFiRisk state"
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="Refresh all protocols")
    scope.add_argument("--protocol", metavar="SLUG", help="Refresh one protocol")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(
        conn_str=get_connection_url(),
        all_protocols=args.all,
        protocol_slug=args.protocol,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
