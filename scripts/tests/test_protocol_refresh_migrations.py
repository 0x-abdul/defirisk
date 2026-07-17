from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_migrations import (
    ContractError,
    MigrationState,
    _expected_nightly_owner_column_grants,
    _nightly_function_body_sha256s,
    _migration_state,
    _record_pending_migrations,
    _nightly_functions_ready,
    inspect_migrations,
    plan_document,
    validate_migration_authorization,
)


DATABASE_IDENTITY = "postgresql:risk_dashboard:migrator@127.0.0.1:5432"


def states(*, applied: bool = False) -> tuple[MigrationState, ...]:
    return (
        MigrationState("0009_protocol_last_refreshed.sql", "a" * 64, applied, "column"),
        MigrationState("0010_protocol_refresh_idempotency.sql", "b" * 64, applied, "index"),
        MigrationState("0011_active_rubric_factor_score_reads.sql", "e" * 64, applied, "policy"),
        MigrationState("0012_runtime_role_grants.sql", "c" * 64, applied, "grants"),
        MigrationState("0013_schema_migration_ledger.sql", "d" * 64, applied, "ledger"),
        MigrationState("0014_nightly_ingest_topology_functions.sql", "f" * 64, applied, "functions"),
    )


def authorization(plan: dict) -> dict:
    return {
        "schema_version": "1.0",
        "receipt_type": "refresh_migration_authorization",
        "authorization_id": "migration-window-2026-07-11",
        "operation": "apply_refresh_migrations",
        "database_identity": plan["database_identity"],
        "plan_sha256": plan["plan_sha256"],
        "allowed_migrations": plan["pending_migrations"],
        "authorized_by": "maintainer",
        "authorized_at": datetime.now(timezone.utc).isoformat(),
    }


def test_plan_is_stable_and_orders_only_refresh_owned_migrations() -> None:
    left = plan_document(DATABASE_IDENTITY, states())
    right = plan_document(DATABASE_IDENTITY, states())
    assert left == right
    assert left["database_identity"] == DATABASE_IDENTITY
    assert left["pending_migrations"] == [
        "0009_protocol_last_refreshed.sql",
        "0010_protocol_refresh_idempotency.sql",
        "0011_active_rubric_factor_score_reads.sql",
        "0012_runtime_role_grants.sql",
        "0013_schema_migration_ledger.sql",
        "0014_nightly_ingest_topology_functions.sql",
    ]


def test_authorization_binds_exact_database_plan_and_order() -> None:
    plan = plan_document(DATABASE_IDENTITY, states())
    receipt = authorization(plan)
    assert validate_migration_authorization(receipt, plan=plan) == receipt

    drifted = json.loads(json.dumps(receipt))
    drifted["allowed_migrations"].reverse()
    with pytest.raises(ContractError, match="exactly"):
        validate_migration_authorization(drifted, plan=plan)

    for wrong_identity in (
        "postgresql:another_database:migrator@127.0.0.1:5432",
        "postgresql:risk_dashboard:another_user@127.0.0.1:5432",
        "postgresql:risk_dashboard:migrator@db.example:5432",
        "postgresql:risk_dashboard:migrator@127.0.0.1:5433",
    ):
        wrong_db = json.loads(json.dumps(receipt))
        wrong_db["database_identity"] = wrong_identity
        with pytest.raises(ContractError, match="identity"):
            validate_migration_authorization(wrong_db, plan=plan)


def test_complete_plan_requires_explicit_empty_authorization() -> None:
    plan = plan_document(DATABASE_IDENTITY, states(applied=True))
    receipt = authorization(plan)
    assert receipt["allowed_migrations"] == []
    validate_migration_authorization(receipt, plan=plan)


def test_ledger_inserts_only_pending_rows_without_rewriting_prior_attribution() -> None:
    class RecordingCursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[str, str, str]]] = []

        def execute(self, query: str, params: tuple[str, str, str]) -> None:
            self.calls.append((query, params))

    cursor = RecordingCursor()
    specs = {state.name: (Path(state.name), state.sha256) for state in states()}
    _record_pending_migrations(
        cursor,
        pending_migrations=("0012_runtime_role_grants.sql", "0013_schema_migration_ledger.sql"),
        specs=specs,
        authorization_id="new-window",
    )

    assert [params[0] for _query, params in cursor.calls] == [
        "0012_runtime_role_grants.sql",
        "0013_schema_migration_ledger.sql",
    ]
    assert all(params[2] == "new-window" for _query, params in cursor.calls)
    assert all("ON CONFLICT" not in query for query, _params in cursor.calls)
    assert all("DO UPDATE" not in query for query, _params in cursor.calls)


def test_missing_ledger_keeps_replay_safe_migrations_pending(tmp_path: Path) -> None:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    migration_source = (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "0014_nightly_ingest_topology_functions.sql"
    ).read_text(encoding="utf-8-sig")
    for state in states():
        content = migration_source if state.name.startswith("0014_") else f"-- {state.name}\n"
        (migrations / state.name).write_text(content, encoding="utf-8")
    function_bodies = _nightly_function_body_sha256s(tmp_path)
    body_parts = migration_source.split("AS $function$")[1:]
    body_by_signature = {
        signature: part.split("$function$;", 1)[0]
        for signature, part in zip(function_bodies, body_parts, strict=True)
    }

    class InspectionCursor:
        def __init__(self) -> None:
            self.rows: list[tuple[object, ...]] = []

        def __enter__(self) -> InspectionCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, _params: object = None) -> InspectionCursor:
            if "polname = 'public_read'" in query:
                self.rows = [("is_current AND rubric_version IN (rubric_versions is_active)",)]
            elif "information_schema.columns" in query or "to_regclass(%s)" in query:
                self.rows = [(True,)]
            elif "SELECT EXISTS (SELECT 1 FROM pg_roles" in query:
                self.rows = [(True,)]
            elif "rolname IN ('rdapp', 'rdapp_nightly_owner')" in query:
                self.rows = [
                    (
                        "rdapp",
                        False,
                        False,
                        False,
                        True,
                        False,
                        True,
                        False,
                        False,
                        False,
                        False,
                    ),
                    (
                        "rdapp_nightly_owner",
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
                    ),
                ]
            elif "p.polname = 'nightly_owner_update'" in query:
                self.rows = [
                    ("protocol_families", True),
                    ("protocol_surfaces", True),
                ]
            elif "has_schema_privilege('rdapp_nightly_owner'" in query:
                self.rows = [(True, False)]
            elif "FROM pg_attribute a" in query and "acl.privilege_type" in query:
                self.rows = list(_expected_nightly_owner_column_grants())
            elif "aclexplode(c.relacl)" in query:
                self.rows = []
            elif "has_schema_privilege" in query:
                self.rows = [(True,)]
            elif "role_table_grants" in query:
                self.rows = [
                    ("protocol_families", "SELECT"),
                    ("protocol_surfaces", "SELECT"),
                ]
            elif "WITH required(signature)" in query:
                self.rows = [
                    (
                        "public.refresh_sync_family_tvl(text,numeric)",
                        True,
                        True,
                        ["search_path=pg_catalog"],
                        "rdapp_nightly_owner",
                        body_by_signature[
                            "public.refresh_sync_family_tvl(text,numeric)"
                        ],
                        True,
                        False,
                        False,
                        False,
                    ),
                    (
                        "public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)",
                        True,
                        True,
                        ["search_path=pg_catalog"],
                        "rdapp_nightly_owner",
                        body_by_signature[
                            "public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)"
                        ],
                        True,
                        False,
                        False,
                        False,
                    ),
                ]
            elif "to_regclass('public.schema_migrations')" in query:
                self.rows = [(False,)]
            else:
                raise AssertionError(f"unexpected query: {query}")
            return self

        def fetchone(self) -> tuple[object, ...]:
            return self.rows[0]

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    class InspectionConnection:
        def cursor(self) -> InspectionCursor:
            return InspectionCursor()

    inspected = inspect_migrations(InspectionConnection(), tmp_path)
    assert all(not state.applied for state in inspected)
    assert all("checksum ledger unavailable" in state.detail for state in inspected)


def test_missing_nightly_functions_are_pending_instead_of_raising() -> None:
    class MissingFunctionsCursor:
        def __init__(self) -> None:
            self.rows = []

        def execute(self, query: str, _params: object = None) -> None:
            if "rolname IN ('rdapp', 'rdapp_nightly_owner')" in query:
                self.rows = [
                    (
                        "rdapp",
                        False,
                        False,
                        False,
                        True,
                        False,
                        True,
                        False,
                        False,
                        False,
                        False,
                    ),
                    (
                        "rdapp_nightly_owner",
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
                    ),
                ]
            elif "p.polname = 'nightly_owner_update'" in query:
                self.rows = [
                    ("protocol_families", True),
                    ("protocol_surfaces", True),
                ]
            elif "has_schema_privilege('rdapp_nightly_owner'" in query:
                self.rows = [(True, False)]
            elif "FROM pg_attribute a" in query and "acl.privilege_type" in query:
                self.rows = list(_expected_nightly_owner_column_grants())
            elif "aclexplode(c.relacl)" in query:
                self.rows = []
            elif "WITH required(signature)" in query:
                self.rows = [
                    (signature, False, None, [], None, None, False, False, False, False)
                    for signature in (
                        "public.refresh_sync_family_tvl(text,numeric)",
                        "public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)",
                    )
                ]
            else:
                raise AssertionError(f"unexpected query: {query}")

        def fetchone(self):
            return self.rows[0]

        def fetchall(self):
            return self.rows

    ready, detail = _nightly_functions_ready(MissingFunctionsCursor())
    assert ready is False
    assert "False" in detail


def test_recorded_contract_drift_requires_manual_remediation() -> None:
    with pytest.raises(ContractError, match="recorded migration contract drift"):
        _migration_state(
            name="0014_nightly_ingest_topology_functions.sql",
            digest="f" * 64,
            effect_applied=False,
            detail="nightly function owner is unsafe",
            ledger_exists=True,
            recorded="f" * 64,
        )
