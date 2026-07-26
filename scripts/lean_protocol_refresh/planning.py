"""Human-readable planning for a lean refresh batch."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .contracts import ContractError, ProtocolRefresh, RefreshBatch


@dataclass(frozen=True)
class ChangePlan:
    factor_id: str
    scope_level: str
    target: str
    old_score: str
    new_score: str
    resulting_grade: str
    field_changes: tuple[str, ...]
    selected_production_old_value: Any


@dataclass(frozen=True)
class BaselineClassification:
    family_slug: str
    rubric_route: str
    current_v15_rows: int
    current_v17_rows: int
    overlap_rows: int
    semantic_change_rows: int
    migration_only_rows: int
    v17_insert_or_replace_rows: int
    v15_retirement_rows: int
    recovery_projection_sha256: str | None
    legacy_history_sha256: str | None = None
    selected_production_baseline_sha256: str | None = None
    selected_change_old_values: tuple[
        tuple[str, str, str, Any], ...
    ] = ()


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
    rubric_route: str
    current_v15_rows: int
    current_v17_rows: int
    overlap_rows: int
    semantic_change_rows: int
    migration_only_rows: int
    v17_insert_or_replace_rows: int
    v15_retirement_rows: int
    recovery_target_rows: int
    recovery_projection_sha256: str | None
    legacy_history_sha256: str | None
    selected_production_baseline_sha256: str
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


def _protocol_plan(
    protocol: ProtocolRefresh, classification: BaselineClassification
) -> ProtocolPlan:
    selected_old_values = {
        (scope_level, target, factor_id): value
        for scope_level, target, factor_id, value
        in classification.selected_change_old_values
    }
    if classification.selected_production_baseline_sha256 is None:
        raise ContractError(
            f"{protocol.family_slug} classification is missing the selected "
            "production baseline binding"
        )
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
                old_score=_score(
                    selected_old_values[
                        (change.scope_level, change.target, change.factor_id)
                    ]
                ),
                new_score=_score(change.new_value),
                resulting_grade=change.resulting_grade,
                field_changes=_field_changes(
                    selected_old_values[
                        (change.scope_level, change.target, change.factor_id)
                    ],
                    change.new_value,
                ),
                selected_production_old_value=selected_old_values[
                    (change.scope_level, change.target, change.factor_id)
                ],
            )
            for change in protocol.changes
        ),
        rubric_route=classification.rubric_route,
        current_v15_rows=classification.current_v15_rows,
        current_v17_rows=classification.current_v17_rows,
        overlap_rows=classification.overlap_rows,
        semantic_change_rows=classification.semantic_change_rows,
        migration_only_rows=classification.migration_only_rows,
        v17_insert_or_replace_rows=classification.v17_insert_or_replace_rows,
        v15_retirement_rows=classification.v15_retirement_rows,
        recovery_target_rows=(
            len(protocol.mixed_recovery.full_target_projection)
            if protocol.mixed_recovery is not None
            else 0
        ),
        recovery_projection_sha256=(
            protocol.mixed_recovery.full_target_projection_semantic_sha256
            if protocol.mixed_recovery is not None
            else None
        ),
        legacy_history_sha256=classification.legacy_history_sha256,
        selected_production_baseline_sha256=(
            classification.selected_production_baseline_sha256
        ),
        production_write=(
            "transaction: factor history + last_refreshed"
            if protocol.outcome == "changed" or protocol.mixed_recovery is not None
            else "transaction: last_refreshed only"
        ),
        pull_request="one protocol PR" if protocol.outcome == "changed" else "none",
    )


def build_plan(
    batch: RefreshBatch,
    operator: OperatorContext,
    classifications: tuple[BaselineClassification, ...],
    *,
    allow_completed_routes: bool = False,
) -> BatchPlan:
    by_family = {item.family_slug: item for item in classifications}
    expected_families = {item.family_slug for item in batch.protocols}
    if len(by_family) != len(classifications) or set(by_family) != expected_families:
        raise ContractError(
            "baseline classifications must contain exactly one entry per protocol"
        )
    completed_routes = {
        item.rubric_route
        for item in classifications
        if item.rubric_route.endswith("_complete")
    }
    if completed_routes and not allow_completed_routes:
        raise ContractError(
            "completed route state cannot create a new approval plan; resume "
            "requires the original approved pre-mutation JSON plan"
        )
    return BatchPlan(
        batch_id=batch.batch_id,
        refresh_date=batch.refresh_date,
        rubric_version=batch.rubric_version,
        protocols=tuple(
            _protocol_plan(item, by_family[item.family_slug])
            for item in batch.protocols
        ),
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
                f"  rubric route: {protocol.rubric_route}",
                f"  write: {protocol.production_write}",
                f"  current v1.5.0 rows: {protocol.current_v15_rows}",
                f"  current v1.7.0 rows: {protocol.current_v17_rows}",
                f"  overlapping scoped rows: {protocol.overlap_rows}",
                f"  semantic changed rows: {protocol.semantic_change_rows}",
                f"  migration-only rows: {protocol.migration_only_rows}",
                (
                    "  v1.7.0 insert/replacement rows: "
                    f"{protocol.v17_insert_or_replace_rows}"
                ),
                f"  v1.5.0 retirement rows: {protocol.v15_retirement_rows}",
                (
                    "  selected production baseline sha256: "
                    f"{protocol.selected_production_baseline_sha256}"
                ),
                f"  score changes: {len(protocol.score_changed_factors)}",
                f"  publication: {protocol.pull_request}",
                "  verification: target-only semantic output comparison",
            ]
        )
        if protocol.recovery_projection_sha256 is not None:
            lines.extend(
                [
                    (
                        "  recovery target rows: "
                        f"{protocol.recovery_target_rows}"
                    ),
                    (
                        "  recovery projection sha256: "
                        f"{protocol.recovery_projection_sha256}"
                    ),
                ]
            )
        if protocol.legacy_history_sha256 is not None:
            lines.append(
                "  legacy history sha256: "
                f"{protocol.legacy_history_sha256}"
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
