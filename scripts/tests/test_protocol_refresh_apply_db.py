from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_apply import db as refresh_db
from protocol_refresh_apply.contracts import ContractError, PublicHandoff, canonical_sha256
from protocol_refresh_apply.db import (
    ApplyMutationReceipt,
    apply_refresh,
    build_apply_plan,
    preflight,
    verify_compose_owned_transition,
    verify_production_topology,
    verify_refresh_date_monotonic,
)


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args) -> None:
            return None

        def fetchone(self):
            return (True,)

    def cursor(self):
        return self._Cursor()


class TopologyConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    class _Cursor:
        def __init__(self, parent: "TopologyConnection") -> None:
            self.parent = parent

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query: str, _params: tuple[str, ...]) -> None:
            self.parent.queries.append(query)

        def fetchall(self):
            return [("v3", "active", True, True)]

    def cursor(self):
        return self._Cursor(self)


def handoff(*, changed: bool) -> PublicHandoff:
    payload = {
        "schema_version": "1.0",
        "batch_id": "batch-01",
        "refresh_id": "2026-07-11-batch-01",
        "family_slug": "example",
        "protocol_slug": "example",
        "surface_slugs": ["v3"],
        "refresh_type": "full_family_refresh",
        "rubric_version": "v1.7.0",
        "effective_refresh_date": "2026-07-11",
        "topology_contract": {
            "mode": "preserve_canonical",
            "canonical_surface_slugs": ["v3"],
            "canonical_surface_fingerprint": canonical_sha256(
                {"family_slug": "example", "surface_slugs": ["v3"]}
            ),
            "operator_approval_artifact_sha256": None,
        },
        "scope": {
            "allowed_surfaces": ["v3"],
            "allowed_factor_ids": ["RD-F-001"],
            "allowed_protocol_fields": ["description"],
            "allowed_family_fields": [],
            "allowed_surface_fields": [],
            "allowed_deployment_fields": [],
        },
        "baseline": {"target_sha256": "a" * 64, "other_protocols_sha256": "b" * 64},
        "expected_result": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none", "active_factor_count": 0, "surface_results": {"v3": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none"}}},
        "changes": {
            "protocol_fields": {"description": "updated"} if changed else {},
            "family_fields": {},
            "surfaces": [],
            "deployments": [],
            "factor_scores": [],
        },
    }
    return PublicHandoff(
        artifact={"payload": payload},
        payload=payload,
        artifact_sha256="c" * 64,
    )


def authorization() -> dict:
    return {
        "authorization_id": "approval:123",
        "operation": "apply_protocol_refresh",
        "artifact_sha256": "c" * 64,
        "plan_sha256": None,
        "database_identity": "postgresql:risk:operator@db.example:5432",
    }


def backup(plan_sha256: str | None = None) -> dict:
    return {
        "backup_id": "backup:123",
        "operation": "apply_protocol_refresh",
        "plan_sha256": plan_sha256,
        "artifact_sha256": "c" * 64,
        "database_identity": "postgresql:risk:operator@db.example:5432",
    }


def before_details(document: PublicHandoff) -> dict:
    normalized = {
        "family_slug": "example",
        "target": True,
        "protocols": [{"slug": "example", "last_refreshed": "2026-01-01"}],
        "families": [],
        "surfaces": [],
        "deployments": [],
        "current_factor_scores": [],
    }
    other = {"family_slug": "example", "target": False, "protocols": []}
    production_plan = refresh_db.build_production_plan(
        document,
        database_identity_value="postgresql:risk:operator@db.example:5432",
        normalized_target=normalized,
        normalized_other=other,
    )
    return {
        "plan": build_apply_plan(document),
        "production_plan": production_plan,
        "plan_sha256": production_plan["plan_sha256"],
        "database_identity": "postgresql:risk:operator@db.example:5432",
        "raw_target_sha256": "a" * 64,
        "raw_other_sha256": canonical_sha256(other),
        "normalized_target_sha256": canonical_sha256(normalized),
        "normalized_other_sha256": canonical_sha256(other),
        "normalized_target": normalized,
        "normalized_other": other,
    }


def compose_snapshot(
    *,
    description: str,
    grade: str = "B",
    updated_at: str = "2026-07-11T00:00:00Z",
) -> dict:
    return {
        "family_slug": "example",
        "protocols": [
            {
                "slug": "example",
                "description": description,
                "total_value_secured_usd": "100",
                "headline_grade": grade,
                "updated_at": updated_at,
            }
        ],
        "families": [
            {
                "family_slug": "example",
                "description": "stable family",
                "headline_grade": grade,
                "updated_at": updated_at,
            }
        ],
        "surfaces": [
            {
                "surface_id": "surface-1",
                "family_slug": "example",
                "surface_slug": "v3",
                "tvs_usd": "100",
                "headline_grade": grade,
                "updated_at": updated_at,
            }
        ],
        "deployments": [],
        "factor_scores": [],
        "factor_score_sources": [],
        "sources": [],
        "grade_history": [],
        "protocol_grade_history": [],
        "factor_score_history": [],
    }


def mutation_receipt(document: PublicHandoff) -> ApplyMutationReceipt:
    return ApplyMutationReceipt(
        run_id="run-1",
        factor_score_ids=(),
        inserted_deployment_ids=(),
        created_source_ids=(),
        row_counts=build_apply_plan(document).operation_counts,
    )


def test_refresh_date_must_not_move_backwards() -> None:
    verify_refresh_date_monotonic(None, "2026-07-11")
    verify_refresh_date_monotonic(date(2026, 7, 11), "2026-07-11")
    verify_refresh_date_monotonic("2026-07-10", "2026-07-11")
    verify_refresh_date_monotonic(
        datetime(2026, 7, 11, 23, 59, tzinfo=timezone.utc),
        "2026-07-11",
    )
    with pytest.raises(ContractError, match="predates current last_refreshed"):
        verify_refresh_date_monotonic(date(2026, 7, 12), "2026-07-11")


def test_preflight_rejects_backward_date_before_snapshot_or_plan() -> None:
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args) -> None:
            return None

        def fetchall(self):
            return [(date(2026, 7, 12),)]

    class Connection:
        def cursor(self):
            return Cursor()

    columns = {table: set(required) for table, required in refresh_db.REQUIRED_COLUMNS.items()}
    with (
        patch.object(refresh_db, "_table_columns", return_value=columns),
        patch.object(refresh_db, "snapshot_hashes") as snapshots,
    ):
        with pytest.raises(ContractError, match="predates current last_refreshed"):
            preflight(Connection(), handoff(changed=False))
    snapshots.assert_not_called()


def test_production_topology_must_match_hash_bound_attestation() -> None:
    document = handoff(changed=False).payload
    rows = [("v3", "active", True, True)]
    verify_production_topology(document, rows)

    drifted_rows = rows + [("v4", "active", False, True)]
    with pytest.raises(ContractError, match="topology attestation"):
        verify_production_topology(document, drifted_rows)


def test_date_only_topology_revalidation_uses_select_without_row_lock() -> None:
    conn = TopologyConnection()

    assert refresh_db._production_topology_rows(conn, "example", lock=False) == [
        ("v3", "active", True, True)
    ]
    assert len(conn.queries) == 1
    assert "FOR UPDATE OF ps" not in conn.queries[0]


def test_surface_topology_revalidation_retains_update_lock() -> None:
    conn = TopologyConnection()

    refresh_db._production_topology_rows(conn, "example", lock=True)

    assert len(conn.queries) == 1
    assert "FOR UPDATE OF ps" in conn.queries[0]


def test_surface_status_change_cannot_alter_attested_gradeable_topology() -> None:
    document = handoff(changed=False).payload
    document["scope"]["allowed_surface_fields"] = ["status"]
    document["changes"]["surfaces"] = [
        {"surface_slug": "v3", "fields": {"status": "deprecated"}}
    ]

    with pytest.raises(ContractError, match="would alter canonical gradeable topology"):
        verify_production_topology(document, [("v3", "active", False, False)])


def test_family_lock_precedes_fresh_serializable_transaction() -> None:
    events: list[tuple[str, object]] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params=None):
            events.append((statement, params))

        def fetchone(self):
            return (True,)

    class Connection:
        def cursor(self):
            return Cursor()

        def commit(self):
            events.append(("COMMIT", None))

        def rollback(self):
            events.append(("ROLLBACK", None))

    refresh_db._acquire_family_session_lock(Connection(), "example")

    assert events == [
        (
            "SELECT pg_advisory_lock(hashtext(%s))",
            ("protocol-refresh:example",),
        ),
        ("COMMIT", None),
        ("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE", None),
    ]


def test_date_only_apply_revalidates_topology_without_update_lock_before_hashing() -> None:
    document = handoff(changed=False)
    conn = FakeConnection()
    with (
        patch.object(
            refresh_db,
            "_production_topology_rows",
            side_effect=ContractError("transaction topology drift"),
        ) as topology,
        patch.object(refresh_db, "normalized_snapshot") as snapshot,
    ):
        with pytest.raises(ContractError, match="transaction topology drift"):
            refresh_db.apply_transaction(
                conn,
                document,
                production_plan={"production_before": {}},
                authorization_id="approval:123",
                backup_id="backup:123",
            )

    topology.assert_called_once_with(conn, "example", lock=False)
    snapshot.assert_not_called()


def test_surface_change_revalidates_topology_with_update_lock_before_reservation() -> None:
    document = handoff(changed=False)
    document.payload["scope"]["allowed_surface_fields"] = ["status"]
    document.payload["changes"]["surfaces"] = [
        {"surface_slug": "v3", "fields": {"status": "active"}}
    ]
    conn = FakeConnection()
    with (
        patch.object(
            refresh_db,
            "_production_topology_rows",
            side_effect=ContractError("transaction topology drift"),
        ) as topology,
        patch.object(refresh_db, "normalized_snapshot") as snapshot,
    ):
        with pytest.raises(ContractError, match="transaction topology drift"):
            refresh_db.apply_transaction(
                conn,
                document,
                production_plan={"production_before": {}},
                authorization_id="approval:123",
                backup_id="backup:123",
            )

    topology.assert_called_once_with(conn, "example", lock=True)
    snapshot.assert_not_called()


def test_compose_transition_allows_only_grade_fields_and_append_only_history() -> None:
    before = compose_snapshot(description="source-approved")
    grade_only = compose_snapshot(
        description="source-approved",
        grade="A",
        updated_at="2026-07-11T01:00:00Z",
    )
    grade_only["grade_history"].append(
        {
            "id": "grade-history-1",
            "protocol_slug": "example",
            "scope_level": "surface",
            "family_slug": None,
            "surface_id": "surface-1",
            "deployment_id": None,
            "triggered_by": "compose.py",
        }
    )
    grade_only["protocol_grade_history"].append(
        {
            "id": "protocol-grade-history-1",
            "protocol_slug": "example",
            "scope_level": "surface",
            "family_slug": None,
            "surface_id": "surface-1",
        }
    )
    verify_compose_owned_transition(before, grade_only, "example")

    unrelated = compose_snapshot(
        description="concurrent description",
        grade="A",
        updated_at="2026-07-11T01:00:00Z",
    )
    with pytest.raises(ContractError, match="non-grade protocols fields"):
        verify_compose_owned_transition(before, unrelated, "example")


def test_production_drift_after_plan_blocks_apply_before_mutation() -> None:
    document = handoff(changed=True)
    recomputed = before_details(document)
    stale_authorization = authorization()
    stale_authorization["plan_sha256"] = "d" * 64
    conn = FakeConnection()
    with (
        patch.object(refresh_db, "preflight", return_value=recomputed),
        patch.object(refresh_db, "apply_transaction") as mutate,
    ):
        with pytest.raises(ContractError, match="drifted from the authorized plan_sha256"):
            apply_refresh(
                conn,
                "postgresql://db.example/risk",
                document,
                authorization=stale_authorization,
                backup=backup(),
                baseline_dump_runner=lambda **_kwargs: "before",
                compose_runner=lambda **_kwargs: 0,
                dump_runner=lambda **_kwargs: "after",
                semantic_verifier=lambda **_kwargs: True,
            )
    mutate.assert_not_called()


def test_no_change_apply_updates_date_without_pipeline() -> None:
    document = handoff(changed=False)
    before = before_details(document)
    after_normalized = {
        **before["normalized_target"],
        "protocols": [{"slug": "example", "last_refreshed": "2026-07-11"}],
    }
    after = {
        "raw_other_sha256": before["raw_other_sha256"],
        "normalized_target": after_normalized,
        "normalized_target_sha256": canonical_sha256(after_normalized),
        "normalized_other_sha256": before["normalized_other_sha256"],
    }
    other = {"family_slug": "example", "target": False, "protocols": []}
    compose = Mock(side_effect=AssertionError("no-change path must not compose"))
    dump = Mock(side_effect=AssertionError("no-change path must not dump"))
    verifier = Mock(side_effect=AssertionError("no-change path must not verify generated output"))
    conn = FakeConnection()
    auth = authorization()
    auth["plan_sha256"] = before["plan_sha256"]
    with (
        patch.object(refresh_db, "preflight", return_value=before),
        patch.object(refresh_db, "already_applied", return_value=False),
        patch.object(
            refresh_db,
            "capture_recovery_snapshot",
            return_value=compose_snapshot(description="source-approved"),
        ),
        patch.object(refresh_db, "apply_transaction", return_value=mutation_receipt(document)),
        patch.object(refresh_db, "normalized_snapshot", return_value=other),
        patch.object(refresh_db, "snapshot_hashes", return_value=after),
        patch.object(refresh_db, "finish_run") as finish,
    ):
        result = apply_refresh(
            conn,
            "postgresql://db.example/risk",
            document,
            authorization=auth,
            backup=backup(before["plan_sha256"]),
            compose_runner=compose,
            dump_runner=dump,
            semantic_verifier=verifier,
        )
    assert result["pipeline_ran"] is False
    assert result["after_snapshot"] == after_normalized
    assert conn.commits == 3
    assert conn.rollbacks == 0
    finish.assert_called_once()
    assert finish.call_args.kwargs["success"] is True
    compose.assert_not_called()
    dump.assert_not_called()
    verifier.assert_not_called()


@pytest.mark.parametrize("failed_stage", ["compose", "dump", "semantic_verification"])
def test_each_post_commit_failure_is_compensated_and_failed_audit_is_preserved(
    failed_stage: str,
) -> None:
    document = handoff(changed=True)
    before = before_details(document)
    other = {"family_slug": "example", "target": False, "protocols": []}
    conn = FakeConnection()
    auth = authorization()
    auth["plan_sha256"] = before["plan_sha256"]
    compose_result = SimpleNamespace(
        returncode=1 if failed_stage == "compose" else 0,
        stdout="",
        stderr="compose failed",
    )
    dump_result = False if failed_stage == "dump" else "dump-root"
    verifier = Mock(
        side_effect=(
            ContractError("semantic mismatch")
            if failed_stage == "semantic_verification"
            else None
        ),
        return_value=True,
    )
    with (
        patch.object(refresh_db, "preflight", return_value=before),
        patch.object(refresh_db, "already_applied", return_value=False),
        patch.object(
            refresh_db,
            "capture_recovery_snapshot",
            return_value=compose_snapshot(description="source-approved"),
        ),
        patch.object(refresh_db, "apply_transaction", return_value=mutation_receipt(document)),
        patch.object(refresh_db, "normalized_snapshot", return_value=other),
        patch.object(refresh_db, "compensate_refresh", return_value="restored-hash") as compensate,
        patch.object(refresh_db, "finish_run") as finish,
    ):
        with pytest.raises(ContractError, match="failed audit run run-1 was preserved"):
            apply_refresh(
                conn,
                "postgresql://db.example/risk",
                document,
                authorization=auth,
                backup=backup(before["plan_sha256"]),
                baseline_dump_runner=lambda **_kwargs: "before-dump-root",
                compose_runner=lambda **_kwargs: compose_result,
                dump_runner=lambda **_kwargs: dump_result,
                semantic_verifier=verifier,
            )
    assert conn.commits == 4
    assert conn.rollbacks == 1
    compensate.assert_called_once()
    finish.assert_called_once()
    assert finish.call_args.kwargs["success"] is False
    assert "compensation: proved" in finish.call_args.kwargs["error"]
    if failed_stage == "semantic_verification":
        assert "semantic mismatch" in finish.call_args.kwargs["error"]


def test_unproved_compensation_still_attempts_to_preserve_failed_audit() -> None:
    document = handoff(changed=True)
    before = before_details(document)
    other = {"family_slug": "example", "target": False, "protocols": []}
    conn = FakeConnection()
    auth = authorization()
    auth["plan_sha256"] = before["plan_sha256"]
    with (
        patch.object(refresh_db, "preflight", return_value=before),
        patch.object(refresh_db, "already_applied", return_value=False),
        patch.object(refresh_db, "capture_recovery_snapshot", return_value={"before": True}),
        patch.object(refresh_db, "apply_transaction", return_value=mutation_receipt(document)),
        patch.object(refresh_db, "normalized_snapshot", return_value=other),
        patch.object(
            refresh_db,
            "run_post_commit_pipeline",
            side_effect=ContractError("dump failed"),
        ),
        patch.object(
            refresh_db,
            "compensate_refresh",
            side_effect=ContractError("restore proof failed"),
        ),
        patch.object(refresh_db, "finish_run") as finish,
    ):
        with pytest.raises(ContractError, match="FAILED/UNPROVED"):
            apply_refresh(
                conn,
                "postgresql://db.example/risk",
                document,
                authorization=auth,
                backup=backup(before["plan_sha256"]),
                baseline_dump_runner=lambda **_kwargs: "before-dump-root",
                compose_runner=lambda **_kwargs: 0,
                dump_runner=lambda **_kwargs: 0,
                semantic_verifier=lambda **_kwargs: True,
            )
    assert conn.commits == 3
    assert conn.rollbacks == 2
    finish.assert_called_once()
    assert finish.call_args.kwargs["success"] is False


def test_failed_compose_does_not_account_changed_live_state_or_overwrite_it() -> None:
    document = handoff(changed=True)
    before = before_details(document)
    baseline = {"stage": "baseline"}
    post_source = {"stage": "post-source"}
    conn = FakeConnection()
    auth = authorization()
    auth["plan_sha256"] = before["plan_sha256"]
    events: list[str] = []

    def refuse_drift(
        _conn,
        _handoff,
        _before_snapshot,
        expected_live_snapshot,
        *_args,
    ):
        events.append("compensation-refused")
        assert expected_live_snapshot == post_source
        raise ContractError("unaccounted target drift at compensation precondition")

    with (
        patch.object(refresh_db, "_acquire_family_session_lock", side_effect=lambda *_: events.append("lock")),
        patch.object(refresh_db, "_release_family_session_lock", side_effect=lambda *_: events.append("unlock")),
        patch.object(refresh_db, "preflight", return_value=before),
        patch.object(refresh_db, "already_applied", return_value=False),
        patch.object(
            refresh_db,
            "capture_recovery_snapshot",
            side_effect=[baseline, post_source],
        ),
        patch.object(refresh_db, "verify_expected_live_snapshot", return_value=post_source),
        patch.object(refresh_db, "apply_transaction", return_value=mutation_receipt(document)),
        patch.object(
            refresh_db,
            "normalized_snapshot",
            return_value={"family_slug": "example", "target": False, "protocols": []},
        ),
        patch.object(refresh_db, "compensate_refresh", side_effect=refuse_drift),
        patch.object(refresh_db, "finish_run") as finish,
    ):
        with pytest.raises(ContractError, match="FAILED/UNPROVED"):
            apply_refresh(
                conn,
                "postgresql://db.example/risk",
                document,
                authorization=auth,
                backup=backup(before["plan_sha256"]),
                baseline_dump_runner=lambda **_kwargs: "before-dump-root",
                compose_runner=lambda **_kwargs: SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr="compose changed a row, then failed",
                ),
                dump_runner=lambda **_kwargs: "unused",
                semantic_verifier=lambda **_kwargs: True,
            )
    assert events == ["lock", "compensation-refused", "unlock"]
    assert finish.call_args.kwargs["success"] is False
    assert "FAILED/UNPROVED" in finish.call_args.kwargs["error"]


def test_compensation_precondition_drift_prevents_any_restore_write() -> None:
    document = handoff(changed=True)
    receipt = mutation_receipt(document)
    with (
        patch.object(refresh_db, "_lock_compensation_rows"),
        patch.object(
            refresh_db,
            "verify_expected_live_snapshot",
            side_effect=ContractError("unaccounted target drift"),
        ),
        patch.object(refresh_db, "_restore_rows") as restore,
    ):
        with pytest.raises(ContractError, match="unaccounted target drift"):
            refresh_db.compensate_refresh(
                FakeConnection(),
                document,
                {"stage": "baseline"},
                {"stage": "expected-live"},
                "a" * 64,
                receipt,
                ContractError("pipeline failed"),
            )
    restore.assert_not_called()


def test_successful_compose_with_unrelated_drift_then_dump_failure_is_unproved() -> None:
    document = handoff(changed=True)
    before = before_details(document)
    baseline = compose_snapshot(description="before source")
    post_source = compose_snapshot(description="source-approved")
    post_compose = compose_snapshot(
        description="concurrent unrelated edit",
        grade="A",
        updated_at="2026-07-11T01:00:00Z",
    )
    conn = FakeConnection()
    auth = authorization()
    auth["plan_sha256"] = before["plan_sha256"]
    dump = Mock(return_value=False)

    def refuse_unaccounted_drift(
        _conn,
        _handoff,
        _before_snapshot,
        expected_live_snapshot,
        *_args,
    ):
        assert expected_live_snapshot == post_source
        raise ContractError("unaccounted target drift at compensation precondition")

    with (
        patch.object(refresh_db, "preflight", return_value=before),
        patch.object(refresh_db, "already_applied", return_value=False),
        patch.object(
            refresh_db,
            "capture_recovery_snapshot",
            side_effect=[baseline, post_source, post_compose],
        ),
        patch.object(refresh_db, "verify_expected_live_snapshot", return_value=post_source),
        patch.object(refresh_db, "apply_transaction", return_value=mutation_receipt(document)),
        patch.object(
            refresh_db,
            "normalized_snapshot",
            return_value={"family_slug": "example", "target": False, "protocols": []},
        ),
        patch.object(
            refresh_db,
            "compensate_refresh",
            side_effect=refuse_unaccounted_drift,
        ),
        patch.object(refresh_db, "finish_run") as finish,
    ):
        with pytest.raises(ContractError, match="FAILED/UNPROVED"):
            apply_refresh(
                conn,
                "postgresql://db.example/risk",
                document,
                authorization=auth,
                backup=backup(before["plan_sha256"]),
                baseline_dump_runner=lambda **_kwargs: "before-dump-root",
                compose_runner=lambda **_kwargs: 0,
                dump_runner=dump,
                semantic_verifier=lambda **_kwargs: True,
            )
    dump.assert_called_once()
    assert finish.call_args.kwargs["success"] is False
    assert "FAILED/UNPROVED" in finish.call_args.kwargs["error"]
