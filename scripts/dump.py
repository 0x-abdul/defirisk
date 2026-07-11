#!/usr/bin/env python3
"""
dump.py — Versioned JSON export for the RiskProduct dashboard.

Reads from Postgres (psycopg v3) and writes static JSON files under
data/api/v1.7.0/ (or a custom --out-root).

Usage:
    python scripts/dump.py
    python scripts/dump.py --out-root /tmp/out
    python scripts/dump.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dependency guard
# ---------------------------------------------------------------------------

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print(
        "ERROR: psycopg v3 is not installed.\n"
        "  Install it with:  pip install 'psycopg[binary]'\n"
        "  or:               pip install psycopg",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUBRIC_VERSION = "v1.7.0"
API_PATH = Path("data") / "api" / RUBRIC_VERSION
CAT4_EVENT_CASCADE = frozenset({"RD-F-063", "RD-F-066", "RD-F-067"})


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------

def _default(obj: Any) -> Any:
    """Custom JSON serialiser for types not natively supported."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        # Ensure UTC, then emit ISO-8601 with Z suffix.
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # date (not datetime)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=_default, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------

def make_envelope(
    data: Any,
    data_as_of: str,
    generated_at: str,
    *,
    risk_score: float | None = None,
    category_severities: dict | None = None,
    cap_applied: str | None = None,
    cap_reason: str | None = None,
) -> dict:
    """Build the canonical API envelope.

    The four optional keyword arguments (risk_score, category_severities,
    cap_applied, cap_reason) are protocol-level fields added in v1.7.0 (M1
    rubric).  Non-protocol envelopes (factors, hacks, incidents, rubric,
    status, etc.) omit all four by passing None to each.

    Pairing rule (CP10-post / 2026-05-30 cap_reason consistency fix): on
    protocol envelopes, `cap_applied` and `cap_reason` are always emitted as
    a pair, even when `cap_reason` is null. This is what schemas/envelope.json
    and openapi.json document; emitting cap_applied without cap_reason
    produced a contract mismatch flagged by the adversarial reviewer.
    """
    env: dict = {
        "rubric_version": RUBRIC_VERSION,
        "data_as_of": data_as_of,
        "generated_at": generated_at,
        "data": data,
    }
    if risk_score is not None:
        env["risk_score"] = round(float(risk_score), 2)
    if category_severities is not None:
        env["category_severities"] = category_severities
    # cap_applied / cap_reason are paired: either both present or both absent.
    # Anchor on cap_applied — if a caller passes cap_reason without cap_applied
    # that is a programming error and we surface the cap_applied=None path.
    if cap_applied is not None:
        env["cap_applied"] = cap_applied
        env["cap_reason"] = cap_reason  # may be null; that's the documented case
    return env


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not url:
        print(
            "ERROR: Neither DATABASE_URL nor LOCAL_DATABASE_URL is set.\n"
            "  Set one of these environment variables to a valid Postgres connection string.",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def fetch_data_as_of(cur: Any) -> str:
    """Return ISO-8601 UTC timestamp of the latest exported DB refresh."""
    cur.execute(
        """
        SELECT GREATEST(
            (SELECT MAX(collected_at) FROM factor_scores WHERE is_current = true),
            (SELECT MAX(updated_at) FROM protocols
             WHERE total_value_secured_usd IS NOT NULL),
            (SELECT MAX(updated_at) FROM deployments WHERE tvs_usd IS NOT NULL)
        ) AS max_ts
        """
    )
    row = cur.fetchone()
    if row and row["max_ts"]:
        ts: datetime = row["max_ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Fallback: epoch — signals no data yet.
    return "1970-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def fetch_protocols(cur: Any) -> list[dict]:
    cur.execute(
        """
        SELECT
            slug, display_name, description, homepage_url, github_org,
            defillama_slug, protocol_type, primary_chain, launched_at,
            headline_grade, total_value_secured_usd,
            graded_at, rubric_version, status, has_active_incident,
            risk_score, category_severities, cap_applied, cap_reason,
            is_published, review_token,
            last_refreshed, created_at, updated_at
        FROM protocols
        ORDER BY slug
        """
    )
    return cur.fetchall()


def fetch_families_by_slug(cur: Any) -> dict[str, dict]:
    cur.execute(
        """
        SELECT
            family_slug, display_name, description, homepage_url,
            protocol_type, primary_chain, primary_surface_id::text AS primary_surface_id,
            headline_grade, total_value_secured_usd, risk_score,
            category_severities, cap_applied, cap_reason, graded_at,
            rubric_version, status, has_active_incident, is_published,
            legacy_caveat, created_at, updated_at
        FROM protocol_families
        ORDER BY family_slug
        """
    )
    return {row["family_slug"]: dict(row) for row in cur.fetchall()}


def fetch_surfaces_by_family(cur: Any) -> dict[str, list[dict]]:
    cur.execute(
        """
        SELECT
            surface_id::text AS surface_id, family_slug, surface_slug,
            display_name, status, launched_at, primary_chain, tvs_usd,
            headline_grade, risk_score, category_severities, cap_applied,
            cap_reason, graded_at, rubric_version, scope_note, is_primary,
            legacy_slug, created_at, updated_at
        FROM protocol_surfaces
        ORDER BY family_slug, is_primary DESC, surface_slug
        """
    )
    result: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        result.setdefault(row["family_slug"], []).append(dict(row))
    return result


def fetch_deployments_by_protocol(cur: Any) -> dict[str, list[dict]]:
    cur.execute(
        """
        SELECT
            id, protocol_slug, surface_id::text AS surface_id, deployment_key,
            chain, anchor_address, display_name,
            tvs_usd, tvs_share, letter, category_grid,
            deployed_at, created_at, updated_at
        FROM deployments
        ORDER BY protocol_slug, chain
        """
    )
    rows = cur.fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        slug = row["protocol_slug"]
        result.setdefault(slug, []).append(dict(row))
    return result


def fetch_factor_scores_by_protocol(cur: Any) -> dict[str, list[dict]]:
    """
    Returns current factor scores with their sources, grouped by protocol_slug.
    Sources are embedded as a list under key 'sources'.
    """
    cur.execute(
        """
        SELECT
            fs.id           AS score_id,
            fs.protocol_slug,
            fs.scope_level,
            fs.family_slug,
            fs.surface_id::text AS surface_id,
            fs.deployment_id,
            fs.factor_id,
            fs.score,
            fs.evidence_summary,
            fs.evidence_detail,
            fs.collection_mode,
            fs.collected_at,
            fs.data_as_of,
            fs.collected_by,
            fs.gap_reason,    -- PD-039 (2026-05-11)
            -- source fields (may be NULL if no source linked)
            s.source_type,
            s.url           AS source_url,
            s.reference     AS source_reference,
            s.title         AS source_title,
            s.retrieved_at  AS source_retrieved_at
        FROM factor_scores fs
        LEFT JOIN factor_score_sources fss ON fss.factor_score_id = fs.id
        LEFT JOIN sources s ON s.id = fss.source_id
        WHERE fs.is_current = true
        ORDER BY fs.protocol_slug, fs.factor_id, fs.id, s.id
        """
    )
    rows = cur.fetchall()

    # Group: protocol -> factor_score_id -> score dict with sources list
    # intermediate: slug -> score_id -> score_entry
    by_slug: dict[str, dict[str, dict]] = {}

    for row in rows:
        slug = row["protocol_slug"]
        score_id = str(row["score_id"])

        if slug not in by_slug:
            by_slug[slug] = OrderedDict()

        if score_id not in by_slug[slug]:
            by_slug[slug][score_id] = {
                "factor_id": row["factor_id"],
                "score_id": str(row["score_id"]),
                "scope_level": row["scope_level"],
                "family_slug": row["family_slug"],
                "surface_id": row["surface_id"],
                "deployment_id": str(row["deployment_id"]) if row["deployment_id"] else None,
                "score": row["score"],
                "evidence_summary": row["evidence_summary"],
                "evidence_detail": row["evidence_detail"],
                "collection_mode": row["collection_mode"],
                "collected_at": row["collected_at"],
                "data_as_of": row["data_as_of"],
                "collected_by": row["collected_by"],
                "gap_reason": row["gap_reason"],   # PD-039 — null on graded scores
                "sources": [],
            }

        # Attach source if present
        if row["source_type"] is not None:
            by_slug[slug][score_id]["sources"].append(
                {
                    "source_type": row["source_type"],
                    "url": row["source_url"],
                    "reference": row["source_reference"],
                    "title": row["source_title"],
                    "retrieved_at": row["source_retrieved_at"],
                }
            )

    # Collapse to lists
    result: dict[str, list[dict]] = {}
    for slug, score_map in by_slug.items():
        result[slug] = list(score_map.values())
    return result


def fetch_grade_history_by_protocol(cur: Any) -> dict[str, list[dict]]:
    cur.execute(
        """
        SELECT
            protocol_slug, deployment_id, scope_level, family_slug, surface_id::text AS surface_id,
            rubric_version,
            letter, critical_flag_count, red_category_count,
            yellow_category_count, gray_on_core_five,
            risk_score, category_severities, cap_applied, cap_reason,
            graded_at, triggered_by, notes
        FROM grade_history
        ORDER BY protocol_slug, graded_at DESC
        """
    )
    rows = cur.fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        slug = row["protocol_slug"]
        entry = {
            "letter": row["letter"],
            "critical_flag_count": row["critical_flag_count"],
            "red_category_count": row["red_category_count"],
            "yellow_category_count": row["yellow_category_count"],
            "gray_on_core_five": row["gray_on_core_five"],
            # v1.7.0 M1 fields (nullable for pre-v1.7.0 history rows)
            "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else None,
            "category_severities": row["category_severities"],
            "cap_applied": row["cap_applied"],
            "cap_reason": row["cap_reason"],
            "graded_at": row["graded_at"],
            "triggered_by": row["triggered_by"],
            "notes": row["notes"],
            "scope_level": row["scope_level"],
            "family_slug": row["family_slug"],
            "surface_id": row["surface_id"],
            "deployment_id": str(row["deployment_id"]) if row["deployment_id"] else None,
            "rubric_version": row["rubric_version"],
        }
        result.setdefault(slug, []).append(entry)
    return result


def fetch_hacks(cur: Any) -> list[dict]:
    cur.execute(
        """
        SELECT
            h.id, h.protocol_slug, h.protocol_name, h.occurred_at,
            h.loss_usd, h.category, h.root_cause, h.description,
            h.postmortem_url, h.funds_recovered_pct, h.is_active, h.status
        FROM hacks h
        ORDER BY h.occurred_at DESC
        """
    )
    return cur.fetchall()


def fetch_hack_factor_links(cur: Any) -> dict[str, list[dict]]:
    cur.execute(
        """
        SELECT hack_id, factor_id, relevance, notes
        FROM hack_factor_links
        ORDER BY hack_id, factor_id
        """
    )
    rows = cur.fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        hack_id = row["hack_id"]
        result.setdefault(hack_id, []).append(
            {
                "factor_id": row["factor_id"],
                "relevance": row["relevance"],
                "notes": row["notes"],
            }
        )
    return result


def fetch_active_rubric(cur: Any) -> dict | None:
    cur.execute(
        """
        SELECT version, frozen_at, changelog_url, notes
        FROM rubric_versions
        WHERE is_active = true
        LIMIT 1
        """
    )
    return cur.fetchone()


def fetch_factors(cur: Any) -> list[dict]:
    cur.execute(
        """
        SELECT
            id, category_id, name, description, scoring_methodology,
            is_critical, curation_archetype, measurement, data_source,
            method, output_format, cadence, evidence_artifact,
            confidence_signal, introduced_in_rubric, deprecated_in_rubric
        FROM factors
        ORDER BY id
        """
    )
    return cur.fetchall()


def fetch_factor_scores_by_factor(cur: Any) -> dict[str, list[dict]]:
    """
    Returns current factor scores grouped by factor_id.
    Each entry includes the protocol slug + display_name so the global factor
    page can render a sortable all-protocols list without an extra join.
    """
    cur.execute(
        """
        WITH candidate_scores AS (
            SELECT
                fs.factor_id,
                fs.protocol_slug,
                p.display_name AS protocol_name,
                p.primary_chain,
                fs.scope_level,
                fs.family_slug,
                fs.surface_id::text AS surface_id,
                fs.deployment_id,
                fs.score,
                fs.evidence_summary,
                fs.evidence_detail,
                fs.collection_mode,
                fs.collected_at,
                fs.data_as_of,
                fs.collected_by,
                fs.gap_reason,
                CASE
                    WHEN fs.scope_level = 'surface' AND fs.surface_id = pf.primary_surface_id THEN 2
                    WHEN fs.scope_level = 'family' AND fs.family_slug = pf.family_slug THEN 1
                    ELSE 0
                END AS precedence
            FROM factor_scores fs
            JOIN protocols p ON p.slug = fs.protocol_slug
            JOIN protocol_families pf ON pf.family_slug = p.slug
            WHERE fs.is_current = true
              AND p.is_published = true
        ),
        effective_scores AS (
            SELECT DISTINCT ON (protocol_slug, factor_id) *
            FROM candidate_scores
            WHERE precedence > 0
            ORDER BY protocol_slug, factor_id, precedence DESC, collected_at DESC
        )
        SELECT *
        FROM effective_scores
        ORDER BY factor_id, protocol_name NULLS LAST
        """
    )
    rows = cur.fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        factor_id = row["factor_id"]
        entry = {
            "protocol_slug": row["protocol_slug"],
            "protocol_name": row["protocol_name"],
            "primary_chain": row["primary_chain"],
            "scope_level": row["scope_level"],
            "family_slug": row["family_slug"],
            "surface_id": row["surface_id"],
            "deployment_id": str(row["deployment_id"]) if row["deployment_id"] else None,
            "score": row["score"],
            "evidence_summary": row["evidence_summary"],
            "evidence_detail": row["evidence_detail"],
            "collection_mode": row["collection_mode"],
            "collected_at": row["collected_at"],
            "data_as_of": row["data_as_of"],
            "collected_by": row["collected_by"],
            "gap_reason": row["gap_reason"],   # PD-039 — null on graded scores
        }
        result.setdefault(factor_id, []).append(entry)
    return result


def fetch_hack_factor_links_by_factor(cur: Any) -> dict[str, list[dict]]:
    """
    Returns hack-factor links grouped by factor_id, joined to hack metadata
    so the per-factor blob can render a "related historical hacks" panel
    without a follow-up fetch.
    """
    cur.execute(
        """
        SELECT
            hfl.factor_id,
            hfl.hack_id,
            hfl.relevance,
            hfl.notes,
            h.protocol_name AS hack_protocol_name,
            h.protocol_slug AS hack_protocol_slug,
            h.occurred_at,
            h.loss_usd,
            h.root_cause
        FROM hack_factor_links hfl
        LEFT JOIN hacks h ON h.id = hfl.hack_id
        ORDER BY hfl.factor_id, h.occurred_at DESC NULLS LAST
        """
    )
    rows = cur.fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        factor_id = row["factor_id"]
        entry = {
            "hack_id": row["hack_id"],
            "relevance": row["relevance"],
            "notes": row["notes"],
            "hack_protocol_name": row["hack_protocol_name"],
            "hack_protocol_slug": row["hack_protocol_slug"],
            "occurred_at": row["occurred_at"],
            "loss_usd": row["loss_usd"],
            "root_cause": row["root_cause"],
        }
        result.setdefault(factor_id, []).append(entry)
    return result


def fetch_all_grade_snapshots(cur: Any, limit_per_protocol: int = 365) -> dict[str, list[dict]]:
    """Fetch last N daily grade snapshots for all protocols, grouped by slug, oldest-first.

    Graceful: returns {} if the protocol_grade_history table doesn't exist yet
    (pre-migration — same pattern as fetch_pipeline_runs).
    """
    try:
        cur.execute(
            """
            SELECT protocol_slug, snapshot_date, rubric_version,
                   grade_letter, critical_count, red_count,
                   yellow_count, gray_core_five
            FROM (
                SELECT pgh.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY pgh.protocol_slug
                           ORDER BY snapshot_date DESC
                       ) AS rn
                FROM protocol_grade_history pgh
                JOIN protocol_families pf ON pf.family_slug = pgh.protocol_slug
                WHERE pgh.scope_level = 'surface'
                  AND pgh.surface_id = pf.primary_surface_id
            ) sub
            WHERE rn <= %s
            ORDER BY protocol_slug, snapshot_date ASC
            """,
            (limit_per_protocol,),
        )
        rows = cur.fetchall()
        result: dict[str, list[dict]] = {}
        for row in rows:
            slug = row["protocol_slug"]
            entry = {
                "snapshot_date": row["snapshot_date"],
                "rubric_version": row["rubric_version"],
                "grade_letter": row["grade_letter"],
                "critical_count": row["critical_count"],
                "red_count": row["red_count"],
                "yellow_count": row["yellow_count"],
                "gray_core_five": row["gray_core_five"],
            }
            result.setdefault(slug, []).append(entry)
        return result
    except Exception:
        return {}


def fetch_grade_snapshots_by_surface(cur: Any, limit_per_surface: int = 365) -> dict[str, list[dict]]:
    """Fetch scoped daily snapshots keyed by surface UUID, oldest first."""
    cur.execute(
        """
        SELECT surface_id::text AS surface_id, snapshot_date, rubric_version,
               grade_letter, critical_count, red_count, yellow_count, gray_core_five
        FROM (
            SELECT pgh.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY pgh.protocol_slug, pgh.surface_id
                       ORDER BY snapshot_date DESC
                   ) AS rn
            FROM protocol_grade_history pgh
            WHERE pgh.scope_level = 'surface'
              AND pgh.surface_id IS NOT NULL
        ) scoped
        WHERE rn <= %s
        ORDER BY surface_id, snapshot_date ASC
        """,
        (limit_per_surface,),
    )
    result: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        result.setdefault(row["surface_id"], []).append(
            {
                "snapshot_date": row["snapshot_date"],
                "rubric_version": row["rubric_version"],
                "grade_letter": row["grade_letter"],
                "critical_count": row["critical_count"],
                "red_count": row["red_count"],
                "yellow_count": row["yellow_count"],
                "gray_core_five": row["gray_core_five"],
            }
        )
    return result


def fetch_grade_changes(cur: Any, limit: int = 200) -> list[dict]:
    """Fetch the most recent grade change events for the /changes/ feed."""
    try:
        cur.execute(
            """
            SELECT gc.id, gc.protocol_slug, p.display_name AS protocol_name,
                   gc.scope_level, gc.family_slug,
                   gc.surface_id::text AS surface_id,
                   gc.deployment_id::text AS deployment_id,
                   gc.detected_at, gc.from_grade, gc.to_grade,
                   gc.rubric_version,
                   gc.snapshot_date_before, gc.snapshot_date_after,
                   gc.reason, gc.is_upgrade
            FROM grade_changes gc
            JOIN protocols p ON p.slug = gc.protocol_slug
            ORDER BY gc.detected_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()
    except Exception:
        return []


def fetch_active_incidents(cur: Any) -> list[dict]:
    cur.execute(
        """
        SELECT
            id, protocol_slug, hack_id, severity, headline,
            detail_url, opened_at, closed_at, status
        FROM active_incidents
        ORDER BY opened_at DESC
        """
    )
    return cur.fetchall()


def _primary_surface(surfaces: list[dict]) -> dict | None:
    for surface in surfaces:
        if surface.get("is_primary"):
            return surface
    return surfaces[0] if surfaces else None


def _legacy_alias_targets(surfaces_by_slug: dict[str, list[dict]]) -> dict[str, str]:
    return {
        surface["legacy_slug"]: family_slug
        for family_slug, family_surfaces in surfaces_by_slug.items()
        for surface in family_surfaces
        if surface.get("legacy_slug") and surface.get("legacy_slug") != family_slug
    }


def _surfaces_with_current_scores(surfaces: list[dict], factor_scores: list[dict]) -> list[dict]:
    scored_surface_ids = {
        score.get("surface_id")
        for score in factor_scores
        if score.get("scope_level") in {"surface", "deployment"}
        and score.get("surface_id")
    }
    family_scored = any(score.get("scope_level") == "family" for score in factor_scores)
    filtered = [
        surface
        for surface in surfaces
        if (
            surface.get("status") != "deprecated"
            or surface.get("is_primary")
            or surface.get("surface_id") in scored_surface_ids
        )
        and (
            surface.get("is_primary")
            or family_scored
            or surface.get("surface_id") in scored_surface_ids
        )
    ]
    return filtered or surfaces


def _effective_surface_scores(factor_scores: list[dict], surface_id: str) -> list[dict]:
    effective: OrderedDict[str, dict] = OrderedDict()
    for score in factor_scores:
        if score.get("scope_level") == "family":
            effective[score["factor_id"]] = dict(score)
    for score in factor_scores:
        if score.get("scope_level") == "surface" and score.get("surface_id") == surface_id:
            effective[score["factor_id"]] = dict(score)
    return sorted(effective.values(), key=lambda score: score["factor_id"])


def _deployment_overrides(factor_scores: list[dict], deployment_id: str) -> list[dict]:
    return sorted(
        [
            dict(score)
            for score in factor_scores
            if score.get("scope_level") == "deployment"
            and score.get("deployment_id") == deployment_id
        ],
        key=lambda score: score["factor_id"],
    )


def _effective_deployment_scores(
    surface_scores: list[dict],
    factor_scores: list[dict],
    deployment_id: str,
) -> list[dict]:
    effective = OrderedDict((score["factor_id"], dict(score)) for score in surface_scores)
    for score in _deployment_overrides(factor_scores, deployment_id):
        effective[score["factor_id"]] = score
    return list(effective.values())


def _category_severities_for_scores(
    scores: list[dict],
    factor_categories: dict[str, int],
    *,
    has_active_incident: bool,
) -> dict[str, float]:
    counts: dict[int, dict[str, int]] = {}
    for score in scores:
        factor_id = score.get("factor_id")
        category_id = factor_categories.get(factor_id)
        color = score.get("score")
        if (
            has_active_incident
            and category_id == 4
            and factor_id in CAT4_EVENT_CASCADE
            and color == "red"
        ):
            color = "yellow"
        if category_id is None or color not in {"green", "yellow", "red"}:
            continue
        category = counts.setdefault(category_id, {"green": 0, "yellow": 0, "red": 0})
        category[color] += 1

    severities: dict[str, float] = {}
    for category_id, category in counts.items():
        denominator = category["green"] + category["yellow"] + category["red"]
        if denominator == 0:
            continue
        severity = (
            (category["red"] * 3 + category["yellow"])
            / (denominator * 3)
            * 100.0
        )
        severities[str(category_id)] = severity
    return severities


def _compat_factor_scores(scores: list[dict]) -> list[dict]:
    """Preserve the legacy top-level factor_scores shape for default views."""
    compat: list[dict] = []
    for score in scores:
        row = dict(score)
        for key in ("score_id", "scope_level", "family_slug", "surface_id"):
            row.pop(key, None)
        compat.append(row)
    return compat


def _compat_grade_history(history: list[dict]) -> list[dict]:
    compat: list[dict] = []
    for entry in history:
        row = dict(entry)
        for key in ("scope_level", "family_slug", "surface_id", "category_severities"):
            row.pop(key, None)
        compat.append(row)
    return compat


def _surface_grade_history(grade_history: list[dict], surface_id: str) -> list[dict]:
    return [
        dict(entry)
        for entry in grade_history
        if entry.get("scope_level") == "surface" and entry.get("surface_id") == surface_id
    ]


def build_surface_payloads(
    surfaces: list[dict],
    factor_scores: list[dict],
    deployments: list[dict],
    grade_history: list[dict],
    factor_categories: dict[str, int] | None = None,
    *,
    has_active_incident: bool = False,
) -> list[dict]:
    factor_categories = factor_categories or {}
    payloads: list[dict] = []
    for surface in surfaces:
        surface_id = surface["surface_id"]
        surface_deployments = [
            dict(dep) for dep in deployments if dep.get("surface_id") == surface_id
        ]
        surface_scores = _effective_surface_scores(factor_scores, surface_id)
        deployment_scores: dict[str, list[dict]] = {}
        deployment_category_severities: dict[str, dict[str, float]] = {}
        deployment_overrides: dict[str, list[dict]] = {}
        for dep in surface_deployments:
            dep_id = str(dep["id"])
            overrides = _deployment_overrides(factor_scores, dep_id)
            effective_deployment_scores = surface_scores
            if overrides:
                deployment_overrides[dep_id] = overrides
                effective_deployment_scores = _effective_deployment_scores(
                    surface_scores,
                    factor_scores,
                    dep_id,
                )
                deployment_scores[dep_id] = effective_deployment_scores
            deployment_category_severities[dep_id] = _category_severities_for_scores(
                effective_deployment_scores,
                factor_categories,
                has_active_incident=has_active_incident,
            )
        payload = dict(surface)
        payload["deployments"] = surface_deployments
        payload["factor_scores"] = surface_scores
        payload["deployment_overrides"] = deployment_overrides
        payload["deployment_factor_scores"] = deployment_scores
        payload["deployment_category_severities"] = deployment_category_severities
        payload["grade_history"] = _surface_grade_history(grade_history, surface_id)
        payloads.append(payload)
    return payloads


def fetch_pipeline_runs(cur: Any, limit: int = 30) -> list[dict]:
    """Fetch the most recent pipeline run records for status.json.

    Graceful: returns [] if the pipeline_runs table doesn't exist yet
    (pre-Phase-2 migration).
    """
    try:
        cur.execute(
            """
            SELECT
                id, run_at, script_name, cadence_bucket,
                protocols_touched, fetchers_invoked,
                success_count, error_count,
                duration_seconds, triggered_by,
                error_summary, notes
            FROM pipeline_runs
            ORDER BY run_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()
    except Exception:
        # Table not yet migrated — return empty list; status page shows 'unwired'
        return []


def emit_status_json(
    pipeline_runs: list[dict],
    protocols: list[dict],
    data_as_of: str,
    generated_at: str,
    api_dir: Path,
    dry_run: bool,
) -> None:
    """Emit data/api/<rubric>/status.json — envelope-wrapped status summary.

    Contains:
      - runs:             last 30 pipeline_runs rows (serialised)
      - bucket_freshness: per-cadence-bucket aggregates (last_run, success_rate)
      - fleet_freshness:  per-protocol graded_at / data_as_of summary
    """
    # 1. Serialise pipeline run rows (uuid → str, timestamps → ISO)
    run_records: list[dict] = []
    for r in pipeline_runs:
        rec = dict(r)
        rec["id"] = str(rec["id"])
        for ts_key in ("run_at",):
            if ts_key in rec and hasattr(rec[ts_key], "isoformat"):
                rec[ts_key] = rec[ts_key].isoformat()
        run_records.append(rec)

    # 2. Per-bucket freshness aggregates (C / E / S)
    bucket_freshness: dict[str, dict] = {}
    for bucket_code in ("C", "E", "S"):
        bucket_runs = [r for r in run_records if r.get("cadence_bucket") == bucket_code]
        if not bucket_runs:
            bucket_freshness[bucket_code] = {
                "cadence_bucket": bucket_code,
                "last_run_at": None,
                "run_count_30": 0,
                "total_errors": 0,
                "total_successes": 0,
                "success_rate_pct": None,
            }
            continue

        last_run = bucket_runs[0]  # sorted DESC by run_at from SQL
        total_ok = sum(r.get("success_count") or 0 for r in bucket_runs)
        total_err = sum(r.get("error_count") or 0 for r in bucket_runs)
        total_ops = total_ok + total_err
        success_rate = round((total_ok / total_ops) * 100, 1) if total_ops else None

        bucket_freshness[bucket_code] = {
            "cadence_bucket": bucket_code,
            "last_run_at": last_run.get("run_at"),
            "run_count_30": len(bucket_runs),
            "total_errors": total_err,
            "total_successes": total_ok,
            "success_rate_pct": success_rate,
        }

    # 3. Fleet freshness: per-protocol graded_at / data_as_of summary
    now_ts = datetime.now(tz=timezone.utc)
    fleet_freshness: list[dict] = []
    for p in protocols:
        graded_at = p.get("graded_at")
        data_as_of_p = p.get("data_as_of") or p.get("updated_at") or p.get("graded_at")
        if hasattr(graded_at, "isoformat"):
            graded_at = graded_at.isoformat()
        if hasattr(data_as_of_p, "isoformat"):
            data_as_of_p = data_as_of_p.isoformat()

        days_stale: int | None = None
        ref_ts = data_as_of_p or graded_at
        if ref_ts:
            try:
                ref_dt = datetime.fromisoformat(str(ref_ts).replace("Z", "+00:00"))
                days_stale = (now_ts - ref_dt).days
            except Exception:
                pass

        fleet_freshness.append({
            "slug": p.get("slug") or p.get("protocol_slug"),
            "headline_grade": p.get("headline_grade"),
            "graded_at": graded_at,
            "data_as_of": data_as_of_p,
            "days_stale": days_stale,
        })

    # 4. Assemble and write
    status_payload = {
        "runs": run_records,
        "bucket_freshness": bucket_freshness,
        "fleet_freshness": fleet_freshness,
        "meta": {
            "runs_window": 30,
            "generated_at": generated_at,
            "data_as_of": data_as_of,
        },
    }

    write_json(
        api_dir / "status.json",
        make_envelope(status_payload, data_as_of, generated_at),
        dry_run,
    )


# ---------------------------------------------------------------------------
# Envelope JSON Schema (static, deterministic)
# ---------------------------------------------------------------------------

# Draft-07 variant (legacy path: schema/envelope.json — kept for back-compat).
#
# Per p0-response 2026-05-30 (P0 #1 / contract audit DRIFT consolidation), the
# Draft-07 schema is now DERIVED from ENVELOPE_SCHEMA_2020 below rather than
# maintained as a parallel hand-written dict. This eliminates the risk of the
# two paths silently drifting from each other on future schema edits — there
# is now exactly one source of truth (the 2020-12 variant), and the Draft-07
# variant is a mechanical conversion of it.
#
# The conversion:
#   - swaps $schema URI to Draft-07
#   - swaps $id URI to the singular /schema/ path
#   - leaves properties / required / additionalProperties / examples intact
#     (Draft-07 supports all of these since Draft-06).
def _derive_draft07_from_2020(schema_2020: dict) -> dict:
    """Return a Draft-07 mirror of a Draft 2020-12 envelope schema.

    Keys whose values are nested dicts (e.g. `properties`) are deep-copied so
    mutating the returned dict cannot leak into the canonical 2020-12 source.
    """
    import copy
    out = copy.deepcopy(schema_2020)
    out["$schema"] = "https://json-schema.org/draft-07/schema#"
    out["$id"] = "https://defirisk.co/api/v1.7.0/schema/envelope.json"
    return out


# ENVELOPE_SCHEMA is initialised AFTER ENVELOPE_SCHEMA_2020 (see below).

# Draft 2020-12 variant (canonical path: schemas/envelope.json — E-23)
# Resolves PD-008: rubric_version and data_as_of are mandatory on every
# response so downstream integrators can distinguish protocol-data changes
# from rubric-version bumps.
ENVELOPE_SCHEMA_2020: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://defirisk.co/api/v1.7.0/schemas/envelope.json",
    "title": "RiskProduct API canonical envelope",
    "description": (
        "Envelope wrapping every API response under /api/v1.7.0/. "
        "Resolves PD-008: rubric_version and data_as_of are mandatory on "
        "every response so downstream integrators can distinguish "
        "protocol-data changes from rubric-version bumps. "
        "Protocol envelopes additionally carry risk_score, "
        "category_severities, cap_applied, and cap_reason (M1 v4 rubric, "
        "introduced in v1.7.0). "
        "The `data` field shape varies per endpoint."
    ),
    "type": "object",
    "required": ["rubric_version", "data_as_of", "generated_at", "data"],
    "additionalProperties": False,
    "properties": {
        "rubric_version": {
            "type": "string",
            "pattern": "^v\\d+\\.\\d+\\.\\d+$",
            "description": (
                "Frozen rubric version string, e.g. v1.7.0. Matches the "
                "published rubric changelog entry current at "
                "grade-computation time."
            ),
            "examples": [RUBRIC_VERSION],
        },
        "data_as_of": {
            "type": "string",
            "format": "date-time",
            "description": (
                "ISO-8601 UTC timestamp of the most recent factor_score "
                "collected_at across the response payload. Distinct from "
                "generated_at: the rubric may re-evaluate without new factor "
                "data arriving. May be the Unix epoch "
                "(1970-01-01T00:00:00Z) when no scores have been collected."
            ),
        },
        "generated_at": {
            "type": "string",
            "format": "date-time",
            "description": (
                "ISO-8601 UTC timestamp of when this dump ran "
                "(when the JSON file was last written by dump.py)."
            ),
        },
        "data": {
            "type": "object",
            "description": (
                "Endpoint-specific payload. Shape documented per-path "
                "in openapi.json."
            ),
        },
        "risk_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "description": (
                "Protocol-level risk score (0–100, 2-decimal precision). "
                "Present only on protocol envelopes (protocols/<slug>.json). "
                "Computed by the M1 v4 rubric: weighted-average category "
                "severity across 13 categories (core-five weighted 1.5×, "
                "non-core 1.0×) plus up to 15 points critical-red penalty. "
                "Introduced in v1.7.0."
            ),
            "examples": [9.0, 34.0, 62.0],
        },
        "category_severities": {
            "type": "object",
            "description": (
                "Per-category severity scores keyed by category ID string "
                "(\"1\" through \"13\"). Each value is a number 0–100. "
                "Present only on protocol envelopes. "
                "0 when denom=0 (all factors gray/gap). "
                "Introduced in v1.7.0 (M1 rubric)."
            ),
            "additionalProperties": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
            },
        },
        "cap_applied": {
            "type": "string",
            "enum": ["none", "D", "F"],
            "description": (
                "Whether the single-category core-five cap overrode the "
                "natural letter grade. 'none' = no cap; 'D' = capped at D; "
                "'F' = capped at F. Present only on protocol envelopes. "
                "Introduced in v1.7.0 (M1 rubric)."
            ),
            "examples": ["none", "D", "F"],
        },
        "cap_reason": {
            "type": ["string", "null"],
            "description": (
                "Human-readable explanation of the cap, e.g. "
                "'Cat 5 severity 67 >= 60 (core-five cap)'. "
                "null when cap_applied='none'. Present only on protocol "
                "envelopes. Introduced in v1.7.0 (M1 rubric)."
            ),
            "examples": [None, "Cat 5 severity 67 >= 60 (core-five cap)"],
        },
        "series_window": {
            "type": "object",
            "description": (
                "Date range of the time-series payload, present only on "
                "history.json envelopes (per-protocol and fleet-wide). "
                "Allows clients to render a chart axis without iterating "
                "the full `series` array. ISO-8601 date strings (UTC)."
            ),
            "required": ["from", "to"],
            "additionalProperties": False,
            "properties": {
                "from": {"type": "string", "format": "date"},
                "to":   {"type": "string", "format": "date"},
            },
        },
    },
}


# Draft-07 schema is now mechanically derived from the canonical 2020-12 dict
# above (CP10 / p0-response 2026-05-30). Single source of truth.
ENVELOPE_SCHEMA: dict = _derive_draft07_from_2020(ENVELOPE_SCHEMA_2020)


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def write_json(path: Path, payload: Any, dry_run: bool) -> None:
    """Serialise payload to JSON without logging token-bearing output paths."""
    if dry_run:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = to_json(payload)
        path.write_text(content, encoding="utf-8")
    except OSError:
        raise RuntimeError("failed to write generated JSON output") from None


def prune_generated_output(api_dir: Path) -> None:
    for prune_dir in (api_dir / "protocols", api_dir / "unpublished"):
        if not prune_dir.exists():
            continue
        try:
            shutil.rmtree(prune_dir)
        except OSError:
            raise RuntimeError("failed to prune generated API output") from None


# ---------------------------------------------------------------------------
# Main dump logic
# ---------------------------------------------------------------------------

def run_dump(out_root: Path, dry_run: bool) -> None:
    url = get_connection_url()

    print("Connecting to database…")
    try:
        # connect_timeout=10: matches the importer + compose.py guard. dump.py
        # is the slowest of the three (full table scans), but a hung connect
        # at start should still fail fast.
        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
    except Exception as exc:
        print(f"ERROR: Could not connect to database.\n  {exc}", file=sys.stderr)
        sys.exit(1)

    with conn:
        with conn.cursor() as cur:
            print("Fetching data…")
            generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            data_as_of = fetch_data_as_of(cur)

            protocols = fetch_protocols(cur)
            families_by_slug = fetch_families_by_slug(cur)
            surfaces_by_slug = fetch_surfaces_by_family(cur)
            deployments_by_slug = fetch_deployments_by_protocol(cur)
            factor_scores_by_slug = fetch_factor_scores_by_protocol(cur)
            grade_history_by_slug = fetch_grade_history_by_protocol(cur)
            hacks = fetch_hacks(cur)
            hack_factor_links = fetch_hack_factor_links(cur)
            active_rubric = fetch_active_rubric(cur)
            factors = fetch_factors(cur)
            factor_scores_by_factor = fetch_factor_scores_by_factor(cur)
            hack_factor_links_by_factor = fetch_hack_factor_links_by_factor(cur)
            active_incidents = fetch_active_incidents(cur)
            pipeline_runs = fetch_pipeline_runs(cur)
            grade_snapshots_by_slug = fetch_all_grade_snapshots(cur)
            grade_snapshots_by_surface = fetch_grade_snapshots_by_surface(cur)
            grade_changes = fetch_grade_changes(cur)

    conn.close()

    # ------------------------------------------------------------------
    # Counts summary (always printed)
    # ------------------------------------------------------------------
    total_scores = sum(len(v) for v in factor_scores_by_slug.values())
    print(
        f"\nCounts:"
        f"\n  protocols      : {len(protocols)}"
        f"\n  deployments    : {sum(len(v) for v in deployments_by_slug.values())}"
        f"\n  factor_scores  : {total_scores}"
        f"\n  hacks          : {len(hacks)}"
        f"\n  factors        : {len(factors)}"
        f"\n  hack-factor lk : {sum(len(v) for v in hack_factor_links_by_factor.values())}"
        f"\n  incidents      : {len(active_incidents)}"
        f"\n  pipeline runs  : {len(pipeline_runs)}"
    )

    if dry_run:
        print("\n[dry-run] No files written.")
        return

    api_dir = out_root / "api" / RUBRIC_VERSION
    print("\nWriting generated API files.")
    # ------------------------------------------------------------------
    # 0. Prune stale per-protocol files.
    #
    # Without this, a protocol that was previously published (so dump.py
    # wrote protocols/<slug>.json) but is now unpublished would leak its
    # data via the stale file under /api/<rubric>/protocols/<slug>.json.
    # Same for protocols whose review_token was rotated.
    #
    # Safe to wipe these directories: they're fully regenerated below.
    # Other top-level files (index.json, factors/, hacks/, schema/, etc.)
    # are overwritten by name and don't need pruning.
    # ------------------------------------------------------------------
    prune_generated_output(api_dir)

    # ------------------------------------------------------------------
    # 1. index.json — published protocols only
    # ------------------------------------------------------------------
    index_protocols = []
    for p in protocols:
        if not p.get("is_published"):
            continue
        family = families_by_slug.get(p["slug"], {})
        surfaces = _surfaces_with_current_scores(
            surfaces_by_slug.get(p["slug"], []),
            factor_scores_by_slug.get(p["slug"], []),
        )
        primary_surface = _primary_surface(surfaces)
        index_protocols.append(
            {
                "slug": p["slug"],
                "display_name": p["display_name"],
                "protocol_type": p["protocol_type"],
                "primary_chain": p["primary_chain"],
                "surface_count": len(surfaces) or 1,
                "primary_surface_slug": (
                    primary_surface.get("surface_slug") if primary_surface else "default"
                ),
                "legacy_caveat": family.get("legacy_caveat"),
                "headline_grade": p["headline_grade"],
                "total_value_secured_usd": p["total_value_secured_usd"],
                "graded_at": p["graded_at"],
                "rubric_version": p["rubric_version"],
                "status": p["status"],
                "has_active_incident": p["has_active_incident"],
            }
        )

    write_json(
        api_dir / "index.json",
        make_envelope(
            {"protocols": index_protocols},
            data_as_of,
            generated_at,
        ),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 2. Per-protocol detail JSON.
    #
    # Published protocols → protocols/<slug>.json (public API surface).
    # Unpublished protocols → unpublished/<slug>-<token>/index.json
    # (obscure path, robots-noindexed, sitemap-excluded — used to share
    # pre-publication review links).
    #
    # review_token is stripped from the public envelope so it never leaks
    # to the published surface — it is only meaningful for the unguessable
    # /unpublished/ URL.
    # ------------------------------------------------------------------
    unpublished_count = 0
    published_protocol_slugs = {p["slug"] for p in protocols if p.get("is_published")}
    legacy_alias_targets = _legacy_alias_targets(surfaces_by_slug)
    factor_categories = {factor["id"]: int(factor["category_id"]) for factor in factors}
    alias_count = 0
    for p in protocols:
        slug = p["slug"]
        if slug in legacy_alias_targets:
            continue
        is_pub = bool(p.get("is_published"))
        protocol_dict = dict(p)
        review_token = protocol_dict.get("review_token")

        # Public surface must never expose the review token.
        if is_pub:
            protocol_dict.pop("review_token", None)

        # Convert any UUID-ish deployment_id values to strings in nested data
        raw_factor_scores = factor_scores_by_slug.get(slug, [])
        raw_grade_history = grade_history_by_slug.get(slug, [])
        raw_deps = deployments_by_slug.get(slug, [])
        family = families_by_slug.get(slug)
        surfaces = _surfaces_with_current_scores(
            surfaces_by_slug.get(slug, []),
            raw_factor_scores,
        )

        if family is None:
            family = {
                "family_slug": slug,
                "display_name": p["display_name"],
                "description": p.get("description"),
                "homepage_url": p.get("homepage_url"),
                "protocol_type": p.get("protocol_type"),
                "primary_chain": p.get("primary_chain"),
                "primary_surface_id": None,
                "legacy_caveat": None,
            }

        if not surfaces:
            surfaces = [
                {
                    "surface_id": None,
                    "family_slug": slug,
                    "surface_slug": "default",
                    "display_name": p["display_name"],
                    "status": "active",
                    "launched_at": p.get("launched_at"),
                    "primary_chain": p.get("primary_chain"),
                    "tvs_usd": p.get("total_value_secured_usd"),
                    "headline_grade": p.get("headline_grade"),
                    "risk_score": p.get("risk_score"),
                    "category_severities": p.get("category_severities"),
                    "cap_applied": p.get("cap_applied"),
                    "cap_reason": p.get("cap_reason"),
                    "graded_at": p.get("graded_at"),
                    "rubric_version": p.get("rubric_version"),
                    "scope_note": None,
                    "is_primary": True,
                    "legacy_slug": slug,
                }
            ]

        primary_surface = _primary_surface(surfaces)
        primary_surface_id = primary_surface.get("surface_id") if primary_surface else None
        surface_payloads = build_surface_payloads(
            surfaces,
            raw_factor_scores,
            raw_deps,
            raw_grade_history,
            factor_categories,
            has_active_incident=bool(p.get("has_active_incident")),
        )
        primary_payload = next(
            (
                surface
                for surface in surface_payloads
                if surface.get("surface_id") == primary_surface_id
            ),
            surface_payloads[0] if surface_payloads else None,
        )
        factor_scores = (
            _compat_factor_scores(primary_payload.get("factor_scores", []))
            if primary_payload
            else _compat_factor_scores(raw_factor_scores)
        )
        grade_history = (
            _compat_grade_history(primary_payload.get("grade_history", []))
            if primary_payload
            else _compat_grade_history(raw_grade_history)
        )
        deps = primary_payload.get("deployments", []) if primary_payload else raw_deps

        protocol_dict["primary_surface_slug"] = (
            primary_surface.get("surface_slug") if primary_surface else "default"
        )
        protocol_dict["legacy_caveat"] = family.get("legacy_caveat")
        protocol_dict["surface_count"] = len(surfaces)

        blob = {
            "protocol": protocol_dict,
            "family": family,
            "surfaces": surface_payloads,
            "deployments": deps,
            "factor_scores": factor_scores,
            "grade_history": grade_history,
        }

        # v1.7.0 (M1 rubric): lift risk_score / category_severities /
        # cap_applied / cap_reason onto the envelope level so API consumers
        # can read them without parsing the full protocol blob.
        # These columns are added to `protocols` by A2/A5 migrations.
        proto_risk_score: float | None = protocol_dict.get("risk_score")
        proto_cat_sev: dict | None = protocol_dict.get("category_severities")
        proto_cap_applied: str | None = protocol_dict.get("cap_applied")
        proto_cap_reason: str | None = protocol_dict.get("cap_reason")

        if is_pub:
            target = api_dir / "protocols" / f"{slug}.json"
        else:
            if not review_token:
                # Skip — protocol has no token; cannot place at unguessable
                # path. Migration 0007 backfills tokens, so this should only
                # fire if the column is somehow null after migration.
                print(f"  WARNING: unpublished protocol {slug!r} has no review_token; skipping detail emit")
                continue
            target = api_dir / "unpublished" / f"{slug}-{review_token}" / "index.json"
            unpublished_count += 1

        write_json(
            target,
            make_envelope(
                {"protocol_data": blob},
                data_as_of,
                generated_at,
                risk_score=proto_risk_score,
                category_severities=proto_cat_sev,
                cap_applied=proto_cap_applied,
                cap_reason=proto_cap_reason,
            ),
            dry_run,
        )

        if is_pub:
            for surface in surface_payloads:
                legacy_slug = surface.get("legacy_slug")
                if not legacy_slug or legacy_slug == slug or legacy_slug in published_protocol_slugs:
                    continue
                alias_protocol = dict(protocol_dict)
                alias_protocol["slug"] = legacy_slug
                alias_protocol["canonical_family_slug"] = slug
                alias_protocol["selected_surface_slug"] = surface.get("surface_slug")
                alias_protocol["primary_surface_slug"] = protocol_dict.get("primary_surface_slug")
                alias_protocol["display_name"] = surface.get("display_name") or alias_protocol.get("display_name")
                alias_protocol["primary_chain"] = surface.get("primary_chain") or alias_protocol.get("primary_chain")
                alias_protocol["launched_at"] = surface.get("launched_at") or alias_protocol.get("launched_at")
                alias_protocol["total_value_secured_usd"] = (
                    surface.get("tvs_usd")
                    if surface.get("tvs_usd") is not None
                    else alias_protocol.get("total_value_secured_usd")
                )
                alias_protocol["headline_grade"] = surface.get("headline_grade") or alias_protocol.get("headline_grade")
                alias_protocol["risk_score"] = (
                    surface.get("risk_score")
                    if surface.get("risk_score") is not None
                    else alias_protocol.get("risk_score")
                )
                alias_protocol["category_severities"] = (
                    surface.get("category_severities")
                    if surface.get("category_severities") is not None
                    else alias_protocol.get("category_severities")
                )
                alias_protocol["cap_applied"] = surface.get("cap_applied") or alias_protocol.get("cap_applied")
                alias_protocol["cap_reason"] = (
                    surface.get("cap_reason")
                    if surface.get("cap_reason") is not None
                    else alias_protocol.get("cap_reason")
                )
                alias_protocol["graded_at"] = surface.get("graded_at") or alias_protocol.get("graded_at")
                alias_protocol["rubric_version"] = surface.get("rubric_version") or alias_protocol.get("rubric_version")
                alias_blob = {
                    "protocol": alias_protocol,
                    "family": family,
                    "surfaces": surface_payloads,
                    "deployments": surface.get("deployments", []),
                    "factor_scores": _compat_factor_scores(surface.get("factor_scores", [])),
                    "grade_history": _compat_grade_history(surface.get("grade_history", [])),
                }
                write_json(
                    api_dir / "protocols" / f"{legacy_slug}.json",
                    make_envelope(
                        {"protocol_data": alias_blob},
                        data_as_of,
                        generated_at,
                        risk_score=surface.get("risk_score"),
                        category_severities=surface.get("category_severities"),
                        cap_applied=surface.get("cap_applied"),
                        cap_reason=surface.get("cap_reason"),
                    ),
                    dry_run,
                )
                alias_count += 1

    # ------------------------------------------------------------------
    # 2b. protocols/<slug>/history.json — daily grade snapshot series (E-32)
    #
    # Envelope carries rubric_version + data_as_of per PD-008.
    # series_window field signals the oldest/newest date in the series so
    # chart consumers can detect rubric-version boundaries without scanning
    # the full array.
    # ------------------------------------------------------------------
    history_files = 0
    for p in protocols:
        slug = p["slug"]
        if slug in legacy_alias_targets:
            continue
        snapshots = grade_snapshots_by_slug.get(slug, [])
        if not snapshots:
            continue

        is_pub = bool(p.get("is_published"))
        review_token = p.get("review_token")
        if not is_pub and not review_token:
            continue  # cannot place unpublished history at unguessable path

        series_window = {
            "from": snapshots[0]["snapshot_date"].isoformat()
                    if hasattr(snapshots[0]["snapshot_date"], "isoformat")
                    else str(snapshots[0]["snapshot_date"]),
            "to": snapshots[-1]["snapshot_date"].isoformat()
                  if hasattr(snapshots[-1]["snapshot_date"], "isoformat")
                  else str(snapshots[-1]["snapshot_date"]),
        }

        history_blob = {
            "protocol_slug": slug,
            "series_window": series_window,
            "series": snapshots,
        }
        envelope = {
            "rubric_version": RUBRIC_VERSION,
            "data_as_of": data_as_of,
            "generated_at": generated_at,
            "series_window": series_window,
            "data": history_blob,
        }
        if is_pub:
            target = api_dir / "protocols" / slug / "history.json"
        else:
            target = api_dir / "unpublished" / f"{slug}-{review_token}" / "history.json"
        write_json(target, envelope, dry_run)
        history_files += 1

    # Preserve legacy history endpoints for surface aliases. The canonical
    # family history remains the primary surface series.
    for p in protocols:
        if not p.get("is_published"):
            continue
        family_slug = p["slug"]
        for surface in surfaces_by_slug.get(family_slug, []):
            legacy_slug = surface.get("legacy_slug")
            surface_id = surface.get("surface_id")
            if (
                not legacy_slug
                or legacy_slug == family_slug
                or legacy_slug in published_protocol_slugs
                or not surface_id
            ):
                continue
            snapshots = grade_snapshots_by_surface.get(surface_id, [])
            if not snapshots:
                continue
            series_window = {
                "from": str(snapshots[0]["snapshot_date"]),
                "to": str(snapshots[-1]["snapshot_date"]),
            }
            write_json(
                api_dir / "protocols" / legacy_slug / "history.json",
                {
                    "rubric_version": RUBRIC_VERSION,
                    "data_as_of": data_as_of,
                    "generated_at": generated_at,
                    "series_window": series_window,
                    "data": {
                        "protocol_slug": legacy_slug,
                        "canonical_family_slug": family_slug,
                        "selected_surface_slug": surface.get("surface_slug"),
                        "series_window": series_window,
                        "series": snapshots,
                    },
                },
                dry_run,
            )
            history_files += 1

    # ------------------------------------------------------------------
    # 2c. history.json — fleet-wide grade snapshot index (E-32)
    #
    # Contains all protocols' last 365 daily grade snapshots in a single
    # envelope. Capped: if the total entry count exceeds ~5 MB equivalent
    # (≈ 50k entries), entries older than 30 days are downsampled to weekly
    # (keep only Sundays) to stay within the size budget.
    # Graceful: emits empty series if no snapshots exist (pre-launch safe).
    # ------------------------------------------------------------------
    CAP_ENTRIES = 50_000  # rough ~5 MB guard
    fleet_series: list[dict] = []
    for p in protocols:
        if not p.get("is_published"):
            continue  # unpublished protocols never appear in the public fleet feed
        slug = p["slug"]
        snapshots = grade_snapshots_by_slug.get(slug, [])
        if snapshots:
            fleet_series.append({
                "protocol_slug": slug,
                "series": snapshots,
            })

    # Downsample if fleet exceeds cap: keep all entries ≤30 days old;
    # for older entries keep only ISO-week Sundays (weekday==6).
    total_entries = sum(len(ps["series"]) for ps in fleet_series)
    if total_entries > CAP_ENTRIES:
        from datetime import date as _date
        from datetime import timedelta as _timedelta
        cutoff_30 = (datetime.now(tz=timezone.utc).date() - _timedelta(days=30))
        downsampled: list[dict] = []
        for ps in fleet_series:
            recent = []
            weekly = []
            for entry in ps["series"]:
                snap_d = entry.get("snapshot_date")
                # normalise to date object
                if snap_d is not None and not isinstance(snap_d, _date):
                    try:
                        snap_d = _date.fromisoformat(str(snap_d))
                    except ValueError:
                        snap_d = None
                if snap_d is None or snap_d >= cutoff_30:
                    recent.append(entry)
                elif snap_d.weekday() == 6:   # Sunday
                    weekly.append(entry)
            downsampled.append({
                "protocol_slug": ps["protocol_slug"],
                "series": recent + weekly,
            })
        fleet_series = downsampled

    write_json(
        api_dir / "history.json",
        make_envelope(
            {"history": fleet_series, "protocol_count": len(fleet_series)},
            data_as_of,
            generated_at,
        ),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 3. hacks.json
    # ------------------------------------------------------------------
    hacks_with_links = []
    for h in hacks:
        hack_dict = dict(h)
        hack_dict["linked_factors"] = hack_factor_links.get(h["id"], [])
        hacks_with_links.append(hack_dict)

    write_json(
        api_dir / "hacks.json",
        make_envelope({"hacks": hacks_with_links}, data_as_of, generated_at),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 4. rubric.json
    # ------------------------------------------------------------------
    if active_rubric:
        rubric_data = {
            "version": active_rubric["version"],
            "frozen_at": active_rubric["frozen_at"],
            "changelog_url": active_rubric["changelog_url"],
            "notes": active_rubric["notes"],
        }
    else:
        # Rubric row not yet seeded — emit minimal stub.
        rubric_data = {
            "version": RUBRIC_VERSION,
            "frozen_at": None,
            "changelog_url": None,
            "notes": "No active rubric version found in database.",
        }

    write_json(
        api_dir / "rubric.json",
        make_envelope(rubric_data, data_as_of, generated_at),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 5. factors.json — top-level index of all 184 factors
    # ------------------------------------------------------------------
    index_factors = []
    for f in factors:
        index_factors.append(
            {
                "id": f["id"],
                "category_id": f["category_id"],
                "name": f["name"],
                "description": f["description"],
                "is_critical": f["is_critical"],
                "curation_archetype": f["curation_archetype"],
                "introduced_in_rubric": f["introduced_in_rubric"],
                "deprecated_in_rubric": f["deprecated_in_rubric"],
            }
        )

    write_json(
        api_dir / "factors.json",
        make_envelope({"factors": index_factors}, data_as_of, generated_at),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 6. factors/<id>.json — per-factor blob: methodology + scored
    #    protocols + linked hacks (Feature A global factor page)
    # ------------------------------------------------------------------
    for f in factors:
        factor_id = f["id"]
        blob = {
            "factor": dict(f),
            "scored_protocols": factor_scores_by_factor.get(factor_id, []),
            "linked_hacks": hack_factor_links_by_factor.get(factor_id, []),
        }
        write_json(
            api_dir / "factors" / f"{factor_id}.json",
            make_envelope({"factor_data": blob}, data_as_of, generated_at),
            dry_run,
        )

    # ------------------------------------------------------------------
    # 7. hacks/<id>.json — per-hack blob: hack record + linked factors
    # ------------------------------------------------------------------
    for h in hacks:
        hack_id = h["id"]
        hack_dict = dict(h)
        blob = {
            "hack": hack_dict,
            "linked_factors": hack_factor_links.get(hack_id, []),
        }
        write_json(
            api_dir / "hacks" / f"{hack_id}.json",
            make_envelope({"hack_data": blob}, data_as_of, generated_at),
            dry_run,
        )

    # ------------------------------------------------------------------
    # 8. incidents.json — active incidents ledger (CEO condition 5C banner)
    # ------------------------------------------------------------------
    incidents_payload = []
    for i in active_incidents:
        i_dict = dict(i)
        i_dict["id"] = str(i_dict["id"])
        incidents_payload.append(i_dict)

    write_json(
        api_dir / "incidents.json",
        make_envelope({"incidents": incidents_payload}, data_as_of, generated_at),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 9a. schema/envelope.json — JSON Schema Draft-07 (legacy path).
    #
    # AUTO-GENERATED from ENVELOPE_SCHEMA_2020 via _derive_draft07_from_2020().
    # DO NOT edit this file directly — edit ENVELOPE_SCHEMA_2020 in this
    # script. The Draft-07 path is kept for backward-compat with consumers
    # that pinned the old singular URL.
    # ------------------------------------------------------------------
    write_json(
        api_dir / "schema" / "envelope.json",
        ENVELOPE_SCHEMA,
        dry_run,
    )

    # ------------------------------------------------------------------
    # 9b. schemas/envelope.json — JSON Schema Draft 2020-12 (E-23 canonical)
    #
    # The plural `schemas/` path is the forward-compatible canonical path
    # introduced by E-23.  The singular `schema/` path above is kept for
    # backward-compatibility with consumers that pinned the old URL.
    # Both files validate the same envelope shape; 2020-12 adds richer
    # semantics (examples[] array, anchor support) for tooling that
    # understands the newer dialect.
    # ------------------------------------------------------------------
    write_json(
        api_dir / "schemas" / "envelope.json",
        ENVELOPE_SCHEMA_2020,
        dry_run,
    )

    # ------------------------------------------------------------------
    # 10. changes.json — grade change feed index (E-34)
    # ------------------------------------------------------------------
    published_slugs = {p["slug"] for p in protocols if p.get("is_published")}
    change_records = []
    for ch in grade_changes:
        if ch.get("protocol_slug") not in published_slugs:
            continue  # never expose grade changes for unpublished protocols
        rec = dict(ch)
        rec["id"] = str(rec["id"])
        if rec.get("detected_at"):
            rec["detected_at"] = rec["detected_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(rec["detected_at"], "strftime") else str(rec["detected_at"])
        if rec.get("snapshot_date_before"):
            rec["snapshot_date_before"] = str(rec["snapshot_date_before"])
        if rec.get("snapshot_date_after"):
            rec["snapshot_date_after"] = str(rec["snapshot_date_after"])
        change_records.append(rec)

    write_json(
        api_dir / "changes.json",
        make_envelope({"changes": change_records}, data_as_of, generated_at),
        dry_run,
    )

    # ------------------------------------------------------------------
    # 11. status.json — pipeline run history + freshness aggregates (E-30 Phase 2)
    # ------------------------------------------------------------------
    # status.json is public — pass only published protocols so unpublished
    # slugs never appear in the fleet_freshness array.
    emit_status_json(
        pipeline_runs,
        [p for p in protocols if p.get("is_published")],
        data_as_of,
        generated_at,
        api_dir,
        dry_run,
    )

    # ------------------------------------------------------------------
    # E-30 status.json emission inserts here
    #
    # E-30 (Phases 2-4) will extend this function to emit additional
    # operational artifacts once the pipeline_runs table is migrated and
    # refresh-continuous.py / refresh-events.py are live.
    #
    # Expected extension: after the status.json write above (step 11),
    # E-30 adds per-cadence run summaries and freshness signals read from
    # the pipeline_runs and protocol_grade_history tables.  The snippet
    # lives at:
    #   .research/wave1-patches/E-30-dump-status.snippet
    #
    # Merge instruction for orchestrator:
    #   1. Read E-30-dump-status.snippet.
    #   2. Insert the snippet body immediately after this comment block
    #      (before the print-summary below).
    #   3. Update the print-summary to include the new file count.
    # ------------------------------------------------------------------

    published_count = sum(1 for p in protocols if p.get("is_published"))
    print(
        f"\nDone."
        f"\n  protocols     : {published_count} published in protocols/, {unpublished_count} in unpublished/ ({len(protocols)} total)"
        f"\n  aliases       : {alias_count} legacy surface alias files"
        f"\n  history.json  : {history_files} per-protocol + 1 fleet index"
        f"\n  factors       : {len(factors)} per-factor + 1 index"
        f"\n  hacks         : {len(hacks)} per-hack + 1 index"
        f"\n  incidents     : {len(active_incidents)} (1 index)"
        f"\n  grade changes : {len(grade_changes)} (1 changes.json)"
        f"\n  pipeline runs : {len(pipeline_runs)} (1 status.json)"
        f"\n  rubric, schema: 2"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump versioned JSON files from the RiskProduct Postgres database.",
    )
    parser.add_argument(
        "--out-root",
        default=None,
        metavar="DIR",
        help=(
            "Root directory for output (default: <repo-root>/data). "
            "Files land at <out-root>/api/v1.7.0/."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print record counts only; do not write any files.",
    )
    return parser.parse_args()


def resolve_out_root(cli_value: str | None) -> Path:
    """
    Resolve the output root directory.

    Default: the repo root's `data/` folder.  The repo root is the directory
    that contains db/schema.ts, which is two levels up from this script
    (scripts/dump.py → scripts/ → repo root).
    """
    if cli_value is not None:
        return Path(cli_value).resolve()
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    return repo_root / "data"


def main() -> None:
    args = parse_args()
    out_root = resolve_out_root(args.out_root)
    run_dump(out_root=out_root, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
