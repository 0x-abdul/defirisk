"""Explicit planning and application for refresh-owned database migrations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

if __package__ == "scripts" or (__package__ and __package__.startswith("scripts.")):
    from scripts.protocol_refresh_apply.contracts import (
        ContractError,
        canonical_sha256,
        load_backup_receipt,
        load_json_strict,
    )
    from scripts.protocol_refresh_apply.db import (
        database_identity as protocol_apply_db_identity,
    )
else:
    from protocol_refresh_apply.contracts import (
        ContractError,
        canonical_sha256,
        load_backup_receipt,
        load_json_strict,
    )
    from protocol_refresh_apply.db import database_identity as protocol_apply_db_identity


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_NAMES = (
    "0009_protocol_last_refreshed.sql",
    "0010_protocol_refresh_idempotency.sql",
    "0011_active_rubric_factor_score_reads.sql",
    "0012_runtime_role_grants.sql",
    "0013_schema_migration_ledger.sql",
    "0014_nightly_ingest_topology_functions.sql",
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class MigrationState:
    name: str
    sha256: str
    applied: bool
    detail: str


def connected_database_identity(conn: Any) -> str:
    """Use the same non-secret database identity as protocol refresh apply."""
    return protocol_apply_db_identity(conn)


def migration_specs(repo_root: Path = REPO_ROOT) -> tuple[tuple[str, Path, str], ...]:
    result = []
    for name in MIGRATION_NAMES:
        path = repo_root / "db" / "migrations" / name
        if not path.is_file():
            raise ContractError(f"required refresh migration is missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append((name, path, digest))
    return tuple(result)


def _has_column(cur: Any, table: str, column: str) -> bool:
    cur.execute(
        """SELECT EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
           )""",
        (table, column),
    )
    return bool(cur.fetchone()[0])


def _has_index(cur: Any, index: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{index}",))
    return bool(cur.fetchone()[0])


def _runtime_grants_ready(cur: Any) -> tuple[bool, str]:
    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rdapp')")
    if not cur.fetchone()[0]:
        return False, "runtime role rdapp is missing"
    cur.execute("SELECT has_schema_privilege('rdapp', 'public', 'USAGE')")
    schema_usage = bool(cur.fetchone()[0])
    cur.execute(
        """SELECT table_name, privilege_type
           FROM information_schema.role_table_grants
           WHERE grantee = 'rdapp'
             AND table_schema = 'public'
             AND table_name IN ('protocol_families', 'protocol_surfaces')
           ORDER BY table_name, privilege_type"""
    )
    grants: dict[str, set[str]] = {}
    for table, privilege in cur.fetchall():
        grants.setdefault(table, set()).add(privilege)
    expected = {"SELECT"}
    ready = schema_usage and grants == {
        "protocol_families": expected,
        "protocol_surfaces": expected,
    }
    printable = {table: sorted(values) for table, values in sorted(grants.items())}
    return ready, f"schema usage: {schema_usage}; runtime grants: {printable}"


def _active_rubric_policy_ready(cur: Any) -> tuple[bool, str]:
    cur.execute(
        "SELECT pg_get_expr(polqual, polrelid) FROM pg_policy "
        "WHERE polname = 'public_read' AND polrelid = 'public.factor_scores'::regclass"
    )
    row = cur.fetchone()
    definition = "" if row is None else str(row[0])
    normalized = " ".join(definition.split()).lower()
    ready = all(token in normalized for token in ("is_current", "rubric_version", "rubric_versions", "is_active", "group by", "having"))
    return ready, "active-rubric factor_scores policy " + ("present" if ready else "missing or incomplete")


def _nightly_functions_ready(cur: Any) -> tuple[bool, str]:
    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rdapp')")
    if not cur.fetchone()[0]:
        return False, "runtime role rdapp is missing"
    signatures = (
        "public.refresh_sync_family_tvl(text,numeric)",
        "public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)",
    )
    cur.execute(
        """WITH required(signature) AS (
             SELECT unnest(%s::text[])
           )
           SELECT required.signature,
                  p.oid IS NOT NULL AS function_exists,
                  p.prosecdef,
                  COALESCE(p.proconfig, ARRAY[]::text[]),
                  pg_get_userbyid(p.proowner),
                  CASE WHEN p.oid IS NULL THEN false
                       ELSE has_function_privilege('rdapp', p.oid, 'EXECUTE')
                  END,
                  EXISTS (
                    SELECT 1
                    FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                    WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                  ) AS public_execute
           FROM required
           LEFT JOIN pg_proc p ON p.oid = to_regprocedure(required.signature)
           ORDER BY required.signature""",
        (list(signatures),),
    )
    rows = cur.fetchall()
    ready = len(rows) == 2 and all(
        function_exists
        and security_definer
        and "search_path=pg_catalog" in settings
        and owner != "rdapp"
        and rdapp_execute
        and not public_execute
        for (
            _signature,
            function_exists,
            security_definer,
            settings,
            owner,
            rdapp_execute,
            public_execute,
        ) in rows
    )
    return ready, f"nightly topology function contracts: {rows}"


def inspect_migrations(conn: Any, repo_root: Path = REPO_ROOT) -> tuple[MigrationState, ...]:
    specs = migration_specs(repo_root)
    with conn.cursor() as cur:
        last_refreshed = _has_column(cur, "protocols", "last_refreshed")
        idempotency = _has_index(cur, "pipeline_runs_protocol_refresh_trigger_unique")
        active_policy_ready, active_policy_detail = _active_rubric_policy_ready(cur)
        grants_ready, grants_detail = _runtime_grants_ready(cur)
        nightly_functions_ready, nightly_functions_detail = _nightly_functions_ready(cur)
        ledger_exists = bool(
            cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL").fetchone()[0]
        )
        ledger: dict[str, str] = {}
        if ledger_exists:
            cur.execute("SELECT filename, sha256 FROM schema_migrations")
            ledger = dict(cur.fetchall())
    details = {
        MIGRATION_NAMES[0]: (last_refreshed, "protocols.last_refreshed exists"),
        MIGRATION_NAMES[1]: (idempotency, "refresh idempotency index exists"),
        MIGRATION_NAMES[2]: (active_policy_ready, active_policy_detail),
        MIGRATION_NAMES[3]: (grants_ready, grants_detail),
        MIGRATION_NAMES[4]: (ledger_exists, "schema migration ledger exists"),
        MIGRATION_NAMES[5]: (nightly_functions_ready, nightly_functions_detail),
    }
    states = []
    for name, _path, digest in specs:
        effect_applied, detail = details[name]
        recorded = ledger.get(name)
        if recorded is not None and recorded != digest:
            raise ContractError(f"recorded migration checksum drift for {name}")
        applied = effect_applied and ledger_exists and recorded == digest
        if not ledger_exists:
            detail = f"{detail}; checksum ledger unavailable"
        elif recorded is None:
            detail = f"{detail}; checksum ledger entry missing"
        states.append(MigrationState(name, digest, applied, detail))
    return tuple(states)


def plan_document(
    database_identity_value: str,
    states: Iterable[MigrationState],
) -> dict[str, Any]:
    rows = [asdict(state) for state in states]
    core = {
        "schema_version": "1.0",
        "operation": "apply_refresh_migrations",
        "database_identity": database_identity_value,
        "migrations": rows,
        "pending_migrations": [row["name"] for row in rows if not row["applied"]],
    }
    return {**core, "plan_sha256": canonical_sha256(core)}


def validate_migration_authorization(
    receipt: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema_version", "receipt_type", "authorization_id", "operation",
        "database_identity", "plan_sha256", "allowed_migrations",
        "authorized_by", "authorized_at",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise ContractError("migration authorization fields must exactly match the contract")
    if receipt["schema_version"] != "1.0":
        raise ContractError("migration authorization schema_version must be 1.0")
    if receipt["receipt_type"] != "refresh_migration_authorization":
        raise ContractError("migration authorization receipt_type is invalid")
    if receipt["operation"] != "apply_refresh_migrations":
        raise ContractError("migration authorization operation is invalid")
    if receipt["database_identity"] != plan["database_identity"]:
        raise ContractError("migration authorization database identity mismatch")
    if receipt["plan_sha256"] != plan["plan_sha256"]:
        raise ContractError("migration authorization plan checksum mismatch")
    allowed = receipt["allowed_migrations"]
    if not isinstance(allowed, list) or allowed != plan["pending_migrations"]:
        raise ContractError("migration authorization must allow exactly the pending migrations")
    if not isinstance(receipt["authorization_id"], str) or not receipt["authorization_id"]:
        raise ContractError("migration authorization_id is required")
    if not isinstance(receipt["authorized_by"], str) or not receipt["authorized_by"]:
        raise ContractError("migration authorized_by is required")
    try:
        parsed = datetime.fromisoformat(str(receipt["authorized_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("migration authorized_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ContractError("migration authorized_at must include a timezone")
    if not isinstance(receipt["plan_sha256"], str) or not SHA256_RE.fullmatch(receipt["plan_sha256"]):
        raise ContractError("migration plan_sha256 must be lowercase SHA-256")
    return dict(receipt)


def _record_pending_migrations(
    cur: Any,
    *,
    pending_migrations: Iterable[str],
    specs: Mapping[str, tuple[Path, str]],
    authorization_id: str,
) -> None:
    for name in pending_migrations:
        _path, digest = specs[name]
        cur.execute(
            """INSERT INTO schema_migrations (
                   filename, sha256, applied_by, authorization_id
               ) VALUES (%s, %s, current_user, %s)""",
            (name, digest, authorization_id),
        )


def apply_pending_migrations(
    conn: Any,
    *,
    repo_root: Path,
    expected_database: str,
    backup_receipt_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        actual_database = cur.fetchone()[0]
    if actual_database != expected_database:
        raise ContractError(
            f"database name mismatch: {actual_database!r} != {expected_database!r}"
        )

    identity = connected_database_identity(conn)
    before = inspect_migrations(conn, repo_root)
    plan = plan_document(identity, before)
    if not plan["pending_migrations"]:
        raise ContractError("no refresh migrations are pending; refusing an apply no-op")
    backup = load_backup_receipt(
        backup_receipt_path,
        expected_operation="apply_refresh_migrations",
        plan_sha256=plan["plan_sha256"],
        database_identity=identity,
    )
    authorization = validate_migration_authorization(
        load_json_strict(authorization_path), plan=plan
    )
    specs = {name: (path, digest) for name, path, digest in migration_specs(repo_root)}

    conn.rollback()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("defirisk-refresh-migrations",))
            locked = plan_document(
                connected_database_identity(conn),
                inspect_migrations(conn, repo_root),
            )
            if locked["plan_sha256"] != plan["plan_sha256"]:
                raise ContractError("refresh migration plan drifted after lock acquisition")
            for name in locked["pending_migrations"]:
                path, digest = specs[name]
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ContractError(f"migration changed after planning: {name}")
                cur.execute(path.read_text(encoding="utf-8-sig"))
            _record_pending_migrations(
                cur,
                pending_migrations=locked["pending_migrations"],
                specs=specs,
                authorization_id=authorization["authorization_id"],
            )
            after = inspect_migrations(conn, repo_root)
            incomplete = [state.name for state in after if not state.applied]
            if incomplete:
                raise ContractError(f"refresh migrations failed postconditions: {incomplete}")
            cur.execute(
                """INSERT INTO pipeline_runs (
                       script_name, cadence_bucket, protocols_touched,
                       fetchers_invoked, success_count, error_count, triggered_by, notes
                   ) VALUES (%s, %s, 0, '[]'::jsonb, %s, 0, %s, %s)""",
                (
                    "manage-refresh-migrations.py",
                    "manual",
                    len(locked["pending_migrations"]),
                    authorization["authorization_id"],
                    json.dumps({"plan_sha256": plan["plan_sha256"]}),
                ),
            )

    return {
        "schema_version": "1.0",
        "operation": "apply_refresh_migrations",
        "database_identity": identity,
        "plan_sha256": plan["plan_sha256"],
        "authorization_id": authorization["authorization_id"],
        "backup_id": backup["backup_id"],
        "applied_migrations": plan["pending_migrations"],
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
