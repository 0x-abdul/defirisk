#!/usr/bin/env python3
"""set_published.py — Flip protocols.is_published on/off.

The editorial gate that controls which protocols appear on the public
dashboard. Unpublished protocols are served only at their unguessable
/unpublished/<slug>-<token>/ review URL; published protocols appear in
index.json and at /protocols/<slug>/. See db/migrations/0006_is_published.sql.

This is the day-to-day tool for the pre-launch review window:
  1. Pull everything to unpublished:   set_published.py --all --off
  2. A team confirms their data:       set_published.py aave-v3 --on
  3. Regenerate JSON + rebuild:        run scripts/dump.py, then rebuild the site
     (or pass --dump here to run dump.py for you).

Usage:
    DATABASE_URL=postgres://... python scripts/set_published.py --list
    DATABASE_URL=postgres://... python scripts/set_published.py aave-v3 uniswap-v4 --on
    DATABASE_URL=postgres://... python scripts/set_published.py spark --off
    DATABASE_URL=postgres://... python scripts/set_published.py --all --off
    DATABASE_URL=postgres://... python scripts/set_published.py aave-v3 --on --dump

Environment:
    DATABASE_URL or LOCAL_DATABASE_URL   psycopg v3 connection string (required)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("ERROR: psycopg (v3) not installed. Run: pip install 'psycopg[binary]'")
    sys.exit(1)


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("  (no protocols)")
        return
    width = max(len(r["slug"]) for r in rows)
    pub = [r for r in rows if r["is_published"]]
    unpub = [r for r in rows if not r["is_published"]]
    print(f"  published   : {len(pub)}")
    print(f"  unpublished : {len(unpub)}")
    print()
    for r in sorted(rows, key=lambda x: (not x["is_published"], x["slug"])):
        flag = "PUBLISHED  " if r["is_published"] else "unpublished"
        print(f"  [{flag}] {r['slug']:<{width}}  {r.get('headline_grade') or '—'}")


def run(
    conn_str: str,
    *,
    slugs: list[str],
    publish: bool | None,
    all_protocols: bool,
    list_only: bool,
    run_dump: bool,
) -> int:
    conn = psycopg.connect(conn_str, row_factory=dict_row, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            if list_only:
                cur.execute(
                    "SELECT slug, is_published, headline_grade FROM protocols ORDER BY slug"
                )
                rows = cur.fetchall()
                print(f"\nProtocols ({len(rows)} total):\n")
                _print_table(rows)
                return 0

            # Resolve target slugs.
            if all_protocols:
                cur.execute("SELECT slug FROM protocols ORDER BY slug")
                targets = [r["slug"] for r in cur.fetchall()]
            else:
                targets = slugs
                # Validate every requested slug exists before mutating anything.
                cur.execute(
                    "SELECT slug FROM protocols WHERE slug = ANY(%s)", (targets,)
                )
                found = {r["slug"] for r in cur.fetchall()}
                missing = [s for s in targets if s not in found]
                if missing:
                    print(
                        f"ERROR: unknown protocol slug(s): {', '.join(missing)}",
                        file=sys.stderr,
                    )
                    return 1

            if not targets:
                print("Nothing to do (no protocols matched).")
                return 0

            # Show before-state for the affected rows.
            cur.execute(
                "SELECT slug, is_published FROM protocols WHERE slug = ANY(%s) ORDER BY slug",
                (targets,),
            )
            before = {r["slug"]: r["is_published"] for r in cur.fetchall()}

            cur.execute(
                "UPDATE protocols SET is_published = %s WHERE slug = ANY(%s)",
                (publish, targets),
            )
            conn.commit()

            verb = "published" if publish else "unpublished"
            changed = [s for s in targets if before.get(s) is not publish]
            print(f"\n{verb.capitalize()} {len(targets)} protocol(s) "
                  f"({len(changed)} changed, {len(targets) - len(changed)} already {verb}):")
            for s in targets:
                mark = "→" if before.get(s) is not publish else " "
                print(f"  {mark} {s}")
    finally:
        conn.close()

    if run_dump:
        dump_py = Path(__file__).resolve().parent / "dump.py"
        print(f"\nRunning {dump_py.name} to regenerate data/api/ ...")
        result = subprocess.run([sys.executable, str(dump_py)], env=os.environ.copy())
        if result.returncode != 0:
            print("ERROR: dump.py failed; data/api/ may be stale.", file=sys.stderr)
            return result.returncode
        print("\nNext: rebuild the site  (cd site && npm run build)  then deploy.")
    else:
        print("\nNext: run  python scripts/dump.py  then rebuild the site "
              "(cd site && npm run build).")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flip protocols.is_published on/off (the public-dashboard gate)."
    )
    parser.add_argument("slugs", nargs="*", metavar="SLUG", help="Protocol slug(s) to flip")
    parser.add_argument("--all", action="store_true", help="Apply to every protocol")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--on", dest="publish", action="store_true", help="Publish (is_published=true)")
    grp.add_argument("--off", dest="publish", action="store_false", help="Unpublish (is_published=false)")
    parser.add_argument("--list", action="store_true", help="Print current publish state and exit")
    parser.add_argument("--dump", action="store_true", help="Run dump.py after the update")
    parser.set_defaults(publish=None)
    args = parser.parse_args(argv)

    if not args.list:
        if args.publish is None:
            parser.error("specify --on or --off (or use --list to inspect state)")
        if not args.slugs and not args.all:
            parser.error("give one or more slugs, or --all")
        if args.slugs and args.all:
            parser.error("use slugs OR --all, not both")

    conn_str = os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not conn_str:
        print(
            "ERROR: No database connection string found.\n"
            "Set DATABASE_URL or LOCAL_DATABASE_URL environment variable.",
            file=sys.stderr,
        )
        return 1

    return run(
        conn_str,
        slugs=args.slugs,
        publish=args.publish,
        all_protocols=args.all,
        list_only=args.list,
        run_dump=args.dump,
    )


if __name__ == "__main__":
    raise SystemExit(main())
