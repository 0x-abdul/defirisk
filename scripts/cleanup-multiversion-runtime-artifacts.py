#!/usr/bin/env python3
"""Remove stale standalone multi-version protocol runtime rows.

This is a local/public-transfer-safe cleanup utility for the preservation-first
multi-version migration. It preserves canonical family surfaces and removes old
standalone protocol/family/default-surface rows that are now represented by
protocol_surfaces.legacy_slug aliases.

Usage:
    python scripts/cleanup-multiversion-runtime-artifacts.py --dry-run --manifest PATH
    python scripts/cleanup-multiversion-runtime-artifacts.py --apply --manifest PATH

By default the script requires LOCAL_DATABASE_URL from .env/environment and
refuses non-local hosts. It never uses DATABASE_URL implicitly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("ERROR: psycopg v3 is required. Install with: pip install 'psycopg[binary]'", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUDIT_DIR = REPO_ROOT / "_local" / "family-cleanup-audits"

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PROTECTED_DATABASES = {"risk_dashboard"}
EXPECTED_NO_ACTION_FKS = {
    ("grade_history", "deployment_id", "deployments", "id"),
    ("factor_scores", "superseded_by", "factor_scores", "id"),
    ("active_incidents", "hack_id", "hacks", "id"),
    ("protocol_families", "family_slug", "protocol_surfaces", "family_slug"),
    ("protocol_families", "primary_surface_id", "protocol_surfaces", "surface_id"),
    ("hacks", "protocol_slug", "protocols", "slug"),
}
FK_TARGET_TABLES = {
    "protocols",
    "protocol_families",
    "protocol_surfaces",
    "deployments",
    "factor_scores",
    "hacks",
}


class CleanupError(RuntimeError):
    """Raised when cleanup preconditions or postconditions fail."""


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def get_database_url(args: argparse.Namespace) -> str:
    if args.db_url:
        return args.db_url
    url = os.environ.get("LOCAL_DATABASE_URL")
    if not url:
        raise CleanupError("LOCAL_DATABASE_URL is required; DATABASE_URL is intentionally not used.")
    return url


def database_target(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": (parsed.path or "").lstrip("/"),
        "user": parsed.username,
        "is_local_host": parsed.hostname in LOCAL_HOSTS,
    }


def require_local_database(url: str, args: argparse.Namespace) -> dict[str, Any]:
    target = database_target(url)
    if not args.expected_database:
        raise CleanupError("--expected-database is required.")
    if target["database"] != args.expected_database:
        raise CleanupError(
            f"Database identity mismatch: connected URL names {target['database']!r}, "
            f"expected {args.expected_database!r}."
        )
    if target["host"] not in LOCAL_HOSTS and not args.allow_nonlocal:
        raise CleanupError(
            "Refusing to run against a non-local database host. "
            "Use --allow-nonlocal only after a separate explicit production-transfer approval."
        )
    if target["host"] not in LOCAL_HOSTS and args.allow_nonlocal and not args.i_understand_nonlocal:
        raise CleanupError("--allow-nonlocal requires --i-understand-nonlocal.")
    if target["database"] in PROTECTED_DATABASES:
        if not args.allow_protected_database or not args.i_understand_protected_database:
            raise CleanupError(
                "Refusing protected database without --allow-protected-database "
                "and --i-understand-protected-database."
            )
    return target


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {"canonical_families", "old_standalone_slugs", "dead_canonical_default_surfaces"}
    missing = sorted(required - set(manifest))
    if missing:
        raise CleanupError(f"Manifest missing keys: {', '.join(missing)}")
    return manifest


def old_slugs(manifest: dict[str, Any]) -> list[str]:
    return sorted(manifest["old_standalone_slugs"])


def canonical_families(manifest: dict[str, Any]) -> list[str]:
    return sorted(manifest["canonical_families"])


def dead_surface_specs(manifest: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "family_slug": item["canonical_family_slug"],
            "surface_slug": item["surface_slug"],
        }
        for item in manifest["dead_canonical_default_surfaces"]
    ]


def fetch_all(cur: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def fetch_one(cur: Any, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cur.execute(query, params)
    row = cur.fetchone()
    return dict(row) if row else None


def fetch_fk_edges(cur: Any) -> list[dict[str, Any]]:
    return fetch_all(
        cur,
        """
        SELECT
            source_table.relname AS table_name,
            source_column.attname AS column_name,
            target_table.relname AS foreign_table_name,
            target_column.attname AS foreign_column_name,
            CASE constraint_row.confdeltype
              WHEN 'a' THEN 'NO ACTION'
              WHEN 'r' THEN 'RESTRICT'
              WHEN 'c' THEN 'CASCADE'
              WHEN 'n' THEN 'SET NULL'
              WHEN 'd' THEN 'SET DEFAULT'
            END AS delete_rule
        FROM pg_constraint constraint_row
        JOIN pg_class source_table ON source_table.oid = constraint_row.conrelid
        JOIN pg_namespace source_schema ON source_schema.oid = source_table.relnamespace
        JOIN pg_class target_table ON target_table.oid = constraint_row.confrelid
        JOIN LATERAL unnest(constraint_row.conkey) WITH ORDINALITY
          AS source_key(attnum, position) ON true
        JOIN LATERAL unnest(constraint_row.confkey) WITH ORDINALITY
          AS target_key(attnum, position) ON target_key.position = source_key.position
        JOIN pg_attribute source_column
          ON source_column.attrelid = source_table.oid
         AND source_column.attnum = source_key.attnum
        JOIN pg_attribute target_column
          ON target_column.attrelid = target_table.oid
         AND target_column.attnum = target_key.attnum
        WHERE constraint_row.contype = 'f'
          AND source_schema.nspname = 'public'
          AND target_table.relname = ANY(%s)
        ORDER BY target_table.relname, source_table.relname, source_key.position
        """,
        (sorted(FK_TARGET_TABLES),),
    )


def validate_fk_edges(fk_edges: list[dict[str, Any]]) -> None:
    blockers: list[dict[str, Any]] = []
    for edge in fk_edges:
        if edge["delete_rule"] not in {"NO ACTION", "RESTRICT"}:
            continue
        key = (
            edge["table_name"],
            edge["column_name"],
            edge["foreign_table_name"],
            edge["foreign_column_name"],
        )
        if key not in EXPECTED_NO_ACTION_FKS:
            blockers.append(edge)
    if blockers:
        raise CleanupError(
            "Unexpected NO ACTION/RESTRICT foreign keys found: "
            + json.dumps(blockers, default=json_default)
        )


def select_dead_surfaces(cur: Any, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in dead_surface_specs(manifest):
        rows.extend(
            fetch_all(
                cur,
                """
                SELECT
                    ps.surface_id::text AS surface_id,
                    ps.family_slug,
                    ps.surface_slug,
                    ps.display_name,
                    ps.status::text AS status,
                    ps.is_primary,
                    ps.legacy_slug,
                    pf.primary_surface_id::text AS family_primary_surface_id,
                    (SELECT count(*) FROM deployments d WHERE d.surface_id = ps.surface_id) AS deployments,
                    (SELECT count(*) FROM factor_scores fs WHERE fs.surface_id = ps.surface_id) AS factor_scores,
                    (SELECT count(*) FROM factor_scores fs WHERE fs.surface_id = ps.surface_id AND fs.is_current = true) AS current_factor_scores,
                    (SELECT count(*) FROM grade_history gh WHERE gh.surface_id = ps.surface_id) AS grade_history,
                    (SELECT count(*) FROM protocol_grade_history pgh WHERE pgh.surface_id = ps.surface_id) AS protocol_grade_history,
                    (SELECT count(*) FROM factor_score_history fsh WHERE fsh.surface_id = ps.surface_id) AS factor_score_history
                FROM protocol_surfaces ps
                JOIN protocol_families pf ON pf.family_slug = ps.family_slug
                WHERE ps.family_slug = %s
                  AND ps.surface_slug = %s
                """,
                (spec["family_slug"], spec["surface_slug"]),
            )
        )
    return rows


def fetch_snapshot(cur: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    slugs = old_slugs(manifest)
    families = canonical_families(manifest)
    dead_surfaces = select_dead_surfaces(cur, manifest)
    target_surface_ids = [row["surface_id"] for row in dead_surfaces]

    old_surfaces = fetch_all(
        cur,
        """
        SELECT surface_id::text AS surface_id, family_slug, surface_slug,
               display_name, status::text AS status, is_primary, legacy_slug
        FROM protocol_surfaces
        WHERE family_slug = ANY(%s)
        ORDER BY family_slug, surface_slug
        """,
        (slugs,),
    )
    target_surface_ids.extend(row["surface_id"] for row in old_surfaces)
    target_surface_ids = sorted(set(target_surface_ids))

    deployment_where = "protocol_slug = ANY(%s)"
    deployment_params: list[Any] = [slugs]
    if target_surface_ids:
        deployment_where += " OR surface_id::text = ANY(%s)"
        deployment_params.append(target_surface_ids)
    deployments = fetch_all(
        cur,
        f"""
        SELECT id::text AS id, protocol_slug, surface_id::text AS surface_id,
               chain, deployment_key, display_name
        FROM deployments
        WHERE {deployment_where}
        ORDER BY protocol_slug, chain, deployment_key NULLS LAST
        """,
        tuple(deployment_params),
    )
    deployment_ids = sorted(row["id"] for row in deployments)

    target_factor_where = ["protocol_slug = ANY(%s)", "family_slug = ANY(%s)"]
    target_factor_params: list[Any] = [slugs, slugs]
    if target_surface_ids:
        target_factor_where.append("surface_id::text = ANY(%s)")
        target_factor_params.append(target_surface_ids)
    if deployment_ids:
        target_factor_where.append("deployment_id::text = ANY(%s)")
        target_factor_params.append(deployment_ids)
    factor_scores = fetch_all(
        cur,
        f"""
        SELECT id::text AS id, protocol_slug, family_slug, surface_id::text AS surface_id,
               deployment_id::text AS deployment_id, factor_id, score::text AS score,
               scope_level, is_current, superseded_by::text AS superseded_by
        FROM factor_scores
        WHERE {' OR '.join(target_factor_where)}
        ORDER BY protocol_slug, family_slug, surface_id, deployment_id, factor_id, id
        """,
        tuple(target_factor_params),
    )
    factor_score_ids = sorted(row["id"] for row in factor_scores)

    history_where = ["protocol_slug = ANY(%s)", "family_slug = ANY(%s)"]
    history_params: list[Any] = [slugs, slugs]
    if target_surface_ids:
        history_where.append("surface_id::text = ANY(%s)")
        history_params.append(target_surface_ids)
    if deployment_ids:
        history_where.append("deployment_id::text = ANY(%s)")
        history_params.append(deployment_ids)
    grade_history = fetch_all(
        cur,
        f"""
        SELECT id::text AS id, protocol_slug, family_slug, surface_id::text AS surface_id,
               deployment_id::text AS deployment_id, letter, graded_at
        FROM grade_history
        WHERE {' OR '.join(history_where)}
        ORDER BY protocol_slug, family_slug, surface_id, deployment_id, graded_at, id
        """,
        tuple(history_params),
    )

    scoped_history_where = ["protocol_slug = ANY(%s)", "family_slug = ANY(%s)"]
    scoped_history_params: list[Any] = [slugs, slugs]
    if target_surface_ids:
        scoped_history_where.append("surface_id::text = ANY(%s)")
        scoped_history_params.append(target_surface_ids)
    protocol_grade_history = fetch_all(
        cur,
        f"""
        SELECT id::text AS id, protocol_slug, family_slug, surface_id::text AS surface_id,
               grade_letter, snapshot_at
        FROM protocol_grade_history
        WHERE {' OR '.join(scoped_history_where)}
        ORDER BY protocol_slug, family_slug, surface_id, snapshot_at, id
        """,
        tuple(scoped_history_params),
    )

    factor_history_where = list(scoped_history_where)
    factor_history_params = list(scoped_history_params)
    if deployment_ids:
        factor_history_where.append("deployment_id::text = ANY(%s)")
        factor_history_params.append(deployment_ids)
    factor_score_history = fetch_all(
        cur,
        f"""
        SELECT id::text AS id, protocol_slug, family_slug, surface_id::text AS surface_id,
               deployment_id::text AS deployment_id, factor_id, score_color, snapshot_at
        FROM factor_score_history
        WHERE {' OR '.join(factor_history_where)}
        ORDER BY protocol_slug, family_slug, surface_id, deployment_id, factor_id, snapshot_at, id
        """,
        tuple(factor_history_params),
    )

    surviving_superseded_refs: list[dict[str, Any]] = []
    doomed_superseded_out_refs: list[dict[str, Any]] = []
    if factor_score_ids:
        surviving_superseded_refs = fetch_all(
            cur,
            """
            SELECT id::text AS id, protocol_slug, factor_id,
                   superseded_by::text AS superseded_by
            FROM factor_scores
            WHERE superseded_by::text = ANY(%s)
              AND NOT (id::text = ANY(%s))
            ORDER BY protocol_slug, factor_id, id
            """,
            (factor_score_ids, factor_score_ids),
        )
        doomed_superseded_out_refs = fetch_all(
            cur,
            """
            SELECT id::text AS id, protocol_slug, factor_id,
                   superseded_by::text AS superseded_by
            FROM factor_scores
            WHERE id::text = ANY(%s)
              AND superseded_by IS NOT NULL
              AND NOT (superseded_by::text = ANY(%s))
            ORDER BY protocol_slug, factor_id, id
            """,
            (factor_score_ids, factor_score_ids),
        )

    return {
        "old_protocols": fetch_all(
            cur,
            """
            SELECT slug, display_name, status::text AS status, is_published,
                   headline_grade, review_token IS NOT NULL AS has_review_token
            FROM protocols
            WHERE slug = ANY(%s)
            ORDER BY slug
            """,
            (slugs,),
        ),
        "old_families": fetch_all(
            cur,
            """
            SELECT family_slug, display_name, status::text AS status, is_published,
                   primary_surface_id::text AS primary_surface_id
            FROM protocol_families
            WHERE family_slug = ANY(%s)
            ORDER BY family_slug
            """,
            (slugs,),
        ),
        "old_surfaces": old_surfaces,
        "dead_surfaces": dead_surfaces,
        "deployments": deployments,
        "factor_scores": factor_scores,
        "factor_score_source_count": fetch_one(
            cur,
            """
            SELECT count(*) AS count
            FROM factor_score_sources
            WHERE factor_score_id::text = ANY(%s)
            """,
            (factor_score_ids if factor_score_ids else ["00000000-0000-0000-0000-000000000000"],),
        )["count"],
        "grade_history": grade_history,
        "protocol_grade_history": protocol_grade_history,
        "factor_score_history": factor_score_history,
        "grade_changes": fetch_all(
            cur,
            """
            SELECT id::text AS id, protocol_slug, from_grade, to_grade, detected_at
            FROM grade_changes
            WHERE protocol_slug = ANY(%s)
            ORDER BY protocol_slug, detected_at, id
            """,
            (slugs,),
        ),
        "protocol_service_providers": fetch_all(
            cur,
            """
            SELECT protocol_slug, provider_id::text AS provider_id, relationship
            FROM protocol_service_providers
            WHERE protocol_slug = ANY(%s)
            ORDER BY protocol_slug, provider_id, relationship
            """,
            (slugs,),
        ),
        "hacks_to_remap": fetch_all(
            cur,
            """
            SELECT id, protocol_slug, protocol_name, occurred_at, loss_usd, category
            FROM hacks
            WHERE protocol_slug = ANY(%s)
            ORDER BY protocol_slug, occurred_at NULLS LAST, id
            """,
            (slugs,),
        ),
        "active_incidents_to_remap": fetch_all(
            cur,
            """
            SELECT id::text AS id, protocol_slug, hack_id, severity::text AS severity,
                   status::text AS status, opened_at
            FROM active_incidents
            WHERE protocol_slug = ANY(%s)
            ORDER BY protocol_slug, opened_at, id
            """,
            (slugs,),
        ),
        "canonical_protocols": fetch_all(
            cur,
            """
            SELECT slug, display_name, status::text AS status, is_published, headline_grade
            FROM protocols
            WHERE slug = ANY(%s)
            ORDER BY slug
            """,
            (families,),
        ),
        "canonical_surfaces": fetch_all(
            cur,
            """
            SELECT family_slug, surface_slug, surface_id::text AS surface_id,
                   status::text AS status, is_primary, legacy_slug, headline_grade
            FROM protocol_surfaces
            WHERE family_slug = ANY(%s)
            ORDER BY family_slug, surface_slug
            """,
            (families,),
        ),
        "alias_collisions": fetch_all(
            cur,
            """
            SELECT legacy_slug, count(*) AS count,
                   array_agg(family_slug || '/' || surface_slug ORDER BY family_slug, surface_slug) AS surfaces
            FROM protocol_surfaces
            WHERE legacy_slug IS NOT NULL
            GROUP BY legacy_slug
            HAVING count(*) > 1
            ORDER BY legacy_slug
            """,
        ),
        "surviving_superseded_refs_to_null": surviving_superseded_refs,
        "doomed_superseded_out_refs": doomed_superseded_out_refs,
        "ids": {
            "target_surface_ids": target_surface_ids,
            "deployment_ids": deployment_ids,
            "factor_score_ids": factor_score_ids,
            "grade_history_ids": [row["id"] for row in grade_history],
            "protocol_grade_history_ids": [row["id"] for row in protocol_grade_history],
            "factor_score_history_ids": [row["id"] for row in factor_score_history],
            "grade_change_ids": [row["id"] for row in fetch_all(
                cur,
                "SELECT id::text AS id FROM grade_changes WHERE protocol_slug = ANY(%s) ORDER BY id",
                (slugs,),
            )],
        },
    }


def summarize_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    return {
        "old_protocols": len(snapshot["old_protocols"]),
        "old_families": len(snapshot["old_families"]),
        "old_surfaces": len(snapshot["old_surfaces"]),
        "dead_surfaces": len(snapshot["dead_surfaces"]),
        "deployments": len(snapshot["deployments"]),
        "factor_scores": len(snapshot["factor_scores"]),
        "factor_score_sources": int(snapshot["factor_score_source_count"]),
        "grade_history": len(snapshot["grade_history"]),
        "protocol_grade_history": len(snapshot["protocol_grade_history"]),
        "factor_score_history": len(snapshot["factor_score_history"]),
        "grade_changes": len(snapshot["grade_changes"]),
        "protocol_service_providers": len(snapshot["protocol_service_providers"]),
        "hacks_to_remap": len(snapshot["hacks_to_remap"]),
        "active_incidents_to_remap": len(snapshot["active_incidents_to_remap"]),
        "surviving_superseded_refs_to_null": len(snapshot["surviving_superseded_refs_to_null"]),
    }


def validate_preconditions(cur: Any, manifest: dict[str, Any], snapshot: dict[str, Any], fk_edges: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    slugs = old_slugs(manifest)
    family_slugs = canonical_families(manifest)

    validate_fk_edges(fk_edges)

    old_protocols_by_slug = {row["slug"]: row for row in snapshot["old_protocols"]}
    for slug, row in old_protocols_by_slug.items():
        if row["is_published"]:
            issues.append(f"Old standalone protocol {slug} is published; refusing to delete.")

    canonical_protocols_by_slug = {row["slug"]: row for row in snapshot["canonical_protocols"]}
    for family_slug in family_slugs:
        proto = canonical_protocols_by_slug.get(family_slug)
        if not proto:
            issues.append(f"Canonical protocol row missing: {family_slug}")
        elif not proto["is_published"]:
            issues.append(f"Canonical protocol {family_slug} is not published; alias replacement would not export.")

    canonical_surface_map = {
        (row["family_slug"], row["surface_slug"]): row
        for row in snapshot["canonical_surfaces"]
    }
    legacy_surface_map: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot["canonical_surfaces"]:
        if row["legacy_slug"]:
            legacy_surface_map.setdefault(row["legacy_slug"], []).append(row)

    for slug, mapping in manifest["old_standalone_slugs"].items():
        family_slug = mapping["canonical_family_slug"]
        surface_slug = mapping["canonical_surface_slug"]
        surface = canonical_surface_map.get((family_slug, surface_slug))
        if not surface:
            issues.append(f"Canonical surface missing for {slug}: {family_slug}/{surface_slug}")
            continue
        if surface.get("legacy_slug") != slug:
            issues.append(
                f"Canonical surface {family_slug}/{surface_slug} legacy_slug is "
                f"{surface.get('legacy_slug')!r}, expected {slug!r}."
            )
        matches = legacy_surface_map.get(slug, [])
        if len(matches) != 1:
            issues.append(f"Legacy alias {slug} resolves to {len(matches)} surfaces, expected exactly 1.")

    if snapshot["alias_collisions"]:
        issues.append("Duplicate protocol_surfaces.legacy_slug values exist.")

    for family_slug, expected_surfaces in manifest["canonical_families"].items():
        present = {
            row["surface_slug"]
            for row in snapshot["canonical_surfaces"]
            if row["family_slug"] == family_slug
        }
        missing = sorted(set(expected_surfaces) - present)
        if missing:
            issues.append(f"Canonical surfaces missing for {family_slug}: {', '.join(missing)}")
        primaries = [
            row
            for row in snapshot["canonical_surfaces"]
            if row["family_slug"] == family_slug and row["is_primary"]
        ]
        if len(primaries) != 1:
            issues.append(f"Canonical family {family_slug} has {len(primaries)} primary surfaces, expected 1.")

    for surface in snapshot["dead_surfaces"]:
        label = f"{surface['family_slug']}/{surface['surface_slug']}"
        if surface["status"] != "deprecated":
            issues.append(f"Dead default surface {label} is status {surface['status']}, expected deprecated.")
        if surface["is_primary"]:
            issues.append(f"Dead default surface {label} is marked primary.")
        if surface["legacy_slug"]:
            issues.append(f"Dead default surface {label} has legacy_slug {surface['legacy_slug']!r}.")
        if surface["family_primary_surface_id"] == surface["surface_id"]:
            issues.append(f"Dead default surface {label} is the family primary_surface_id.")
        if int(surface["current_factor_scores"]) != 0:
            issues.append(f"Dead default surface {label} has current factor rows; expected zero.")

    for slug in slugs:
        target = manifest["old_standalone_slugs"][slug]["canonical_family_slug"]
        if target not in canonical_protocols_by_slug:
            issues.append(f"Remap target protocol missing for {slug}: {target}")

    if issues:
        raise CleanupError("Precondition validation failed:\n- " + "\n- ".join(issues))
    return issues


def remap_slug(cur: Any, table: str, slug: str, target_slug: str) -> list[str]:
    id_expr = "id::text" if table == "active_incidents" else "id"
    cur.execute(
        f"""
        UPDATE {table}
        SET protocol_slug = %s
        WHERE protocol_slug = %s
        RETURNING {id_expr} AS id
        """,
        (target_slug, slug),
    )
    return [str(row["id"]) for row in cur.fetchall()]


def delete_by_ids(cur: Any, table: str, ids: list[str]) -> int:
    if not ids:
        return 0
    cur.execute(f"DELETE FROM {table} WHERE id::text = ANY(%s)", (ids,))
    return int(cur.rowcount)


def apply_cleanup(cur: Any, manifest: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    slugs = old_slugs(manifest)
    effects: dict[str, Any] = {
        "hack_remaps": {},
        "active_incident_remaps": {},
        "deleted": {},
        "cleared_primary_surface_families": [],
        "nulled_superseded_refs": [],
    }

    for slug, mapping in manifest["old_standalone_slugs"].items():
        target_slug = mapping["canonical_family_slug"]
        hack_ids = remap_slug(cur, "hacks", slug, target_slug)
        incident_ids = remap_slug(cur, "active_incidents", slug, target_slug)
        if hack_ids:
            effects["hack_remaps"][slug] = {"target": target_slug, "ids": hack_ids}
        if incident_ids:
            effects["active_incident_remaps"][slug] = {"target": target_slug, "ids": incident_ids}

    factor_score_ids = snapshot["ids"]["factor_score_ids"]
    if factor_score_ids:
        cur.execute(
            """
            UPDATE factor_scores
            SET superseded_by = NULL
            WHERE superseded_by::text = ANY(%s)
              AND NOT (id::text = ANY(%s))
            RETURNING id::text AS id
            """,
            (factor_score_ids, factor_score_ids),
        )
        effects["nulled_superseded_refs"] = [row["id"] for row in cur.fetchall()]

    effects["deleted"]["grade_history"] = delete_by_ids(cur, "grade_history", snapshot["ids"]["grade_history_ids"])
    effects["deleted"]["protocol_grade_history"] = delete_by_ids(
        cur,
        "protocol_grade_history",
        snapshot["ids"]["protocol_grade_history_ids"],
    )
    effects["deleted"]["factor_score_history"] = delete_by_ids(
        cur,
        "factor_score_history",
        snapshot["ids"]["factor_score_history_ids"],
    )
    effects["deleted"]["grade_changes"] = delete_by_ids(cur, "grade_changes", snapshot["ids"]["grade_change_ids"])

    cur.execute(
        """
        DELETE FROM protocol_service_providers
        WHERE protocol_slug = ANY(%s)
        """,
        (slugs,),
    )
    effects["deleted"]["protocol_service_providers"] = int(cur.rowcount)

    effects["deleted"]["factor_scores"] = delete_by_ids(cur, "factor_scores", factor_score_ids)

    cur.execute(
        """
        UPDATE protocol_families
        SET primary_surface_id = NULL
        WHERE family_slug = ANY(%s)
          AND primary_surface_id IS NOT NULL
        RETURNING family_slug
        """,
        (slugs,),
    )
    effects["cleared_primary_surface_families"] = [row["family_slug"] for row in cur.fetchall()]

    effects["deleted"]["deployments"] = delete_by_ids(cur, "deployments", snapshot["ids"]["deployment_ids"])

    surface_ids = snapshot["ids"]["target_surface_ids"]
    if surface_ids:
        cur.execute(
            """
            DELETE FROM protocol_surfaces
            WHERE surface_id::text = ANY(%s)
            """,
            (surface_ids,),
        )
        effects["deleted"]["protocol_surfaces"] = int(cur.rowcount)
    else:
        effects["deleted"]["protocol_surfaces"] = 0

    cur.execute("DELETE FROM protocol_families WHERE family_slug = ANY(%s)", (slugs,))
    effects["deleted"]["protocol_families"] = int(cur.rowcount)

    cur.execute("DELETE FROM protocols WHERE slug = ANY(%s)", (slugs,))
    effects["deleted"]["protocols"] = int(cur.rowcount)

    return effects


def post_cleanup_checks(cur: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    slugs = old_slugs(manifest)
    families = canonical_families(manifest)
    mappings = manifest["old_standalone_slugs"]
    dead_specs = dead_surface_specs(manifest)

    checks = {
        "old_protocol_rows": fetch_one(cur, "SELECT count(*) AS count FROM protocols WHERE slug = ANY(%s)", (slugs,))["count"],
        "old_family_rows": fetch_one(cur, "SELECT count(*) AS count FROM protocol_families WHERE family_slug = ANY(%s)", (slugs,))["count"],
        "old_surface_rows": fetch_one(cur, "SELECT count(*) AS count FROM protocol_surfaces WHERE family_slug = ANY(%s)", (slugs,))["count"],
        "old_deployment_rows": fetch_one(cur, "SELECT count(*) AS count FROM deployments WHERE protocol_slug = ANY(%s)", (slugs,))["count"],
        "old_factor_score_rows": fetch_one(cur, "SELECT count(*) AS count FROM factor_scores WHERE protocol_slug = ANY(%s) OR family_slug = ANY(%s)", (slugs, slugs))["count"],
        "old_grade_history_rows": fetch_one(cur, "SELECT count(*) AS count FROM grade_history WHERE protocol_slug = ANY(%s) OR family_slug = ANY(%s)", (slugs, slugs))["count"],
        "old_protocol_grade_history_rows": fetch_one(cur, "SELECT count(*) AS count FROM protocol_grade_history WHERE protocol_slug = ANY(%s) OR family_slug = ANY(%s)", (slugs, slugs))["count"],
        "old_factor_score_history_rows": fetch_one(cur, "SELECT count(*) AS count FROM factor_score_history WHERE protocol_slug = ANY(%s) OR family_slug = ANY(%s)", (slugs, slugs))["count"],
        "old_hack_refs": fetch_one(cur, "SELECT count(*) AS count FROM hacks WHERE protocol_slug = ANY(%s)", (slugs,))["count"],
        "old_active_incident_refs": fetch_one(cur, "SELECT count(*) AS count FROM active_incidents WHERE protocol_slug = ANY(%s)", (slugs,))["count"],
        "alias_collisions": fetch_all(
            cur,
            """
            SELECT legacy_slug, count(*) AS count
            FROM protocol_surfaces
            WHERE legacy_slug IS NOT NULL
            GROUP BY legacy_slug
            HAVING count(*) > 1
            ORDER BY legacy_slug
            """,
        ),
        "canonical_surface_missing": [],
        "canonical_primary_counts": fetch_all(
            cur,
            """
            SELECT family_slug, count(*) FILTER (WHERE is_primary) AS primary_count
            FROM protocol_surfaces
            WHERE family_slug = ANY(%s)
            GROUP BY family_slug
            ORDER BY family_slug
            """,
            (families,),
        ),
        "legacy_alias_resolution": [],
        "dead_surface_rows": [],
    }

    for family_slug, surfaces in manifest["canonical_families"].items():
        for surface_slug in surfaces:
            row = fetch_one(
                cur,
                """
                SELECT surface_id::text AS surface_id
                FROM protocol_surfaces
                WHERE family_slug = %s AND surface_slug = %s
                """,
                (family_slug, surface_slug),
            )
            if not row:
                checks["canonical_surface_missing"].append(f"{family_slug}/{surface_slug}")

    for old_slug, mapping in mappings.items():
        rows = fetch_all(
            cur,
            """
            SELECT family_slug, surface_slug, surface_id::text AS surface_id, legacy_slug
            FROM protocol_surfaces
            WHERE legacy_slug = %s
            ORDER BY family_slug, surface_slug
            """,
            (old_slug,),
        )
        checks["legacy_alias_resolution"].append({"legacy_slug": old_slug, "matches": rows})

    for spec in dead_specs:
        rows = fetch_all(
            cur,
            """
            SELECT surface_id::text AS surface_id, family_slug, surface_slug
            FROM protocol_surfaces
            WHERE family_slug = %s AND surface_slug = %s
            """,
            (spec["family_slug"], spec["surface_slug"]),
        )
        checks["dead_surface_rows"].extend(rows)

    failures: list[str] = []
    zero_keys = [
        "old_protocol_rows",
        "old_family_rows",
        "old_surface_rows",
        "old_deployment_rows",
        "old_factor_score_rows",
        "old_grade_history_rows",
        "old_protocol_grade_history_rows",
        "old_factor_score_history_rows",
        "old_hack_refs",
        "old_active_incident_refs",
    ]
    for key in zero_keys:
        if int(checks[key]) != 0:
            failures.append(f"{key}={checks[key]}")
    if checks["alias_collisions"]:
        failures.append("alias_collisions present")
    if checks["canonical_surface_missing"]:
        failures.append("canonical surfaces missing")
    for row in checks["canonical_primary_counts"]:
        if int(row["primary_count"]) != 1:
            failures.append(f"{row['family_slug']} primary_count={row['primary_count']}")
    for item in checks["legacy_alias_resolution"]:
        if len(item["matches"]) != 1:
            failures.append(f"{item['legacy_slug']} alias matches={len(item['matches'])}")
    if checks["dead_surface_rows"]:
        failures.append("dead default surfaces still present")
    if failures:
        raise CleanupError("Post-cleanup checks failed: " + "; ".join(failures))
    return checks


def write_audit(path: Path, audit: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit, default=json_default, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean stale standalone multi-version protocol runtime rows.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate and write planned audit; no DB writes.")
    mode.add_argument("--apply", action="store_true", help="Apply cleanup in one transaction.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--db-url", default=None, help="Explicit DB URL. Defaults to LOCAL_DATABASE_URL only.")
    parser.add_argument("--expected-database", required=True, help="Exact database name expected in the connection URL.")
    parser.add_argument("--allow-nonlocal", action="store_true", help="Allow a non-local DB host after explicit approval.")
    parser.add_argument("--i-understand-nonlocal", action="store_true", help="Second guard required with --allow-nonlocal.")
    parser.add_argument("--allow-protected-database", action="store_true")
    parser.add_argument("--i-understand-protected-database", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(REPO_ROOT / ".env")
    manifest = load_manifest(args.manifest)
    db_url = get_database_url(args)
    target = require_local_database(db_url, args)
    mode = "apply" if args.apply else "dry-run"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    audit_path = args.audit_dir / f"runtime-cleanup-{mode}-audit.json"

    with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '30s'")
            db_identity = fetch_one(
                cur,
                """
                SELECT current_database() AS database,
                       inet_server_addr()::text AS server_addr,
                       inet_server_port() AS server_port,
                       current_user AS db_user
                """,
            )
            fk_edges = fetch_fk_edges(cur)
            before = fetch_snapshot(cur, manifest)
            validate_preconditions(cur, manifest, before, fk_edges)

        audit: dict[str, Any] = {
            "mode": mode,
            "generated_at": generated_at,
            "manifest_path": str(args.manifest.resolve()),
            "db_target": target,
            "db_identity": db_identity,
            "old_slug_mappings": manifest["old_standalone_slugs"],
            "dead_canonical_default_surfaces": manifest["dead_canonical_default_surfaces"],
            "review_fixes_applied": [
                "live FK discovery with unexpected NO ACTION/RESTRICT abort",
                "explicit FK-safe deletion order",
                "deployment grade_history rows explicitly deleted before deployments",
                "LOCAL_DATABASE_URL-only default with local-host guard",
                "identity-level dry-run/apply audit",
                "legacy alias resolution and protected surface checks",
            ],
            "fk_edges": fk_edges,
            "before_summary": summarize_snapshot(before),
            "before": before,
        }

        if args.dry_run:
            audit["planned_effects"] = {
                "remap_hacks": before["hacks_to_remap"],
                "remap_active_incidents": before["active_incidents_to_remap"],
                "null_surviving_superseded_refs": before["surviving_superseded_refs_to_null"],
                "delete_ids": before["ids"],
            }
            write_audit(audit_path, audit)
            print("DRY-RUN OK")
            print(f"  database: {target['database']} on {target['host']}:{target['port']}")
            print(f"  audit: {audit_path}")
            print("  planned:", json.dumps(summarize_snapshot(before), default=json_default, sort_keys=True))
            return 0

        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '30s'")
                effects = apply_cleanup(cur, manifest, before)
                after = fetch_snapshot(cur, manifest)
                checks = post_cleanup_checks(cur, manifest)
                audit["effects"] = effects
                audit["after_summary"] = summarize_snapshot(after)
                audit["after"] = after
                audit["post_checks"] = checks

        write_audit(audit_path, audit)
        print("APPLY OK")
        print(f"  database: {target['database']} on {target['host']}:{target['port']}")
        print(f"  audit: {audit_path}")
        print("  deleted:", json.dumps(audit["effects"]["deleted"], default=json_default, sort_keys=True))
        print("  hack_remaps:", sum(len(item["ids"]) for item in audit["effects"]["hack_remaps"].values()))
        print("  active_incident_remaps:", sum(len(item["ids"]) for item in audit["effects"]["active_incident_remaps"].values()))
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CleanupError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(1)
