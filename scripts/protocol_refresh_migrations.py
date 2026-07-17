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
NIGHTLY_FUNCTION_SIGNATURES = (
    "public.refresh_sync_family_tvl(text,numeric)",
    "public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)",
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


def _expected_nightly_owner_column_grants() -> set[tuple[str, str, str]]:
    grants: set[tuple[str, str, str]] = set()
    for table, privileges in {
        "protocol_families": {
            "SELECT": {"family_slug", "primary_surface_id"},
            "UPDATE": {
                "total_value_secured_usd",
                "headline_grade",
                "rubric_version",
                "graded_at",
                "risk_score",
                "category_severities",
                "cap_applied",
                "cap_reason",
                "updated_at",
            },
        },
        "protocol_surfaces": {
            "SELECT": {"surface_id", "family_slug", "is_primary"},
            "UPDATE": {
                "tvs_usd",
                "headline_grade",
                "rubric_version",
                "graded_at",
                "risk_score",
                "category_severities",
                "cap_applied",
                "cap_reason",
                "updated_at",
            },
        },
    }.items():
        for privilege, columns in privileges.items():
            grants.update((table, column, privilege) for column in columns)
    return grants


def _nightly_function_body_sha256s(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    content = (
        repo_root / "db" / "migrations" / "0014_nightly_ingest_topology_functions.sql"
    ).read_text(encoding="utf-8-sig")
    remaining = content
    bodies: list[str] = []
    for _signature in NIGHTLY_FUNCTION_SIGNATURES:
        marker = "AS $function$"
        if marker not in remaining:
            raise ContractError("migration 0014 is missing a required function body")
        remaining = remaining.split(marker, 1)[1]
        if "$function$;" not in remaining:
            raise ContractError("migration 0014 has an unterminated function body")
        body, remaining = remaining.split("$function$;", 1)
        bodies.append(body)
    return {
        signature: hashlib.sha256(body.encode("utf-8")).hexdigest()
        for signature, body in zip(NIGHTLY_FUNCTION_SIGNATURES, bodies, strict=True)
    }


def _nightly_functions_ready(
    cur: Any,
    expected_body_sha256s: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    expected_body_sha256s = expected_body_sha256s or _nightly_function_body_sha256s()
    cur.execute(
        """SELECT r.rolname, r.rolsuper, r.rolcreatedb, r.rolcreaterole,
                  r.rolcanlogin, r.rolreplication, r.rolinherit, r.rolbypassrls,
                  EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.roleid = r.oid OR m.member = r.oid
                  ) AS has_memberships,
                  EXISTS (
                    SELECT 1 FROM pg_stat_activity a
                    WHERE a.usesysid = r.oid
                      AND a.pid <> pg_backend_pid()
                  ) AS has_active_sessions,
                  EXISTS (
                    SELECT 1
                    FROM pg_shdepend d
                    WHERE d.refclassid = 'pg_authid'::regclass
                      AND d.refobjid = r.oid
                      AND d.deptype = 'o'
                      AND NOT (
                        d.dbid = (
                          SELECT oid FROM pg_database WHERE datname = current_database()
                        )
                        AND d.classid = 'pg_proc'::regclass
                        AND (
                          d.objid = to_regprocedure('public.refresh_sync_family_tvl(text,numeric)')
                          OR d.objid = to_regprocedure('public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)')
                        )
                      )
                  ) AS owns_unexpected_objects
           FROM pg_roles r
           WHERE rolname IN ('rdapp', 'rdapp_nightly_owner')
           ORDER BY rolname"""
    )
    roles = {row[0]: row[1:] for row in cur.fetchall()}
    if "rdapp" not in roles:
        return False, "runtime role rdapp is missing"
    if roles.get("rdapp_nightly_owner") != (
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ):
        return False, f"nightly function owner role is missing or unsafe: {roles}"
    cur.execute(
        """SELECT c.relname,
                  p.polcmd = 'w'
                    AND p.polroles = ARRAY[r.oid]
                    AND pg_get_expr(p.polqual, p.polrelid) = 'true'
                    AND pg_get_expr(p.polwithcheck, p.polrelid) = 'true'
           FROM pg_policy p
           JOIN pg_class c ON c.oid = p.polrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN pg_roles r ON r.rolname = 'rdapp_nightly_owner'
           WHERE n.nspname = 'public'
             AND c.relname IN ('protocol_families', 'protocol_surfaces')
             AND p.polname = 'nightly_owner_update'
           ORDER BY c.relname"""
    )
    policies = dict(cur.fetchall())
    if policies != {"protocol_families": True, "protocol_surfaces": True}:
        return False, f"nightly function owner RLS policies are missing or unsafe: {policies}"
    cur.execute(
        """SELECT has_schema_privilege('rdapp_nightly_owner', 'public', 'USAGE'),
                  has_schema_privilege('rdapp_nightly_owner', 'public', 'CREATE')"""
    )
    schema_usage, schema_create = cur.fetchone()
    cur.execute(
        """SELECT c.relname, a.attname, acl.privilege_type
           FROM pg_attribute a
           JOIN pg_class c ON c.oid = a.attrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           CROSS JOIN LATERAL aclexplode(a.attacl) acl
           JOIN pg_roles r ON r.oid = acl.grantee
           WHERE r.rolname = 'rdapp_nightly_owner'
             AND n.nspname = 'public'
           ORDER BY c.relname, a.attname, acl.privilege_type"""
    )
    column_grants = set(cur.fetchall())
    expected_column_grants = _expected_nightly_owner_column_grants()
    cur.execute(
        """SELECT c.relname, acl.privilege_type
           FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           CROSS JOIN LATERAL aclexplode(c.relacl) acl
           JOIN pg_roles r ON r.oid = acl.grantee
           WHERE r.rolname = 'rdapp_nightly_owner'
             AND n.nspname = 'public'"""
    )
    table_grants = cur.fetchall()
    if (
        not schema_usage
        or schema_create
        or column_grants != expected_column_grants
        or table_grants
    ):
        return False, (
            "nightly function owner privileges are unsafe: "
            f"schema_usage={schema_usage}; schema_create={schema_create}; "
            f"column_grants={sorted(column_grants)}; table_grants={table_grants}"
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
                  p.prosrc,
                  CASE WHEN p.oid IS NULL THEN false
                       ELSE has_function_privilege('rdapp', p.oid, 'EXECUTE')
                  END,
                  EXISTS (
                    SELECT 1
                    FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                    WHERE acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'rdapp')
                      AND acl.privilege_type = 'EXECUTE'
                      AND acl.is_grantable
                  ) AS rdapp_grant_option,
                  EXISTS (
                    SELECT 1
                    FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                    WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                  ) AS public_execute,
                  EXISTS (
                    SELECT 1
                    FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                    WHERE acl.privilege_type = 'EXECUTE'
                      AND acl.grantee NOT IN (
                        p.proowner,
                        (SELECT oid FROM pg_roles WHERE rolname = 'rdapp')
                      )
                  ) AS unexpected_execute
           FROM required
           LEFT JOIN pg_proc p ON p.oid = to_regprocedure(required.signature)
           ORDER BY required.signature""",
        (list(NIGHTLY_FUNCTION_SIGNATURES),),
    )
    rows = cur.fetchall()
    checked_rows = []
    for (
            _signature,
            function_exists,
            security_definer,
            settings,
            owner,
            function_body,
            rdapp_execute,
            rdapp_grant_option,
            public_execute,
            unexpected_execute,
    ) in rows:
        body_matches = bool(
            function_body is not None
            and hashlib.sha256(function_body.encode("utf-8")).hexdigest()
            == expected_body_sha256s.get(_signature)
        )
        checked_rows.append(
            (
                _signature,
                function_exists,
                security_definer,
                settings,
                owner,
                rdapp_execute,
                rdapp_grant_option,
                public_execute,
                unexpected_execute,
                body_matches,
            )
        )
    ready = len(checked_rows) == 2 and all(
        function_exists
        and security_definer
        and "search_path=pg_catalog" in settings
        and owner == "rdapp_nightly_owner"
        and rdapp_execute
        and not rdapp_grant_option
        and not public_execute
        and not unexpected_execute
        and body_matches
        for (
            _signature,
            function_exists,
            security_definer,
            settings,
            owner,
            rdapp_execute,
            rdapp_grant_option,
            public_execute,
            unexpected_execute,
            body_matches,
        ) in checked_rows
    )
    return ready, (
        f"nightly topology function contracts: {checked_rows}; RLS policies: {policies}; "
        f"owner column grants: {sorted(column_grants)}"
    )


def _migration_state(
    *,
    name: str,
    digest: str,
    effect_applied: bool,
    detail: str,
    ledger_exists: bool,
    recorded: str | None,
) -> MigrationState:
    if recorded is not None and recorded != digest:
        raise ContractError(f"recorded migration checksum drift for {name}")
    if ledger_exists and recorded == digest and not effect_applied:
        raise ContractError(
            f"recorded migration contract drift for {name}; manual remediation is required: {detail}"
        )
    applied = effect_applied and ledger_exists and recorded == digest
    if not ledger_exists:
        detail = f"{detail}; checksum ledger unavailable"
    elif recorded is None:
        detail = f"{detail}; checksum ledger entry missing"
    return MigrationState(name, digest, applied, detail)


def inspect_migrations(conn: Any, repo_root: Path = REPO_ROOT) -> tuple[MigrationState, ...]:
    specs = migration_specs(repo_root)
    with conn.cursor() as cur:
        last_refreshed = _has_column(cur, "protocols", "last_refreshed")
        idempotency = _has_index(cur, "pipeline_runs_protocol_refresh_trigger_unique")
        active_policy_ready, active_policy_detail = _active_rubric_policy_ready(cur)
        grants_ready, grants_detail = _runtime_grants_ready(cur)
        nightly_functions_ready, nightly_functions_detail = _nightly_functions_ready(
            cur,
            _nightly_function_body_sha256s(repo_root),
        )
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
        states.append(
            _migration_state(
                name=name,
                digest=digest,
                effect_applied=effect_applied,
                detail=detail,
                ledger_exists=ledger_exists,
                recorded=recorded,
            )
        )
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
