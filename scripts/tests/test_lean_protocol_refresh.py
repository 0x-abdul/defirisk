from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lean_protocol_refresh import (
    BaselineClassification,
    ContractError,
    OperatorContext,
    RUBRIC_VERSION,
    apply_batch,
    build_plan,
    render_plan,
)
from lean_protocol_refresh.contracts import (
    CANONICAL_FACTOR_IDS,
    load_change_set,
    validate_change_set,
)
from lean_protocol_refresh.execution import (
    BatchState,
    ProtocolState,
    is_already_applied,
)


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "apply-lean-protocol-refresh.py"


def _runner_module():
    spec = importlib.util.spec_from_file_location("lean_refresh_runner", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operator_context() -> OperatorContext:
    return OperatorContext(
        operations_adapter="reviewed_adapter:create",
        production_target="risk-production/postgres",
        backup="s3://reviewed-backups/refresh-2026-07-23.dump",
        transaction_command="apply one family transaction",
        repository="owner/risk-dashboard",
        base_branch="main",
        deployment="deploy workflow production",
        live_check="https://risk.example.org/protocols/falcon",
        rollback="rollback failed family; restore batch backup if required",
    )


def classifications(batch, route: str = "standard_v17"):
    return tuple(
        BaselineClassification(
            protocol.family_slug,
            "mixed_recovery" if protocol.mixed_recovery is not None else route,
            180 if protocol.mixed_recovery is not None else 0,
            4 if protocol.mixed_recovery is not None else 184,
            0,
            len(protocol.changes),
            179 if protocol.mixed_recovery is not None else 0,
            180 if protocol.mixed_recovery is not None else len(protocol.changes),
            180 if protocol.mixed_recovery is not None else 0,
            (
                protocol.mixed_recovery.full_target_projection_semantic_sha256
                if protocol.mixed_recovery is not None
                else None
            ),
            None,
            hashlib.sha256(protocol.family_slug.encode("utf-8")).hexdigest(),
            tuple(
                (
                    change.scope_level,
                    change.target,
                    change.factor_id,
                    change.old_value,
                )
                for change in protocol.changes
            ),
        )
        for protocol in batch.protocols
    )


def factor_row(factor_id: str, score: str, url: str, summary: str) -> dict:
    return {
        "factor_id": factor_id,
        "score": score,
        "evidence_summary": summary,
        "sources": [{"url": url, "title": "Public evidence"}],
    }


def change_set(*, second: bool = False) -> dict:
    protocols = [
        {
            "family_slug": "falcon",
            "surface_slugs": ["default"],
            "topology": {
                "mode": "preserve",
                "family_slug": "falcon",
                "surface_slugs": ["default"],
                "deployment_targets": [],
            },
            "outcome": "changed",
            "last_refreshed": "2026-07-23",
            "resulting_grade": "B",
            "rubric_version": RUBRIC_VERSION,
            "changes": [
                {
                    "factor_id": "RD-F-001",
                    "old_value": factor_row(
                        "RD-F-001",
                        "yellow",
                        "https://old.example.org/falcon",
                        "Previous public evidence.",
                    ),
                    "new_value": factor_row(
                        "RD-F-001",
                        "green",
                        "https://docs.example.org/falcon",
                        "Updated public evidence.",
                    ),
                    "evidence": [
                        {"url": "https://docs.example.org/falcon", "title": "Docs"}
                    ],
                    "resulting_score": "green",
                    "resulting_grade": "B",
                }
            ],
        }
    ]
    if second:
        protocols.append(
            {
                "family_slug": "maple",
                "surface_slugs": ["default"],
                "topology": {
                    "mode": "preserve",
                    "family_slug": "maple",
                    "surface_slugs": ["default"],
                    "deployment_targets": [],
                },
                "outcome": "no_change",
                "last_refreshed": "2026-07-23",
                "resulting_grade": "A",
                "rubric_version": RUBRIC_VERSION,
                "changes": [],
            }
        )
    return {
        "schema_version": "lean-protocol-refresh/v1",
        "batch_id": "2026-07-23-pilot",
        "refresh_date": "2026-07-23",
        "rubric_version": RUBRIC_VERSION,
        "protocols": protocols,
    }


def mixed_recovery_change_set() -> dict:
    document = change_set()
    protocol = document["protocols"][0]
    projection = []
    changed_new = protocol["changes"][0]["new_value"]
    for factor_id in sorted(CANONICAL_FACTOR_IDS):
        value = (
            copy.deepcopy(changed_new)
            if factor_id == "RD-F-001"
            else factor_row(
                factor_id,
                "green",
                f"https://docs.example.org/falcon/{factor_id}",
                f"Approved target evidence for {factor_id}.",
            )
        )
        value["factor_id"] = factor_id
        projection.append(
            {
                "factor_id": factor_id,
                "scope_level": "surface",
                "target": "default",
                "value": value,
            }
        )
    def canonical(value):
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    protocol_hash = hashlib.sha256(canonical(protocol)).hexdigest()
    protocol["mixed_recovery"] = {
        "schema_version": "lean-protocol-refresh/mixed-recovery/v1",
        "source_rubric_version": "v1.5.0",
        "target_rubric_version": RUBRIC_VERSION,
        "selection_policy": "prefer_target_then_source",
        "full_target_projection": projection,
        "full_target_projection_semantic_sha256": hashlib.sha256(
            canonical(projection)
        ).hexdigest(),
        "protocol_change_semantic_sha256": protocol_hash,
    }
    return document


def complete_applied_rows(protocol) -> tuple[tuple[str, object], ...]:
    approved_rows = (
        protocol.mixed_recovery.full_target_projection
        if protocol.mixed_recovery is not None
        else protocol.changes
    )
    rows = [
        (
            f"{change.scope_level}|{change.target}|{change.factor_id}",
            change.new_value,
        )
        for change in approved_rows
    ]
    used = {key for key, _value in rows}
    for factor_id in sorted(CANONICAL_FACTOR_IDS):
        key = f"surface|default|{factor_id}"
        if key in used:
            continue
        used.add(key)
        rows.append(
            (
                key,
                {
                    "factor_id": factor_id,
                    "score": "yellow",
                    "sources": [],
                },
            )
        )
    assert len(rows) == len(CANONICAL_FACTOR_IDS)
    return tuple(rows)


class FakeOperations:
    def __init__(self, states=None, fail_family=None, batch_state=None):
        self.states = states or {}
        self.fail_family = fail_family
        self.batch_state = batch_state or BatchState(False, False)
        self.calls = []

    def verify_batch_backup(self, batch):
        self.calls.append(("backup", batch.batch_id))

    def bind_approved_plan(self, plan):
        self.calls.append(("bind-plan", plan.get("batch_id")))

    def read_baseline_classifications(self, batch):
        self.calls.append(("classify", batch.batch_id))
        return classifications(batch)

    def read_protocol_state(self, family_slug):
        self.calls.append(("read", family_slug))
        return self.states.get(
            family_slug,
            ProtocolState(family_slug, ("default",), None),
        )

    def validate_protocol_resume(self, protocol, state):
        self.calls.append(("resume", protocol.family_slug))

    def begin_protocol(self, protocol):
        self.calls.append(("begin", protocol.family_slug))

    def apply_protocol(self, protocol):
        self.calls.append(("apply", protocol.family_slug))
        if protocol.family_slug == self.fail_family:
            raise RuntimeError("injected apply failure")

    def compare_target_output(self, protocol):
        self.calls.append(("compare", protocol.family_slug))

    def commit_protocol(self, protocol):
        self.calls.append(("commit", protocol.family_slug))

    def rollback_protocol(self, protocol):
        self.calls.append(("rollback", protocol.family_slug))

    def ensure_protocol_pull_request(self, protocol):
        self.calls.append(("pr", protocol.family_slug))

    def select_publication_trigger(self, family_slug):
        self.calls.append(("trigger", family_slug))

    def merge_protocol_pull_request(self, protocol):
        self.calls.append(("merge", protocol.family_slug))

    def read_batch_state(self, batch, protocols):
        self.calls.append(("batch-state", tuple(item.family_slug for item in protocols)))
        return self.batch_state

    def deploy_batch(self, batch, protocols):
        self.calls.append(("deploy", tuple(item.family_slug for item in protocols)))

    def verify_live(self, batch, protocols):
        self.calls.append(("live", tuple(item.family_slug for item in protocols)))


def test_plan_distinguishes_changed_and_no_change_protocols() -> None:
    batch = validate_change_set(change_set(second=True))
    plan = build_plan(batch, operator_context(), classifications(batch))
    changed, no_change = plan.protocols
    assert changed.pull_request == "one protocol PR"
    assert changed.changed_factors == ("RD-F-001 (surface:default)",)
    assert no_change.pull_request == "none"
    assert no_change.production_write == "transaction: last_refreshed only"
    assert plan.backup_count == plan.deployment_count == plan.confirmation_count == 1


def test_rendered_plan_contains_exact_operator_scope_and_old_new_values() -> None:
    batch = validate_change_set(change_set())
    plan = build_plan(
        batch,
        operator_context(),
        classifications(batch),
    )
    rendered = render_plan(plan)
    assert "Production target: risk-production/postgres" in rendered
    assert "rubric v1.7.0" in rendered
    assert "rubric version: v1.7.0" in rendered
    assert "Operations adapter: reviewed_adapter:create" in rendered
    assert "Publication: owner/risk-dashboard (base main)" in rendered
    assert "semantic changed rows: 1" in rendered
    assert "score changes: 1" in rendered
    assert "row details: attached public-safe refresh.json change set" in rendered


def test_plan_does_not_infer_migration_from_184_approved_changes() -> None:
    document = change_set()
    template = document["protocols"][0]["changes"][0]
    changes = []
    for factor_id in sorted(CANONICAL_FACTOR_IDS):
        change = copy.deepcopy(template)
        change["factor_id"] = factor_id
        change["old_value"]["factor_id"] = factor_id
        change["new_value"]["factor_id"] = factor_id
        changes.append(change)
    document["protocols"][0]["changes"] = changes

    rendered = render_plan(
        build_plan(
            validate_change_set(document),
            operator_context(),
            classifications(validate_change_set(document)),
        )
    )

    assert "semantic changed rows: 184" in rendered
    assert "rubric route: standard_v17" in rendered
    assert "rubric route: v1.5.0" not in rendered


def test_private_source_is_rejected_before_operations() -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["evidence"][0]["url"] = (
        "http://10.0.0.4/private-review"
    )
    with pytest.raises(ContractError, match="private or credentialed"):
        validate_change_set(document)


def test_change_factor_must_exist_in_v17_rubric() -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    row["factor_id"] = "RD-F-169"
    row["old_value"]["factor_id"] = "RD-F-169"
    row["new_value"]["factor_id"] = "RD-F-169"
    with pytest.raises(ContractError, match="factor_id is invalid"):
        validate_change_set(document)


def test_local_source_reference_is_rejected_even_with_public_url() -> None:
    document = change_set()
    source = document["protocols"][0]["changes"][0]["evidence"][0]
    source["reference"] = r"C:\private\review.md"
    with pytest.raises(ContractError, match="local path"):
        validate_change_set(document)


def test_internal_reference_outside_source_is_rejected() -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["new_value"]["evidence_summary"] = (
        r"See C:\private\review.md"
    )
    with pytest.raises(ContractError, match="internal reference or local path"):
        validate_change_set(document)


@pytest.mark.parametrize(
    "reference",
    [
        r"See (C:\private\review.md)",
        "See .research/protocols/falcon/notes.md",
        "See docs/private-review.md",
        "See db/private-review.json",
        "See file:///tmp/private-review.md",
        r"See \\private-server\share\private-review.md",
        r"See ..\private\private-review.md",
        "See ./private/private-review.md",
        "See /etc/private-review.md",
        "See /var/private-review.json",
        "See /srv/private-review.txt",
        "See /root/private-review.yaml",
        "See /mnt/private-review.csv",
        "See /workspace/private-review.md",
        r"path=\\private-server\share\private-review.md",
        r"path=..\private\private-review.md",
        "path:../private/private-review.md",
        "path=/etc/private-review.conf",
        "https://example.org,local=/etc/private-review.conf",
    ],
)
def test_punctuated_or_relative_local_reference_is_rejected(reference: str) -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["new_value"]["evidence_summary"] = reference
    with pytest.raises(ContractError, match="internal reference or local path"):
        validate_change_set(document)


def test_resulting_score_must_match_complete_new_row() -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    row["new_value"] = {
        "factor_id": "RD-F-001",
        "score": "red",
        "evidence_summary": "Unsupported mismatch.",
        "sources": [
            {
                "url": "https://docs.example.org/falcon",
                "title": "Public evidence",
            }
        ],
    }
    row["resulting_score"] = "not_assessed"
    row["evidence"] = []
    with pytest.raises(ContractError, match="differs from new.score"):
        validate_change_set(document)


def test_resume_skips_semantically_applied_protocol() -> None:
    batch = validate_change_set(change_set(second=True))
    refresh = batch.protocols[0]
    state = ProtocolState(
        family_slug="falcon",
        surface_slugs=("default",),
        last_refreshed="2026-07-23",
        applied_changes=complete_applied_rows(refresh),
        resulting_grade="B",
        rubric_version=RUBRIC_VERSION,
    )
    operations = FakeOperations(states={"falcon": state})
    report = apply_batch(batch, operations)
    assert report.results[0].status == "skipped"
    assert ("begin", "falcon") not in operations.calls
    assert ("begin", "maple") in operations.calls
    assert ("pr", "falcon") in operations.calls
    assert ("pr", "maple") not in operations.calls
    assert sum(call[0] == "deploy" for call in operations.calls) == 1
    assert sum(call[0] == "live" for call in operations.calls) == 1


def test_mixed_no_change_resume_requires_full_target_projection() -> None:
    parsed = validate_change_set(mixed_recovery_change_set()).protocols[0]
    protocol = replace(parsed, outcome="no_change", changes=())
    applied = complete_applied_rows(protocol)
    state = ProtocolState(
        family_slug=protocol.family_slug,
        surface_slugs=protocol.surface_slugs,
        last_refreshed=protocol.last_refreshed,
        deployment_targets=protocol.deployment_targets,
        applied_changes=applied,
        resulting_grade=protocol.resulting_grade,
        rubric_version=protocol.rubric_version,
    )

    assert is_already_applied(protocol, state)
    changed = list(applied)
    key, value = changed[0]
    changed[0] = (key, {**value, "score": "red"})
    assert not is_already_applied(
        protocol,
        replace(state, applied_changes=tuple(changed)),
    )


def test_mixed_resume_validation_prevents_legacy_state_bypass() -> None:
    batch = validate_change_set(mixed_recovery_change_set())
    protocol = batch.protocols[0]
    state = ProtocolState(
        family_slug=protocol.family_slug,
        surface_slugs=protocol.surface_slugs,
        last_refreshed=protocol.last_refreshed,
        deployment_targets=protocol.deployment_targets,
        applied_changes=complete_applied_rows(protocol),
        resulting_grade=protocol.resulting_grade,
        rubric_version=protocol.rubric_version,
    )

    class UnsafeResumeOperations(FakeOperations):
        def validate_protocol_resume(self, protocol, state):
            raise ContractError("current v1.5.0 rows remain")

    operations = UnsafeResumeOperations(states={protocol.family_slug: state})
    report = apply_batch(batch, operations)

    assert report.results[0].status == "failed"
    assert "current v1.5.0 rows remain" in report.results[0].detail
    assert ("begin", protocol.family_slug) not in operations.calls


def test_failure_rolls_back_only_failed_protocol_and_continues() -> None:
    document = change_set(second=True)
    document["protocols"].reverse()
    batch = validate_change_set(document)
    operations = FakeOperations(fail_family="falcon")
    report = apply_batch(batch, operations)
    assert [(item.family_slug, item.status) for item in report.results] == [
        ("maple", "applied"),
        ("falcon", "failed"),
    ]
    assert ("commit", "maple") in operations.calls
    assert ("rollback", "maple") not in operations.calls
    assert ("rollback", "falcon") in operations.calls
    assert ("commit", "falcon") not in operations.calls
    assert ("pr", "falcon") not in operations.calls
    assert ("pr", "maple") not in operations.calls
    assert report.deployment_completed
    assert report.live_verified


def test_precommit_history_failure_rolls_back_protocol() -> None:
    batch = validate_change_set(mixed_recovery_change_set())

    class HistoryFailureOperations(FakeOperations):
        def compare_target_output(self, protocol):
            self.calls.append(("compare", protocol.family_slug))
            raise ContractError(
                "post-migration source-join identities differ"
            )

    operations = HistoryFailureOperations()
    report = apply_batch(batch, operations)

    assert report.results[0].status == "failed"
    assert ("rollback", batch.protocols[0].family_slug) in operations.calls
    assert ("commit", batch.protocols[0].family_slug) not in operations.calls


def test_publication_failure_withholds_shared_deployment() -> None:
    class PublicationFailure(FakeOperations):
        def merge_protocol_pull_request(self, protocol):
            super().merge_protocol_pull_request(protocol)
            raise RuntimeError("injected PR failure")

    operations = PublicationFailure()
    report = apply_batch(validate_change_set(change_set()), operations)
    assert report.results[0].status == "publication_failed"
    assert report.batch_error == (
        "deployment withheld until every changed protocol PR is merged"
    )
    assert not any(call[0] in {"deploy", "live"} for call in operations.calls)


def test_earlier_publication_failure_never_reaches_final_trigger_pr() -> None:
    document = change_set()
    final = copy.deepcopy(document["protocols"][0])
    final["family_slug"] = "stargate"
    final["topology"]["family_slug"] = "stargate"
    for change in final["changes"]:
        change["old_value"]["factor_id"] = change["factor_id"]
        change["new_value"]["factor_id"] = change["factor_id"]
        for side in ("old_value", "new_value"):
            if "family_slug" in change[side]:
                change[side]["family_slug"] = "stargate"
    document["protocols"].append(final)

    class FirstPublicationFails(FakeOperations):
        def merge_protocol_pull_request(self, protocol):
            super().merge_protocol_pull_request(protocol)
            if protocol.family_slug == "falcon":
                raise RuntimeError("first PR failed")

    operations = FirstPublicationFails()
    report = apply_batch(validate_change_set(document), operations)
    assert report.results[0].status == "publication_failed"
    assert ("pr", "stargate") not in operations.calls
    assert ("merge", "stargate") not in operations.calls
    assert not any(call[0] in {"deploy", "live"} for call in operations.calls)


def test_final_database_failure_moves_framework_trigger_to_last_success() -> None:
    document = change_set()
    final = copy.deepcopy(document["protocols"][0])
    final["family_slug"] = "stargate"
    final["topology"]["family_slug"] = "stargate"
    for change in final["changes"]:
        for side in ("old_value", "new_value"):
            if "family_slug" in change[side]:
                change[side]["family_slug"] = "stargate"
    document["protocols"].append(final)
    operations = FakeOperations(fail_family="stargate")
    report = apply_batch(validate_change_set(document), operations)
    assert ("trigger", "falcon") in operations.calls
    assert ("pr", "falcon") in operations.calls
    assert ("pr", "stargate") not in operations.calls
    assert ("deploy", ("falcon",)) in operations.calls
    assert report.results[1].status == "failed"


def test_single_protocol_export_aliases_are_accepted() -> None:
    protocol = change_set()["protocols"][0]
    protocol["schema_version"] = "lean-protocol-refresh/v1"
    protocol["refresh_id"] = "falcon-refresh"
    protocol["effective_refresh_date"] = protocol.pop("last_refreshed")
    protocol["last_refreshed"] = "2026-07-23"
    protocol["factor_changes"] = protocol.pop("changes")
    row = protocol["factor_changes"][0]
    row["before"] = row.pop("old_value")
    row["after"] = row.pop("new_value")
    row["public_sources"] = row.pop("evidence")
    batch = validate_change_set(protocol)
    assert batch.batch_id == "falcon-refresh"
    assert batch.protocols[0].changes[0].new_value["score"] == "green"


def test_batch_date_does_not_constrain_protocol_refresh_dates() -> None:
    document = change_set(second=True)
    document["refresh_date"] = "2026-07-23"
    document["protocols"][0]["last_refreshed"] = "2026-07-22"
    batch = validate_change_set(document)
    assert batch.refresh_date == "2026-07-23"
    assert [item.last_refreshed for item in batch.protocols] == [
        "2026-07-22",
        "2026-07-23",
    ]
    rendered = render_plan(
        build_plan(batch, operator_context(), classifications(batch))
    )
    assert "protocol refresh date: 2026-07-22" in rendered
    assert "protocol refresh date: 2026-07-23" in rendered


def test_effective_refresh_date_must_match_its_protocol_date() -> None:
    protocol = change_set()["protocols"][0]
    protocol["effective_refresh_date"] = "2026-07-22"
    with pytest.raises(ContractError, match="differs from last_refreshed"):
        validate_change_set(protocol)


@pytest.mark.parametrize("field", ["rubric_version"])
def test_batch_requires_the_supported_rubric_version(field: str) -> None:
    document = change_set()
    document[field] = "v1.6.0"
    with pytest.raises(ContractError, match="rubric_version must be v1.7.0"):
        validate_change_set(document)


def test_protocol_rubric_must_match_the_batch() -> None:
    document = change_set()
    document["protocols"][0]["rubric_version"] = "v1.6.0"
    with pytest.raises(ContractError, match=r"protocols\[0\]\.rubric_version must be v1.7.0"):
        validate_change_set(document)


def test_missing_protocol_rubric_version_is_rejected() -> None:
    document = change_set()
    del document["protocols"][0]["rubric_version"]
    with pytest.raises(ContractError, match=r"protocols\[0\] fields invalid"):
        validate_change_set(document)


def test_internal_nested_change_shape_and_null_batch_are_accepted() -> None:
    document = change_set()
    document["batch_id"] = None
    row = document["protocols"][0]["changes"][0]
    nested = {
        "factor_id": row["factor_id"],
        "scope_level": "surface",
        "target": {"family_slug": "falcon", "surface_slug": "default"},
        "old": {
            "factor_id": "RD-F-001",
            "score": "yellow",
            "evidence_summary": "Previous public evidence.",
            "sources": [
                {"url": "https://old.example.org", "source_type": "docs"}
            ],
        },
        "new": {
            "factor_id": "RD-F-001",
            "score": "green",
            "evidence_summary": "Updated public evidence.",
            "collection_mode": "manual",
            "gap_reason": None,
            "notes": "Complete public row metadata.",
            "sources": [
                {"url": "https://new.example.org", "source_type": "docs"}
            ],
        },
        "resulting_score": "green",
        "resulting_grade": "B",
    }
    document["protocols"][0]["changes"] = [nested]
    batch = validate_change_set(document)
    assert batch.batch_id == "refresh-2026-07-23"
    change = batch.protocols[0].changes[0]
    assert len(change.evidence) == 2
    assert change.new_value["collection_mode"] == "manual"
    assert change.new_value["notes"] == "Complete public row metadata."


def test_same_factor_may_change_on_two_approved_surfaces() -> None:
    document = change_set()
    protocol = document["protocols"][0]
    protocol["surface_slugs"] = ["default", "institutional"]
    protocol["topology"]["surface_slugs"] = ["default", "institutional"]
    first = protocol["changes"][0]
    first["scope_level"] = "surface"
    first["target"] = "default"
    second = dict(first)
    second["target"] = "institutional"
    protocol["changes"] = [first, second]
    batch = validate_change_set(document)
    assert [
        (change.scope_level, change.target, change.factor_id)
        for change in batch.protocols[0].changes
    ] == [
        ("surface", "default", "RD-F-001"),
        ("surface", "institutional", "RD-F-001"),
    ]


def test_deployment_change_requires_exact_approved_target() -> None:
    document = change_set()
    protocol = document["protocols"][0]
    protocol["topology"]["deployment_targets"] = [
        "default/ethereum/primary"
    ]
    row = protocol["changes"][0]
    row["scope_level"] = "deployment"
    row["target"] = "default/ethereum/invented"
    with pytest.raises(ContractError, match="approved deployments"):
        validate_change_set(document)


def test_resume_after_deploy_skips_second_deployment() -> None:
    batch = validate_change_set(change_set(second=True))
    operations = FakeOperations(batch_state=BatchState(True, False))
    report = apply_batch(batch, operations)
    assert report.deployment_completed
    assert report.live_verified
    assert not any(call[0] == "deploy" for call in operations.calls)
    assert sum(call[0] == "live" for call in operations.calls) == 1


def test_apply_can_stop_after_database_before_any_publication() -> None:
    batch = validate_change_set(change_set(second=True))
    operations = FakeOperations()

    report = apply_batch(
        batch,
        operations,
        stop_before_publication=True,
    )

    assert report.publication_pending
    assert all(item.status == "applied" for item in report.results)
    assert not any(
        call[0] in {"trigger", "pr", "merge", "batch-state", "deploy", "live"}
        for call in operations.calls
    )


def test_scalar_factor_values_are_rejected() -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["old_value"] = "yellow"
    with pytest.raises(ContractError, match="complete factor row"):
        validate_change_set(document)


def test_embedded_surface_identity_must_match_wrapper() -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["new_value"]["surface_slug"] = "invented"
    with pytest.raises(ContractError, match="surface_slug differs from wrapper"):
        validate_change_set(document)


def test_unapproved_complete_row_fields_are_rejected_even_when_unchanged() -> None:
    document = change_set()
    for side in ("old_value", "new_value"):
        document["protocols"][0]["changes"][0][side]["protocol_slug"] = (
            "different-family"
        )
        document["protocols"][0]["changes"][0][side]["rubric_version"] = "v0"
    with pytest.raises(ContractError, match="unsupported fields"):
        validate_change_set(document)


def test_complete_row_sources_must_be_public() -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["old_value"]["sources"][0]["url"] = (
        "http://127.0.0.1/internal"
    )
    with pytest.raises(ContractError, match="private or credentialed"):
        validate_change_set(document)


def test_public_http_source_with_url_less_curator_note_is_accepted() -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    sources = [
        {
            "source_type": "docs",
            "url": "https://docs.example.org/falcon",
            "reference": "Falcon public documentation",
        },
        {
            "source_type": "curator_note",
            "reference": "Public-source review disposition recorded by the curator.",
        },
    ]
    row["new_value"]["sources"] = copy.deepcopy(sources)
    row["evidence"] = copy.deepcopy(sources)

    change = validate_change_set(document).protocols[0].changes[0]

    assert change.resulting_score == "green"
    assert change.evidence[0].url == "https://docs.example.org/falcon"


def test_supported_rubric_migration_marker_is_accepted() -> None:
    document = change_set()
    document["rubric_migration"] = {
        "migration": True,
        "source_rubric_version": "v1.5.0",
        "target_rubric_version": RUBRIC_VERSION,
    }

    assert validate_change_set(document).protocols[0].family_slug == "falcon"


def test_hash_bound_mixed_recovery_projection_is_retained() -> None:
    refresh = validate_change_set(mixed_recovery_change_set()).protocols[0]

    assert refresh.mixed_recovery is not None
    assert refresh.mixed_recovery.selection_policy == "prefer_target_then_source"
    assert len(refresh.mixed_recovery.full_target_projection) == 184
    assert {
        row.factor_id for row in refresh.mixed_recovery.full_target_projection
    } == CANONICAL_FACTOR_IDS


@pytest.mark.parametrize(
    "mutation,match",
    [
        (
            lambda recovery: recovery.update(
                full_target_projection_semantic_sha256="0" * 64
            ),
            "full_target_projection_semantic_sha256",
        ),
        (
            lambda recovery: recovery.update(
                protocol_change_semantic_sha256="0" * 64
            ),
            "protocol_change_semantic_sha256",
        ),
        (
            lambda recovery: recovery["full_target_projection"].pop(),
            "exact 184 canonical scoped rows",
        ),
    ],
)
def test_mixed_recovery_rejects_tampered_binding(mutation, match: str) -> None:
    document = mixed_recovery_change_set()
    recovery = document["protocols"][0]["mixed_recovery"]
    mutation(recovery)
    if "full_target_projection" in recovery:
        projection = recovery["full_target_projection"]
        recovery["full_target_projection_semantic_sha256"] = hashlib.sha256(
            json.dumps(
                projection,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        if match == "full_target_projection_semantic_sha256":
            recovery["full_target_projection_semantic_sha256"] = "0" * 64

    with pytest.raises(ContractError, match=match):
        validate_change_set(document)


def test_mixed_recovery_requires_change_new_to_match_projection() -> None:
    document = mixed_recovery_change_set()
    recovery = document["protocols"][0]["mixed_recovery"]
    recovery["full_target_projection"][0]["value"]["score"] = "red"
    recovery["full_target_projection_semantic_sha256"] = hashlib.sha256(
        json.dumps(
            recovery["full_target_projection"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ContractError, match="differs from approved change"):
        validate_change_set(document)


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {},
        {
            "migration": False,
            "source_rubric_version": "v1.5.0",
            "target_rubric_version": RUBRIC_VERSION,
        },
        {
            "migration": True,
            "source_rubric_version": "v1.4.0",
            "target_rubric_version": RUBRIC_VERSION,
        },
    ],
)
def test_malformed_rubric_migration_marker_is_rejected(marker: object) -> None:
    document = change_set()
    document["rubric_migration"] = marker

    with pytest.raises(ContractError, match="rubric_migration"):
        validate_change_set(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reference", 123),
        ("relation", {}),
        ("retrieved_at", []),
        ("retrieved_at", "not-a-date"),
        ("retrieved_at", "2026-99-99"),
        ("notes", 123),
        ("score_id", {}),
        ("title", ""),
    ],
)
def test_source_metadata_must_be_non_empty_text(
    field: str,
    value: object,
) -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["new_value"]["sources"][0][field] = value

    with pytest.raises(ContractError, match=field):
        validate_change_set(document)


def test_url_less_auxiliary_source_requires_reference() -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    row["new_value"]["sources"].append({"source_type": "curator_note"})

    with pytest.raises(ContractError, match="reference"):
        validate_change_set(document)


@pytest.mark.parametrize(
    "safe_material",
    [
        "Bearer authentication overview",
        "Authorization: Bearer token",
        "Authorization: Bearer <token>",
        "Bearer OAuth2.0 authentication overview",
        "The public example specifies password=none.",
        "The protocol uses a local cache for performance.",
    ],
)
def test_safe_neighbors_are_not_mistaken_for_private_material(
    safe_material: str,
) -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["new_value"]["notes"] = safe_material

    assert validate_change_set(document).protocols[0].family_slug == "falcon"


@pytest.mark.parametrize("score", ["green", "yellow", "red", "gray"])
def test_curator_note_only_is_rejected_for_graded_and_gray_rows(score: str) -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    curator_note = {
        "source_type": "curator_note",
        "reference": "Curator interpretation without independently verifiable evidence.",
    }
    row["new_value"]["score"] = score
    row["new_value"]["sources"] = [copy.deepcopy(curator_note)]
    row["resulting_score"] = score
    row["evidence"] = [copy.deepcopy(curator_note)]

    with pytest.raises(ContractError, match="public|HTTP|verifiable"):
        validate_change_set(document)


@pytest.mark.parametrize(
    "source_type",
    [
        "url",
        "github",
        "etherscan",
        "transaction",
        "audit_report",
        "governance_post",
        "docs",
        "partner_feed",
    ],
)
@pytest.mark.parametrize("url_value", ["missing", None])
def test_url_dependent_source_types_require_non_null_url(
    source_type: str,
    url_value: str | None,
) -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    source = {
        "source_type": source_type,
        "reference": "Source declared without a public URL.",
    }
    if url_value is None:
        source["url"] = None
    row["new_value"]["sources"] = [copy.deepcopy(source)]
    row["evidence"] = [copy.deepcopy(source)]

    with pytest.raises(ContractError, match="public|HTTP|URL|locator"):
        validate_change_set(document)


def test_url_less_commit_sha_is_allowed_only_as_auxiliary_evidence() -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    commit = {
        "source_type": "commit_sha",
        "reference": "0123456789abcdef0123456789abcdef01234567",
    }
    public_source = {
        "source_type": "github",
        "url": "https://github.com/example/falcon/commit/0123456789abcdef",
        "reference": "Public commit",
    }
    row["new_value"]["sources"] = [
        copy.deepcopy(public_source),
        copy.deepcopy(commit),
    ]
    row["evidence"] = [
        copy.deepcopy(public_source),
        copy.deepcopy(commit),
    ]

    change = validate_change_set(document).protocols[0].changes[0]
    assert change.evidence[0].url == public_source["url"]

    row["new_value"]["sources"] = [copy.deepcopy(commit)]
    row["evidence"] = [copy.deepcopy(commit)]
    with pytest.raises(ContractError, match="public|HTTP|verifiable"):
        validate_change_set(document)


@pytest.mark.parametrize("score", ["not_assessed", "not_applicable"])
def test_source_free_non_scoring_rows_are_accepted(score: str) -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    row["new_value"]["score"] = score
    row["new_value"]["sources"] = []
    row["resulting_score"] = score
    row["evidence"] = []

    change = validate_change_set(document).protocols[0].changes[0]

    assert change.resulting_score == score
    assert change.evidence == ()


@pytest.mark.parametrize(
    "unsafe_material",
    [
        "Evidence copied from the internal cache.",
        "Evidence copied from internal-cache/falcon.json.",
        r"Evidence copied from C:\Users\analyst\falcon.json.",
        "Evidence copied from scripts/private/falcon.json.",
        "Evidence copied from ../research/falcon.md.",
        "Private review URL: http://10.0.0.8/falcon.",
        "Credentialed URL: https://analyst:secret@example.org/falcon.",
        "Authorization: Bearer public-refresh-secret-token",
        "api_token=public-refresh-secret-token",
        "Based on unpublished analyst material.",
        "local_reference: research/falcon.md",
    ],
)
def test_unsafe_material_in_old_row_is_rejected(unsafe_material: str) -> None:
    document = change_set()
    document["protocols"][0]["changes"][0]["old_value"]["evidence_summary"] = (
        unsafe_material
    )

    with pytest.raises(ContractError):
        validate_change_set(document)


def test_local_reference_source_field_is_rejected() -> None:
    document = change_set()
    source = document["protocols"][0]["changes"][0]["new_value"]["sources"][0]
    source["local_reference"] = "research/falcon.md"

    with pytest.raises(ContractError, match="internal-only|unsupported|local"):
        validate_change_set(document)


def test_load_change_set_enforces_source_boundary(
    tmp_path: Path,
) -> None:
    accepted = change_set()
    row = accepted["protocols"][0]["changes"][0]
    row["new_value"]["sources"].append(
        {
            "source_type": "curator_note",
            "reference": "Auxiliary public-safe curator disposition.",
        }
    )
    row["evidence"].append(
        {
            "source_type": "curator_note",
            "reference": "Auxiliary public-safe curator disposition.",
        }
    )
    accepted_path = tmp_path / "accepted.json"
    accepted_path.write_text(json.dumps(accepted), encoding="utf-8")

    assert load_change_set(accepted_path).protocols[0].family_slug == "falcon"

    unsafe = change_set()
    unsafe["protocols"][0]["changes"][0]["old_value"]["notes"] = (
        "Evidence copied from internal cache."
    )
    unsafe_path = tmp_path / "unsafe.json"
    unsafe_path.write_text(json.dumps(unsafe), encoding="utf-8")

    with pytest.raises(ContractError):
        load_change_set(unsafe_path)


@pytest.mark.parametrize("historical_score", ["yellow", "not_assessed", "not_applicable"])
def test_load_change_set_accepts_hash_bound_historical_disposition(
    tmp_path: Path,
    historical_score: str,
) -> None:
    document = change_set()
    change = document["protocols"][0]["changes"][0]
    change["old_value"] = {
        "factor_id": "RD-F-001",
        "scope_level": "surface",
        "surface_slug": "default",
        "score": historical_score,
        "collection_mode": "manual",
        "gap_reason": None,
        "sources": [],
    }
    change["historical_old_remediation"] = {
        "schema_version": "lean-protocol-refresh/historical-old-remediation/v1",
        "mode": "historical_evidence_unavailable",
        "specialist": "code-security-analyst",
        "baseline_fragment_semantic_sha256": "1" * 64,
        "baseline_row_semantic_sha256": "2" * 64,
        "explanation": (
            "The retained score is immutable historical state and is not "
            "presented as a publicly substantiated claim."
        ),
        "evidence_summary": (
            "No public-safe evidence can substantiate the retained historical "
            "score; it is shown only as immutable baseline state."
        ),
        "evidence_detail": None,
        "notes": None,
        "sources": [],
    }
    path = tmp_path / "remediated.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    parsed = load_change_set(path)
    assert (
        parsed.protocols[0].changes[0].historical_old_remediation["mode"]
        == "historical_evidence_unavailable"
    )
    if historical_score in {"not_assessed", "not_applicable"}:
        remediation = change["historical_old_remediation"]
        remediation["mode"] = "public_evidence"
        remediation["explanation"] = "The historical row was reviewed."
        remediation["evidence_summary"] = "Public evidence was reviewed."
        with pytest.raises(ContractError, match="public_evidence mode"):
            validate_change_set(document)


def test_sparse_same_rubric_fixture_remains_accepted() -> None:
    sparse = validate_change_set(change_set())
    assert len(sparse.protocols[0].changes) == 1


def test_metadata_only_change_is_visible_in_exact_plan() -> None:
    document = change_set()
    row = document["protocols"][0]["changes"][0]
    row["new_value"]["score"] = "yellow"
    row["resulting_score"] = "yellow"
    row["old_value"]["gap_reason"] = "source_unavailable"
    row["new_value"]["gap_reason"] = "protocol_opacity"
    batch = validate_change_set(document)
    rendered = render_plan(
        build_plan(batch, operator_context(), classifications(batch))
    )
    assert "score changes: 0" in rendered
    assert "semantic changed rows: 1" in rendered


def test_resume_comparison_is_order_insensitive() -> None:
    document = change_set()
    protocol = document["protocols"][0]
    protocol["surface_slugs"] = ["default", "institutional"]
    protocol["topology"]["surface_slugs"] = ["default", "institutional"]
    protocol["topology"]["deployment_targets"] = [
        "default/ethereum/primary",
        "institutional/base/primary",
    ]
    second = copy.deepcopy(protocol["changes"][0])
    second["factor_id"] = "RD-F-002"
    second["old_value"]["factor_id"] = "RD-F-002"
    second["new_value"]["factor_id"] = "RD-F-002"
    protocol["changes"].append(second)
    batch = validate_change_set(document)
    refresh = batch.protocols[0]
    applied_changes = tuple(reversed(complete_applied_rows(refresh)))
    state = ProtocolState(
        family_slug="falcon",
        surface_slugs=tuple(reversed(refresh.surface_slugs)),
        deployment_targets=tuple(reversed(refresh.deployment_targets)),
        last_refreshed=refresh.last_refreshed,
        applied_changes=applied_changes,
        resulting_grade=refresh.resulting_grade,
        rubric_version=refresh.rubric_version,
    )
    operations = FakeOperations(states={"falcon": state})
    report = apply_batch(batch, operations)
    assert report.results[0].status == "skipped"
    assert ("begin", "falcon") not in operations.calls


def test_sparse_expected_changes_resume_against_complete_184_row_state() -> None:
    refresh = validate_change_set(change_set()).protocols[0]
    expected_change = refresh.changes[0]
    expected_key = (
        f"{expected_change.scope_level}|{expected_change.target}|"
        f"{expected_change.factor_id}"
    )
    actual_rows = list(complete_applied_rows(refresh))
    complete_state = ProtocolState(
        family_slug=refresh.family_slug,
        surface_slugs=refresh.surface_slugs,
        deployment_targets=refresh.deployment_targets,
        last_refreshed=refresh.last_refreshed,
        applied_changes=tuple(actual_rows),
        resulting_grade=refresh.resulting_grade,
        rubric_version=refresh.rubric_version,
    )

    assert is_already_applied(refresh, complete_state)
    assert not is_already_applied(
        refresh,
        replace(complete_state, applied_changes=(actual_rows[0],)),
    )
    assert not is_already_applied(
        refresh,
        replace(complete_state, applied_changes=tuple(actual_rows[1:])),
    )

    mismatched = list(actual_rows)
    mismatched[0] = (
        expected_key,
        {**expected_change.new_value, "score": "red"},
    )
    assert not is_already_applied(
        refresh,
        replace(complete_state, applied_changes=tuple(mismatched)),
    )

    duplicate_actual = tuple(actual_rows) + (actual_rows[0],)
    assert not is_already_applied(
        refresh,
        replace(complete_state, applied_changes=duplicate_actual),
    )

    wrong_universe = list(actual_rows)
    wrong_universe[-1] = (
        "surface|default|RD-F-999",
        {
            "factor_id": "RD-F-999",
            "score": "yellow",
            "sources": [],
        },
    )
    assert not is_already_applied(
        refresh,
        replace(complete_state, applied_changes=tuple(wrong_universe)),
    )

    duplicate_expected = replace(
        refresh, changes=refresh.changes + refresh.changes
    )
    assert not is_already_applied(duplicate_expected, complete_state)


def test_incomplete_active_state_never_skips_no_change_refresh() -> None:
    refresh = validate_change_set(change_set(second=True)).protocols[1]
    incomplete_state = ProtocolState(
        family_slug=refresh.family_slug,
        surface_slugs=refresh.surface_slugs,
        deployment_targets=refresh.deployment_targets,
        last_refreshed=refresh.last_refreshed,
        applied_changes=(),
        resulting_grade=refresh.resulting_grade,
        rubric_version=refresh.rubric_version,
    )

    assert is_already_applied(
        refresh,
        replace(
            incomplete_state,
            applied_changes=complete_applied_rows(refresh),
        ),
    )
    assert not is_already_applied(refresh, incomplete_state)


@pytest.mark.parametrize(
    ("state_grade", "state_rubric"),
    [("A", RUBRIC_VERSION), ("B", "v1.6.0")],
)
def test_resume_requires_resulting_grade_and_rubric_version(
    state_grade: str, state_rubric: str
) -> None:
    batch = validate_change_set(change_set())
    refresh = batch.protocols[0]
    state = ProtocolState(
        family_slug=refresh.family_slug,
        surface_slugs=refresh.surface_slugs,
        deployment_targets=refresh.deployment_targets,
        last_refreshed=refresh.last_refreshed,
        applied_changes=tuple(
            (f"{change.scope_level}|{change.target}|{change.factor_id}", change.new_value)
            for change in refresh.changes
        ),
        resulting_grade=state_grade,
        rubric_version=state_rubric,
    )
    operations = FakeOperations(states={refresh.family_slug: state})
    report = apply_batch(batch, operations)
    assert report.results[0].status == "applied"


def test_runner_requires_exact_context_for_plan_and_apply() -> None:
    runner = _runner_module()
    with pytest.raises(SystemExit) as plan_error:
        runner.parse_args(["changes.json", "--plan", "--operations", "adapter:create"])
    assert plan_error.value.code == 2
    with pytest.raises(SystemExit) as apply_error:
        runner.parse_args(["changes.json", "--apply", "--operations", "adapter:create"])
    assert apply_error.value.code == 2


def test_runner_requires_approved_plan_for_apply() -> None:
    runner = _runner_module()
    args = ["changes.json", "--apply", "--operations", "adapter:create"]
    for name, value in vars(operator_context()).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])
    with pytest.raises(SystemExit) as error:
        runner.parse_args(args)
    assert error.value.code == 2


def test_runner_passes_same_context_to_apply_factory() -> None:
    runner = _runner_module()
    batch = validate_change_set(change_set())
    context = operator_context()
    received = []

    def factory(received_batch, received_context):
        received.extend([received_batch, received_context])
        return FakeOperations()

    runner._resolve_operations_factory = lambda spec: factory
    operations = runner._load_operations(context.operations_adapter, batch, context)
    assert isinstance(operations, FakeOperations)
    assert received == [batch, context]


def test_public_factory_constructs_from_real_operator_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lean_protocol_refresh.production import ProductionOperations, create_operations

    context = operator_context()
    context = OperatorContext(
        **{
            **vars(context),
            "repository": "owner/risk-dashboard",
        }
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("RISKDASHBOARD_REPOSITORY_ROOT", str(tmp_path))
    operations = create_operations(validate_change_set(change_set()), context)
    assert isinstance(operations, ProductionOperations)
    assert operations.repository == "owner/risk-dashboard"


def test_plan_uses_only_read_only_adapter_classification() -> None:
    runner = _runner_module()
    batch = validate_change_set(change_set())
    calls = []

    def factory(*args):
        calls.append(args)
        return FakeOperations()

    runner._resolve_operations_factory = lambda spec: factory
    runner.load_change_set = lambda path: batch
    args = ["change-set.json", "--plan", "--operations", "adapter:create"]
    for name, value in vars(operator_context()).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])
    assert runner.main(args) == 0
    assert len(calls) == 1
    assert calls[0][0] == batch
    assert calls[0][1].operations_adapter == "adapter:create"


def test_apply_rejects_drift_from_approved_plan_before_backup(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    batch = validate_change_set(change_set())
    operations = FakeOperations()
    approved_plan = tmp_path / "approved-plan.json"
    approved_plan.write_text("{}", encoding="utf-8")
    runner._resolve_operations_factory = lambda spec: (
        lambda received_batch, received_context: operations
    )
    runner.load_change_set = lambda path: batch
    args = [
        "change-set.json",
        "--apply",
        "--approved-plan",
        str(approved_plan),
        "--operations",
        "adapter:create",
    ]
    for name, value in vars(operator_context()).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])

    assert runner.main(args) == 2
    assert ("classify", batch.batch_id) in operations.calls
    assert ("backup", batch.batch_id) not in operations.calls


def test_valid_json_plan_round_trip_applies(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    batch = validate_change_set(change_set())
    context = replace(operator_context(), operations_adapter="adapter:create")
    approved_plan = tmp_path / "approved-plan.json"
    approved_plan.write_text(
        json.dumps(
            runner._json_plan(
                build_plan(batch, context, classifications(batch))
            )
        ),
        encoding="utf-8",
    )
    operations = FakeOperations()
    runner._resolve_operations_factory = lambda spec: (
        lambda received_batch, received_context: operations
    )
    runner.load_change_set = lambda path: batch
    args = [
        "change-set.json",
        "--apply",
        "--approved-plan",
        str(approved_plan),
        "--operations",
        "adapter:create",
    ]
    for name, value in vars(context).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])

    assert runner.main(args) == 0
    assert ("backup", batch.batch_id) in operations.calls


def test_standard_route_resume_accepts_exact_completed_state_with_new_hash() -> None:
    runner = _runner_module()
    batch = validate_change_set(change_set())
    context = operator_context()
    approved = runner._json_plan(
        build_plan(batch, context, classifications(batch))
    )
    completed_classification = replace(
        classifications(batch)[0],
        selected_production_baseline_sha256="f" * 64,
    )
    current = runner._json_plan(
        build_plan(
            batch,
            context,
            (completed_classification,),
            allow_completed_routes=True,
        )
    )
    protocol = batch.protocols[0]
    operations = FakeOperations(
        states={
            protocol.family_slug: ProtocolState(
                family_slug=protocol.family_slug,
                surface_slugs=protocol.surface_slugs,
                last_refreshed=protocol.last_refreshed,
                deployment_targets=protocol.deployment_targets,
                applied_changes=complete_applied_rows(protocol),
                resulting_grade=protocol.resulting_grade,
                rubric_version=protocol.rubric_version,
            )
        }
    )

    runner._validate_approved_plan_state(
        batch,
        operations,
        approved,
        current,
    )

    assert ("resume", protocol.family_slug) in operations.calls


def test_partial_batch_resume_accepts_completed_mixed_route(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    document = mixed_recovery_change_set()
    document["protocols"].append(change_set(second=True)["protocols"][1])
    batch = validate_change_set(document)
    context = replace(operator_context(), operations_adapter="adapter:create")
    legacy_hash = "a" * 64
    approved_classifications = (
        replace(
            classifications(batch)[0],
            legacy_history_sha256=legacy_hash,
        ),
        classifications(batch)[1],
    )
    approved_plan = tmp_path / "approved-plan.json"
    approved_plan.write_text(
        json.dumps(
            runner._json_plan(
                build_plan(batch, context, approved_classifications)
            )
        ),
        encoding="utf-8",
    )
    mixed = batch.protocols[0]
    mixed_state = ProtocolState(
        family_slug=mixed.family_slug,
        surface_slugs=mixed.surface_slugs,
        last_refreshed=mixed.last_refreshed,
        deployment_targets=mixed.deployment_targets,
        applied_changes=complete_applied_rows(mixed),
        resulting_grade=mixed.resulting_grade,
        rubric_version=mixed.rubric_version,
    )

    class PartialOperations(FakeOperations):
        def read_baseline_classifications(self, received_batch):
            self.calls.append(("classify", received_batch.batch_id))
            return (
                BaselineClassification(
                    mixed.family_slug,
                    "mixed_recovery_complete",
                    0,
                    184,
                    0,
                    len(mixed.changes),
                    0,
                    0,
                    0,
                    mixed.mixed_recovery.full_target_projection_semantic_sha256,
                    legacy_hash,
                    "f" * 64,
                    classifications(received_batch)[0].selected_change_old_values,
                ),
                classifications(received_batch)[1],
            )

    operations = PartialOperations(states={mixed.family_slug: mixed_state})
    runner._resolve_operations_factory = lambda spec: (
        lambda received_batch, received_context: operations
    )
    runner.load_change_set = lambda path: batch
    args = [
        "change-set.json",
        "--apply",
        "--approved-plan",
        str(approved_plan),
        "--operations",
        "adapter:create",
    ]
    for name, value in vars(context).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])

    assert runner.main(args) == 0
    assert ("begin", mixed.family_slug) not in operations.calls
    assert ("begin", "maple") in operations.calls


def test_resume_accepts_completed_full_v15_migration(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    document = change_set()
    template = document["protocols"][0]["changes"][0]
    document["protocols"][0]["changes"] = []
    for factor_id in sorted(CANONICAL_FACTOR_IDS):
        change = copy.deepcopy(template)
        change["factor_id"] = factor_id
        change["old_value"]["factor_id"] = factor_id
        change["new_value"]["factor_id"] = factor_id
        document["protocols"][0]["changes"].append(change)
    batch = validate_change_set(document)
    protocol = batch.protocols[0]
    context = replace(operator_context(), operations_adapter="adapter:create")
    legacy_hash = "b" * 64
    approved_classification = BaselineClassification(
        protocol.family_slug,
        "full_v15_migration",
        184,
        0,
        0,
        184,
        0,
        184,
        184,
        None,
        legacy_hash,
        "a" * 64,
        tuple(
            (
                change.scope_level,
                change.target,
                change.factor_id,
                change.old_value,
            )
            for change in protocol.changes
        ),
    )
    approved_plan = tmp_path / "approved-plan.json"
    approved_plan.write_text(
        json.dumps(
            runner._json_plan(
                build_plan(batch, context, (approved_classification,))
            )
        ),
        encoding="utf-8",
    )
    state = ProtocolState(
        family_slug=protocol.family_slug,
        surface_slugs=protocol.surface_slugs,
        last_refreshed=protocol.last_refreshed,
        deployment_targets=protocol.deployment_targets,
        applied_changes=complete_applied_rows(protocol),
        resulting_grade=protocol.resulting_grade,
        rubric_version=protocol.rubric_version,
    )

    class CompletedMigrationOperations(FakeOperations):
        def read_baseline_classifications(self, received_batch):
            self.calls.append(("classify", received_batch.batch_id))
            return (
                BaselineClassification(
                    protocol.family_slug,
                    "full_v15_migration_complete",
                    0,
                    184,
                    0,
                    184,
                    0,
                    184,
                    0,
                    None,
                    legacy_hash,
                    "c" * 64,
                    approved_classification.selected_change_old_values,
                ),
            )

    operations = CompletedMigrationOperations(
        states={protocol.family_slug: state}
    )
    runner._resolve_operations_factory = lambda spec: (
        lambda received_batch, received_context: operations
    )
    runner.load_change_set = lambda path: batch
    args = [
        "change-set.json",
        "--apply",
        "--approved-plan",
        str(approved_plan),
        "--operations",
        "adapter:create",
    ]
    for name, value in vars(context).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])

    assert runner.main(args) == 0
    assert ("begin", protocol.family_slug) not in operations.calls


def test_new_plan_cannot_bless_completed_route_state() -> None:
    batch = validate_change_set(mixed_recovery_change_set())
    completed = replace(
        classifications(batch)[0],
        rubric_route="mixed_recovery_complete",
        current_v15_rows=0,
        current_v17_rows=184,
        migration_only_rows=0,
        v17_insert_or_replace_rows=0,
        v15_retirement_rows=0,
        legacy_history_sha256="c" * 64,
    )
    with pytest.raises(ContractError, match="original approved pre-mutation"):
        build_plan(batch, operator_context(), (completed,))


def test_apply_rejects_approved_completed_route_even_when_current_matches(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    batch = validate_change_set(mixed_recovery_change_set())
    context = replace(operator_context(), operations_adapter="adapter:create")
    completed = replace(
        classifications(batch)[0],
        rubric_route="mixed_recovery_complete",
        current_v15_rows=0,
        current_v17_rows=184,
        migration_only_rows=0,
        v17_insert_or_replace_rows=0,
        v15_retirement_rows=0,
        legacy_history_sha256="d" * 64,
    )
    approved_plan = tmp_path / "approved-plan.json"
    approved_plan.write_text(
        json.dumps(
            runner._json_plan(
                build_plan(
                    batch,
                    context,
                    (completed,),
                    allow_completed_routes=True,
                )
            )
        ),
        encoding="utf-8",
    )

    class CompletedOperations(FakeOperations):
        def read_baseline_classifications(self, received_batch):
            self.calls.append(("classify", received_batch.batch_id))
            return (completed,)

    operations = CompletedOperations()
    runner._resolve_operations_factory = lambda spec: (
        lambda received_batch, received_context: operations
    )
    runner.load_change_set = lambda path: batch
    args = [
        "change-set.json",
        "--apply",
        "--approved-plan",
        str(approved_plan),
        "--operations",
        "adapter:create",
    ]
    for name, value in vars(context).items():
        if name != "operations_adapter":
            args.extend([f"--{name.replace('_', '-')}", value])

    assert runner.main(args) == 2
    assert ("backup", batch.batch_id) not in operations.calls
