#!/usr/bin/env python3
"""Export an approved internal refresh as a non-authorizing public JSON handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from protocol_refresh_public.contracts import (
    ContractError,
    build_public_handoff,
    load_json_strict,
    write_json,
)


def export_handoff(accepted_path: Path, status_path: Path, output_path: Path) -> dict:
    if output_path.suffix.casefold() != ".json":
        raise ContractError("public handoff output must be a .json file")
    accepted = load_json_strict(accepted_path)
    status = load_json_strict(status_path)
    handoff = build_public_handoff(accepted, status)
    write_json(output_path, handoff)
    return handoff


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "refresh_dir",
        nargs="?",
        type=Path,
        help="directory containing accepted-changes.json and status.json",
    )
    parser.add_argument("--accepted-changes", type=Path)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    accepted = args.accepted_changes
    status = args.status
    if args.refresh_dir is not None:
        accepted = accepted or args.refresh_dir / "accepted-changes.json"
        status = status or args.refresh_dir / "status.json"
    if accepted is None or status is None:
        print(
            json.dumps({"ok": False, "errors": ["provide refresh_dir or both input paths"]}),
            file=sys.stderr,
        )
        return 2
    try:
        handoff = export_handoff(accepted, status, args.output)
    except ContractError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output),
                "artifact_sha256": handoff["integrity"]["artifact_sha256"],
                "production_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
