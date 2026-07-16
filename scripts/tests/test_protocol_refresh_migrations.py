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
    _record_pending_migrations,
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
    for state in states():
        (migrations / state.name).write_text(f"-- {state.name}\n", encoding="utf-8")

    class InspectionCursor:
        def __init__(self) -> None:
            self.rows: list[tuple[object, ...]] = []

        def __enter__(self) -> InspectionCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, _params: object = None) -> InspectionCursor:
            if "pg_policy" in query:
                self.rows = [("is_current AND rubric_version IN (rubric_versions is_active)",)]
            elif "information_schema.columns" in query or "to_regclass(%s)" in query:
                self.rows = [(True,)]
            elif "pg_roles" in query or "has_schema_privilege" in query:
                self.rows = [(True,)]
            elif "role_table_grants" in query:
                self.rows = [
                    ("protocol_families", "SELECT"),
                    ("protocol_surfaces", "SELECT"),
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
