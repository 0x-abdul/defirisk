#!/usr/bin/env python3
"""Validate and import a canonical protocol family assessment.

The importer consumes a merged grading.json, writes protocol/family/surface,
deployment, factor, and source rows transactionally, then optionally runs
compose.py and dump.py. It never composes or edits grades by hand.

Use `--dry-run` for validation only. Database writes require explicit
`--apply`. By default only LOCAL_DATABASE_URL is accepted; a non-local target
also requires `--db-url`, `--allow-nonlocal`, and
`--i-understand-nonlocal`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from protocol_validation import (
    VALID_COLLECTION_MODES,
    VALID_FACTOR_SCORE_SCOPES,
    VALID_GAP_REASONS,
    VALID_PROTOCOL_STATUSES,
    VALID_SCORES,
    VALID_SOURCE_TYPES,
    VALID_SURFACE_STATUSES,
)

# Force UTF-8 stdout/stderr on Windows (defaults to cp1252 which can't print '✓' etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
RUBRIC_VERSION_DEFAULT = "v1.7.0"
DEFAULT_SURFACE_SLUG = "default"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PROTECTED_DATABASES = {"risk_dashboard"}


def database_target(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "database": (parsed.path or "").lstrip("/"),
        "user": parsed.username,
    }


def resolve_database_url(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    url = args.db_url or os.environ.get("LOCAL_DATABASE_URL")
    if not url:
        raise ValueError("LOCAL_DATABASE_URL is required unless --db-url is provided.")
    target = database_target(url)
    if not args.expected_database:
        raise ValueError("--expected-database is required with --apply.")
    if target["database"] != args.expected_database:
        raise ValueError(
            f"Database identity mismatch: connected URL names {target['database']!r}, "
            f"expected {args.expected_database!r}."
        )
    if target["host"] not in LOCAL_HOSTS and not args.allow_nonlocal:
        raise ValueError("Refusing non-local database host without --allow-nonlocal.")
    if target["host"] not in LOCAL_HOSTS and not args.i_understand_nonlocal:
        raise ValueError("--allow-nonlocal requires --i-understand-nonlocal.")
    if target["database"] in PROTECTED_DATABASES:
        if not args.allow_protected_database or not args.i_understand_protected_database:
            raise ValueError(
                "Refusing protected database without --allow-protected-database "
                "and --i-understand-protected-database."
            )
    return url, target


# ---------------------------------------------------------------------------
# Family/surface normalisation
# ---------------------------------------------------------------------------

def _surface_status_from_protocol(status: str | None) -> str:
    return "deprecated" if status == "deprecated" else "active"


def normalise_family(grading: dict, slug: str) -> dict:
    protocol = grading.get("protocol", {})
    raw = dict(grading.get("family") or {})
    family_slug = raw.get("family_slug") or raw.get("slug") or protocol.get("slug") or slug
    return {
        "family_slug": family_slug,
        "display_name": raw.get("display_name") or protocol.get("display_name") or family_slug,
        "description": raw.get("description", protocol.get("description")),
        "homepage_url": raw.get("homepage_url", protocol.get("homepage_url")),
        "protocol_type": raw.get("protocol_type") or protocol.get("protocol_type"),
        "primary_chain": raw.get("primary_chain") or protocol.get("primary_chain"),
        "primary_surface_slug": raw.get("primary_surface_slug") or raw.get("primary_surface"),
        "legacy_caveat": raw.get("legacy_caveat"),
    }


def normalise_surfaces(grading: dict, family: dict) -> list[dict]:
    protocol = grading.get("protocol", {})
    raw_surfaces = grading.get("surfaces")
    if not raw_surfaces:
        return [
            {
                "surface_slug": DEFAULT_SURFACE_SLUG,
                "display_name": protocol.get("display_name") or family["display_name"],
                "status": _surface_status_from_protocol(protocol.get("status")),
                "launched_at": protocol.get("launched_at"),
                "primary_chain": protocol.get("primary_chain") or family.get("primary_chain"),
                "tvs_usd": protocol.get("total_value_secured_usd"),
                "scope_note": None,
                "is_primary": True,
                "legacy_slug": protocol.get("slug"),
            }
        ]

    surfaces: list[dict] = []
    primary = family.get("primary_surface_slug")
    for raw in raw_surfaces:
        s = dict(raw)
        surface_slug = s.get("surface_slug") or s.get("slug")
        surfaces.append(
            {
                "surface_slug": surface_slug,
                "display_name": s.get("display_name") or surface_slug,
                "status": s.get("status") or "active",
                "launched_at": s.get("launched_at"),
                "primary_chain": s.get("primary_chain") or family.get("primary_chain"),
                "tvs_usd": (
                    s.get("tvs_usd")
                    if s.get("tvs_usd") is not None
                    else s.get("total_value_secured_usd")
                ),
                "scope_note": s.get("scope_note"),
                "is_primary": bool(s.get("is_primary")) or (primary is not None and surface_slug == primary),
                "legacy_slug": s.get("legacy_slug") or s.get("protocol_slug"),
            }
        )
    if surfaces and not any(s["is_primary"] for s in surfaces):
        surfaces[0]["is_primary"] = True
    return surfaces


def primary_surface_slug(surfaces: list[dict]) -> str:
    for s in surfaces:
        if s.get("is_primary"):
            return s["surface_slug"]
    return surfaces[0]["surface_slug"] if surfaces else DEFAULT_SURFACE_SLUG


# ---------------------------------------------------------------------------
# Grading file resolution
# ---------------------------------------------------------------------------

def find_grading_file(slug: str, override: Optional[str] = None) -> Path:
    """Locate grading.json by slug, honoring --grading-file first."""
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"--grading-file not found: {path}")
        return path

    candidate = REPO_ROOT / ".research" / "protocols" / slug / "grading.json"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"No grading.json found for slug {slug!r}. Expected: "
        f"{candidate.relative_to(REPO_ROOT)}. Pass --grading-file PATH to override."
    )

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(grading: dict, slug: str) -> list[str]:
    """Return list of error strings; empty list = valid."""
    errors: list[str] = []

    # Top-level structure
    if "protocol" not in grading:
        errors.append("missing top-level 'protocol' key")
    if "factor_scores" not in grading:
        errors.append("missing top-level 'factor_scores' key")

    # Protocol section
    p = grading.get("protocol", {})
    if p.get("slug") != slug:
        errors.append(f"protocol.slug ({p.get('slug')!r}) does not match arg ({slug!r})")
    for required in ("slug", "display_name", "protocol_type", "primary_chain"):
        if not p.get(required):
            errors.append(f"protocol.{required} is required")
    status = p.get("status", "live")
    if status not in VALID_PROTOCOL_STATUSES:
        errors.append(f"protocol.status {status!r} not in {sorted(VALID_PROTOCOL_STATUSES)}")

    family = normalise_family(grading, slug)
    for required in ("family_slug", "display_name", "protocol_type", "primary_chain"):
        if not family.get(required):
            errors.append(f"family.{required} is required")
    if family.get("family_slug") != p.get("slug"):
        errors.append("family.family_slug must equal protocol.slug")

    surfaces = normalise_surfaces(grading, family)
    if not surfaces:
        errors.append("surfaces must contain at least one surface")
    surface_slugs: set[str] = set()
    primary_count = 0
    for i, surface in enumerate(surfaces):
        surface_slug = surface.get("surface_slug")
        if not surface_slug:
            errors.append(f"surfaces[{i}].surface_slug is required")
        elif surface_slug in surface_slugs:
            errors.append(f"surfaces[{i}].surface_slug {surface_slug!r} duplicated")
        surface_slugs.add(surface_slug)
        if not surface.get("display_name"):
            errors.append(f"surfaces[{i}].display_name is required")
        if surface.get("status") not in VALID_SURFACE_STATUSES:
            errors.append(
                f"surfaces[{i}].status {surface.get('status')!r} not in {sorted(VALID_SURFACE_STATUSES)}"
            )
        if not surface.get("primary_chain"):
            errors.append(f"surfaces[{i}].primary_chain is required")
        if surface.get("is_primary"):
            primary_count += 1
    if surfaces and primary_count != 1:
        errors.append("exactly one surface must be primary")

    # Deployments (optional but if present, validate)
    for i, d in enumerate(grading.get("deployments", [])):
        if not d.get("chain"):
            errors.append(f"deployments[{i}].chain is required")
        d_surface = d.get("surface_slug") or primary_surface_slug(surfaces)
        if d_surface not in surface_slugs:
            errors.append(f"deployments[{i}].surface_slug {d_surface!r} is not in surfaces")

    # Factor scores
    fs_list = grading.get("factor_scores", [])
    if not fs_list:
        errors.append("factor_scores must be a non-empty list")
    seen_scoped_factors: set[tuple[str, str, str]] = set()
    for i, fs in enumerate(fs_list):
        fid = fs.get("factor_id")
        if not fid or not fid.startswith("RD-F-"):
            errors.append(f"factor_scores[{i}].factor_id invalid: {fid!r}")
        scope = fs.get("scope_level") or fs.get("scope") or "surface"
        if scope not in VALID_FACTOR_SCORE_SCOPES:
            errors.append(f"factor_scores[{i}].scope_level {scope!r} not in {sorted(VALID_FACTOR_SCORE_SCOPES)}")
        if scope == "family":
            target = fs.get("family_slug") or family["family_slug"]
            if target != family["family_slug"]:
                errors.append(f"factor_scores[{i}].family_slug {target!r} does not match family")
        elif scope == "deployment":
            target_surface = fs.get("surface_slug") or primary_surface_slug(surfaces)
            if target_surface not in surface_slugs:
                errors.append(f"factor_scores[{i}].surface_slug {target_surface!r} is not in surfaces")
            chain = fs.get("chain") or "?"
            deployment_key = fs.get("deployment_key") or fs.get("deployment_slug") or "primary"
            target = f"{target_surface}:{chain}:{deployment_key}"
        else:
            target = fs.get("surface_slug") or primary_surface_slug(surfaces)
            if target not in surface_slugs:
                errors.append(f"factor_scores[{i}].surface_slug {target!r} is not in surfaces")
        scoped_key = (scope, target, fid)
        if scoped_key in seen_scoped_factors:
            errors.append(f"factor_scores[{i}].factor_id {fid!r} duplicated for {scope} {target!r}")
        seen_scoped_factors.add(scoped_key)

        score = fs.get("score")
        if score not in VALID_SCORES:
            errors.append(f"factor_scores[{i}].score {score!r} not in {sorted(VALID_SCORES)}")

        if not fs.get("evidence_summary"):
            errors.append(f"factor_scores[{i}].evidence_summary is required")

        if score == "not_assessed" and not fs.get("notes"):
            errors.append(f"factor_scores[{i}].notes is required when score='not_assessed'")

        cm = fs.get("collection_mode", "manual")
        if cm not in VALID_COLLECTION_MODES:
            errors.append(f"factor_scores[{i}].collection_mode {cm!r} not in {sorted(VALID_COLLECTION_MODES)}")

        gap_reason = fs.get("gap_reason")
        if gap_reason is not None:
            if gap_reason not in VALID_GAP_REASONS:
                errors.append(
                    f"factor_scores[{i}].gap_reason {gap_reason!r} not in {sorted(VALID_GAP_REASONS)}"
                )
            if score in ("green", "yellow", "red"):
                errors.append(
                    f"factor_scores[{i}].gap_reason must be null/omitted for graded score {score!r}"
                )

        sources = fs.get("sources", [])
        # ER-17: every factor_score must have ≥1 source.
        # Exception: not_assessed and not_applicable scores legitimately have no source.
        if score not in ("not_assessed", "not_applicable") and not sources:
            errors.append(f"factor_scores[{i}] (score={score!r}) requires ≥1 source per ER-17")
        for j, s in enumerate(sources):
            st = s.get("source_type")
            if st not in VALID_SOURCE_TYPES:
                errors.append(f"factor_scores[{i}].sources[{j}].source_type {st!r} not in {sorted(VALID_SOURCE_TYPES)}")
            if not s.get("reference"):
                errors.append(f"factor_scores[{i}].sources[{j}].reference is required")

    return errors


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso_date() -> str:
    return date.today().isoformat()


def upsert_protocol(cur, p: dict, rubric_version: str) -> None:
    """UPSERT into protocols. graded_at + rubric_version set NOW."""
    cur.execute(
        """
        INSERT INTO protocols (
            slug, display_name, description, homepage_url, github_org,
            defillama_slug, protocol_type, primary_chain, launched_at,
            total_value_secured_usd, graded_at, rubric_version, status,
            has_active_incident
        ) VALUES (
            %(slug)s, %(display_name)s, %(description)s, %(homepage_url)s, %(github_org)s,
            %(defillama_slug)s, %(protocol_type)s, %(primary_chain)s, %(launched_at)s,
            %(total_value_secured_usd)s, NOW(), %(rubric_version)s, %(status)s,
            COALESCE(%(has_active_incident)s, false)
        )
        ON CONFLICT (slug) DO UPDATE SET
            display_name             = EXCLUDED.display_name,
            description              = COALESCE(EXCLUDED.description, protocols.description),
            homepage_url             = COALESCE(EXCLUDED.homepage_url, protocols.homepage_url),
            github_org               = COALESCE(EXCLUDED.github_org, protocols.github_org),
            defillama_slug           = COALESCE(EXCLUDED.defillama_slug, protocols.defillama_slug),
            protocol_type            = EXCLUDED.protocol_type,
            primary_chain            = EXCLUDED.primary_chain,
            launched_at              = COALESCE(EXCLUDED.launched_at, protocols.launched_at),
            total_value_secured_usd  = COALESCE(EXCLUDED.total_value_secured_usd, protocols.total_value_secured_usd),
            graded_at                = NOW(),
            rubric_version           = EXCLUDED.rubric_version,
            status                   = EXCLUDED.status,
            has_active_incident      = COALESCE(%(has_active_incident)s, protocols.has_active_incident),
            updated_at               = NOW()
        """,
        {
            "slug": p["slug"],
            "display_name": p["display_name"],
            "description": p.get("description"),
            "homepage_url": p.get("homepage_url"),
            "github_org": p.get("github_org"),
            "defillama_slug": p.get("defillama_slug"),
            "protocol_type": p["protocol_type"],
            "primary_chain": p["primary_chain"],
            "launched_at": p.get("launched_at"),
            "total_value_secured_usd": p.get("total_value_secured_usd"),
            "rubric_version": rubric_version,
            "status": p.get("status", "live"),
            "has_active_incident": p.get("has_active_incident"),
        },
    )


def upsert_family(cur, family: dict, protocol: dict, rubric_version: str) -> None:
    cur.execute(
        """
        INSERT INTO protocol_families (
            family_slug, display_name, description, homepage_url,
            protocol_type, primary_chain, total_value_secured_usd,
            graded_at, rubric_version, status, has_active_incident,
            legacy_caveat
        ) VALUES (
            %(family_slug)s, %(display_name)s, %(description)s, %(homepage_url)s,
            %(protocol_type)s, %(primary_chain)s, %(total_value_secured_usd)s,
            NOW(), %(rubric_version)s, %(status)s,
            COALESCE(
                %(has_active_incident)s,
                (SELECT has_active_incident FROM protocols WHERE slug = %(family_slug)s),
                false
            ),
            %(legacy_caveat)s
        )
        ON CONFLICT (family_slug) DO UPDATE SET
            display_name             = EXCLUDED.display_name,
            description              = COALESCE(EXCLUDED.description, protocol_families.description),
            homepage_url             = COALESCE(EXCLUDED.homepage_url, protocol_families.homepage_url),
            protocol_type            = EXCLUDED.protocol_type,
            primary_chain            = EXCLUDED.primary_chain,
            total_value_secured_usd  = COALESCE(EXCLUDED.total_value_secured_usd, protocol_families.total_value_secured_usd),
            graded_at                = NOW(),
            rubric_version           = EXCLUDED.rubric_version,
            status                   = EXCLUDED.status,
            has_active_incident      = COALESCE(
                %(has_active_incident)s,
                (SELECT has_active_incident FROM protocols WHERE slug = %(family_slug)s),
                protocol_families.has_active_incident
            ),
            legacy_caveat            = COALESCE(EXCLUDED.legacy_caveat, protocol_families.legacy_caveat),
            updated_at               = NOW()
        """,
        {
            "family_slug": family["family_slug"],
            "display_name": family["display_name"],
            "description": family.get("description"),
            "homepage_url": family.get("homepage_url"),
            "protocol_type": family["protocol_type"],
            "primary_chain": family["primary_chain"],
            "total_value_secured_usd": protocol.get("total_value_secured_usd"),
            "rubric_version": rubric_version,
            "status": protocol.get("status", "live"),
            "has_active_incident": protocol.get("has_active_incident"),
            "legacy_caveat": family.get("legacy_caveat"),
        },
    )


def inherit_incident_state(cur: Any, protocol: dict, surfaces: list[dict]) -> bool:
    """Preserve active runtime incidents when an assessment omits the flag."""
    explicit = protocol.get("has_active_incident")
    if explicit is not None:
        return bool(explicit)

    candidate_slugs = list(
        dict.fromkeys(
            [
                protocol["slug"],
                *[
                    surface["legacy_slug"]
                    for surface in surfaces
                    if surface.get("legacy_slug")
                ],
            ]
        )
    )
    cur.execute(
        """
        SELECT
          COALESCE(bool_or(p.has_active_incident), false)
          OR EXISTS (
            SELECT 1
            FROM active_incidents ai
            WHERE ai.protocol_slug = ANY(%s)
              AND ai.status = 'open'
          ) AS has_active_incident
        FROM protocols p
        WHERE p.slug = ANY(%s)
        """,
        (candidate_slugs, candidate_slugs),
    )
    row = cur.fetchone()
    inherited = bool(row[0] if not isinstance(row, dict) else row["has_active_incident"])
    protocol["has_active_incident"] = inherited
    return inherited


def ensure_surface_set_safe(
    cur: Any,
    family: dict,
    surfaces: list[dict],
    *,
    allow_surface_removal: bool,
) -> None:
    """Block accidental partial-family imports that would deprecate live surfaces."""
    cur.execute(
        """
        SELECT surface_slug, legacy_slug
        FROM protocol_surfaces
        WHERE family_slug = %s
          AND status <> 'deprecated'
        """,
        (family["family_slug"],),
    )
    incoming = {surface["surface_slug"] for surface in surfaces}
    omitted = []
    for row in cur.fetchall():
        surface_slug = row[0] if not isinstance(row, dict) else row["surface_slug"]
        legacy_slug = row[1] if not isinstance(row, dict) else row["legacy_slug"]
        if surface_slug in incoming:
            continue
        if surface_slug == DEFAULT_SURFACE_SLUG and legacy_slug == family["family_slug"]:
            continue
        omitted.append(surface_slug)
    if omitted and not allow_surface_removal:
        raise ValueError(
            "Import omits existing active surface(s): "
            + ", ".join(sorted(omitted))
            + ". Re-run with the full family packet or explicitly pass "
            "--allow-surface-removal after review."
        )


def upsert_surfaces(cur, family: dict, surfaces: list[dict], rubric_version: str) -> dict[str, str]:
    surface_ids: dict[str, str] = {}
    legacy_slugs = [
        surface.get("legacy_slug")
        for surface in surfaces
        if surface.get("legacy_slug")
    ]
    legacy_was_published = False
    if legacy_slugs:
        cur.execute(
            "SELECT COALESCE(bool_or(is_published), false) FROM protocols WHERE slug = ANY(%s)",
            (legacy_slugs,),
        )
        legacy_was_published = bool(cur.fetchone()[0])
    if legacy_was_published:
        cur.execute(
            """
            UPDATE protocols
            SET is_published = true,
                updated_at = NOW()
            WHERE slug = %s
            """,
            (family["family_slug"],),
        )
        cur.execute(
            """
            UPDATE protocol_families
            SET is_published = true,
                updated_at = NOW()
            WHERE family_slug = %s
            """,
            (family["family_slug"],),
        )
    selected_slugs = [surface["surface_slug"] for surface in surfaces]
    for legacy_slug in legacy_slugs:
        cur.execute(
            """
            UPDATE protocol_surfaces
            SET legacy_slug = NULL,
                updated_at = NOW()
            WHERE legacy_slug = %s
              AND (
                family_slug <> %s
                OR (family_slug = %s AND NOT (surface_slug = ANY(%s)))
              )
            """,
            (legacy_slug, family["family_slug"], family["family_slug"], selected_slugs),
        )
        cur.execute(
            """
            UPDATE protocols
            SET is_published = false,
                updated_at = NOW()
            WHERE slug = %s
              AND slug <> %s
            """,
            (legacy_slug, family["family_slug"]),
        )
        cur.execute(
            """
            UPDATE protocol_families
            SET is_published = false,
                updated_at = NOW()
            WHERE family_slug = %s
              AND family_slug <> %s
            """,
            (legacy_slug, family["family_slug"]),
        )

    cur.execute(
        "UPDATE protocol_surfaces SET is_primary = false WHERE family_slug = %s",
        (family["family_slug"],),
    )
    for surface in surfaces:
        cur.execute(
            """
            INSERT INTO protocol_surfaces (
                family_slug, surface_slug, display_name, status,
                launched_at, primary_chain, tvs_usd, rubric_version,
                scope_note, is_primary, legacy_slug
            ) VALUES (
                %(family_slug)s, %(surface_slug)s, %(display_name)s, %(status)s,
                %(launched_at)s, %(primary_chain)s, %(tvs_usd)s, %(rubric_version)s,
                %(scope_note)s, %(is_primary)s, %(legacy_slug)s
            )
            ON CONFLICT (family_slug, surface_slug) DO UPDATE SET
                display_name  = EXCLUDED.display_name,
                status        = EXCLUDED.status,
                launched_at   = COALESCE(EXCLUDED.launched_at, protocol_surfaces.launched_at),
                primary_chain = EXCLUDED.primary_chain,
                tvs_usd       = COALESCE(EXCLUDED.tvs_usd, protocol_surfaces.tvs_usd),
                rubric_version = EXCLUDED.rubric_version,
                scope_note    = COALESCE(EXCLUDED.scope_note, protocol_surfaces.scope_note),
                is_primary    = EXCLUDED.is_primary,
                legacy_slug   = COALESCE(EXCLUDED.legacy_slug, protocol_surfaces.legacy_slug),
                updated_at    = NOW()
            RETURNING surface_id
            """,
            {
                "family_slug": family["family_slug"],
                "surface_slug": surface["surface_slug"],
                "display_name": surface["display_name"],
                "status": surface.get("status", "active"),
                "launched_at": surface.get("launched_at"),
                "primary_chain": surface["primary_chain"],
                "tvs_usd": surface.get("tvs_usd"),
                "rubric_version": rubric_version,
                "scope_note": surface.get("scope_note"),
                "is_primary": surface.get("is_primary", False),
                "legacy_slug": surface.get("legacy_slug"),
            },
        )
        surface_ids[surface["surface_slug"]] = str(cur.fetchone()[0])

    cur.execute(
        """
        UPDATE factor_scores
        SET is_current = false
        WHERE protocol_slug = %s
          AND is_current = true
          AND scope_level IN ('surface', 'deployment')
          AND surface_id IN (
              SELECT surface_id
              FROM protocol_surfaces
              WHERE family_slug = %s
                AND NOT (surface_slug = ANY(%s))
          )
        """,
        (family["family_slug"], family["family_slug"], selected_slugs),
    )
    cur.execute(
        """
        UPDATE protocol_surfaces
        SET status = 'deprecated',
            is_primary = false,
            legacy_slug = NULL,
            updated_at = NOW()
        WHERE family_slug = %s
          AND NOT (surface_slug = ANY(%s))
        """,
        (family["family_slug"], selected_slugs),
    )

    primary_slug = primary_surface_slug(surfaces)
    cur.execute(
        """
        UPDATE protocol_families
        SET primary_surface_id = %s::uuid,
            updated_at = NOW()
        WHERE family_slug = %s
        """,
        (surface_ids[primary_slug], family["family_slug"]),
    )
    return surface_ids


def upsert_deployments(
    cur,
    slug: str,
    deployments: list[dict],
    surface_ids: dict[str, str],
    default_surface_slug: str,
) -> tuple[int, dict[tuple[str, str, str], str]]:
    n = 0
    deployment_ids: dict[tuple[str, str, str], str] = {}
    for d in deployments:
        surface_slug = d.get("surface_slug") or default_surface_slug
        deployment_key = d.get("deployment_key") or d.get("deployment_slug") or "primary"
        cur.execute(
            """
            INSERT INTO deployments (
                protocol_slug, surface_id, deployment_key, chain,
                anchor_address, display_name, tvs_usd, tvs_share, deployed_at
            ) VALUES (
                %(protocol_slug)s, %(surface_id)s::uuid, %(deployment_key)s, %(chain)s,
                %(anchor_address)s, %(display_name)s, %(tvs_usd)s, %(tvs_share)s, %(deployed_at)s
            )
            ON CONFLICT (surface_id, chain, deployment_key) DO UPDATE SET
                protocol_slug   = EXCLUDED.protocol_slug,
                anchor_address = COALESCE(EXCLUDED.anchor_address, deployments.anchor_address),
                display_name   = COALESCE(EXCLUDED.display_name, deployments.display_name),
                tvs_usd        = COALESCE(EXCLUDED.tvs_usd, deployments.tvs_usd),
                tvs_share      = COALESCE(EXCLUDED.tvs_share, deployments.tvs_share),
                deployed_at    = COALESCE(EXCLUDED.deployed_at, deployments.deployed_at),
                updated_at     = NOW()
            RETURNING id
            """,
            {
                "protocol_slug": slug,
                "surface_id": surface_ids[surface_slug],
                "deployment_key": deployment_key,
                "chain": d["chain"],
                "anchor_address": d.get("anchor_address"),
                "display_name": d.get("display_name"),
                "tvs_usd": d.get("tvs_usd"),
                "tvs_share": d.get("tvs_share"),
                "deployed_at": d.get("deployed_at"),
            },
        )
        deployment_ids[(surface_slug, d["chain"], deployment_key)] = str(cur.fetchone()[0])
        n += 1
    return n, deployment_ids


def get_or_create_source(cur, source: dict, retrieved_by: str) -> str:
    """Find a sources row by (source_type, url, reference) or insert; return its UUID."""
    url = source.get("url") or None
    reference = source["reference"]
    source_type = source["source_type"]
    cur.execute(
        """
        SELECT id
        FROM sources
        WHERE source_type = %s
          AND reference = %s
          AND COALESCE(url, '') = COALESCE(%s, '')
        LIMIT 1
        """,
        (source_type, reference, url),
    )
    row = cur.fetchone()
    if row:
        return str(row[0])

    cur.execute(
        """
        INSERT INTO sources (source_type, url, reference, title, retrieved_at, retrieved_by, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            source_type,
            url,
            reference,
            source.get("title"),
            source.get("retrieved_at") or _now_iso(),
            retrieved_by,
            source.get("notes"),
        ),
    )
    return str(cur.fetchone()[0])


def display_path(path: Path) -> str:
    """Return a repo-relative path when possible, otherwise the absolute path."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def resolve_factor_target(
    fs: dict,
    family: dict,
    surface_ids: dict[str, str],
    deployment_ids: dict[tuple[str, str, str], str],
    default_surface_slug: str,
) -> dict[str, str | None]:
    scope = fs.get("scope_level") or fs.get("scope") or "surface"
    if scope == "family":
        return {
            "scope_level": "family",
            "family_slug": fs.get("family_slug") or family["family_slug"],
            "surface_id": None,
            "deployment_id": None,
        }
    if scope == "deployment":
        surface_slug = fs.get("surface_slug") or default_surface_slug
        deployment_key = fs.get("deployment_key") or fs.get("deployment_slug") or fs.get("chain") or "primary"
        chain = fs.get("chain")
        deployment_id = None
        if chain:
            deployment_id = deployment_ids.get((surface_slug, chain, deployment_key))
        if not deployment_id:
            raise ValueError(
                f"deployment-scoped factor {fs.get('factor_id')} references "
                f"{surface_slug}/{chain or '?'}:{deployment_key}, but no matching deployment exists"
            )
        return {
            "scope_level": "deployment",
            "family_slug": None,
            "surface_id": surface_ids[surface_slug],
            "deployment_id": deployment_id,
        }
    surface_slug = fs.get("surface_slug") or default_surface_slug
    return {
        "scope_level": "surface",
        "family_slug": None,
        "surface_id": surface_ids[surface_slug],
        "deployment_id": None,
    }


def supersede_prior_factor_scores(
    cur,
    slug: str,
    factor_id: str,
    rubric_version: str,
    target: dict[str, str | None],
    new_row_id: str,
) -> int:
    """Mark prior current rows for the same scoped factor target as superseded."""
    cur.execute(
        """
        UPDATE factor_scores
        SET is_current = false, superseded_by = %s::uuid
        WHERE protocol_slug = %s
          AND factor_id = %s
          AND rubric_version = %s
          AND scope_level = %s
          AND COALESCE(family_slug, '') = COALESCE(%s, '')
          AND COALESCE(surface_id::text, '') = COALESCE(%s, '')
          AND COALESCE(deployment_id::text, '') = COALESCE(%s, '')
          AND is_current = true
          AND id != %s::uuid
        """,
        (
            new_row_id,
            slug,
            factor_id,
            rubric_version,
            target["scope_level"],
            target["family_slug"],
            target["surface_id"],
            target["deployment_id"],
            new_row_id,
        ),
    )
    return cur.rowcount


def assessment_scoped_keys(
    factor_scores: list[dict],
    family_slug: str,
    default_surface_slug: str,
) -> set[tuple[str, str, str]]:
    keys = set()
    for fs in factor_scores:
        scope = fs.get("scope_level") or fs.get("scope") or "surface"
        if scope in {"protocol", "family"}:
            target = fs.get("family_slug") or family_slug
        elif scope == "deployment":
            surface = fs.get("surface_slug") or default_surface_slug
            chain = fs.get("chain")
            deployment_key = (
                fs.get("deployment_key")
                or fs.get("deployment_slug")
                or chain
                or "primary"
            )
            target = f"{surface}/{chain or '?'}/{deployment_key}"
        else:
            target = fs.get("surface_slug") or default_surface_slug
        keys.add((scope, target, fs["factor_id"]))
    return keys


def current_factor_scoped_rows(
    cur, slug: str
) -> tuple[tuple[str, str, str, str], ...]:
    cur.execute(
        """
        SELECT fs.rubric_version, fs.scope_level,
               CASE
                 WHEN fs.scope_level IN ('protocol', 'family')
                   THEN fs.protocol_slug
                 WHEN fs.scope_level = 'surface'
                   THEN surface_direct.surface_slug
                 ELSE CONCAT_WS('/',
                   surface_dep.surface_slug, d.chain, d.deployment_key)
               END AS target,
               fs.factor_id
        FROM factor_scores fs
        LEFT JOIN protocol_surfaces surface_direct
          ON surface_direct.surface_id=fs.surface_id
        LEFT JOIN deployments d ON d.id=fs.deployment_id
        LEFT JOIN protocol_surfaces surface_dep
          ON surface_dep.surface_id=d.surface_id
        WHERE fs.protocol_slug = %s AND fs.is_current = true
        ORDER BY 1,2,3,4
        """,
        (slug,),
    )
    return tuple(
        (str(version), str(scope), str(target), str(factor_id))
        for version, scope, target, factor_id in cur.fetchall()
    )


def ensure_v17_import_baseline_safe(
    cur,
    slug: str,
    rubric_version: str,
    expected_scoped_keys: set[tuple[str, str, str]],
) -> None:
    """Prevent generic imports from creating or extending mixed current baselines."""
    if rubric_version != "v1.7.0":
        return
    rows = current_factor_scoped_rows(cur, slug)
    if not rows:
        return
    versions = {row[0] for row in rows}
    observed_scoped_keys = {
        (scope, target, factor_id)
        for _version, scope, target, factor_id in rows
    }
    if (
        versions == {"v1.7.0"}
        and len(rows) == len(observed_scoped_keys)
        and observed_scoped_keys <= expected_scoped_keys
    ):
        return
    summary = ", ".join(
        f"{version}={sum(row[0] == version for row in rows)}"
        for version in sorted(versions)
    )
    raise ValueError(
        "generic v1.7.0 import requires any existing current rows to be a "
        "unique sole-v1.7.0 scoped subset of the incoming assessment; mixed, "
        "legacy, or scope-mismatched baselines must use "
        f"Lean Refresh Task B mixed_recovery (found {summary})"
    )


def verify_v17_import_postcondition(
    cur,
    slug: str,
    rubric_version: str,
    expected_scoped_keys: set[tuple[str, str, str]],
) -> None:
    if rubric_version != "v1.7.0":
        return
    rows = current_factor_scoped_rows(cur, slug)
    observed_scoped_keys = {
        (scope, target, factor_id)
        for version, scope, target, factor_id in rows
        if version == "v1.7.0"
    }
    if (
        {row[0] for row in rows} != {"v1.7.0"}
        or len(rows) != len(observed_scoped_keys)
        or observed_scoped_keys != expected_scoped_keys
    ):
        raise ValueError(
            "generic v1.7.0 import postcondition requires the exact incoming "
            "scoped-key set and no other current rubric rows"
        )


def insert_factor_score(
    cur,
    slug: str,
    fs: dict,
    rubric_version: str,
    retrieved_by: str,
    family: dict,
    surface_ids: dict[str, str],
    deployment_ids: dict[tuple[str, str, str], str],
    default_surface_slug: str,
) -> str:
    """Insert one factor_scores row + its factor_score_sources joins. Returns the row id."""
    target = resolve_factor_target(fs, family, surface_ids, deployment_ids, default_surface_slug)
    cur.execute(
        """
        INSERT INTO factor_scores (
            protocol_slug, scope_level, family_slug, surface_id, deployment_id,
            factor_id, rubric_version, score,
            evidence_summary, evidence_detail, collection_mode,
            gap_reason, collected_at, collected_by, data_as_of, is_current, notes
        ) VALUES (
            %(protocol_slug)s, %(scope_level)s, %(family_slug)s, %(surface_id)s::uuid, %(deployment_id)s::uuid,
            %(factor_id)s, %(rubric_version)s, %(score)s,
            %(evidence_summary)s, %(evidence_detail)s, %(collection_mode)s,
            %(gap_reason)s, NOW(), %(collected_by)s, NOW(), false, %(notes)s
        )
        RETURNING id
        """,
        {
            "protocol_slug": slug,
            "scope_level": target["scope_level"],
            "family_slug": target["family_slug"],
            "surface_id": target["surface_id"],
            "deployment_id": target["deployment_id"],
            "factor_id": fs["factor_id"],
            "rubric_version": rubric_version,
            "score": fs["score"],
            "evidence_summary": fs["evidence_summary"][:1000],   # safety cap
            "evidence_detail": fs.get("evidence_detail"),
            "collection_mode": fs.get("collection_mode", "manual"),
            "gap_reason": fs.get("gap_reason"),
            "collected_by": retrieved_by,
            "notes": fs.get("notes"),
        },
    )
    fs_id = str(cur.fetchone()[0])

    # Re-imports can already have a current row for this exact scoped target.
    # Insert the replacement as non-current first so the partial unique index
    # is not violated, supersede the prior current row, then promote this row.
    supersede_prior_factor_scores(cur, slug, fs["factor_id"], rubric_version, target, fs_id)
    cur.execute(
        """
        UPDATE factor_scores
        SET is_current = true
        WHERE id = %s::uuid
        """,
        (fs_id,),
    )

    # Insert sources + factor_score_sources joins
    seen_source_ids: set[str] = set()
    for src in fs.get("sources", []):
        source_id = get_or_create_source(cur, src, retrieved_by)
        if source_id in seen_source_ids:
            continue   # don't double-link the same source to one factor_score
        seen_source_ids.add(source_id)
        cur.execute(
            """
            INSERT INTO factor_score_sources (factor_score_id, source_id, relation)
            VALUES (%s::uuid, %s::uuid, 'primary')
            ON CONFLICT DO NOTHING
            """,
            (fs_id, source_id),
        )

    return fs_id


# ---------------------------------------------------------------------------
# Subprocess helpers (compose.py + dump.py)
# ---------------------------------------------------------------------------

def _subprocess_database_env(db_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env.pop("LOCAL_DATABASE_URL", None)
    return env


def run_compose(slug: str, dry_run: bool, db_url: str) -> int:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "compose.py"), "--protocol", slug]
    if dry_run:
        cmd.append("--dry-run")
    print(f"\n→ {' '.join(cmd[1:])}", flush=True)
    return subprocess.call(cmd, cwd=REPO_ROOT, env=_subprocess_database_env(db_url))


def run_dump(slug: str, db_url: str) -> int:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "dump.py")]
    print(f"\n→ {' '.join(cmd[1:])} (all protocols)", flush=True)
    return subprocess.call(cmd, cwd=REPO_ROOT, env=_subprocess_database_env(db_url))


def run_post_import(
    slug: str,
    db_url: str,
    *,
    skip_compose: bool,
    run_dump_requested: bool,
    skip_dump: bool,
) -> int:
    if not skip_compose:
        rc = run_compose(slug, dry_run=False, db_url=db_url)
        if rc != 0:
            print(f"\nERROR: compose.py exited {rc} for {slug}; dump skipped", file=sys.stderr)
            return rc

    if run_dump_requested and not skip_dump:
        rc = run_dump(slug, db_url=db_url)
        if rc != 0:
            print(f"\nERROR: dump.py exited {rc} for {slug}", file=sys.stderr)
            return rc
    else:
        print("\nSkipping dump.py. Run with --run-dump after review, or run scripts/dump.py manually.")

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],   # first paragraph
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug", help="Protocol slug (e.g. stargate)")
    parser.add_argument("--grading-file", help="Path to grading.json (overrides default search)")
    parser.add_argument("--rubric-version", default=RUBRIC_VERSION_DEFAULT,
                        help=f"Rubric version (default: {RUBRIC_VERSION_DEFAULT})")
    parser.add_argument("--collected-by", default="protocol-import",
                        help="Value for collected_by + retrieved_by columns")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Validate + parse only; do not write to DB or run compose/dump.")
    mode.add_argument("--apply", action="store_true",
                      help="Apply the validated import transaction.")
    parser.add_argument("--db-url", default=None,
                        help="Explicit DB URL. Defaults to LOCAL_DATABASE_URL only.")
    parser.add_argument("--expected-database", default=None,
                        help="Required exact database name for --apply.")
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--i-understand-nonlocal", action="store_true")
    parser.add_argument("--allow-protected-database", action="store_true")
    parser.add_argument("--i-understand-protected-database", action="store_true")
    parser.add_argument("--allow-surface-removal", action="store_true",
                        help="Allow omission/deprecation of an existing non-default surface.")
    parser.add_argument("--skip-compose", action="store_true",
                        help="Skip the compose.py invocation after DB writes")
    parser.add_argument("--run-dump", action="store_true",
                        help="Run dump.py after successful DB writes + compose")
    parser.add_argument("--skip-dump", action="store_true",
                        help="Deprecated compatibility flag; dump is skipped unless --run-dump is passed")
    args = parser.parse_args(argv)

    # 1. Locate + load grading.json
    try:
        path = find_grading_file(args.slug, args.grading_file)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"Reading grading from: {display_path(path)}")
    try:
        grading = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {path}: {e}", file=sys.stderr)
        return 2

    # 2. Validate structure
    errors = validate(grading, args.slug)
    if errors:
        print(f"\nValidation FAILED ({len(errors)} errors):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 3

    n_factors = len(grading["factor_scores"])
    n_deploys = len(grading.get("deployments", []))
    family = normalise_family(grading, args.slug)
    surfaces = normalise_surfaces(grading, family)
    default_surface = primary_surface_slug(surfaces)
    print(
        f"Validation OK: {n_factors} factor_scores, {n_deploys} deployments, "
        f"{len(surfaces)} surface(s)"
    )

    if args.dry_run:
        print("\n--dry-run: validation only; skipping DB writes, compose.py, and dump.py")
        return 0

    # 3. DB connection
    try:
        db_url, target = resolve_database_url(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg (v3) not installed. pip install psycopg", file=sys.stderr)
        return 1

    # 4. Transactional DB writes
    # connect_timeout=10: prevents indefinite hang if Docker Postgres is paused
    # or the connection string points at an unreachable host. Failure here
    # propagates as a normal exception → orchestrator catches → quarantine.
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            print(
                f"\nWriting to database {target['database']} on "
                f"{target['host']}:{target['port'] or 'default'}..."
            )
            ensure_v17_import_baseline_safe(
                cur,
                args.slug,
                args.rubric_version,
                assessment_scoped_keys(
                    grading["factor_scores"],
                    family["family_slug"],
                    default_surface,
                ),
            )
            ensure_surface_set_safe(
                cur,
                family,
                surfaces,
                allow_surface_removal=args.allow_surface_removal,
            )
            inherit_incident_state(cur, grading["protocol"], surfaces)
            upsert_protocol(cur, grading["protocol"], args.rubric_version)
            upsert_family(cur, family, grading["protocol"], args.rubric_version)
            surface_ids = upsert_surfaces(cur, family, surfaces, args.rubric_version)
            n_dep, deployment_ids = upsert_deployments(
                cur,
                args.slug,
                grading.get("deployments", []),
                surface_ids,
                default_surface,
            )
            n_fs = 0
            n_src_links = 0
            expected_scoped_keys = assessment_scoped_keys(
                grading["factor_scores"],
                family["family_slug"],
                default_surface,
            )
            for fs in grading["factor_scores"]:
                insert_factor_score(
                    cur,
                    args.slug,
                    fs,
                    args.rubric_version,
                    args.collected_by,
                    family,
                    surface_ids,
                    deployment_ids,
                    default_surface,
                )
                n_fs += 1
                n_src_links += len(fs.get("sources", []))
            verify_v17_import_postcondition(
                cur,
                args.slug,
                args.rubric_version,
                expected_scoped_keys,
            )
            print("  protocol UPSERTed")
            print(f"  family {family['family_slug']} UPSERTed")
            print(f"  {len(surface_ids)} surfaces UPSERTed")
            print(f"  {n_dep} deployments UPSERTed")
            print(f"  {n_fs} factor_scores INSERTed (prior current rows superseded)")
            print(f"  {n_src_links} factor_score_sources joins")

    # 5. Compose and optional dump must stay on the validated target and fail closed.
    rc = run_post_import(
        args.slug,
        db_url,
        skip_compose=args.skip_compose,
        run_dump_requested=args.run_dump,
        skip_dump=args.skip_dump,
    )
    if rc != 0:
        return rc

    print(f"\nDone: {args.slug} imported successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
