#!/usr/bin/env python3
"""Verify that generated API deltas are isolated to one protocol family."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from protocol_refresh_public.contracts import ContractError
from protocol_refresh_public.output import verify_output_isolation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--family", "--family-slug", dest="family_slug", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = verify_output_isolation(args.before, args.after, args.family_slug)
    except ContractError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["isolated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
