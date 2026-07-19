from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from datetime import datetime, timezone
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_apply.contracts import (
    ContractError,
    canonical_sha256,
    load_backup_receipt,
    validate_backup_receipt,
    normalize_data_as_of,
    validate_apply_payload,
    validate_production_authorization_receipt,
    validate_public_handoff,
)
from protocol_refresh_apply.db import (
    build_apply_plan,
    build_production_plan,
    normalize_snapshot,
    run_post_commit_pipeline,
    verify_compensation,
    verify_no_change_date_only,
)
from protocol_refresh_public.contracts import (
    build_public_handoff,
    canonical_surface_fingerprint,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def _load_apply_command():
    script = Path(__file__).resolve().parents[1] / "apply-protocol-refresh.py"
    spec = importlib.util.spec_from_file_location("protocol_refresh_apply_command", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_isolated_runner_requires_complete_explicit_toolchain_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = _load_apply_command()
    monkeypatch.setenv("PROTOCOL_REFRESH_REPO_ROOT", str(tmp_path))
    with pytest.raises(ContractError, match="toolchain root is incomplete"):
        command.resolve_repo_root()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "compose.py").write_text("# fixture\n", encoding="utf-8")
    (scripts / "dump.py").write_text("# fixture\n", encoding="utf-8")
    assert command.resolve_repo_root() == tmp_path.resolve()


def accepted_changes(*, changed: bool = False) -> dict:
    changes = {
        "protocol_fields": {"description": "updated"} if changed else {},
        "family_fields": {},
        "surfaces": [],
        "deployments": [],
        "factor_scores": [],
    }
    return {
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
            "canonical_surface_fingerprint": canonical_surface_fingerprint(
                "example", ["v3"]
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
        "baseline": {"target_sha256": SHA_A, "other_protocols_sha256": SHA_B},
        "expected_result": {
            "headline_grade": "B", "risk_score": "17.41", "cap_state": "none",
            "active_factor_count": 0,
            "surface_results": {"v3": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none"}},
        },
        "changes": changes,
    }


def public_handoff(*, changed: bool = False):
    document = accepted_changes(changed=changed)
    status = {
        "batch_id": document["batch_id"],
        "refresh_id": document["refresh_id"],
        "family_slug": "example",
        "protocol_slug": "example",
        "surface_slugs": ["v3"],
        "local_state": "local_ready_for_review",
        "local_outcome": "changed" if changed else "no_change",
        "approval_state": "approved",
        "reviewed_by": "curator",
        "reviewed_at": "2026-07-11T00:00:00Z",
        "production_authorized": False,
        "production_state": "not_started",
        "checksums": {"accepted_changes_sha256": canonical_sha256(document)},
    }
    return validate_public_handoff(build_public_handoff(document, status))


def factor_artifact(
    *,
    score: str = "green",
    collection_mode: str = "manual",
    evidence_summary: str = "Current primary evidence supports this score.",
    source_type: str = "docs",
    reference: str = "https://example.com/docs",
    relation: str = "primary",
) -> dict:
    document = accepted_changes()
    document["changes"]["factor_scores"] = [
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "surface_slug": "v3",
            "chain": None,
            "deployment_key": None,
            "expected_current_sha256": None,
            "score": score,
            "evidence_summary": evidence_summary,
            "collection_mode": collection_mode,
            "sources": [
                {
                    "source_type": source_type,
                    "reference": reference,
                    "relation": relation,
                }
            ],
        }
    ]
    document["expected_result"]["active_factor_count"] = 1
    status = {
        "batch_id": document["batch_id"],
        "refresh_id": document["refresh_id"],
        "family_slug": "example",
        "protocol_slug": "example",
        "surface_slugs": ["v3"],
        "local_state": "local_ready_for_review",
        "local_outcome": "changed",
        "approval_state": "approved",
        "reviewed_by": "curator",
        "reviewed_at": "2026-07-11T00:00:00Z",
        "production_authorized": False,
        "production_state": "not_started",
        "checksums": {"accepted_changes_sha256": canonical_sha256(document)},
    }
    return build_public_handoff(document, status)


def authorization_receipt(**overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "receipt_type": "protocol_refresh_production_authorization",
        "authorization_id": "approval:123",
        "operation": "apply_protocol_refresh",
        "refresh_id": "2026-07-11-batch-01",
        "family_slug": "example",
        "artifact_sha256": SHA_A,
        "plan_sha256": SHA_B,
        "database_identity": "postgresql:risk:operator@db.example:5432",
        "authorized_by": "release-operator",
        "authorized_at": "2026-07-11T00:00:00Z",
        "expires_at": "2026-07-12T00:00:00Z",
    }
    value.update(overrides)
    return value


def backup_receipt(**overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "receipt_type": "database_backup_receipt",
        "operation": "apply_protocol_refresh",
        "plan_sha256": SHA_B,
        "artifact_sha256": SHA_A,
        "backup_id": "backup:123",
        "backup_path": "/backups/risk-20260711.dump",
        "sha256": SHA_B,
        "size_bytes": 1024,
        "created_at": "2026-07-11T00:01:00Z",
        "database_identity": "postgresql:risk:operator@db.example:5432",
        "restore_command": "pg_restore --clean --if-exists risk-20260711.dump",
        "restore_test": {
            "status": "succeeded",
            "tested_at": "2026-07-11T00:05:00Z",
            "evidence": {"scratch_database": "risk_restore_test", "checks": 12},
        },
    }
    value.update(overrides)
    return value


def test_backup_validator_requires_complete_restore_evidence() -> None:
    normalized = validate_backup_receipt(
        backup_receipt(),
        expected_operation="apply_protocol_refresh",
        plan_sha256=SHA_B,
        artifact_sha256=SHA_A,
        database_identity="postgresql:risk:operator@db.example:5432",
    )
    assert normalized["backup_id"] == "backup:123"
    assert normalized["restore_test"]["status"] == "succeeded"

    missing = backup_receipt()
    missing["restore_test"] = {"status": "succeeded", "tested_at": "2026-07-11T00:05:00Z"}
    with pytest.raises(ContractError, match="evidence"):
        validate_backup_receipt(missing)
    with pytest.raises(ContractError, match="does not match"):
        validate_backup_receipt(backup_receipt(), database_identity="another-db")
    with pytest.raises(ContractError, match="plan_sha256"):
        validate_backup_receipt(backup_receipt(), plan_sha256=SHA_A)
    with pytest.raises(ContractError, match="artifact_sha256"):
        validate_backup_receipt(backup_receipt(), artifact_sha256=SHA_B)


def test_backup_loader_verifies_accessible_file_size_and_sha256(tmp_path: Path) -> None:
    backup_path = tmp_path / "risk.dump"
    content = b"verified disposable backup bytes"
    backup_path.write_bytes(content)
    receipt = backup_receipt(
        backup_path=backup_path.name,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    receipt_path = tmp_path / "backup-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    loaded = load_backup_receipt(
        receipt_path,
        expected_operation="apply_protocol_refresh",
        plan_sha256=SHA_B,
        artifact_sha256=SHA_A,
        database_identity="postgresql:risk:operator@db.example:5432",
    )
    assert loaded["verified_backup_path"] == str(backup_path.resolve())

    backup_path.write_bytes(b"x" * len(content))
    with pytest.raises(ContractError, match="SHA-256 mismatch"):
        load_backup_receipt(
            receipt_path,
            expected_operation="apply_protocol_refresh",
            plan_sha256=SHA_B,
            artifact_sha256=SHA_A,
        )


def test_protocol_authorization_is_separate_and_exactly_bound() -> None:
    normalized = validate_production_authorization_receipt(
        authorization_receipt(),
        artifact_sha256=SHA_A,
        plan_sha256=SHA_B,
        refresh_id="2026-07-11-batch-01",
        family_slug="example",
        database_identity="postgresql:risk:operator@db.example:5432",
        now=datetime(2026, 7, 11, 1, tzinfo=timezone.utc),
    )
    assert normalized["operation"] == "apply_protocol_refresh"
    with pytest.raises(ContractError, match="artifact_sha256"):
        validate_production_authorization_receipt(
            authorization_receipt(), artifact_sha256=SHA_B
        )
    with pytest.raises(ContractError, match="plan_sha256"):
        validate_production_authorization_receipt(
            authorization_receipt(), artifact_sha256=SHA_A, plan_sha256=SHA_A
        )
    with pytest.raises(ContractError, match="schema_version|receipt_type"):
        validate_production_authorization_receipt(public_handoff().artifact)


def test_migration_authorization_binds_exact_plan_and_allowlist() -> None:
    receipt = {
        "schema_version": "1.0",
        "receipt_type": "production_authorization_receipt",
        "authorization_id": "migration:123",
        "operation": "apply_refresh_migrations",
        "plan_sha256": SHA_A,
        "allowed_migrations": [
            "db/migrations/0009_protocol_last_refreshed.sql",
            "db/migrations/0010_protocol_refresh_idempotency.sql",
        ],
        "database_identity": "postgresql:risk:operator@db.example:5432",
        "authorized_by": "release-operator",
        "authorized_at": "2026-07-11T00:00:00Z",
    }
    normalized = validate_production_authorization_receipt(
        receipt,
        expected_operation="apply_refresh_migrations",
        plan_sha256=SHA_A,
        allowed_migrations=receipt["allowed_migrations"],
    )
    assert normalized["plan_sha256"] == SHA_A
    assert normalized["artifact_sha256"] is None
    with pytest.raises(ContractError, match="operation"):
        validate_production_authorization_receipt(receipt)
    with pytest.raises(ContractError, match="allowed_migrations"):
        validate_production_authorization_receipt(
            receipt,
            expected_operation="apply_refresh_migrations",
            plan_sha256=SHA_A,
            allowed_migrations=list(reversed(receipt["allowed_migrations"])),
        )


def test_plan_distinguishes_date_only_and_changed_paths() -> None:
    no_change = build_apply_plan(public_handoff())
    assert no_change.requires_pipeline is False
    assert no_change.operation_counts["last_refreshed_rows"] == 1
    assert no_change.operation_counts["protocol_rows"] == 0

    changed = build_apply_plan(public_handoff(changed=True))
    assert changed.requires_pipeline is True
    assert changed.operation_counts["protocol_rows"] == 1
    assert changed.surfaces == ("v3",)


def test_compensation_fingerprints_fail_closed() -> None:
    before = {"protocols": [{"slug": "example"}]}
    assert verify_compensation(before, before, SHA_B, SHA_B) == canonical_sha256(before)
    with pytest.raises(ContractError, match="unrelated"):
        verify_compensation(before, before, SHA_B, SHA_A)


def test_normalized_snapshot_ignores_environment_specific_ids() -> None:
    first = {
        "family_slug": "example",
        "target": True,
        "protocols": [{"slug": "example", "updated_at": "one"}],
        "families": [{"family_slug": "example", "primary_surface_id": "surface-1"}],
        "surfaces": [
            {"surface_id": "surface-1", "family_slug": "example", "surface_slug": "v3"}
        ],
        "deployments": [
            {
                "id": "deployment-1",
                "protocol_slug": "example",
                "surface_id": "surface-1",
                "chain": "ethereum",
                "deployment_key": "primary",
            }
        ],
        "current_factor_scores": [
            {
                "id": "factor-1",
                "protocol_slug": "example",
                "factor_id": "RD-F-001",
                "surface_id": "surface-1",
                "deployment_id": None,
                "sources": [{"id": "source-1", "source_type": "docs", "reference": "r"}],
            }
        ],
    }
    second = deepcopy(first)
    second["protocols"][0]["updated_at"] = "two"
    second["families"][0]["primary_surface_id"] = "surface-2"
    second["surfaces"][0]["surface_id"] = "surface-2"
    second["deployments"][0].update({"id": "deployment-2", "surface_id": "surface-2"})
    second["current_factor_scores"][0].update({"id": "factor-2", "surface_id": "surface-2"})
    second["current_factor_scores"][0]["sources"][0]["id"] = "source-2"
    assert normalize_snapshot(first) == normalize_snapshot(second)

    first_handoff = public_handoff(changed=True)
    second_handoff = deepcopy(first_handoff)
    second_handoff.payload["baseline"] = {
        "target_sha256": "1" * 64,
        "other_protocols_sha256": "2" * 64,
    }
    first_plan = build_production_plan(
        first_handoff,
        database_identity_value="production-db",
        normalized_target=normalize_snapshot(first),
        normalized_other={"family_slug": "example", "target": False},
    )
    second_plan = build_production_plan(
        second_handoff,
        database_identity_value="production-db",
        normalized_target=normalize_snapshot(second),
        normalized_other={"family_slug": "example", "target": False},
    )
    assert first_plan["production_before"] == second_plan["production_before"]


def test_surface_primary_alias_changes_are_rejected() -> None:
    artifact = public_handoff().artifact
    artifact["payload"]["scope"]["allowed_surface_fields"] = ["is_primary"]
    artifact["payload"]["changes"]["surfaces"] = [
        {"surface_slug": "v3", "fields": {"is_primary": True}}
    ]
    with pytest.raises(ContractError, match="unsupported fields"):
        validate_public_handoff(artifact)


def test_data_as_of_is_explicit_utc() -> None:
    assert normalize_data_as_of(None, "2026-07-11") == "2026-07-11T00:00:00Z"
    assert normalize_data_as_of("2026-07-11T05:00:00+05:00", "2026-07-11") == (
        "2026-07-11T00:00:00Z"
    )
    with pytest.raises(ContractError, match="timezone"):
        normalize_data_as_of("2026-07-11T00:00:00", "2026-07-11")


def test_factor_and_source_database_enums_are_validated_independently() -> None:
    assert validate_public_handoff(factor_artifact()).payload["changes"]["factor_scores"]
    for score in ("green", "yellow", "red", "gray", "not_assessed", "not_applicable"):
        validate_public_handoff(factor_artifact(score=score))
    for mode in ("programmatic", "manual", "hybrid"):
        validate_public_handoff(factor_artifact(collection_mode=mode))
    for source_type in (
        "url",
        "github",
        "etherscan",
        "transaction",
        "audit_report",
        "governance_post",
        "docs",
        "partner_feed",
        "curator_note",
        "commit_sha",
    ):
        score = "gray" if source_type in {"partner_feed", "curator_note"} else "green"
        validate_public_handoff(factor_artifact(score=score, source_type=source_type))

    invalid_cases = [
        ({"score": "blue"}, "score must be one of"),
        ({"collection_mode": "automated"}, "collection_mode must be one of"),
        ({"relation": "supporting"}, "relation must be one of"),
        ({"evidence_summary": "   "}, "evidence_summary must be non-empty"),
        ({"reference": "   "}, "reference must be non-empty"),
        ({"sources": []}, "sources must be non-empty"),
    ]
    for overrides, message in invalid_cases:
        payload = deepcopy(factor_artifact()["payload"])
        factor = payload["changes"]["factor_scores"][0]
        source = factor["sources"][0]
        for key, value in overrides.items():
            (source if key in {"source_type", "reference", "relation"} else factor)[key] = value
        with pytest.raises(ContractError, match=message):
            validate_apply_payload(payload)


@pytest.mark.parametrize("score", ["not_assessed", "not_applicable"])
def test_apply_contract_allows_source_optional_scores(score: str) -> None:
    payload = deepcopy(factor_artifact(score=score)["payload"])
    payload["changes"]["factor_scores"][0]["sources"] = []
    assert validate_apply_payload(payload)["changes"]["factor_scores"][0]["sources"] == []


def test_apply_contract_allows_public_safe_gray_curator_note() -> None:
    payload = factor_artifact(score="gray", source_type="curator_note")["payload"]
    assert validate_apply_payload(payload)["changes"]["factor_scores"][0]["sources"][0][
        "source_type"
    ] == "curator_note"


def test_apply_contract_rejects_non_public_independent_locator() -> None:
    payload = factor_artifact()["payload"]
    payload["changes"]["factor_scores"][0]["sources"][0]["reference"] = (
        "internal memo"
    )

    with pytest.raises(ContractError, match=r"public HTTP\(S\) locator"):
        validate_apply_payload(payload)


@pytest.mark.parametrize("score", ["green", "yellow", "red"])
@pytest.mark.parametrize("source_type", ["curator_note", "partner_feed"])
def test_apply_contract_rejects_conditional_only_decisive_scores(
    score: str,
    source_type: str,
) -> None:
    payload = factor_artifact(score="gray", source_type=source_type)["payload"]
    payload["changes"]["factor_scores"][0]["score"] = score

    with pytest.raises(ContractError, match="independently verifiable public source"):
        validate_apply_payload(payload)


def test_apply_contract_rejects_source_less_gray_score() -> None:
    payload = factor_artifact(score="gray", source_type="curator_note")["payload"]
    payload["changes"]["factor_scores"][0]["sources"] = []

    with pytest.raises(ContractError, match="sources must be non-empty"):
        validate_apply_payload(payload)


def test_no_change_verifier_allows_only_last_refreshed() -> None:
    before = {"protocols": [{"slug": "example", "last_refreshed": "2026-01-01"}]}
    after = deepcopy(before)
    after["protocols"][0]["last_refreshed"] = "2026-07-11"
    verify_no_change_date_only(before, after, "2026-07-11")
    after["protocols"][0]["description"] = "unexpected"
    with pytest.raises(ContractError, match="beyond last_refreshed"):
        verify_no_change_date_only(before, after, "2026-07-11")


@pytest.mark.parametrize("failed_stage", ["compose", "dump", "verify"])
def test_each_post_commit_stage_failure_is_fatal(failed_stage: str) -> None:
    calls: list[str] = []

    def compose(**_kwargs):
        calls.append("compose")
        return SimpleNamespace(
            returncode=1 if failed_stage == "compose" else 0,
            stdout="",
            stderr="compose failed",
        )

    def dump(**_kwargs):
        calls.append("dump")
        return False if failed_stage == "dump" else "dump-root"

    def verify(**_kwargs):
        calls.append("verify")
        return failed_stage != "verify"

    with pytest.raises(ContractError, match="failed|failure"):
        run_post_commit_pipeline(
            compose_runner=compose,
            dump_runner=dump,
            semantic_verifier=verify,
            db_url="postgresql://db.example/risk",
            family_slug="example",
            before_dump_result="before-dump-root",
        )
    if failed_stage == "compose":
        assert calls == ["compose"]
    elif failed_stage == "dump":
        assert calls == ["compose", "dump"]
    else:
        assert calls == ["compose", "dump", "verify"]
