"""Resumable execution over a narrow, injectable operations interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from typing import Any, Mapping

from .contracts import (
    CANONICAL_FACTOR_IDS,
    EXPECTED_FACTOR_COUNT,
    ProtocolRefresh,
    RefreshBatch,
)
from .planning import BaselineClassification


@dataclass(frozen=True)
class ProtocolState:
    """Production semantic state used only to decide whether work is complete."""

    family_slug: str
    surface_slugs: tuple[str, ...]
    last_refreshed: str | None
    deployment_targets: tuple[str, ...] = ()
    applied_changes: tuple[tuple[str, object], ...] = ()
    resulting_grade: str | None = None
    rubric_version: str | None = None


@dataclass(frozen=True)
class BatchState:
    """Semantic deployment state used to resume after deploy/live interruption."""

    deployed: bool
    live_verified: bool


@dataclass(frozen=True)
class ProtocolResult:
    family_slug: str
    status: str
    detail: str


@dataclass(frozen=True)
class ApplyReport:
    batch_id: str
    backup_verified: bool
    results: tuple[ProtocolResult, ...]
    deployment_completed: bool
    live_verified: bool
    batch_error: str | None = None
    publication_pending: bool = False


@runtime_checkable
class BatchOperations(Protocol):
    """All effects required by Task B; implementations are operator-owned."""

    def verify_batch_backup(self, batch: RefreshBatch) -> None:
        """Create/locate one backup and prove it is non-empty and listable."""

    def read_baseline_classifications(
        self, batch: RefreshBatch
    ) -> tuple[BaselineClassification, ...]:
        """Read exact production baseline routes and counts without mutation."""

    def bind_approved_plan(self, plan: Mapping[str, Any]) -> None:
        """Bind the unchanged confirmed plan for resume and locked checks."""

    def read_protocol_state(self, family_slug: str) -> ProtocolState:
        """Read current semantic state without mutation."""

    def validate_protocol_resume(
        self, protocol: ProtocolRefresh, state: ProtocolState
    ) -> None:
        """Validate route-specific state before treating a protocol as complete."""

    def begin_protocol(self, protocol: ProtocolRefresh) -> None:
        """Begin the target protocol's transaction."""

    def apply_protocol(self, protocol: ProtocolRefresh) -> None:
        """Preserve changed-row history and update last_refreshed."""

    def compare_target_output(self, protocol: ProtocolRefresh) -> None:
        """Compose/dump temporarily and reject unrelated semantic changes."""

    def commit_protocol(self, protocol: ProtocolRefresh) -> None:
        """Commit only this protocol's successful transaction."""

    def rollback_protocol(self, protocol: ProtocolRefresh) -> None:
        """Roll back only this protocol after any failure."""

    def ensure_protocol_pull_request(self, protocol: ProtocolRefresh) -> None:
        """Create or continue exactly one PR for a changed protocol."""

    def merge_protocol_pull_request(self, protocol: ProtocolRefresh) -> None:
        """Merge the changed protocol's successful PR."""

    def read_batch_state(
        self, batch: RefreshBatch, protocols: tuple[ProtocolRefresh, ...]
    ) -> BatchState:
        """Read whether this exact semantic batch is deployed and live-verified."""

    def deploy_batch(
        self, batch: RefreshBatch, protocols: tuple[ProtocolRefresh, ...]
    ) -> None:
        """Run one deployment for the successfully processed protocols."""

    def verify_live(
        self, batch: RefreshBatch, protocols: tuple[ProtocolRefresh, ...]
    ) -> None:
        """Run one final live check covering the deployed protocols."""


def _expected_changes(protocol: ProtocolRefresh) -> tuple[tuple[str, object], ...]:
    expected: list[tuple[str, object]] = []
    approved_rows = (
        protocol.mixed_recovery.full_target_projection
        if protocol.mixed_recovery is not None
        else protocol.changes
    )
    for change in approved_rows:
        value = change.new_value
        if isinstance(value, dict):
            value = dict(value)
            value["factor_id"] = change.factor_id
            value["scope_level"] = change.scope_level
            value["family_slug"] = protocol.family_slug
            if change.scope_level == "surface":
                value["surface_slug"] = change.target
            elif change.scope_level == "deployment":
                surface, chain, deployment_key = change.target.split("/")
                value.update(
                    {
                        "surface_slug": surface,
                        "chain": chain,
                        "deployment_key": deployment_key,
                    }
                )
        expected.append(
            (
                f"{change.scope_level}|{change.target}|{change.factor_id}",
                value,
            )
        )
    return tuple(expected)


def _normalized_changes(
    changes: tuple[tuple[str, object], ...],
) -> dict[str, str] | None:
    def persisted(value: object) -> object:
        """Normalize to fields the public database can reproduce on resume."""
        if not isinstance(value, dict):
            return value
        factor_fields = (
            "category",
            "score",
            "evidence_summary",
            "evidence_detail",
            "collection_mode",
            "gap_reason",
            "notes",
        )
        normalized = {field: value.get(field) for field in factor_fields}
        sources = value.get("sources")
        if isinstance(sources, list):
            normalized["sources"] = sorted(
                (
                    {
                        "source_type": source.get("source_type"),
                        "url": source.get("url"),
                        "reference": source.get("reference"),
                        "relation": source.get("relation", "primary"),
                    }
                    for source in sources
                    if isinstance(source, dict)
                ),
                key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
            )
        return normalized

    normalized: dict[str, str] = {}
    for key, value in changes:
        if key in normalized:
            return None
        normalized[key] = json.dumps(
            persisted(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    return normalized


def is_already_applied(protocol: ProtocolRefresh, state: ProtocolState) -> bool:
    """Compare semantic state; no attempt IDs or receipt chains are involved."""
    if state.family_slug != protocol.family_slug:
        return False
    if sorted(state.surface_slugs) != sorted(protocol.surface_slugs):
        return False
    if sorted(state.deployment_targets) != sorted(protocol.deployment_targets):
        return False
    if state.last_refreshed != protocol.last_refreshed:
        return False
    if state.resulting_grade != protocol.resulting_grade:
        return False
    if state.rubric_version != protocol.rubric_version:
        return False
    actual = _normalized_changes(state.applied_changes)
    if actual is None or len(actual) != EXPECTED_FACTOR_COUNT:
        return False
    if {key.rsplit("|", 1)[-1] for key in actual} != CANONICAL_FACTOR_IDS:
        return False
    if protocol.outcome == "no_change" and protocol.mixed_recovery is None:
        return True
    expected = _normalized_changes(_expected_changes(protocol))
    if expected is None:
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def apply_batch(
    batch: RefreshBatch,
    operations: BatchOperations,
    *,
    stop_before_publication: bool = False,
) -> ApplyReport:
    """Apply independent protocol transactions after one batch backup check.

    A protocol failure is reported and isolated. Remaining protocols still run.
    Backup validation failure occurs before any transaction and propagates.
    """
    operations.verify_batch_backup(batch)
    results: list[ProtocolResult] = []
    for protocol in batch.protocols:
        state = operations.read_protocol_state(protocol.family_slug)
        if (
            state.family_slug != protocol.family_slug
            or sorted(state.surface_slugs) != sorted(protocol.surface_slugs)
            or sorted(state.deployment_targets)
            != sorted(protocol.deployment_targets)
        ):
            results.append(
                ProtocolResult(
                    protocol.family_slug,
                    "failed",
                    "production family/surface topology differs from approved scope",
                )
            )
            continue
        if is_already_applied(protocol, state):
            try:
                operations.validate_protocol_resume(protocol, state)
            except Exception as exc:
                results.append(
                    ProtocolResult(protocol.family_slug, "failed", str(exc))
                )
                continue
            results.append(
                ProtocolResult(protocol.family_slug, "skipped", "already applied")
            )
            continue
        begun = False
        try:
            operations.begin_protocol(protocol)
            begun = True
            operations.apply_protocol(protocol)
            operations.compare_target_output(protocol)
            operations.commit_protocol(protocol)
        except Exception as exc:  # Adapters expose database/tool failures here.
            if begun:
                try:
                    operations.rollback_protocol(protocol)
                except Exception as rollback_exc:
                    results.append(
                        ProtocolResult(
                            protocol.family_slug,
                            "failed",
                            f"{exc}; rollback also failed: {rollback_exc}",
                        )
                    )
                    continue
            results.append(ProtocolResult(protocol.family_slug, "failed", str(exc)))
            continue
        results.append(ProtocolResult(protocol.family_slug, "applied", "verified"))

    if stop_before_publication:
        return ApplyReport(
            batch.batch_id,
            True,
            tuple(results),
            False,
            False,
            None,
            any(item.status in {"applied", "skipped"} for item in results),
        )

    # Publication resumes independently from database application. A changed
    # protocol that was already applied still continues its existing PR.
    publishable_changed = [
        protocol
        for index, protocol in enumerate(batch.protocols)
        if results[index].status in {"applied", "skipped"}
        and protocol.outcome == "changed"
    ]
    select_trigger = getattr(operations, "select_publication_trigger", None)
    if publishable_changed and callable(select_trigger):
        select_trigger(publishable_changed[-1].family_slug)
    for index, protocol in enumerate(batch.protocols):
        if results[index].status not in {"applied", "skipped"}:
            continue
        if protocol.outcome == "no_change":
            continue
        try:
            operations.ensure_protocol_pull_request(protocol)
            operations.merge_protocol_pull_request(protocol)
        except Exception as exc:
            results[index] = ProtocolResult(
                protocol.family_slug, "publication_failed", str(exc)
            )
            # The final protocol PR may be the sole automatic deployment
            # trigger. Never reach it after an earlier required record failed.
            break

    # A committed database change must not become public without its required
    # protocol record. Resume will skip the already-applied database state and
    # continue the same PR; it must not deploy a partial publication set.
    if any(item.status == "publication_failed" for item in results):
        return ApplyReport(
            batch.batch_id,
            True,
            tuple(results),
            False,
            False,
            "deployment withheld until every changed protocol PR is merged",
        )

    deployable = tuple(
        protocol
        for index, protocol in enumerate(batch.protocols)
        if results[index].status in {"applied", "skipped"}
    )
    if not deployable:
        return ApplyReport(batch.batch_id, True, tuple(results), False, False)
    try:
        batch_state = operations.read_batch_state(batch, deployable)
    except Exception as exc:
        return ApplyReport(
            batch.batch_id,
            True,
            tuple(results),
            False,
            False,
            f"deployment state inspection failed: {exc}",
        )
    if batch_state.live_verified:
        return ApplyReport(batch.batch_id, True, tuple(results), True, True)
    deployment_completed = batch_state.deployed
    if not deployment_completed:
        try:
            operations.deploy_batch(batch, deployable)
            deployment_completed = True
        except Exception as exc:
            return ApplyReport(
                batch.batch_id,
                True,
                tuple(results),
                False,
                False,
                f"deployment failed: {exc}",
            )
    try:
        operations.verify_live(batch, deployable)
    except Exception as exc:
        return ApplyReport(
            batch.batch_id,
            True,
            tuple(results),
            deployment_completed,
            False,
            f"live verification failed: {exc}",
        )
    return ApplyReport(batch.batch_id, True, tuple(results), True, True)
