"""Plan or apply one scoped, separately authorized production protocol refresh."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from protocol_refresh_apply.contracts import (
    ContractError,
    load_backup_receipt,
    load_production_authorization_receipt,
    load_public_handoff,
)
from protocol_refresh_apply.db import apply_refresh, build_apply_plan, preflight
from protocol_refresh_apply.runners import (
    make_compose_runner,
    make_dump_runner,
    make_semantic_verifier,
)


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_repo_root() -> Path:
    """Resolve the toolchain root for an isolated, reviewed runner.

    A public handoff can be validated by a temporary reviewed script while the
    compose/dump tools remain in the installed checkout.  The override is
    explicit and fails before database work if it does not contain both tools.
    """
    configured = os.environ.get("PROTOCOL_REFRESH_REPO_ROOT")
    root = Path(configured).resolve() if configured else DEFAULT_REPO_ROOT
    required = (root / "scripts" / "compose.py", root / "scripts" / "dump.py")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ContractError(
            "protocol refresh toolchain root is incomplete: " + ", ".join(missing)
        )
    return root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, help="Sanitized public handoff JSON")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Read-only database plan and drift check")
    mode.add_argument("--apply", action="store_true", help="Perform the separately authorized apply")
    parser.add_argument("--db-url", help="PostgreSQL URL; otherwise DATABASE_URL is used")
    parser.add_argument(
        "--plan-out",
        type=Path,
        help="Write the machine-readable production plan; refuses overwrite",
    )
    parser.add_argument(
        "--authorization-receipt",
        "--authorization",
        type=Path,
        help="Separate production authorization JSON (required for --apply)",
    )
    parser.add_argument(
        "--backup-receipt",
        type=Path,
        help="Validated backup and restore-test receipt JSON (required for --apply)",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Transaction receipt destination (required for --apply)",
    )
    parser.add_argument(
        "--dump-out-root",
        type=Path,
        help="Disposable dump root; defaults to a new temporary directory",
    )
    args = parser.parse_args(argv)
    if args.apply:
        if args.plan_out is not None:
            parser.error("--plan-out is valid only with --plan")
        missing = [
            flag
            for flag, value in (
                ("--authorization-receipt", args.authorization_receipt),
                ("--backup-receipt", args.backup_receipt),
                ("--receipt-out", args.receipt_out),
            )
            if value is None
        ]
        if missing:
            parser.error("--apply requires " + ", ".join(missing))
    return args


def _database_url(explicit: str | None) -> str:
    value = explicit or os.environ.get("DATABASE_URL")
    if not value:
        raise ContractError("--db-url or DATABASE_URL is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ContractError("database URL must be a PostgreSQL URL with an explicit host")
    return value


def _prepare_receipt_path(path: Path) -> Path:
    target = path.resolve()
    if not target.parent.is_dir():
        raise ContractError(f"transaction receipt parent does not exist: {target.parent}")
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".refresh-receipt-", delete=True):
            pass
    except OSError as exc:
        raise ContractError(f"transaction receipt directory is not writable: {target.parent}") from exc
    return target


def _write_receipt(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_plan_new(path: Path, value: dict[str, object]) -> None:
    target = path.resolve()
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, ensure_ascii=True) + "\n")
    except FileExistsError as exc:
        raise ContractError(f"refusing to overwrite existing production plan: {target}") from exc


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=True, default=str))


def _database_contract_error(exc: Exception) -> ContractError:
    diagnostic = str(exc).strip() or exc.__class__.__name__
    return ContractError(f"database operation failed ({exc.__class__.__name__}): {diagnostic}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = None
    try:
        repo_root = resolve_repo_root()
        handoff = load_public_handoff(args.handoff.resolve())
        db_url = _database_url(args.db_url)
        try:
            import psycopg
        except ImportError as exc:
            raise ContractError("psycopg v3 is required for protocol refresh DB work") from exc
        conn = psycopg.connect(db_url, connect_timeout=10)
        if args.plan:
            details = preflight(conn, handoff)
            conn.rollback()
            production_plan = details["production_plan"]
            if args.plan_out is not None:
                _write_plan_new(args.plan_out, production_plan)
            _print(production_plan)
            return 0

        receipt_out = _prepare_receipt_path(args.receipt_out)
        plan = build_apply_plan(handoff)
        details = preflight(conn, handoff)
        conn.rollback()
        db_identity = details["database_identity"]
        authorization = load_production_authorization_receipt(
            args.authorization_receipt,
            expected_operation="apply_protocol_refresh",
            artifact_sha256=handoff.artifact_sha256,
            plan_sha256=details["plan_sha256"],
            refresh_id=plan.refresh_id,
            family_slug=plan.family_slug,
            database_identity=db_identity,
        )
        backup = load_backup_receipt(
            args.backup_receipt,
            expected_operation="apply_protocol_refresh",
            plan_sha256=details["plan_sha256"],
            artifact_sha256=handoff.artifact_sha256,
            database_identity=db_identity,
        )
        out_root = (
            args.dump_out_root.resolve()
            if args.dump_out_root is not None
            else Path(tempfile.mkdtemp(prefix=f"protocol-refresh-{plan.family_slug}-"))
        )
        before_out_root = Path(tempfile.mkdtemp(prefix=f"protocol-refresh-before-{plan.family_slug}-"))
        result = apply_refresh(
            conn,
            db_url,
            handoff,
            authorization=authorization,
            backup=backup,
            baseline_dump_runner=make_dump_runner(repo_root, before_out_root),
            compose_runner=make_compose_runner(repo_root),
            dump_runner=make_dump_runner(repo_root, out_root),
            semantic_verifier=make_semantic_verifier(
                rubric_version=handoff.payload["rubric_version"],
                expected_surfaces=plan.surfaces,
                effective_refresh_date=plan.effective_refresh_date,
                expected_result=handoff.payload["expected_result"],
            ),
        )
        _write_receipt(receipt_out, result)
        _print(result)
        return 0
    except (ContractError, OSError, ValueError) as exc:
        if conn is not None:
            conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        psycopg_module = sys.modules.get("psycopg")
        psycopg_error = getattr(psycopg_module, "Error", None)
        if psycopg_error is None or not isinstance(exc, psycopg_error):
            raise
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        wrapped = _database_contract_error(exc)
        print(f"ERROR: {wrapped}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
