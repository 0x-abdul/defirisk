"""Scoped PostgreSQL plan/apply/compensation engine for protocol refreshes."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from .contracts import (
    DEPLOYMENT_FIELDS,
    FAMILY_FIELDS,
    PROTOCOL_FIELDS,
    SURFACE_FIELDS,
    ContractError,
    PublicHandoff,
    canonical_json_bytes,
    canonical_sha256,
    normalize_data_as_of,
)


SCRIPT_NAME = "apply-protocol-refresh.py"
REQUIRED_COLUMNS = {
    "protocols": {"slug", "last_refreshed"} | PROTOCOL_FIELDS,
    "protocol_families": {"family_slug"} | FAMILY_FIELDS,
    "protocol_surfaces": {"surface_id", "family_slug", "surface_slug"} | SURFACE_FIELDS,
    "deployments": {
        "id",
        "protocol_slug",
        "surface_id",
        "chain",
        "deployment_key",
    }
    | DEPLOYMENT_FIELDS,
    "rubric_versions": {"version", "is_active"},
    "factors": {"id", "deprecated_in_rubric"},
    "factor_scores": {
        "id",
        "protocol_slug",
        "factor_id",
        "rubric_version",
        "score",
        "evidence_summary",
        "evidence_detail",
        "collection_mode",
        "collected_at",
        "collected_by",
        "data_as_of",
        "is_current",
        "superseded_by",
        "notes",
        "gap_reason",
        "scope_level",
        "family_slug",
        "surface_id",
        "deployment_id",
    },
    "sources": {
        "id",
        "source_type",
        "url",
        "reference",
        "title",
        "retrieved_at",
        "retrieved_by",
    },
    "factor_score_sources": {"factor_score_id", "source_id", "relation"},
    "pipeline_runs": {
        "id",
        "script_name",
        "triggered_by",
        "success_count",
        "error_count",
        "error_summary",
    },
    "change_log": {"changed_by", "entity_type", "entity_id", "diff", "reason"},
}


@dataclass(frozen=True)
class ApplyPlan:
    refresh_id: str
    family_slug: str
    surfaces: tuple[str, ...]
    factors: tuple[str, ...]
    effective_refresh_date: str
    semantic_changes: bool
    operation_counts: dict[str, int]

    @property
    def requires_pipeline(self) -> bool:
        return self.semantic_changes


@dataclass(frozen=True)
class ApplyMutationReceipt:
    run_id: str
    factor_score_ids: tuple[str, ...]
    inserted_deployment_ids: tuple[str, ...]
    created_source_ids: tuple[str, ...]
    row_counts: dict[str, int]


Runner = Callable[..., Any]


def verify_refresh_date_monotonic(
    current_last_refreshed: Any,
    effective_refresh_date: str,
) -> None:
    """Reject an apply that would move a non-null refresh date backwards."""
    try:
        requested = date.fromisoformat(effective_refresh_date)
    except (TypeError, ValueError) as exc:
        raise ContractError("effective_refresh_date must be a valid date") from exc
    if current_last_refreshed is None:
        return
    try:
        if isinstance(current_last_refreshed, datetime):
            current = current_last_refreshed.date()
        elif isinstance(current_last_refreshed, date):
            current = current_last_refreshed
        else:
            current = date.fromisoformat(str(current_last_refreshed))
    except (TypeError, ValueError) as exc:
        raise ContractError("current last_refreshed must be a valid date") from exc
    if requested < current:
        raise ContractError(
            f"effective refresh date {requested} predates current last_refreshed {current}"
        )


def build_apply_plan(handoff: PublicHandoff | dict[str, Any]) -> ApplyPlan:
    """Build the exact one-family plan from a verified handoff or payload."""
    document = handoff.payload if isinstance(handoff, PublicHandoff) else handoff
    changes = document["changes"]
    semantic = any(
        bool(changes.get(key))
        for key in ("protocol_fields", "family_fields", "surfaces", "deployments", "factor_scores")
    )
    return ApplyPlan(
        refresh_id=document["refresh_id"],
        family_slug=document["family_slug"],
        surfaces=tuple(document["surface_slugs"]),
        factors=tuple(document["scope"]["allowed_factor_ids"]),
        effective_refresh_date=document["effective_refresh_date"],
        semantic_changes=semantic,
        operation_counts={
            "protocol_rows": 1 if changes["protocol_fields"] else 0,
            "protocol_fields": len(changes["protocol_fields"]),
            "family_rows": 1 if changes["family_fields"] else 0,
            "family_fields": len(changes["family_fields"]),
            "surface_rows": len(changes["surfaces"]),
            "deployment_rows": len(changes["deployments"]),
            "factor_rows": len(changes["factor_scores"]),
            "last_refreshed_rows": 1,
            "pipeline_run_rows": 1,
        },
    )


def database_identity(conn: Any) -> str:
    """Return a non-secret identity used by authorization and backup receipts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT current_database(), current_user,
                   COALESCE(inet_server_addr()::text, 'local'),
                   COALESCE(inet_server_port()::text, 'local')
            """
        )
        database, user, host, port = cur.fetchone()
    return f"postgresql:{database}:{user}@{host}:{port}"


def _fetch_json_rows(conn: Any, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = [row[0] for row in cur.fetchall()]
    return sorted(rows, key=canonical_json_bytes)


def _sole_active_rubric_version(conn: Any, *, expected: str | None = None) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM rubric_versions WHERE is_active = true ORDER BY version")
        rows = cur.fetchall()
    if len(rows) != 1:
        raise ContractError("expected exactly one active rubric version")
    version = str(rows[0][0])
    if expected is not None and version != expected:
        raise ContractError("active production rubric does not match the handoff")
    return version


def raw_snapshot(
    conn: Any, family_slug: str, *, target: bool, rubric_version: str | None = None
) -> dict[str, Any]:
    """Capture deterministic current rows using the producer's DB fingerprint shape."""
    operator = "=" if target else "<>"
    rubric_version = _sole_active_rubric_version(conn, expected=rubric_version)
    protocols = _fetch_json_rows(
        conn,
        f"SELECT to_jsonb(p) FROM protocols p WHERE p.slug {operator} %s",
        (family_slug,),
    )
    families = _fetch_json_rows(
        conn,
        f"SELECT to_jsonb(pf) FROM protocol_families pf WHERE pf.family_slug {operator} %s",
        (family_slug,),
    )
    surfaces = _fetch_json_rows(
        conn,
        f"SELECT to_jsonb(ps) FROM protocol_surfaces ps WHERE ps.family_slug {operator} %s",
        (family_slug,),
    )
    deployments = _fetch_json_rows(
        conn,
        f"""
        SELECT to_jsonb(d)
        FROM deployments d
        JOIN protocol_surfaces ps ON ps.surface_id = d.surface_id
        WHERE ps.family_slug {operator} %s
        """,
        (family_slug,),
    )
    factors = _fetch_json_rows(
        conn,
        f"""
        SELECT to_jsonb(fs) || jsonb_build_object(
          'sources', COALESCE((
            SELECT jsonb_agg(
              to_jsonb(s) || jsonb_build_object('relation', fss.relation)
              ORDER BY s.source_type, COALESCE(s.url, ''), s.reference
            )
            FROM factor_score_sources fss
            JOIN sources s ON s.id = fss.source_id
            WHERE fss.factor_score_id = fs.id
          ), '[]'::jsonb)
        )
        FROM factor_scores fs
        WHERE fs.protocol_slug {operator} %s AND fs.is_current = true
          AND fs.rubric_version = %s
        """,
        (family_slug, rubric_version),
    )
    return {
        "family_slug": family_slug,
        "target": target,
        "protocols": protocols,
        "families": families,
        "surfaces": surfaces,
        "deployments": deployments,
        "current_factor_scores": factors,
    }


def _without(row: dict[str, Any], *fields: str) -> dict[str, Any]:
    result = deepcopy(row)
    for field in fields:
        result.pop(field, None)
    return result


def _baseline_data_as_of(value: Any) -> Any:
    """Retain an evidence date while excluding non-semantic apply clock noise."""
    if not isinstance(value, str) or len(value) < 10:
        return value
    candidate = value[:10]
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return value
    return candidate


def normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Remove environment IDs and operation timestamps from a raw snapshot."""
    surfaces = snapshot.get("surfaces", [])
    deployments = snapshot.get("deployments", [])
    surface_keys = {
        str(row.get("surface_id")): str(row.get("surface_slug"))
        for row in surfaces
    }
    deployment_keys = {
        str(row.get("id")): {
            "surface_slug": surface_keys.get(str(row.get("surface_id"))),
            "chain": row.get("chain"),
            "deployment_key": row.get("deployment_key"),
        }
        for row in deployments
    }

    normalized_families: list[dict[str, Any]] = []
    for row in snapshot.get("families", []):
        item = _without(row, "created_at", "updated_at", "review_token", "graded_at")
        primary = item.pop("primary_surface_id", None)
        item["primary_surface"] = surface_keys.get(str(primary)) if primary else None
        normalized_families.append(item)

    normalized_surfaces = [
        _without(row, "surface_id", "created_at", "updated_at", "graded_at")
        for row in snapshot.get("surfaces", [])
    ]
    normalized_deployments: list[dict[str, Any]] = []
    for row in snapshot.get("deployments", []):
        item = _without(row, "id", "surface_id", "created_at", "updated_at")
        item["surface_slug"] = surface_keys.get(str(row.get("surface_id")))
        normalized_deployments.append(item)

    normalized_factors: list[dict[str, Any]] = []
    for row in snapshot.get("current_factor_scores", []):
        item = _without(row, "id", "superseded_by", "collected_at")
        if "data_as_of" in item:
            item["data_as_of"] = _baseline_data_as_of(item["data_as_of"])
        surface_id = item.pop("surface_id", None)
        deployment_id = item.pop("deployment_id", None)
        item["surface_slug"] = surface_keys.get(str(surface_id)) if surface_id else None
        deployment = deployment_keys.get(str(deployment_id)) if deployment_id else None
        item["deployment_chain"] = deployment.get("chain") if deployment else None
        item["deployment_key"] = deployment.get("deployment_key") if deployment else None
        item["sources"] = sorted(
            [
                _without(source, "id", "created_at", "retrieved_at")
                for source in item.get("sources", [])
            ],
            key=canonical_json_bytes,
        )
        normalized_factors.append(item)

    result = {
        "family_slug": snapshot["family_slug"],
        "target": snapshot["target"],
        "protocols": [
            _without(row, "created_at", "updated_at", "review_token", "graded_at")
            for row in snapshot.get("protocols", [])
        ],
        "families": normalized_families,
        "surfaces": normalized_surfaces,
        "deployments": normalized_deployments,
        "current_factor_scores": normalized_factors,
    }
    for key in ("protocols", "families", "surfaces", "deployments", "current_factor_scores"):
        result[key] = sorted(result[key], key=canonical_json_bytes)
    return result


def normalized_snapshot(conn: Any, family_slug: str, *, target: bool) -> dict[str, Any]:
    return normalize_snapshot(raw_snapshot(conn, family_slug, target=target))


def snapshot_hashes(conn: Any, family_slug: str) -> dict[str, Any]:
    raw_target = raw_snapshot(conn, family_slug, target=True)
    raw_other = raw_snapshot(conn, family_slug, target=False)
    normalized_target = normalize_snapshot(raw_target)
    normalized_other = normalize_snapshot(raw_other)
    return {
        "raw_target_sha256": canonical_sha256(raw_target),
        "raw_other_sha256": canonical_sha256(raw_other),
        "normalized_target_sha256": canonical_sha256(normalized_target),
        "normalized_other_sha256": canonical_sha256(normalized_other),
        "raw_target": raw_target,
        "raw_other": raw_other,
        "normalized_target": normalized_target,
        "normalized_other": normalized_other,
    }


def factor_target_key(entry: dict[str, Any]) -> str:
    """Return a stable semantic key for one factor/scope target."""
    factor_id = entry["factor_id"]
    if entry["scope_level"] == "family":
        return f"family:{factor_id}"
    if entry["scope_level"] == "surface":
        return f"surface:{entry['surface_slug']}:{factor_id}"
    return (
        f"deployment:{entry['surface_slug']}:{entry['chain']}:"
        f"{entry['deployment_key']}:{factor_id}"
    )


def _normalized_factor_key(row: dict[str, Any]) -> str:
    entry = {
        "factor_id": row.get("factor_id"),
        "scope_level": row.get("scope_level"),
        "surface_slug": row.get("surface_slug"),
        "chain": row.get("deployment_chain"),
        "deployment_key": row.get("deployment_key"),
    }
    return factor_target_key(entry)


def production_factor_hashes(
    normalized_target: dict[str, Any],
    factor_changes: list[dict[str, Any]],
) -> dict[str, str | None]:
    """Hash current production factor rows using semantic, ID-free targets."""
    current: dict[str, dict[str, Any]] = {}
    for row in normalized_target.get("current_factor_scores", []):
        key = _normalized_factor_key(row)
        if key in current:
            raise ContractError(f"normalized production snapshot has duplicate factor target {key}")
        current[key] = row
    result: dict[str, str | None] = {}
    for entry in factor_changes:
        key = factor_target_key(entry)
        row = current.get(key)
        result[key] = canonical_sha256(row) if row is not None else None
    return result


def verify_current_factor_baseline(
    normalized_target: dict[str, Any],
    expected_sha256: str,
) -> str:
    """Fail closed when any retained current factor differs from the sealed baseline.

    Per-change old-row fingerprints cannot detect stale non-target factors that
    still affect the composed result. The public handoff therefore binds the
    complete, ID-normalized current-factor set captured before local refresh.
    """
    factors = normalized_target.get("current_factor_scores")
    if not isinstance(factors, list):
        raise ContractError("normalized production snapshot has no current factor scores")
    observed_sha256 = canonical_sha256(factors)
    if observed_sha256 != expected_sha256:
        raise ContractError(
            "production current factor baseline does not match the approved local baseline"
        )
    return observed_sha256


def build_production_plan(
    handoff: PublicHandoff,
    *,
    database_identity_value: str,
    normalized_target: dict[str, Any],
    normalized_other: dict[str, Any],
) -> dict[str, Any]:
    """Build the separately authorizable production plan and its SHA."""
    document = handoff.payload
    apply_plan = build_apply_plan(document)
    factor_hashes = production_factor_hashes(
        normalized_target,
        document["changes"]["factor_scores"],
    )
    core = {
        "schema_version": "1.0",
        "plan_type": "protocol_refresh_production_plan",
        "artifact_sha256": handoff.artifact_sha256,
        "database_identity": database_identity_value,
        "refresh_id": apply_plan.refresh_id,
        "family_slug": apply_plan.family_slug,
        "surface_slugs": list(apply_plan.surfaces),
        "factor_ids": list(apply_plan.factors),
        "effective_refresh_date": apply_plan.effective_refresh_date,
        "expected_result": deepcopy(document["expected_result"]),
        "operation_counts": apply_plan.operation_counts,
        "pipeline_required": apply_plan.requires_pipeline,
        "production_before": {
            "target_sha256": canonical_sha256(normalized_target),
            "unrelated_protocols_sha256": canonical_sha256(normalized_other),
            "factor_current_sha256": factor_hashes,
            "current_factor_scores_sha256": canonical_sha256(
                normalized_target["current_factor_scores"]
            ),
            "target_snapshot": normalized_target,
        },
        "local_audit_metadata": {
            "baseline": deepcopy(document.get("baseline")),
            "factor_expected_current_sha256": {
                factor_target_key(entry): entry.get("expected_current_sha256")
                for entry in document["changes"]["factor_scores"]
            },
        },
    }
    return {**core, "plan_sha256": canonical_sha256(core)}


def verify_production_plan_sha(plan: dict[str, Any]) -> str:
    """Verify and return a production plan's self-contained checksum."""
    expected = plan.get("plan_sha256")
    unsigned = deepcopy(plan)
    unsigned.pop("plan_sha256", None)
    actual = canonical_sha256(unsigned)
    if expected != actual:
        raise ContractError("production plan_sha256 does not match its plan core")
    return actual


def _table_columns(conn: Any) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
            """
        )
        result: dict[str, set[str]] = {}
        for table, column in cur.fetchall():
            result.setdefault(table, set()).add(column)
    return result


def _current_factor_row(
    conn: Any,
    document: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any] | None:
    params: list[Any] = [document["family_slug"], entry["factor_id"], document["rubric_version"]]
    level = entry["scope_level"]
    if level == "family":
        predicate = "fs.scope_level = 'family' AND fs.family_slug = %s"
        params.append(document["family_slug"])
    elif level == "surface":
        predicate = "fs.scope_level = 'surface' AND ps.family_slug = %s AND ps.surface_slug = %s"
        params.extend([document["family_slug"], entry["surface_slug"]])
    else:
        predicate = (
            "fs.scope_level = 'deployment' AND ps.family_slug = %s AND ps.surface_slug = %s "
            "AND d.chain = %s AND d.deployment_key = %s"
        )
        params.extend(
            [document["family_slug"], entry["surface_slug"], entry["chain"], entry["deployment_key"]]
        )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT to_jsonb(fs) || jsonb_build_object(
              'sources', COALESCE((
                SELECT jsonb_agg(to_jsonb(s) || jsonb_build_object('relation', fss.relation)
                                 ORDER BY s.source_type, COALESCE(s.url, ''), s.reference)
                FROM factor_score_sources fss
                JOIN sources s ON s.id = fss.source_id
                WHERE fss.factor_score_id = fs.id
              ), '[]'::jsonb)
            )
            FROM factor_scores fs
            LEFT JOIN deployments d ON d.id = fs.deployment_id
            LEFT JOIN protocol_surfaces ps ON ps.surface_id = COALESCE(fs.surface_id, d.surface_id)
            WHERE fs.protocol_slug = %s AND fs.factor_id = %s
              AND fs.rubric_version = %s AND fs.is_current = true AND {predicate}
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    if len(rows) > 1:
        raise ContractError(f"factor target has multiple current rows: {entry['factor_id']}")
    return rows[0][0] if rows else None


def verify_production_topology(
    document: dict[str, Any],
    rows: list[tuple[str, str, bool, bool]],
) -> None:
    """Bind the approved topology attestation to the live gradeable surfaces."""
    existing = {row[0] for row in rows}
    named = set(document["surface_slugs"])
    if not named <= existing:
        raise ContractError(
            f"handoff names unknown/foreign surfaces: {sorted(named - existing)}"
        )
    gradeable = {
        slug
        for slug, status, is_primary, has_scores in rows
        if status != "deprecated" or is_primary or has_scores
    }
    canonical_surfaces = set(
        document["topology_contract"]["canonical_surface_slugs"]
    )
    if canonical_surfaces != gradeable:
        raise ContractError(
            "topology attestation does not match production gradeable surfaces: "
            f"expected {sorted(gradeable)}, got {sorted(canonical_surfaces)}"
        )
    if document["refresh_type"] == "full_family_refresh" and named != gradeable:
        raise ContractError(
            "full family refresh must enumerate every gradeable surface: "
            f"expected {sorted(gradeable)}, got {sorted(named)}"
        )

    projected_status = {slug: status for slug, status, _is_primary, _has_scores in rows}
    for change in document["changes"]["surfaces"]:
        if "status" in change["fields"]:
            projected_status[change["surface_slug"]] = change["fields"]["status"]
    projected_gradeable = {
        slug
        for slug, _status, is_primary, has_scores in rows
        if projected_status[slug] != "deprecated" or is_primary or has_scores
    }
    if projected_gradeable != canonical_surfaces:
        raise ContractError(
            "surface status changes would alter canonical gradeable topology: "
            f"expected {sorted(canonical_surfaces)}, got {sorted(projected_gradeable)}"
        )


def _production_topology_rows(
    conn: Any,
    family_slug: str,
    *,
    lock: bool = False,
) -> list[tuple[str, str, bool, bool]]:
    lock_clause = " FOR UPDATE OF ps" if lock else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ps.surface_slug, ps.status::text, ps.is_primary,
                   EXISTS (
                     SELECT 1 FROM factor_scores fs
                     WHERE fs.surface_id = ps.surface_id AND fs.is_current = true
                   )
            FROM protocol_surfaces ps
            WHERE ps.family_slug = %s
            ORDER BY ps.surface_slug{lock_clause}
            """,
            (family_slug,),
        )
        return cur.fetchall()


def preflight(conn: Any, handoff: PublicHandoff) -> dict[str, Any]:
    """Perform read-only schema/ownership checks and build a production plan."""
    document = handoff.payload
    plan = build_apply_plan(document)
    columns = _table_columns(conn)
    for table, required in REQUIRED_COLUMNS.items():
        missing = required - columns.get(table, set())
        if missing:
            raise ContractError(f"database is missing {table} columns: {sorted(missing)}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_refreshed FROM protocols WHERE slug = %s",
            (plan.family_slug,),
        )
        protocol_rows = cur.fetchall()
        if len(protocol_rows) != 1:
            raise ContractError("expected exactly one canonical protocols row")
        verify_refresh_date_monotonic(
            protocol_rows[0][0],
            plan.effective_refresh_date,
        )
        cur.execute(
            "SELECT count(*) FROM protocol_families WHERE family_slug = %s",
            (plan.family_slug,),
        )
        if cur.fetchone()[0] != 1:
            raise ContractError("expected exactly one canonical protocol_families row")
        cur.execute("SELECT version FROM rubric_versions WHERE is_active = true")
        active = [row[0] for row in cur.fetchall()]
        if active != [document["rubric_version"]]:
            raise ContractError(
                f"handoff rubric is not the sole active database rubric: {active}"
            )
        cur.execute(
            "SELECT id FROM factors WHERE id = ANY(%s) AND deprecated_in_rubric IS NULL ORDER BY id",
            (list(plan.factors),),
        )
        found = [row[0] for row in cur.fetchall()]
        if found != list(plan.factors):
            raise ContractError("allowed factor IDs do not exactly match active database rows")

    verify_production_topology(
        document,
        _production_topology_rows(conn, plan.family_slug),
    )

    hashes = snapshot_hashes(conn, plan.family_slug)
    verify_current_factor_baseline(
        hashes["normalized_target"],
        document["baseline"]["current_factor_scores_sha256"],
    )
    identity = database_identity(conn)
    production_plan = build_production_plan(
        handoff,
        database_identity_value=identity,
        normalized_target=hashes["normalized_target"],
        normalized_other=hashes["normalized_other"],
    )
    return {
        "plan": plan,
        "production_plan": production_plan,
        "plan_sha256": production_plan["plan_sha256"],
        "database_identity": identity,
        **hashes,
    }


def already_applied(conn: Any, refresh_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pipeline_runs WHERE script_name = %s AND triggered_by = %s",
            (SCRIPT_NAME, f"protocol-refresh:{refresh_id}"),
        )
        return cur.fetchone() is not None


def reconcile_failed_reservation(conn: Any, handoff: PublicHandoff, *, authorization: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
    """Release only a proved-compensated failed reservation, retaining its audit row."""
    family_slug = handoff.payload["family_slug"]
    _acquire_family_session_lock(conn, family_slug)
    try:
        details = preflight(conn, handoff)
        plan: ApplyPlan = details["plan"]
        production_plan = details["production_plan"]
        if authorization["operation"] != "reconcile_protocol_refresh":
            raise ContractError("authorization does not permit refresh reconciliation")
        if authorization["artifact_sha256"] != handoff.artifact_sha256 or authorization["plan_sha256"] != production_plan["plan_sha256"]:
            raise ContractError("reconciliation authorization is not bound to this exact plan")
        if authorization["database_identity"] != details["database_identity"]:
            raise ContractError("reconciliation authorization database identity mismatch")
        if backup.get("operation") != "apply_protocol_refresh" or backup.get("artifact_sha256") != handoff.artifact_sha256 or backup.get("plan_sha256") != production_plan["plan_sha256"]:
            raise ContractError("backup receipt does not cover the refresh being reconciled")
        expected = {factor_target_key(entry): entry.get("expected_current_sha256") for entry in handoff.payload["changes"]["factor_scores"]}
        actual = production_factor_hashes(details["normalized_target"], handoff.payload["changes"]["factor_scores"])
        if actual != expected:
            raise ContractError("current factor hashes do not prove the compensated pre-apply state")
        with conn.cursor() as cur:
            cur.execute("SELECT id, success_count, error_count, error_summary FROM pipeline_runs WHERE script_name = %s AND triggered_by = %s FOR UPDATE", (SCRIPT_NAME, f"protocol-refresh:{plan.refresh_id}"))
            row = cur.fetchone()
            if row is None:
                raise ContractError("no active failed reservation exists for this refresh")
            run_id, success_count, error_count, error_summary = row
            if success_count != 0 or error_count != 1 or "compensation proved" not in json.dumps(error_summary, sort_keys=True):
                raise ContractError("reservation is not a proved-compensated failed refresh")
            historical_key = f"protocol-refresh-failed:{plan.refresh_id}:{run_id}"
            cur.execute("UPDATE pipeline_runs SET triggered_by = %s WHERE id = %s AND script_name = %s", (historical_key, run_id, SCRIPT_NAME))
            if cur.rowcount != 1:
                raise ContractError("failed reservation could not be preserved and released")
            cur.execute("INSERT INTO change_log (changed_by, entity_type, entity_id, diff, reason) VALUES (%s, 'protocol_refresh_reconciliation', %s, %s::jsonb, %s)", (SCRIPT_NAME, family_slug, json.dumps({"refresh_id": plan.refresh_id, "run_id": str(run_id), "artifact_sha256": handoff.artifact_sha256, "plan_sha256": production_plan["plan_sha256"], "authorization_id": authorization["authorization_id"], "backup_id": backup["backup_id"], "historical_key": historical_key}, sort_keys=True), "released only a proved-compensated failed refresh reservation"))
            if cur.rowcount != 1:
                raise ContractError("reconciliation audit insert failed")
        conn.commit()
        return {"schema_version": "1.0", "receipt_type": "protocol_refresh_reconciliation_receipt", "status": "reconciled", "refresh_id": plan.refresh_id, "family_slug": family_slug, "artifact_sha256": handoff.artifact_sha256, "plan_sha256": production_plan["plan_sha256"], "released_run_id": str(run_id), "historical_key": historical_key, "database_identity": details["database_identity"]}
    finally:
        _release_family_session_lock(conn, family_slug)


def _update_fields(
    cur: Any,
    table: str,
    key_column: str,
    key_value: Any,
    fields: dict[str, Any],
    allowed: set[str],
) -> int:
    if not fields:
        return 0
    unsupported = set(fields) - allowed
    if unsupported:
        raise ContractError(f"unsupported {table} fields: {sorted(unsupported)}")
    from psycopg import sql

    assignments = [sql.SQL("{} = %s").format(sql.Identifier(name)) for name in sorted(fields)]
    query = sql.SQL("UPDATE {} SET {}, updated_at = now() WHERE {} = %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(assignments),
        sql.Identifier(key_column),
    )
    cur.execute(query, [fields[name] for name in sorted(fields)] + [key_value])
    if cur.rowcount != 1:
        raise ContractError(f"scoped update expected one {table} row, changed {cur.rowcount}")
    return cur.rowcount


def _surface_id(cur: Any, family_slug: str, surface_slug: str) -> Any:
    cur.execute(
        "SELECT surface_id FROM protocol_surfaces WHERE family_slug = %s AND surface_slug = %s",
        (family_slug, surface_slug),
    )
    row = cur.fetchone()
    if row is None:
        raise ContractError(f"surface is not owned by target family: {surface_slug}")
    return row[0]


def _deployment_id(
    cur: Any,
    family_slug: str,
    surface_slug: str,
    chain: str,
    deployment_key: str,
) -> Any:
    cur.execute(
        """
        SELECT d.id FROM deployments d
        JOIN protocol_surfaces ps ON ps.surface_id = d.surface_id
        WHERE ps.family_slug = %s AND ps.surface_slug = %s
          AND d.chain = %s AND d.deployment_key = %s
        """,
        (family_slug, surface_slug, chain, deployment_key),
    )
    row = cur.fetchone()
    if row is None:
        raise ContractError(
            f"deployment does not exist for scope: {surface_slug}/{chain}/{deployment_key}"
        )
    return row[0]


def _apply_deployment(cur: Any, family_slug: str, entry: dict[str, Any]) -> tuple[str, bool]:
    from psycopg import sql

    fields = entry["fields"]
    unsupported = set(fields) - DEPLOYMENT_FIELDS
    if unsupported:
        raise ContractError(f"unsupported deployment fields: {sorted(unsupported)}")
    surface_id = _surface_id(cur, family_slug, entry["surface_slug"])
    cur.execute(
        "SELECT id FROM deployments WHERE surface_id = %s AND chain = %s AND deployment_key = %s",
        (surface_id, entry["chain"], entry["deployment_key"]),
    )
    existing = cur.fetchone()
    columns = ["protocol_slug", "surface_id", "chain", "deployment_key", *sorted(fields)]
    values = [family_slug, surface_id, entry["chain"], entry["deployment_key"]]
    values.extend(fields[name] for name in sorted(fields))
    updates = [
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
        for name in sorted(fields)
    ]
    updates.append(sql.SQL("updated_at = now()"))
    query = sql.SQL(
        "INSERT INTO deployments ({}) VALUES ({}) "
        "ON CONFLICT (surface_id, chain, deployment_key) DO UPDATE SET {} RETURNING id"
    ).format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        sql.SQL(", ").join(updates),
    )
    cur.execute(query, values)
    row = cur.fetchone()
    if row is None:
        raise ContractError("deployment upsert did not return exactly one row")
    return str(row[0]), existing is None


def _apply_factor_score(
    cur: Any,
    document: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    family = document["family_slug"]
    family_target = None
    surface_id = None
    deployment_id = None
    if entry["scope_level"] == "family":
        family_target = family
    elif entry["scope_level"] == "surface":
        surface_id = _surface_id(cur, family, entry["surface_slug"])
    else:
        surface_id = _surface_id(cur, family, entry["surface_slug"])
        deployment_id = _deployment_id(
            cur,
            family,
            entry["surface_slug"],
            entry["chain"],
            entry["deployment_key"],
        )

    current = _current_factor_row(cur.connection, document, entry)
    cur.execute(
        """
        INSERT INTO factor_scores (
          protocol_slug, deployment_id, factor_id, rubric_version, score,
          evidence_summary, evidence_detail, collection_mode, gap_reason,
          collected_at, collected_by, data_as_of, is_current, notes,
          scope_level, family_slug, surface_id
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s,
          false, %s, %s, %s, %s
        ) RETURNING id
        """,
        (
            family,
            deployment_id,
            entry["factor_id"],
            document["rubric_version"],
            entry["score"],
            entry["evidence_summary"],
            entry.get("evidence_detail"),
            entry["collection_mode"],
            entry.get("gap_reason"),
            entry.get("collected_by", "protocol-refresh"),
            normalize_data_as_of(
                entry.get("data_as_of"), document["effective_refresh_date"]
            ),
            f"protocol_refresh:{document['refresh_id']}",
            entry["scope_level"],
            family_target,
            surface_id,
        ),
    )
    new_id = cur.fetchone()[0]
    created_source_ids: list[str] = []
    for source in entry["sources"]:
        cur.execute(
            """
            INSERT INTO sources (
              source_type, url, reference, title, retrieved_at, retrieved_by,
              is_archived, archive_url, notes
            ) VALUES (%s, %s, %s, %s, COALESCE(%s, now()), %s, %s, %s, %s)
            ON CONFLICT DO NOTHING RETURNING id
            """,
            (
                source["source_type"],
                source.get("url"),
                source["reference"],
                source.get("title"),
                source.get("retrieved_at"),
                source.get("retrieved_by", "protocol-refresh"),
                source.get("is_archived", False),
                source.get("archive_url"),
                source.get("notes"),
            ),
        )
        created = cur.fetchone()
        if created is not None:
            created_source_ids.append(str(created[0]))
        cur.execute(
            """
            SELECT id FROM sources
            WHERE source_type = %s AND COALESCE(url, '') = COALESCE(%s, '')
              AND reference = %s
            """,
            (source["source_type"], source.get("url"), source["reference"]),
        )
        source_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO factor_score_sources (factor_score_id, source_id, relation) VALUES (%s, %s, %s)",
            (new_id, source_id, source.get("relation", "primary")),
        )
        if cur.rowcount != 1:
            raise ContractError("factor source link expected one inserted row")
    if current is not None:
        cur.execute(
            "UPDATE factor_scores SET is_current = false, superseded_by = %s "
            "WHERE id = %s AND is_current = true",
            (new_id, current["id"]),
        )
        if cur.rowcount != 1:
            raise ContractError(f"could not supersede current factor row {entry['factor_id']}")
    cur.execute(
        "UPDATE factor_scores SET is_current = true WHERE id = %s AND is_current = false",
        (new_id,),
    )
    if cur.rowcount != 1:
        raise ContractError(f"could not promote replacement factor row {entry['factor_id']}")
    return str(new_id), tuple(created_source_ids)


def apply_transaction(
    conn: Any,
    handoff: PublicHandoff,
    *,
    production_plan: dict[str, Any],
    authorization_id: str,
    backup_id: str,
) -> ApplyMutationReceipt:
    """Reserve idempotency and apply only allowlisted rows in one transaction."""
    document = handoff.payload
    plan = build_apply_plan(document)
    row_counts = {key: 0 for key in plan.operation_counts}
    # Topology is revalidated inside the family advisory lock and serializable
    # transaction for every refresh. A row lock is needed only when this
    # transaction is allowed to mutate a surface row; date-only and
    # factor-only refreshes preserve topology and must not require UPDATE on
    # protocol_surfaces merely to validate it.
    topology_write_lock = bool(document["changes"]["surfaces"])
    verify_production_topology(
        document,
        _production_topology_rows(conn, plan.family_slug, lock=topology_write_lock),
    )
    _sole_active_rubric_version(conn, expected=document["rubric_version"])
    current_factor_hashes = production_factor_hashes(
        normalized_snapshot(conn, plan.family_slug, target=True),
        document["changes"]["factor_scores"],
    )
    authorized_factor_hashes = production_plan["production_before"][
        "factor_current_sha256"
    ]
    if current_factor_hashes != authorized_factor_hashes:
        raise ContractError("production factor rows drifted from the authorized plan")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_runs (
              script_name, cadence_bucket, protocols_touched, fetchers_invoked,
              success_count, error_count, triggered_by, notes
            ) VALUES (%s, 'manual', 1, '[]'::jsonb, 0, 0, %s, %s)
            ON CONFLICT DO NOTHING RETURNING id
            """,
            (
                SCRIPT_NAME,
                f"protocol-refresh:{plan.refresh_id}",
                json.dumps(
                    {
                        "family_slug": plan.family_slug,
                        "artifact_sha256": handoff.artifact_sha256,
                        "plan_sha256": production_plan["plan_sha256"],
                        "authorization_id": authorization_id,
                        "backup_id": backup_id,
                        "local_audit_metadata": production_plan["local_audit_metadata"],
                    },
                    sort_keys=True,
                ),
            ),
        )
        reservation = cur.fetchone()
        if reservation is None:
            raise ContractError(f"refresh {plan.refresh_id} was already reserved/applied")
        run_id = str(reservation[0])
        row_counts["pipeline_run_rows"] = 1

        row_counts["protocol_rows"] = _update_fields(
            cur,
            "protocols",
            "slug",
            plan.family_slug,
            document["changes"]["protocol_fields"],
            PROTOCOL_FIELDS,
        )
        row_counts["protocol_fields"] = len(document["changes"]["protocol_fields"])
        row_counts["family_rows"] = _update_fields(
            cur,
            "protocol_families",
            "family_slug",
            plan.family_slug,
            document["changes"]["family_fields"],
            FAMILY_FIELDS,
        )
        row_counts["family_fields"] = len(document["changes"]["family_fields"])
        for entry in document["changes"]["surfaces"]:
            surface_id = _surface_id(cur, plan.family_slug, entry["surface_slug"])
            row_counts["surface_rows"] += _update_fields(
                cur,
                "protocol_surfaces",
                "surface_id",
                surface_id,
                entry["fields"],
                SURFACE_FIELDS,
            )
        inserted_deployment_ids: list[str] = []
        for entry in document["changes"]["deployments"]:
            deployment_id, inserted = _apply_deployment(cur, plan.family_slug, entry)
            row_counts["deployment_rows"] += 1
            if inserted:
                inserted_deployment_ids.append(deployment_id)
        factor_score_ids: list[str] = []
        created_source_ids: list[str] = []
        for entry in document["changes"]["factor_scores"]:
            factor_id, source_ids = _apply_factor_score(cur, document, entry)
            factor_score_ids.append(factor_id)
            created_source_ids.extend(source_ids)
            row_counts["factor_rows"] += 1

        cur.execute(
            "UPDATE protocols SET last_refreshed = %s, updated_at = now() WHERE slug = %s",
            (plan.effective_refresh_date, plan.family_slug),
        )
        if cur.rowcount != 1:
            raise ContractError("last_refreshed update escaped or missed the target protocol")
        row_counts["last_refreshed_rows"] = 1
        if row_counts != plan.operation_counts:
            raise ContractError(
                f"apply row-count assertion failed: expected {plan.operation_counts}, got {row_counts}"
            )
        cur.execute(
            """
            INSERT INTO change_log (changed_by, entity_type, entity_id, diff, reason)
            VALUES (%s, 'protocol_refresh', %s, %s::jsonb, %s)
            """,
            (
                SCRIPT_NAME,
                plan.family_slug,
                json.dumps(
                    {
                        "refresh_id": plan.refresh_id,
                        "artifact_sha256": handoff.artifact_sha256,
                        "plan_sha256": production_plan["plan_sha256"],
                        "authorization_id": authorization_id,
                        "backup_id": backup_id,
                        "row_counts": row_counts,
                    }
                ),
                "approved production protocol data refresh",
            ),
        )
        if cur.rowcount != 1:
            raise ContractError("change audit expected one inserted row")
    return ApplyMutationReceipt(
        run_id,
        tuple(factor_score_ids),
        tuple(inserted_deployment_ids),
        tuple(created_source_ids),
        row_counts,
    )


def verify_runtime_factor_score_receipt(
    conn: Any, handoff: PublicHandoff, receipt: ApplyMutationReceipt
) -> None:
    """Prove source-transaction UUIDs are the authorized current active-rubric targets."""
    document = handoff.payload
    expected_ids = receipt.factor_score_ids
    changes = document["changes"]["factor_scores"]
    if len(expected_ids) != len(changes):
        raise ContractError("runtime factor-score receipt count does not match the authorized targets")
    if len(expected_ids) != len(set(expected_ids)):
        raise ContractError("runtime factor-score receipt contains duplicate UUIDs")
    if not expected_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text, protocol_slug, factor_id, rubric_version, is_current "
            "FROM factor_scores WHERE id::text = ANY(%s)",
            (list(expected_ids),),
        )
        rows = cur.fetchall()
    if len(rows) != len(expected_ids):
        raise ContractError("runtime factor-score receipt includes a missing UUID")
    expected_factors = {str(entry["factor_id"]) for entry in changes}
    for row in rows:
        if (
            str(row[1]) != document["family_slug"]
            or str(row[3]) != document["rubric_version"]
            or row[4] is not True
            or str(row[2]) not in expected_factors
        ):
            raise ContractError("runtime factor-score receipt includes a foreign or inactive target")


def capture_recovery_snapshot(conn: Any, family_slug: str) -> dict[str, Any]:
    """Capture all target rows that source apply or compose may mutate."""
    target = raw_snapshot(conn, family_slug, target=True)
    factor_scores = _fetch_json_rows(
        conn,
        "SELECT to_jsonb(fs) FROM factor_scores fs WHERE fs.protocol_slug = %s",
        (family_slug,),
    )
    factor_score_sources = _fetch_json_rows(
        conn,
        """
        SELECT to_jsonb(fss) FROM factor_score_sources fss
        JOIN factor_scores fs ON fs.id = fss.factor_score_id
        WHERE fs.protocol_slug = %s
        """,
        (family_slug,),
    )
    sources = _fetch_json_rows(
        conn,
        """
        SELECT DISTINCT to_jsonb(s) FROM sources s
        JOIN factor_score_sources fss ON fss.source_id = s.id
        JOIN factor_scores fs ON fs.id = fss.factor_score_id
        WHERE fs.protocol_slug = %s
        """,
        (family_slug,),
    )
    histories = {
        table: _fetch_json_rows(
            conn,
            f"SELECT to_jsonb(t) FROM {table} t WHERE t.protocol_slug = %s",
            (family_slug,),
        )
        for table in ("grade_history", "protocol_grade_history", "factor_score_history")
    }
    return {
        "family_slug": family_slug,
        "protocols": target["protocols"],
        "families": target["families"],
        "surfaces": target["surfaces"],
        "deployments": target["deployments"],
        "factor_scores": factor_scores,
        "factor_score_sources": factor_score_sources,
        "sources": sources,
        **histories,
    }


def _row_ids(rows: list[dict[str, Any]], key: str = "id") -> set[str]:
    return {str(row[key]) for row in rows}


def _live_ids(cur: Any, table: str, *, family_slug: str | None = None) -> set[str]:
    from psycopg import sql

    if table == "deployments" and family_slug is not None:
        cur.execute(
            """
            SELECT d.id::text FROM deployments d
            JOIN protocol_surfaces ps ON ps.surface_id = d.surface_id
            WHERE ps.family_slug = %s
            """,
            (family_slug,),
        )
        return {str(row[0]) for row in cur.fetchall()}
    query = sql.SQL("SELECT id::text FROM {}").format(sql.Identifier(table))
    params: tuple[Any, ...] = ()
    if family_slug is not None:
        query += sql.SQL(" WHERE protocol_slug = %s")
        params = (family_slug,)
    cur.execute(query, params)
    return {str(row[0]) for row in cur.fetchall()}


def _delete_ids(cur: Any, table: str, ids: set[str]) -> None:
    if not ids:
        return
    from psycopg import sql

    cur.execute(
        sql.SQL("DELETE FROM {} WHERE id::text = ANY(%s)").format(sql.Identifier(table)),
        (sorted(ids),),
    )
    if cur.rowcount != len(ids):
        raise ContractError(
            f"compensation expected to delete {len(ids)} {table} rows, deleted {cur.rowcount}"
        )


def _restore_rows(
    cur: Any,
    table: str,
    key: str,
    rows: list[dict[str, Any]],
) -> None:
    from psycopg import sql

    for row in rows:
        columns = sorted(set(row) - {key})
        assignments = [
            sql.SQL("{} = restored.{}").format(sql.Identifier(column), sql.Identifier(column))
            for column in columns
        ]
        query = sql.SQL(
            "UPDATE {} AS live SET {} "
            "FROM jsonb_populate_record(NULL::{}, %s::jsonb) AS restored "
            "WHERE live.{}::text = %s"
        ).format(
            sql.Identifier(table),
            sql.SQL(", ").join(assignments),
            sql.Identifier(table),
            sql.Identifier(key),
        )
        cur.execute(query, (json.dumps(row, default=str), str(row[key])))
        if cur.rowcount != 1:
            raise ContractError(
                f"compensation could not restore {table} row {row[key]!r}; changed {cur.rowcount}"
            )


def _restore_history_table(
    cur: Any,
    table: str,
    rows: list[dict[str, Any]],
    family_slug: str,
) -> None:
    before_ids = _row_ids(rows)
    live_ids = _live_ids(cur, table, family_slug=family_slug)
    missing = before_ids - live_ids
    if missing:
        raise ContractError(f"compensation found missing pre-apply {table} rows: {sorted(missing)}")
    _delete_ids(cur, table, live_ids - before_ids)
    _restore_rows(cur, table, "id", rows)


def verify_compensation(
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    before_other_sha256: str,
    after_other_sha256: str,
) -> str:
    before_hash = canonical_sha256(before_snapshot)
    after_hash = canonical_sha256(after_snapshot)
    if before_hash != after_hash:
        raise ContractError("compensation restored target does not match the pre-apply snapshot")
    if before_other_sha256 != after_other_sha256:
        raise ContractError("compensation changed an unrelated protocol")
    return after_hash


def verify_expected_live_snapshot(
    conn: Any,
    family_slug: str,
    expected_snapshot: dict[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """Fail closed when target state differs from the last accounted stage."""
    actual = capture_recovery_snapshot(conn, family_slug)
    expected_hash = canonical_sha256(expected_snapshot)
    actual_hash = canonical_sha256(actual)
    if actual_hash != expected_hash:
        raise ContractError(
            f"unaccounted target drift at {stage}: expected {expected_hash}, got {actual_hash}"
        )
    return actual


COMPOSE_GRADE_FIELDS = {
    "headline_grade",
    "rubric_version",
    "graded_at",
    "risk_score",
    "category_severities",
    "cap_applied",
    "cap_reason",
    "updated_at",
}


def _without_fields(rows: list[dict[str, Any]], fields: set[str]) -> list[dict[str, Any]]:
    return sorted(
        [{key: value for key, value in row.items() if key not in fields} for row in rows],
        key=canonical_json_bytes,
    )


def _verify_append_only_history(
    *,
    table: str,
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    family_slug: str,
    surface_ids: set[str],
    factor_ids: set[str],
) -> None:
    before_by_id = {str(row.get("id")): row for row in before_rows}
    after_by_id = {str(row.get("id")): row for row in after_rows}
    if len(before_by_id) != len(before_rows) or len(after_by_id) != len(after_rows):
        raise ContractError(f"compose transition has duplicate/missing {table} row IDs")
    if not set(before_by_id) <= set(after_by_id):
        raise ContractError(f"compose transition deleted existing {table} rows")
    for row_id, before_row in before_by_id.items():
        if canonical_sha256(before_row) != canonical_sha256(after_by_id[row_id]):
            raise ContractError(f"compose transition modified existing {table} row {row_id}")
    for row_id in set(after_by_id) - set(before_by_id):
        row = after_by_id[row_id]
        if row.get("protocol_slug") != family_slug:
            raise ContractError(f"compose appended foreign {table} row {row_id}")
        if row.get("scope_level") != "surface":
            raise ContractError(f"compose appended non-surface {table} row {row_id}")
        if str(row.get("surface_id")) not in surface_ids:
            raise ContractError(f"compose appended {table} row for an unknown surface")
        if row.get("family_slug") is not None or row.get("deployment_id") is not None:
            raise ContractError(f"compose appended incorrectly scoped {table} row {row_id}")
        if table == "grade_history" and row.get("triggered_by") != "compose.py":
            raise ContractError(f"compose grade history row {row_id} has an invalid trigger")
        if table == "factor_score_history" and row.get("factor_id") not in factor_ids:
            raise ContractError("compose appended history for an unknown factor")


def verify_compose_owned_transition(
    before: dict[str, Any],
    after: dict[str, Any],
    family_slug: str,
) -> None:
    """Allow only compose.py grade fields and append-only target history."""
    if before.get("family_slug") != family_slug or after.get("family_slug") != family_slug:
        raise ContractError("compose transition family identity mismatch")
    for table in ("protocols", "families", "surfaces"):
        if _without_fields(before.get(table, []), COMPOSE_GRADE_FIELDS) != _without_fields(
            after.get(table, []), COMPOSE_GRADE_FIELDS
        ):
            raise ContractError(f"compose transition changed non-grade {table} fields")
    for table in (
        "deployments",
        "factor_scores",
        "factor_score_sources",
        "sources",
    ):
        if canonical_sha256(before.get(table, [])) != canonical_sha256(after.get(table, [])):
            raise ContractError(f"compose transition changed {table}")

    surface_ids = {str(row.get("surface_id")) for row in before.get("surfaces", [])}
    factor_ids = {str(row.get("factor_id")) for row in before.get("factor_scores", [])}
    for table in ("grade_history", "protocol_grade_history", "factor_score_history"):
        _verify_append_only_history(
            table=table,
            before_rows=before.get(table, []),
            after_rows=after.get(table, []),
            family_slug=family_slug,
            surface_ids=surface_ids,
            factor_ids=factor_ids,
        )


def _lock_compensation_rows(conn: Any, family_slug: str) -> None:
    """Lock target-owned rows before the final optimistic restore check."""
    queries = (
        "SELECT slug FROM protocols WHERE slug = %s FOR UPDATE",
        "SELECT family_slug FROM protocol_families WHERE family_slug = %s FOR UPDATE",
        "SELECT surface_id FROM protocol_surfaces WHERE family_slug = %s FOR UPDATE",
        "SELECT id FROM deployments WHERE protocol_slug = %s FOR UPDATE",
        "SELECT id FROM factor_scores WHERE protocol_slug = %s FOR UPDATE",
        "SELECT id FROM grade_history WHERE protocol_slug = %s FOR UPDATE",
        "SELECT id FROM protocol_grade_history WHERE protocol_slug = %s FOR UPDATE",
        "SELECT id FROM factor_score_history WHERE protocol_slug = %s FOR UPDATE",
        """
        SELECT s.id FROM sources s
        WHERE EXISTS (
          SELECT 1 FROM factor_score_sources fss
          JOIN factor_scores fs ON fs.id = fss.factor_score_id
          WHERE fss.source_id = s.id AND fs.protocol_slug = %s
        ) FOR UPDATE
        """,
        """
        SELECT fss.factor_score_id, fss.source_id
        FROM factor_score_sources fss
        JOIN factor_scores fs ON fs.id = fss.factor_score_id
        WHERE fs.protocol_slug = %s FOR UPDATE OF fss
        """,
    )
    with conn.cursor() as cur:
        for query in queries:
            cur.execute(query, (family_slug,))


def compensate_refresh(
    conn: Any,
    handoff: PublicHandoff,
    before_snapshot: dict[str, Any],
    expected_live_snapshot: dict[str, Any],
    before_other_sha256: str,
    receipt: ApplyMutationReceipt,
    cause: Exception,
) -> str:
    """Restore exact target state while preserving the failed pipeline run."""
    document = handoff.payload
    family = document["family_slug"]
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    _lock_compensation_rows(conn, family)
    verify_expected_live_snapshot(
        conn,
        family,
        expected_live_snapshot,
        stage="compensation precondition",
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pipeline_runs WHERE id = %s AND script_name = %s",
            (receipt.run_id, SCRIPT_NAME),
        )
        if cur.fetchone()[0] != 1:
            raise ContractError("compensation refused: failed apply audit reservation is missing")
        before_factor_ids = _row_ids(before_snapshot["factor_scores"])
        live_factor_ids = _live_ids(cur, "factor_scores", family_slug=family)
        if live_factor_ids != before_factor_ids | set(receipt.factor_score_ids):
            raise ContractError("compensation refused: target factor rows exceed the transaction receipt")
        before_deployment_ids = _row_ids(before_snapshot["deployments"])
        live_deployment_ids = _live_ids(cur, "deployments", family_slug=family)
        if live_deployment_ids != before_deployment_ids | set(receipt.inserted_deployment_ids):
            raise ContractError("compensation refused: target deployments exceed the transaction receipt")

        for row in before_snapshot["factor_scores"]:
            if row.get("is_current"):
                staged = dict(row)
                staged["is_current"] = False
                _restore_rows(cur, "factor_scores", "id", [staged])
        _delete_ids(cur, "factor_scores", set(receipt.factor_score_ids))
        _restore_rows(cur, "factor_scores", "id", before_snapshot["factor_scores"])
        _delete_ids(cur, "deployments", set(receipt.inserted_deployment_ids))
        _restore_rows(cur, "deployments", "id", before_snapshot["deployments"])
        _restore_rows(cur, "protocol_surfaces", "surface_id", before_snapshot["surfaces"])
        _restore_rows(cur, "protocol_families", "family_slug", before_snapshot["families"])
        _restore_rows(cur, "protocols", "slug", before_snapshot["protocols"])
        _delete_ids(cur, "sources", set(receipt.created_source_ids))
        for table in ("grade_history", "protocol_grade_history", "factor_score_history"):
            _restore_history_table(cur, table, before_snapshot[table], family)

    restored = capture_recovery_snapshot(conn, family)
    other_hash = canonical_sha256(normalized_snapshot(conn, family, target=False))
    restored_hash = verify_compensation(
        before_snapshot,
        restored,
        before_other_sha256,
        other_hash,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO change_log (changed_by, entity_type, entity_id, diff, reason)
            VALUES (%s, 'protocol_refresh_compensation', %s, %s::jsonb, %s)
            """,
            (
                SCRIPT_NAME,
                family,
                json.dumps(
                    {
                        "refresh_id": document["refresh_id"],
                        "run_id": receipt.run_id,
                        "artifact_sha256": handoff.artifact_sha256,
                        "restored_target_sha256": restored_hash,
                        "failure": str(cause),
                    }
                ),
                "restored pre-apply production state after post-commit failure",
            ),
        )
        if cur.rowcount != 1:
            raise ContractError("compensation audit expected one inserted row")
    return restored_hash


def finish_run(
    conn: Any,
    run_id: str,
    *,
    success: bool,
    error: str | None,
    duration_seconds: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
            SET success_count = %s, error_count = %s, error_summary = %s::jsonb,
                duration_seconds = %s
            WHERE id = %s AND script_name = %s
            """,
            (
                1 if success else 0,
                0 if success else 1,
                json.dumps(None if success else [error or "unknown protocol refresh failure"]),
                duration_seconds,
                run_id,
                SCRIPT_NAME,
            ),
        )
        if cur.rowcount != 1:
            raise ContractError("could not finalize the protocol refresh pipeline run")


def _assert_runner_success(name: str, result: Any) -> Any:
    returncode = getattr(result, "returncode", None)
    if returncode not in (None, 0):
        detail = getattr(result, "stderr", None) or getattr(result, "stdout", None) or ""
        raise ContractError(f"{name} failed with exit {returncode}: {str(detail).strip()}")
    if result is False or (isinstance(result, int) and not isinstance(result, bool) and result != 0):
        raise ContractError(f"{name} reported failure")
    return result


def run_post_commit_pipeline(
    *,
    compose_runner: Runner,
    dump_runner: Runner,
    semantic_verifier: Runner,
    db_url: str,
    family_slug: str,
    before_dump_result: Any = None,
    runtime_factor_score_ids: tuple[str, ...] = (),
    on_compose_success: Runner | None = None,
    verify_live_state: Runner | None = None,
) -> Any:
    """Invoke compose, dump, and semantic verification only through injected runners."""
    compose_result = compose_runner(db_url=db_url, family_slug=family_slug)
    _assert_runner_success("compose runner", compose_result)
    if on_compose_success is not None:
        on_compose_success()
    if verify_live_state is not None:
        verify_live_state(stage="after successful compose")
    dump_result = dump_runner(db_url=db_url, family_slug=family_slug)
    _assert_runner_success("dump runner", dump_result)
    if verify_live_state is not None:
        verify_live_state(stage="after candidate dump")
    verification = semantic_verifier(
        db_url=db_url,
        family_slug=family_slug,
        before_dump_result=before_dump_result,
        dump_result=dump_result,
        runtime_factor_score_ids=runtime_factor_score_ids,
    )
    _assert_runner_success("semantic verifier", verification)
    if verify_live_state is not None:
        verify_live_state(stage="after semantic verification")
    return dump_result


def verify_no_change_date_only(
    before: dict[str, Any],
    after: dict[str, Any],
    effective_refresh_date: str,
) -> None:
    expected = deepcopy(before)
    protocols = expected.get("protocols", [])
    if len(protocols) != 1:
        raise ContractError("date-only verification expected one protocol row")
    protocols[0]["last_refreshed"] = effective_refresh_date
    if canonical_sha256(expected) != canonical_sha256(after):
        raise ContractError("no-change refresh mutated data beyond last_refreshed")


def _apply_refresh_locked(
    conn: Any,
    db_url: str,
    handoff: PublicHandoff,
    *,
    authorization: dict[str, Any],
    backup: dict[str, Any],
    baseline_dump_runner: Runner | None = None,
    compose_runner: Runner | None = None,
    dump_runner: Runner | None = None,
    semantic_verifier: Runner | None = None,
) -> dict[str, Any]:
    """Apply, verify, and compensate one exact authorized family refresh."""
    started = time.monotonic()
    before = preflight(conn, handoff)
    plan: ApplyPlan = before["plan"]
    production_plan = before["production_plan"]
    verify_production_plan_sha(production_plan)
    if authorization["operation"] != "apply_protocol_refresh":
        raise ContractError("authorization does not permit protocol refresh apply")
    if authorization["artifact_sha256"] != handoff.artifact_sha256:
        raise ContractError("authorization is not bound to this exact handoff")
    if authorization["plan_sha256"] != production_plan["plan_sha256"]:
        raise ContractError("production drifted from the authorized plan_sha256")
    if authorization["database_identity"] != before["database_identity"]:
        raise ContractError("authorization database identity does not match the connected target")
    if backup["database_identity"] != before["database_identity"]:
        raise ContractError("backup database identity does not match the connected target")
    if backup.get("operation") != "apply_protocol_refresh":
        raise ContractError("backup receipt does not cover protocol refresh apply")
    if backup.get("plan_sha256") != production_plan["plan_sha256"]:
        raise ContractError("backup receipt is not bound to the authorized production plan")
    if backup.get("artifact_sha256") != handoff.artifact_sha256:
        raise ContractError("backup receipt is not bound to the exact public handoff")
    if plan.semantic_changes and any(
        runner is None
        for runner in (baseline_dump_runner, compose_runner, dump_runner, semantic_verifier)
    ):
        raise ContractError(
            "changed refresh requires injected baseline dump, compose, candidate dump, "
            "and semantic runners"
        )
    if already_applied(conn, plan.refresh_id):
        raise ContractError(f"refresh {plan.refresh_id} was already reserved/applied")

    recovery_before = capture_recovery_snapshot(conn, plan.family_slug)
    expected_live_snapshot = recovery_before
    receipt: ApplyMutationReceipt | None = None
    source_committed = False
    try:
        before_dump_result = None
        if plan.semantic_changes:
            before_dump_result = baseline_dump_runner(  # type: ignore[misc]
                db_url=db_url,
                family_slug=plan.family_slug,
            )
            _assert_runner_success("baseline dump runner", before_dump_result)
        receipt = apply_transaction(
            conn,
            handoff,
            production_plan=production_plan,
            authorization_id=authorization["authorization_id"],
            backup_id=backup["backup_id"],
        )
        verify_runtime_factor_score_receipt(conn, handoff, receipt)
        inside_other = canonical_sha256(
            normalized_snapshot(conn, plan.family_slug, target=False)
        )
        if inside_other != production_plan["production_before"]["unrelated_protocols_sha256"]:
            raise ContractError("unrelated protocol rows changed inside the apply transaction")
        expected_live_snapshot = capture_recovery_snapshot(conn, plan.family_slug)
        conn.commit()
        source_committed = True
        verify_expected_live_snapshot(
            conn,
            plan.family_slug,
            expected_live_snapshot,
            stage="after source commit",
        )

        dump_result = None
        if plan.semantic_changes:
            compose_transition_error: ContractError | None = None

            def account_successful_compose() -> None:
                nonlocal compose_transition_error, expected_live_snapshot
                candidate = capture_recovery_snapshot(
                    conn,
                    plan.family_slug,
                )
                try:
                    verify_compose_owned_transition(
                        expected_live_snapshot,
                        candidate,
                        plan.family_slug,
                    )
                except ContractError as exc:
                    compose_transition_error = exc
                    return
                expected_live_snapshot = candidate

            def verify_live_state(*, stage: str) -> None:
                if compose_transition_error is not None:
                    if stage == "after successful compose":
                        return
                    raise compose_transition_error
                verify_expected_live_snapshot(
                    conn,
                    plan.family_slug,
                    expected_live_snapshot,
                    stage=stage,
                )

            dump_result = run_post_commit_pipeline(
                compose_runner=compose_runner,  # type: ignore[arg-type]
                dump_runner=dump_runner,  # type: ignore[arg-type]
                semantic_verifier=semantic_verifier,  # type: ignore[arg-type]
                db_url=db_url,
                family_slug=plan.family_slug,
                before_dump_result=before_dump_result,
                runtime_factor_score_ids=receipt.factor_score_ids,
                on_compose_success=account_successful_compose,
                verify_live_state=verify_live_state,
            )
        verify_expected_live_snapshot(
            conn,
            plan.family_slug,
            expected_live_snapshot,
            stage="before final snapshot",
        )
        after = snapshot_hashes(conn, plan.family_slug)
        if (
            after["normalized_other_sha256"]
            != production_plan["production_before"]["unrelated_protocols_sha256"]
        ):
            raise ContractError("unrelated protocol invariant failed after verification")
        if not plan.semantic_changes:
            verify_no_change_date_only(
                before["normalized_target"],
                after["normalized_target"],
                plan.effective_refresh_date,
            )
        finish_run(
            conn,
            receipt.run_id,
            success=True,
            error=None,
            duration_seconds=round(time.monotonic() - started),
        )
        conn.commit()
        return {
            "schema_version": "1.0",
            "receipt_type": "protocol_refresh_transaction_receipt",
            "status": "succeeded",
            "refresh_id": plan.refresh_id,
            "family_slug": plan.family_slug,
            "artifact_sha256": handoff.artifact_sha256,
            "plan_sha256": production_plan["plan_sha256"],
            "authorization_id": authorization["authorization_id"],
            "backup_id": backup["backup_id"],
            "database_identity": before["database_identity"],
            "run_id": receipt.run_id,
            "row_counts": receipt.row_counts,
            "before_snapshot": before["normalized_target"],
            "after_snapshot": after["normalized_target"],
            "before_target_sha256": before["normalized_target_sha256"],
            "after_target_sha256": after["normalized_target_sha256"],
            "unrelated_protocols_sha256": after["normalized_other_sha256"],
            "pipeline_ran": plan.semantic_changes,
            "dump_result": str(dump_result) if dump_result is not None else None,
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        conn.rollback()
        if receipt is not None and not source_committed:
            raise ContractError(
                "refresh source transaction did not commit; no post-commit compensation was needed"
            ) from exc
        if receipt is None:
            raise

        compensation_error: Exception | None = None
        restored_hash: str | None = None
        try:
            restored_hash = compensate_refresh(
                conn,
                handoff,
                recovery_before,
                expected_live_snapshot,
                production_plan["production_before"]["unrelated_protocols_sha256"],
                receipt,
                exc,
            )
            conn.commit()
        except Exception as rollback_exc:
            conn.rollback()
            compensation_error = rollback_exc
        compensation_status = (
            f"proved ({restored_hash})"
            if compensation_error is None
            else f"FAILED/UNPROVED ({compensation_error})"
        )
        audit_error: Exception | None = None
        try:
            finish_run(
                conn,
                receipt.run_id,
                success=False,
                error=f"{exc}; compensation: {compensation_status}",
                duration_seconds=round(time.monotonic() - started),
            )
            conn.commit()
        except Exception as run_audit_exc:
            conn.rollback()
            audit_error = run_audit_exc
        if compensation_error is not None or audit_error is not None:
            details = [f"refresh failure: {exc}", f"compensation: {compensation_status}"]
            if audit_error is not None:
                details.append(f"failed audit preservation: {audit_error}")
            raise ContractError("; ".join(details)) from exc
        raise ContractError(
            f"post-commit refresh failure: {exc}; compensation proved pre-apply state {restored_hash}; "
            f"failed audit run {receipt.run_id} was preserved"
        ) from exc


def _acquire_family_session_lock(conn: Any, family_slug: str) -> None:
    acquired = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_lock(hashtext(%s))",
                (f"protocol-refresh:{family_slug}",),
            )
            cur.fetchone()
        acquired = True
        # A session lock survives commit. Start the serializable snapshot only
        # after any prior holder has completed and this session owns the lock.
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    except Exception:
        conn.rollback()
        if acquired:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    (f"protocol-refresh:{family_slug}",),
                )
                cur.fetchone()
            conn.commit()
        raise


def _release_family_session_lock(conn: Any, family_slug: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_unlock(hashtext(%s))",
            (f"protocol-refresh:{family_slug}",),
        )
        row = cur.fetchone()
    if row is None or row[0] is not True:
        raise ContractError("family session advisory lock could not be released cleanly")


def apply_refresh(
    conn: Any,
    db_url: str,
    handoff: PublicHandoff,
    *,
    authorization: dict[str, Any],
    backup: dict[str, Any],
    baseline_dump_runner: Runner | None = None,
    compose_runner: Runner | None = None,
    dump_runner: Runner | None = None,
    semantic_verifier: Runner | None = None,
) -> dict[str, Any]:
    """Hold the family session lock across plan, pipeline, and recovery."""
    family_slug = handoff.payload["family_slug"]
    _acquire_family_session_lock(conn, family_slug)
    try:
        return _apply_refresh_locked(
            conn,
            db_url,
            handoff,
            authorization=authorization,
            backup=backup,
            baseline_dump_runner=baseline_dump_runner,
            compose_runner=compose_runner,
            dump_runner=dump_runner,
            semantic_verifier=semantic_verifier,
        )
    finally:
        _release_family_session_lock(conn, family_slug)
