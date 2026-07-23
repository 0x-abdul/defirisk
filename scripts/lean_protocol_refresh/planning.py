"""Human-readable planning for a lean refresh batch."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .contracts import ProtocolRefresh, RefreshBatch


@dataclass(frozen=True)
class ChangePlan:
    factor_id: str
    scope_level: str
    target: str
    old_score: str
    new_score: str
    resulting_grade: str
    field_changes: tuple[str, ...]


@dataclass(frozen=True)
class ProtocolPlan:
    family_slug: str
    surface_slugs: tuple[str, ...]
    last_refreshed: str
    outcome: str
    previous_grade: str | None
    resulting_grade: str
    rubric_version: str
    changed_factors: tuple[str, ...]
    score_changed_factors: tuple[str, ...]
    changes: tuple[ChangePlan, ...]
    production_write: str
    pull_request: str


@dataclass(frozen=True)
class OperatorContext:
    operations_adapter: str
    production_target: str
    backup: str
    transaction_command: str
    repository: str
    base_branch: str
    deployment: str
    live_check: str
    rollback: str


@dataclass(frozen=True)
class BatchPlan:
    batch_id: str
    refresh_date: str
    rubric_version: str
    protocols: tuple[ProtocolPlan, ...]
    operator: OperatorContext
    backup_count: int = 1
    deployment_count: int = 1
    confirmation_count: int = 1


def _score(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("score")
    return str(value) if value is not None else "missing"


def _json_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _field_changes(old_value: Any, new_value: Any) -> tuple[str, ...]:
    if not isinstance(old_value, dict) or not isinstance(new_value, dict):
        return (f"value: {_json_value(old_value)} -> {_json_value(new_value)}",)
    changed: list[str] = []
    for field in sorted(set(old_value) | set(new_value)):
        old_field = old_value.get(field)
        new_field = new_value.get(field)
        if old_field != new_field:
            changed.append(
                f"{field}: {_json_value(old_field)} -> {_json_value(new_field)}"
            )
    return tuple(changed)


def _protocol_plan(protocol: ProtocolRefresh) -> ProtocolPlan:
    changed = tuple(
        f"{change.factor_id} ({change.scope_level}:{change.target})"
        for change in protocol.changes
    )
    return ProtocolPlan(
        family_slug=protocol.family_slug,
        surface_slugs=protocol.surface_slugs,
        last_refreshed=protocol.last_refreshed,
        outcome=protocol.outcome,
        previous_grade=protocol.previous_grade,
        resulting_grade=protocol.resulting_grade,
        rubric_version=protocol.rubric_version,
        changed_factors=changed,
        score_changed_factors=tuple(
            change.factor_id
            for change in protocol.changes
            if _score(change.old_value) != _score(change.new_value)
        ),
        changes=tuple(
            ChangePlan(
                factor_id=change.factor_id,
                scope_level=change.scope_level,
                target=change.target,
                old_score=_score(change.old_value),
                new_score=_score(change.new_value),
                resulting_grade=change.resulting_grade,
                field_changes=_field_changes(change.old_value, change.new_value),
            )
            for change in protocol.changes
        ),
        production_write=(
            "transaction: factor history + last_refreshed"
            if protocol.outcome == "changed"
            else "transaction: last_refreshed only"
        ),
        pull_request="one protocol PR" if protocol.outcome == "changed" else "none",
    )


def build_plan(batch: RefreshBatch, operator: OperatorContext) -> BatchPlan:
    return BatchPlan(
        batch_id=batch.batch_id,
        refresh_date=batch.refresh_date,
        rubric_version=batch.rubric_version,
        protocols=tuple(_protocol_plan(item) for item in batch.protocols),
        operator=operator,
    )


def render_plan(plan: BatchPlan) -> str:
    """Render the exact single-confirmation envelope for an operator."""
    lines = [
        (
            f"Lean refresh batch: {plan.batch_id} ({plan.refresh_date}; "
            f"rubric {plan.rubric_version})"
        ),
        "Authorization: one confirmation for this exact batch",
    ]
    lines.extend(
        [
            f"Production target: {plan.operator.production_target}",
            f"Operations adapter: {plan.operator.operations_adapter}",
            f"Backup: {plan.operator.backup}",
            f"Transaction command: {plan.operator.transaction_command}",
            (
                f"Publication: {plan.operator.repository} "
                f"(base {plan.operator.base_branch})"
            ),
            f"Deployment: {plan.operator.deployment}",
            f"Live verification: {plan.operator.live_check}",
            f"Rollback: {plan.operator.rollback}",
        ]
    )
    lines.append("")
    for protocol in plan.protocols:
        lines.extend(
            [
                f"- {protocol.family_slug} [{', '.join(protocol.surface_slugs)}]",
                f"  protocol refresh date: {protocol.last_refreshed}",
                f"  outcome: {protocol.outcome}",
                (
                    f"  grade: {protocol.previous_grade} -> {protocol.resulting_grade}"
                    if protocol.previous_grade
                    else f"  resulting grade: {protocol.resulting_grade}"
                ),
                f"  rubric version: {protocol.rubric_version}",
                (
                    "  rubric migration: v1.5.0 -> v1.7.0"
                    if len(protocol.changes) == 184
                    else "  rubric migration: none"
                ),
                f"  write: {protocol.production_write}",
                f"  full-pass rows: {len(protocol.changed_factors)}",
                f"  score changes: {len(protocol.score_changed_factors)}",
                f"  publication: {protocol.pull_request}",
                "  verification: target-only semantic output comparison",
            ]
        )
        if protocol.score_changed_factors:
            lines.append(
                "  row details: attached public-safe refresh.json change set"
            )
        if (
            protocol.family_slug == "stargate"
            and protocol.previous_grade == "B"
            and protocol.resulting_grade == "F"
            and "RD-F-133" in protocol.score_changed_factors
        ):
            lines.append(
                "  consequential change: RD-F-133 is red; the Category 8 "
                "core-five cap produces grade F"
            )
    lines.extend(
        [
            "",
            "After successful protocol transactions: merge successful changed-protocol PRs,",
            "run one deployment, then perform one final live check for every protocol.",
            "Failure isolation: roll back only the failed protocol and continue the batch.",
        ]
    )
    return "\n".join(lines) + "\n"
