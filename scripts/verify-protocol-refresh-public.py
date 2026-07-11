#!/usr/bin/env python3
"""Statically verify public refresh handoffs, publication proposals, and readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from protocol_refresh_public.contracts import (
    ContractError,
    load_json_strict,
    verify_public_handoff,
)
from protocol_refresh_public.publication import validate_publication_metadata
from protocol_refresh_public.readiness import evaluate_readiness


REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", nargs="?", type=Path)
    parser.add_argument("--publication-metadata", type=Path)
    parser.add_argument("--require-publication-metadata", action="store_true")
    parser.add_argument("--readiness", action="store_true")
    readiness_gate = parser.add_mutually_exclusive_group()
    readiness_gate.add_argument(
        "--foundation-only",
        action="store_true",
        help="exit nonzero unless foundation_ready is true",
    )
    readiness_gate.add_argument(
        "--apply-ready",
        action="store_true",
        help="exit nonzero unless apply_ready is true",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report: dict = {"ok": True, "errors": []}
    try:
        if args.handoff is not None:
            handoff = load_json_strict(args.handoff)
            report["errors"].extend(verify_public_handoff(handoff))
            if args.publication_metadata is not None:
                proposal = load_json_strict(args.publication_metadata)
                report["errors"].extend(validate_publication_metadata(handoff, proposal))
                report["publication_metadata_checked"] = True
            elif args.require_publication_metadata:
                report["errors"].append("publication metadata is required for this verification")
        elif args.publication_metadata is not None or args.require_publication_metadata:
            report["errors"].append("publication metadata verification requires a handoff")
        readiness_requested = (
            args.readiness or args.foundation_only or args.apply_ready or args.handoff is None
        )
        if readiness_requested:
            report["readiness"] = evaluate_readiness(args.repo_root)
    except ContractError as exc:
        report["errors"].append(str(exc))

    required_gate = None
    if args.foundation_only:
        required_gate = "foundation_ready"
    elif args.apply_ready:
        required_gate = "apply_ready"
    if required_gate is not None:
        readiness = report.get("readiness", {})
        report["selected_readiness"] = required_gate
        report["readiness_requirement_met"] = readiness.get(required_gate) is True

    contract_valid = not report["errors"]
    gate_met = report.get("readiness_requirement_met", True)
    report["contract_valid"] = contract_valid
    report["ok"] = contract_valid and gate_met
    stream = sys.stdout if report["ok"] else sys.stderr
    print(json.dumps(report, indent=2, sort_keys=True), file=stream)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
