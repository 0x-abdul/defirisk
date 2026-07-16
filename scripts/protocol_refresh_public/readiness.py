"""Static readiness gates for public protocol refresh infrastructure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json_strict


FOUNDATION_FILES = (
    "scripts/export-protocol-refresh.py",
    "scripts/verify-protocol-output.py",
    "scripts/verify-protocol-refresh-public.py",
    "docs/ops/protocol-refresh/README.md",
    "docs/ops/protocol-refresh/schemas/public-handoff.schema.json",
    "docs/ops/protocol-refresh/schemas/publication-metadata.schema.json",
    "docs/ops/protocol-refresh/templates/change-record.template.md",
    ".github/ISSUE_TEMPLATE/protocol-data-refresh.md",
)
MIGRATIONS = (
    ("db/migrations/0011_active_rubric_factor_score_reads.sql", ("CREATE POLICY public_read", "sole active rubric")),
    (
        "db/migrations/0008_protocol_surfaces.sql",
        ("CREATE TABLE IF NOT EXISTS protocol_families", "CREATE TABLE IF NOT EXISTS protocol_surfaces"),
    ),
    (
        "db/migrations/0009_protocol_last_refreshed.sql",
        ("ADD COLUMN IF NOT EXISTS last_refreshed", "WHERE last_refreshed IS NULL"),
    ),
    (
        "db/migrations/0010_protocol_refresh_idempotency.sql",
        ("CREATE UNIQUE INDEX IF NOT EXISTS", "pipeline_runs", "apply-protocol-refresh.py"),
    ),
    (
        "db/migrations/0012_runtime_role_grants.sql",
        ("GRANT USAGE ON SCHEMA public", "protocol_families", "protocol_surfaces"),
    ),
    (
        "db/migrations/0013_schema_migration_ledger.sql",
        ("CREATE TABLE IF NOT EXISTS schema_migrations", "authorization_id", "sha256"),
    ),
)
APPLY_FILES = (
    "scripts/apply-protocol-refresh.py",
    "scripts/dump.py",
    "scripts/protocol_refresh_apply/contracts.py",
    "scripts/protocol_refresh_apply/db.py",
    "scripts/protocol_refresh_apply/runners.py",
    "scripts/manage-refresh-migrations.py",
    "scripts/protocol_refresh_migrations.py",
    "scripts/verify-runtime-grant-policy.py",
    "db/runtime-role-policy.json",
    "docs/ops/protocol-refresh/production-apply-operator.md",
)
ROLLOUT_EVIDENCE = "docs/ops/protocol-refresh/rollout-evidence.json"


def _missing_files(root: Path, paths: tuple[str, ...]) -> list[str]:
    return [path for path in paths if not (root / path).is_file()]


def _migration_blockers(root: Path) -> list[str]:
    blockers: list[str] = []
    for relative, markers in MIGRATIONS:
        path = root / relative
        if not path.is_file():
            blockers.append(f"missing migration {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in content:
                blockers.append(f"{relative} missing required marker {marker!r}")
    return blockers


def _rollout_evidence_blockers(root: Path) -> list[str]:
    path = root / ROLLOUT_EVIDENCE
    if not path.is_file():
        return [f"missing rollout evidence {ROLLOUT_EVIDENCE}"]
    try:
        evidence = load_json_strict(path)
    except ContractError as exc:
        return [str(exc)]
    blockers: list[str] = []
    required_true = (
        "family_import_cleanup_complete",
        "family_parity_verified",
        "pilot_refreshes_verified",
    )
    for name in required_true:
        if evidence.get(name) is not True:
            blockers.append(f"rollout evidence {name} must be true")
    pilots = evidence.get("pilot_refresh_ids")
    if not isinstance(pilots, list) or not pilots or not all(isinstance(item, str) and item for item in pilots):
        blockers.append("rollout evidence requires non-empty pilot_refresh_ids")
    return blockers


def _dump_export_blockers(root: Path) -> list[str]:
    path = root / "scripts/dump.py"
    if not path.is_file():
        return []
    content = path.read_text(encoding="utf-8")
    start = content.find("def fetch_protocols")
    end = content.find("\ndef ", start + 1)
    if start >= 0 and end < 0:
        end = len(content)
    section = content[start:end] if start >= 0 and end > start else ""
    if "last_refreshed" not in section or "FROM protocols" not in section:
        return ["scripts/dump.py fetch_protocols must select protocols.last_refreshed"]
    return []


def evaluate_readiness(repo_root: Path | str) -> dict[str, Any]:
    """Evaluate files only; never connect to a DB, GitHub, or production."""
    root = Path(repo_root).resolve()
    foundation_blockers = [f"missing foundation file {path}" for path in _missing_files(root, FOUNDATION_FILES)]
    foundation_blockers.extend(_migration_blockers(root))
    foundation_ready = not foundation_blockers

    apply_blockers = [] if foundation_ready else ["foundation_ready is false"]
    apply_blockers.extend(f"missing apply capability {path}" for path in _missing_files(root, APPLY_FILES))
    apply_blockers.extend(_dump_export_blockers(root))
    apply_ready = not apply_blockers

    rollout_blockers = [] if apply_ready else ["apply_ready is false"]
    rollout_blockers.extend(_rollout_evidence_blockers(root))
    rollout_ready = not rollout_blockers

    return {
        "foundation_ready": foundation_ready,
        "apply_ready": apply_ready,
        "rollout_ready": rollout_ready,
        "production_ready": rollout_ready,
        "production_ready_alias": "rollout_ready",
        "foundation_blockers": foundation_blockers,
        "apply_blockers": apply_blockers,
        "rollout_blockers": rollout_blockers,
        "static_only": True,
    }
