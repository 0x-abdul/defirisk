"""Plan or execute a lean, public-safe protocol refresh batch."""

from __future__ import annotations

import argparse
import importlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lean_protocol_refresh import (
    ContractError,
    OperatorContext,
    apply_batch,
    build_plan,
    load_change_set,
    render_plan,
)
from lean_protocol_refresh.execution import is_already_applied


OPERATIONS_SPEC_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
)


def _validate_operations_spec(spec: str) -> str:
    """Validate the reviewed adapter identity before resolution."""
    if not isinstance(spec, str) or not OPERATIONS_SPEC_RE.fullmatch(spec):
        raise ContractError("--operations must use module.path:factory syntax")
    return spec


def _resolve_operations_factory(spec: str) -> Any:
    """Resolve a reviewed operator adapter factory as ``module:callable``."""
    _validate_operations_spec(spec)
    module_name, factory_name = spec.split(":", 1)
    try:
        factory = getattr(importlib.import_module(module_name), factory_name)
    except (ImportError, AttributeError, TypeError) as exc:
        raise ContractError(f"cannot load operations adapter {spec}: {exc}") from exc
    if not callable(factory):
        raise ContractError(f"operations adapter factory is not callable: {spec}")
    return factory


def _load_operations(spec: str, batch: Any, context: OperatorContext) -> Any:
    return _resolve_operations_factory(spec)(batch, context)


def _operator_context(args: argparse.Namespace) -> OperatorContext:
    return OperatorContext(
        operations_adapter=args.operations,
        production_target=args.production_target,
        backup=args.backup,
        transaction_command=args.transaction_command,
        repository=args.repository,
        base_branch=args.base_branch,
        deployment=args.deployment,
        live_check=args.live_check,
        rollback=args.rollback,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("change_set", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Print the confirmation plan")
    mode.add_argument("--apply", action="store_true", help="Apply or resume the batch")
    parser.add_argument(
        "--approved-plan",
        type=Path,
        help="Exact JSON plan previously shown and confirmed (required for --apply)",
    )
    parser.add_argument(
        "--operations",
        help="Reviewed module:factory providing production operations (required for both modes)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--production-target", help="Named production database/system")
    parser.add_argument("--backup", help="Exact backup path or reviewed backup class")
    parser.add_argument("--transaction-command", help="Reviewed per-protocol command class")
    parser.add_argument("--repository", help="Public owner/repository target")
    parser.add_argument("--base-branch", help="Public repository base branch")
    parser.add_argument("--deployment", help="Exact deployment workflow or command class")
    parser.add_argument("--live-check", help="Exact final live verification target")
    parser.add_argument("--rollback", help="Per-protocol and batch recovery command class")
    args = parser.parse_args(argv)
    context_fields = (
        "production_target",
        "backup",
        "transaction_command",
        "repository",
        "base_branch",
        "deployment",
        "live_check",
        "rollback",
    )
    supplied_context = [name for name in context_fields if getattr(args, name)]
    if len(supplied_context) != len(context_fields) or not args.operations:
        missing = [f"--{name.replace('_', '-')}" for name in context_fields if not getattr(args, name)]
        if not args.operations:
            missing.insert(0, "--operations")
        parser.error("both --plan and --apply require the exact Task B context: " + ", ".join(missing))
    if args.apply and args.approved_plan is None:
        parser.error("--apply requires --approved-plan")
    if args.plan and args.approved_plan is not None:
        parser.error("--approved-plan is valid only with --apply")
    return args


def _json_plan(plan: Any) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(plan)))


_ROUTE_STATE_FIELDS = {
    "rubric_route",
    "current_v15_rows",
    "current_v17_rows",
    "overlap_rows",
    "migration_only_rows",
    "v17_insert_or_replace_rows",
    "v15_retirement_rows",
}


def _validate_approved_plan_state(
    batch: Any,
    operations: Any,
    approved: dict[str, Any],
    current: dict[str, Any],
) -> None:
    approved_protocols = approved.get("protocols")
    admissible_approved_routes = {
        "standard_v17",
        "full_v15_migration",
        "mixed_recovery",
    }
    if (
        not isinstance(approved_protocols, list)
        or any(
            item.get("rubric_route") not in admissible_approved_routes
            for item in approved_protocols
            if isinstance(item, dict)
        )
        or any(not isinstance(item, dict) for item in approved_protocols)
    ):
        raise ContractError(
            "approved plan must contain only original supported pre-mutation "
            "routes; completed route state cannot authorize apply"
        )
    if approved == current:
        return
    approved_without_protocols = {
        key: value for key, value in approved.items() if key != "protocols"
    }
    current_without_protocols = {
        key: value for key, value in current.items() if key != "protocols"
    }
    current_protocols = current.get("protocols")
    if (
        approved_without_protocols != current_without_protocols
        or not isinstance(approved_protocols, list)
        or not isinstance(current_protocols, list)
        or len(approved_protocols) != len(current_protocols)
        or len(current_protocols) != len(batch.protocols)
    ):
        raise ContractError(
            "current read-only baseline or operator context differs from "
            "the exact approved plan; rerun --plan and obtain confirmation"
        )
    allowed_transitions = {
        ("mixed_recovery", "mixed_recovery_complete"),
        ("full_v15_migration", "full_v15_migration_complete"),
    }
    for protocol, approved_item, current_item in zip(
        batch.protocols,
        approved_protocols,
        current_protocols,
        strict=True,
    ):
        if approved_item == current_item:
            continue
        routes = (
            approved_item.get("rubric_route"),
            current_item.get("rubric_route"),
        )
        approved_stable = {
            key: value
            for key, value in approved_item.items()
            if key not in _ROUTE_STATE_FIELDS
        }
        current_stable = {
            key: value
            for key, value in current_item.items()
            if key not in _ROUTE_STATE_FIELDS
        }
        if routes not in allowed_transitions or approved_stable != current_stable:
            raise ContractError(
                "current read-only baseline or operator context differs from "
                "the exact approved plan; rerun --plan and obtain confirmation"
            )
        state = operations.read_protocol_state(protocol.family_slug)
        if not is_already_applied(protocol, state):
            raise ContractError(
                f"{protocol.family_slug} route changed but its exact approved "
                "final semantic state is not complete"
            )
        operations.validate_protocol_resume(protocol, state)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        batch = load_change_set(args.change_set)
        context = _operator_context(args)
        if args.plan:
            operations = _load_operations(args.operations, batch, context)
            classifications = operations.read_baseline_classifications(batch)
            plan = build_plan(
                batch,
                context,
                classifications,
            )
            print(json.dumps(_json_plan(plan), indent=2) if args.json else render_plan(plan), end="")
            return 0
        operations = _load_operations(args.operations, batch, context)
        try:
            approved_plan = json.loads(
                args.approved_plan.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot load approved plan: {exc}") from exc
        operations.bind_approved_plan(approved_plan)
        classifications = operations.read_baseline_classifications(batch)
        current_plan = _json_plan(
            build_plan(
                batch,
                context,
                classifications,
                allow_completed_routes=True,
            )
        )
        _validate_approved_plan_state(
            batch, operations, approved_plan, current_plan
        )
        report = apply_batch(batch, operations)
        print(json.dumps(asdict(report), indent=2))
        return (
            1
            if report.batch_error
            or any(
                item.status in {"failed", "publication_failed"}
                for item in report.results
            )
            else 0
        )
    except ContractError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
