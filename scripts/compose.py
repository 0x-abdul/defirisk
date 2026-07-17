#!/usr/bin/env python3
"""compose.py — Compute rubric grades from DB factor scores and write results.

For each protocol with ≥1 current factor_score:
  1. Aggregate factor scores into per-category counts (green/yellow/red/gray).
  2. Apply Cat 4 event-cascade exclusion when protocol has active incident.
  3. Count critical-red factors (is_critical=True AND score='red').
  4. Call rubric.grade() → {letter, risk_score, cap_applied, cap_reason, ...}.
  5. INSERT into grade_history (with risk_score, cap_applied, cap_reason).
  6. UPDATE protocols.headline_grade + graded_at + rubric_version.

Rubric version: v1.7.0 (M1 "Curve & Calibrate" v4)

Usage:
    DATABASE_URL=postgres://... python scripts/compose.py
    DATABASE_URL=postgres://... python scripts/compose.py --protocol aave-v3
    DATABASE_URL=postgres://... python scripts/compose.py --dry-run

Environment:
    DATABASE_URL or LOCAL_DATABASE_URL   psycopg v3 connection string (required)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path

# Make scripts/ importable when invoked from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("ERROR: psycopg (v3) not installed. Run: pip install 'psycopg[binary]'")
    sys.exit(1)

from rubric import CORE_FIVE, RUBRIC_VERSION, grade  # noqa: E402

# ── Constants ────────────────────────────────────────────────────────────────

# CORE_FIVE is imported from rubric.py (single source of truth):
# frozenset({1, 2, 3, 5, 8}) — Code, Governance, Oracle, Ops History, Fork Lineage

# CAT_RED_THRESHOLD is removed in v1.7.0.  Under M1, the per-category severity
# formula (0–100 weighted average) replaces the old red/yellow/green light
# logic.  The Cat 3 "min_reds=2" exception was a workaround for a binary light
# system; it is no longer needed because a single red factor in a large
# category now contributes a proportionally small severity increment rather
# than flipping the category to red.

# Cat 4 (Economic) factor IDs that are event-cascade eligible.
# Decision (M1 v4): KEEP as a severity input transformation.
#
# Under v1.6.0 these factors were capped at yellow to prevent a single
# active-incident economic finding from flipping Cat 4's binary light to red
# and elevating the grade band.  Under M1, the severity formula naturally
# dilutes their impact proportionally — a protocol with 18 Cat 4 factors
# cannot be pushed to F by 2 event-cascade reds alone.  However, the
# transformation is retained because:
#   1. It preserves the architectural intent: event-driven economic findings
#      (utilization crisis, bad debt) are not structural design failures and
#      should not accumulate toward the structural risk score the same way.
#   2. The downstream API consumers (dump.py, pro app) may rely on the
#      category_severities dict reflecting this distinction.
#   3. The spec (handoff §6 line 91) says "default keep it".
# If a future calibration audit finds it adds nothing numerically, it can be
# removed in a subsequent patch without touching the core algorithm.
CAT4_EVENT_CASCADE: frozenset[str] = frozenset({"RD-F-063", "RD-F-066", "RD-F-067"})


# ── Category display rollup (M1 v4) ──────────────────────────────────────────

def _category_light(
    green_count: int,
    yellow_count: int,
    red_count: int,
) -> str:
    """Derive the display colour for a category from its severity score.

    Implements the M1 v4 display rollup (handoff §2):
        severity ≥ 50  → red
        20 ≤ sev < 50  → yellow
        0 < sev < 20   → green
        denom = 0      → gray

    Gray factors are excluded from the denominator (PD-039).
    """
    from rubric import category_severity
    denom = green_count + yellow_count + red_count
    if denom == 0:
        return "gray"
    sev = category_severity(green_count, yellow_count, red_count)
    if sev >= 50:
        return "red"
    if sev >= 20:
        return "yellow"
    return "green"


# ── DB queries ───────────────────────────────────────────────────────────────

def _fetch_protocols(cur: psycopg.Cursor, slug: str | None) -> list[dict]:
    if slug:
        cur.execute(
            """SELECT slug, display_name, launched_at, total_value_secured_usd,
                      status, has_active_incident
               FROM protocols WHERE slug = %s""",
            (slug,),
        )
    else:
        cur.execute(
            """SELECT slug, display_name, launched_at, total_value_secured_usd,
                      status, has_active_incident
               FROM protocols ORDER BY slug"""
        )
    return cur.fetchall()


def _fetch_factor_scores(
    cur: psycopg.Cursor, protocol_slug: str, rubric_version: str
) -> list[dict]:
    """Fetch current factor scores for the active grading rubric."""
    cur.execute(
        """SELECT fs.id, fs.factor_id, fs.score,
                  fs.scope_level, fs.family_slug, fs.surface_id, fs.deployment_id,
                  f.category_id, f.is_critical
           FROM factor_scores fs
           JOIN factors f ON f.id = fs.factor_id
           WHERE fs.protocol_slug = %s
             AND fs.rubric_version = %s
             AND fs.is_current = true""",
        (protocol_slug, rubric_version),
    )
    return cur.fetchall()


def _fetch_surfaces(cur: psycopg.Cursor, protocol_slug: str) -> list[dict]:
    cur.execute(
        """SELECT surface_id::text AS surface_id, family_slug, surface_slug,
                  display_name, status, launched_at, primary_chain, tvs_usd,
                  scope_note, is_primary, legacy_slug
           FROM protocol_surfaces
           WHERE family_slug = %s
           ORDER BY is_primary DESC, surface_slug""",
        (protocol_slug,),
    )
    return cur.fetchall()


def _fetch_all_categories(cur: psycopg.Cursor) -> list[dict]:
    cur.execute("SELECT id, slug, name, is_core_five FROM categories ORDER BY id")
    return cur.fetchall()


def _insert_grade_history(
    cur: psycopg.Cursor,
    *,
    protocol_slug: str,
    rubric_version: str,
    letter: str,
    critical_flag_count: int,
    red_category_count: int,
    yellow_category_count: int,
    gray_on_core_five: bool,
    graded_at: datetime,
    triggered_by: str,
    risk_score: float | None = None,
    category_severities: dict | None = None,
    cap_applied: str | None = None,
    cap_reason: str | None = None,
    scope_level: str = "surface",
    family_slug: str | None = None,
    surface_id: str | None = None,
    deployment_id: str | None = None,
) -> str:
    cur.execute(
        """INSERT INTO grade_history
               (protocol_slug, deployment_id, scope_level, family_slug, surface_id,
                rubric_version, letter,
                critical_flag_count, red_category_count, yellow_category_count,
                gray_on_core_five, graded_at, triggered_by,
                risk_score, category_severities, cap_applied, cap_reason)
           VALUES (%s, %s::uuid, %s, %s, %s::uuid,
                   %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s::jsonb, %s, %s)
           RETURNING id""",
        (
            protocol_slug, deployment_id, scope_level, family_slug, surface_id,
            rubric_version, letter,
            critical_flag_count, red_category_count, yellow_category_count,
            gray_on_core_five, graded_at, triggered_by,
            risk_score,
            json.dumps(category_severities) if category_severities is not None else None,
            cap_applied, cap_reason,
        ),
    )
    return cur.fetchone()["id"]


def _upsert_protocol_grade_snapshot(
    cur: psycopg.Cursor,
    *,
    protocol_slug: str,
    rubric_version: str,
    letter: str,
    critical_count: int,
    red_count: int,
    yellow_count: int,
    gray_core_five: bool,
    snapshot_at: datetime,
    source_run_id: str | None,
    notes: str | None = None,
    scope_level: str = "surface",
    family_slug: str | None = None,
    surface_id: str | None = None,
) -> None:
    """Insert one scoped protocol_grade_history row; idempotent per scope/date."""
    snapshot_date = snapshot_at.date()
    cur.execute(
        """INSERT INTO protocol_grade_history
               (protocol_slug, scope_level, family_slug, surface_id,
                snapshot_at, snapshot_date, rubric_version,
                grade_letter, critical_count, red_count, yellow_count,
                gray_core_five, source_run_id, notes)
           VALUES (%s, %s, %s, %s::uuid,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (
            protocol_slug, scope_level, family_slug, surface_id,
            snapshot_at, snapshot_date, rubric_version,
            letter, critical_count, red_count, yellow_count,
            gray_core_five, source_run_id, notes,
        ),
    )


def _upsert_factor_score_snapshots(
    cur: psycopg.Cursor,
    *,
    protocol_slug: str,
    factor_scores: list[dict],
    rubric_version: str,
    snapshot_at: datetime,
    source_run_id: str | None,
    notes: str | None = None,
    scope_level: str = "surface",
    family_slug: str | None = None,
    surface_id: str | None = None,
    deployment_id: str | None = None,
) -> None:
    """Insert one scoped factor_score_history row per effective factor."""
    snapshot_date = snapshot_at.date()
    cur.executemany(
        """INSERT INTO factor_score_history
               (protocol_slug, scope_level, family_slug, surface_id, deployment_id,
                factor_id, snapshot_at, snapshot_date,
                score_color, score_value, rubric_version, source_run_id, notes)
           VALUES (%s, %s, %s, %s::uuid, %s::uuid,
                   %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        [
            (
                protocol_slug,
                scope_level,
                family_slug,
                surface_id,
                deployment_id,
                fs["factor_id"],
                snapshot_at,
                snapshot_date,
                fs["score"],
                None,       # score_value reserved for numeric values
                rubric_version,
                source_run_id,
                notes,
            )
            for fs in factor_scores
        ],
    )


def _create_compose_pipeline_run(cur: psycopg.Cursor, protocol_slug: str | None) -> str | None:
    """Create a pipeline_runs row and fail closed on schema or privilege drift."""
    scope = protocol_slug if protocol_slug else "all"
    cur.execute(
        """INSERT INTO pipeline_runs
               (script_name, cadence_bucket, protocols_touched,
                fetchers_invoked, success_count, error_count,
                triggered_by)
           VALUES ('compose.py', 'compose', 0, '[]'::jsonb, 0, 0, %s)
           RETURNING id""",
        (f"compose.py:{scope}",),
    )
    return str(cur.fetchone()["id"])


def _update_compose_pipeline_run(
    cur: psycopg.Cursor,
    run_id: str,
    processed: int,
    skipped: int,
    duration_seconds: int,
) -> None:
    cur.execute(
        """UPDATE pipeline_runs
           SET protocols_touched = %s,
               success_count     = %s,
               error_count       = %s,
               duration_seconds  = %s
           WHERE id = %s""",
        (processed + skipped, processed, skipped, duration_seconds, run_id),
    )


def _update_protocol_grade(
    cur: psycopg.Cursor,
    *,
    protocol_slug: str,
    letter: str,
    rubric_version: str,
    graded_at: datetime,
    risk_score: float | None = None,
    category_severities: dict | None = None,
    cap_applied: str | None = None,
    cap_reason: str | None = None,
) -> None:
    cur.execute(
        """UPDATE protocols
           SET headline_grade       = %s,
               rubric_version       = %s,
               graded_at            = %s,
               risk_score           = %s,
               category_severities  = %s::jsonb,
               cap_applied          = %s,
               cap_reason           = %s,
               updated_at           = now()
           WHERE slug = %s""",
        (
            letter,
            rubric_version,
            graded_at,
            risk_score,
            json.dumps(category_severities) if category_severities is not None else None,
            cap_applied,
            cap_reason,
            protocol_slug,
        ),
    )


# ── Age calculation ──────────────────────────────────────────────────────────
# Note: _age_months is no longer used by grade() under M1 v4 (TVL/age floors
# for A grade were removed in v1.7.0).  Kept here for any external callers
# (dump.py envelope assembly, detect-grade-changes.py, etc.).

def _update_surface_grade(
    cur: psycopg.Cursor,
    *,
    family_slug: str,
    surface_id: str,
    letter: str,
    rubric_version: str,
    graded_at: datetime,
    risk_score: float | None = None,
    category_severities: dict | None = None,
    cap_applied: str | None = None,
    cap_reason: str | None = None,
) -> None:
    cur.execute(
        """SELECT public.refresh_update_surface_grade(
                 %s, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s
               )""",
        (
            family_slug,
            surface_id,
            letter,
            rubric_version,
            graded_at,
            risk_score,
            json.dumps(category_severities) if category_severities is not None else None,
            cap_applied,
            cap_reason,
        ),
    )


def _age_months(launched_at: date | None) -> int:
    if launched_at is None:
        return 0
    today = datetime.now(tz=timezone.utc).date()
    delta_days = (today - launched_at).days
    return max(0, delta_days // 30)


# ── Grade computation for one protocol ───────────────────────────────────────

def compute_grade(
    protocol: dict,
    factor_scores: list[dict],
    categories: list[dict],
) -> dict:
    """Compute M1 v4 grade for one protocol.

    Returns:
        {
            letter, risk_score, base_risk_score, critical_red_count,
            critical_penalty, category_severities, cap_applied, cap_reason,
            # Legacy summary fields (kept for logging + snapshot writes):
            critical_flag_count,   # alias for critical_red_count
            red_category_count,    # derived from category_lights
            yellow_category_count, # derived from category_lights
            gray_on_core_five,     # derived from category_lights (always False under M1)
            category_lights,       # dict[cat_id → "red"|"yellow"|"green"|"gray"]
        }
    """
    has_active_incident: bool = bool(protocol.get("has_active_incident"))

    # Build per-category color counts.
    # Gray factors are excluded from the severity denominator per PD-039 but
    # we still track them so category_lights can return "gray" for all-gray cats.
    by_category_counts: dict[int, dict[str, int]] = {}
    for cat in categories:
        by_category_counts[cat["id"]] = {"green": 0, "yellow": 0, "red": 0, "gray": 0}

    for fs in factor_scores:
        cat_id = fs["category_id"]
        score = fs["score"]

        # Cat 4 event-cascade integrity rule (retained under M1 — see constant comment).
        # When a protocol has an active incident, event-driven Cat 4 factors
        # (F063/F066/F067) are capped at yellow for the severity computation.
        if cat_id == 4 and has_active_incident and fs["factor_id"] in CAT4_EVENT_CASCADE:
            score = "yellow" if score == "red" else score

        # Normalise: not_assessed / not_applicable count as gray
        if score not in ("green", "yellow", "red"):
            score = "gray"

        if cat_id not in by_category_counts:
            by_category_counts[cat_id] = {"green": 0, "yellow": 0, "red": 0, "gray": 0}
        by_category_counts[cat_id][score] += 1

    # Critical-red count: ★ factors with score='red' (original score, before any cap)
    critical_red_count = sum(
        1 for fs in factor_scores if fs["is_critical"] and fs["score"] == "red"
    )

    # Call the core grade function
    result = grade(
        category_counts=by_category_counts,
        critical_red_count=critical_red_count,
    )

    # Derive display category lights from severity (M1 §2 display rollup)
    category_lights: dict[int, str] = {}
    for cat_id, counts in by_category_counts.items():
        category_lights[cat_id] = _category_light(
            green_count=counts["green"],
            yellow_count=counts["yellow"],
            red_count=counts["red"],
        )

    # Legacy summary counts (kept for logging + snapshot writes; not rubric inputs)
    red_category_count = sum(1 for light in category_lights.values() if light == "red")
    yellow_category_count = sum(1 for light in category_lights.values() if light == "yellow")
    # gray_on_core_five: no longer a rubric input under M1; gray is excluded from
    # severity denominator so all-gray core-five categories contribute 0 severity
    # (not penalised, not rewarded).  Computed here only for legacy snapshot columns.
    gray_on_core_five = any(
        category_lights.get(cat_id, "gray") == "gray" for cat_id in CORE_FIVE
    )

    return {
        # M1 primary outputs
        "letter": result["letter"],
        "risk_score": result["risk_score"],
        "base_risk_score": result["base_risk_score"],
        "critical_red_count": result["critical_red_count"],
        "critical_penalty": result["critical_penalty"],
        "category_severities": result["category_severities"],
        "cap_applied": result["cap_applied"],
        "cap_reason": result["cap_reason"],
        # Legacy / display fields
        "critical_flag_count": critical_red_count,
        "red_category_count": red_category_count,
        "yellow_category_count": yellow_category_count,
        "gray_on_core_five": gray_on_core_five,
        "category_lights": category_lights,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def _surface_context(protocol: dict, surface: dict) -> dict:
    """Use surface launch/TVS metadata when present without changing rubric inputs."""
    context = dict(protocol)
    if surface.get("launched_at") is not None:
        context["launched_at"] = surface["launched_at"]
    if surface.get("tvs_usd") is not None:
        context["total_value_secured_usd"] = surface["tvs_usd"]
    return context


def _effective_surface_scores(factor_scores: list[dict], surface_id: str) -> list[dict]:
    """Apply family -> surface specificity for a surface headline grade."""
    effective: dict[str, dict] = {}
    surface_id_str = str(surface_id)

    for fs in factor_scores:
        if fs.get("scope_level") == "family":
            effective[fs["factor_id"]] = dict(fs)

    for fs in factor_scores:
        if fs.get("scope_level") == "surface" and str(fs.get("surface_id")) == surface_id_str:
            effective[fs["factor_id"]] = dict(fs)

    return sorted(effective.values(), key=lambda fs: fs["factor_id"])


def _has_surface_scores(factor_scores: list[dict], surface_id: str) -> bool:
    surface_id_str = str(surface_id)
    return any(
        fs.get("scope_level") == "surface" and str(fs.get("surface_id")) == surface_id_str
        for fs in factor_scores
    )


def run(
    conn_str: str,
    *,
    slug: str | None,
    dry_run: bool,
    skip_history: bool = False,
    connection: psycopg.Connection | None = None,
) -> int:
    owns_connection = connection is None
    try:
        # connect_timeout=10: subprocess of importer; if DB is paused we want
        # to surface that quickly to the orchestrator instead of hanging.
        conn = connection or psycopg.connect(conn_str, connect_timeout=10)
    except psycopg.Error as exc:
        print(f"ERROR: Cannot connect to database: {exc}", file=sys.stderr)
        return 1

    start_time = datetime.now(tz=timezone.utc)

    with (conn if owns_connection else nullcontext()):
        with conn.cursor(row_factory=dict_row) as cur:
            # Verify active rubric version
            cur.execute("SELECT version FROM rubric_versions WHERE is_active = true ORDER BY version")
            active_rows = cur.fetchall()
            if len(active_rows) != 1:
                print(
                    "ERROR: Expected exactly one active rubric version in DB.",
                    file=sys.stderr,
                )
                return 1
            db_rubric_version = active_rows[0]["version"]
            if db_rubric_version != RUBRIC_VERSION:
                print(
                    f"WARNING: DB rubric version '{db_rubric_version}' differs from "
                    f"code constant '{RUBRIC_VERSION}'. Using DB version.",
                    file=sys.stderr,
                )

            rubric_version = db_rubric_version
            protocols = _fetch_protocols(cur, slug)
            categories = _fetch_all_categories(cur)

            # Create a pipeline_runs row for this compose invocation (graceful
            # if table doesn't exist yet — pre-migration fallback returns None).
            run_id: str | None = None
            if not dry_run:
                run_id = _create_compose_pipeline_run(cur, slug)

        if not protocols:
            msg = f"Protocol '{slug}' not found." if slug else "No protocols in DB."
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1

        graded_at = datetime.now(tz=timezone.utc)
        processed = 0
        skipped = 0

        for protocol in protocols:
            pslug = protocol["slug"]
            with conn.cursor(row_factory=dict_row) as cur:
                factor_scores = _fetch_factor_scores(cur, pslug, rubric_version)
                surfaces = _fetch_surfaces(cur, pslug)

            if not factor_scores:
                print(f"  SKIP {pslug}: no current factor scores")
                skipped += 1
                continue

            if not surfaces:
                print(f"  SKIP {pslug}: no protocol_surfaces rows; run migration/backfill first")
                skipped += 1
                continue

            for surface in surfaces:
                if (
                    surface.get("status") == "deprecated"
                    and not surface.get("is_primary")
                    and not _has_surface_scores(factor_scores, surface["surface_id"])
                ):
                    print(f"  SKIP {pslug}/{surface['surface_slug']}: deprecated surface with no current surface scores")
                    skipped += 1
                    continue

                effective_scores = _effective_surface_scores(factor_scores, surface["surface_id"])
                if not effective_scores:
                    print(f"  SKIP {pslug}/{surface['surface_slug']}: no effective factor scores")
                    skipped += 1
                    continue

                g = compute_grade(_surface_context(protocol, surface), effective_scores, categories)

                print(
                    f"  {pslug}/{surface['surface_slug']}: {g['letter']} "
                    f"(score={g['risk_score']:.1f} crit={g['critical_flag_count']} "
                    f"cap={g['cap_applied']})"
                )

                if dry_run:
                    processed += 1
                    continue

                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        _insert_grade_history(
                            cur,
                            protocol_slug=pslug,
                            rubric_version=rubric_version,
                            letter=g["letter"],
                            critical_flag_count=g["critical_flag_count"],
                            red_category_count=g["red_category_count"],
                            yellow_category_count=g["yellow_category_count"],
                            gray_on_core_five=g["gray_on_core_five"],
                            graded_at=graded_at,
                            triggered_by="compose.py",
                            risk_score=g["risk_score"],
                            category_severities=g["category_severities"],
                            cap_applied=g["cap_applied"],
                            cap_reason=g["cap_reason"],
                            scope_level="surface",
                            surface_id=surface["surface_id"],
                        )
                        _update_surface_grade(
                            cur,
                            family_slug=pslug,
                            surface_id=surface["surface_id"],
                            letter=g["letter"],
                            rubric_version=rubric_version,
                            graded_at=graded_at,
                            risk_score=g["risk_score"],
                            category_severities=g["category_severities"],
                            cap_applied=g["cap_applied"],
                            cap_reason=g["cap_reason"],
                        )
                        if surface.get("is_primary"):
                            _update_protocol_grade(
                                cur,
                                protocol_slug=pslug,
                                letter=g["letter"],
                                rubric_version=rubric_version,
                                graded_at=graded_at,
                                risk_score=g["risk_score"],
                                category_severities=g["category_severities"],
                                cap_applied=g["cap_applied"],
                                cap_reason=g["cap_reason"],
                            )
                        if not skip_history:
                            _upsert_protocol_grade_snapshot(
                                cur,
                                protocol_slug=pslug,
                                rubric_version=rubric_version,
                                letter=g["letter"],
                                critical_count=g["critical_flag_count"],
                                red_count=g["red_category_count"],
                                yellow_count=g["yellow_category_count"],
                                gray_core_five=g["gray_on_core_five"],
                                snapshot_at=graded_at,
                                source_run_id=run_id,
                                scope_level="surface",
                                surface_id=surface["surface_id"],
                            )
                            _upsert_factor_score_snapshots(
                                cur,
                                protocol_slug=pslug,
                                factor_scores=effective_scores,
                                rubric_version=rubric_version,
                                snapshot_at=graded_at,
                                source_run_id=run_id,
                                scope_level="surface",
                                surface_id=surface["surface_id"],
                            )

                processed += 1

        # Update the pipeline_runs row with final counts.
        if run_id is not None:
            duration_s = int((datetime.now(tz=timezone.utc) - start_time).total_seconds())
            with conn.cursor(row_factory=dict_row) as cur:
                _update_compose_pipeline_run(cur, run_id, processed, skipped, duration_s)

    if owns_connection:
        conn.close()

    suffix = " (dry-run — nothing written)" if dry_run else ""
    print(f"\nDone: {processed} graded, {skipped} skipped{suffix}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute rubric grades from DB factor scores")
    parser.add_argument("--protocol", metavar="SLUG", help="Grade a single protocol")
    parser.add_argument("--dry-run", action="store_true", help="Print grades without writing to DB")
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Skip writing to protocol_grade_history + factor_score_history (dev convenience)",
    )
    args = parser.parse_args(argv)

    conn_str = os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not conn_str:
        print(
            "ERROR: No database connection string found.\n"
            "Set DATABASE_URL or LOCAL_DATABASE_URL environment variable.",
            file=sys.stderr,
        )
        return 1

    return run(conn_str, slug=args.protocol, dry_run=args.dry_run, skip_history=args.skip_history)


if __name__ == "__main__":
    raise SystemExit(main())
