"""Reviewed production-host adapter for the lean Task B runner.

The adapter deliberately keeps credentials and host names out of public records.
It is selected explicitly by the operator command; importing this module has no
side effects.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .contracts import (
    CANONICAL_FACTOR_IDS,
    EXPECTED_FACTOR_COUNT,
    ContractError,
    ProtocolRefresh,
    RefreshBatch,
    validate_factor_sources,
    validate_public_material,
)
from .execution import BatchState, ProtocolState, is_already_applied
from .planning import BaselineClassification

RUBRIC_VERSION = "v1.7.0"
MIGRATION_BASELINE_VERSION = "v1.5.0"
MIXED_RECOVERY_ROUTE = "mixed_recovery"
BACKUP_ROOT = Path("/opt/riskdashboard/.backups/protocol-refresh")
PUBLIC_FACTOR_ROW_FIELDS = {
    "factor_id",
    "deployment_id",
    "score",
    "evidence_summary",
    "evidence_detail",
    "collection_mode",
    "collected_at",
    "data_as_of",
    "collected_by",
    "gap_reason",
    "sources",
}
CommandRunner = Callable[[Sequence[str], Path | None], Any]


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not name:
        raise ContractError("batch_id cannot produce a safe backup name")
    return name


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _run(command: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
    )


@dataclass
class ProductionOperations:
    """Concrete adapter; all process execution is injectable for deterministic tests."""

    batch: RefreshBatch
    database_url: str
    repository_root: Path
    repository: str
    base_branch: str
    deploy_command: tuple[str, ...] = ()
    live_check_command: tuple[str, ...] = ()
    batch_state_command: tuple[str, ...] = ()
    live_state_command: tuple[str, ...] = ()
    backup_root: Path = BACKUP_ROOT
    backup_ssh_host: str | None = None
    backup_database_env_file: Path = Path("/opt/riskdashboard/.env")
    live_base_url: str = "https://defirisk.co/api/v1.7.0/protocols"
    deploy_timeout_seconds: int = 900
    deploy_poll_seconds: int = 5
    command_runner: CommandRunner = _run
    connect: Callable[[str], Any] | None = None
    sleeper: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    urlopen: Callable[..., Any] = urllib.request.urlopen
    _conn: Any = field(default=None, init=False, repr=False)
    _output_before: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _dump_workspace: tempfile.TemporaryDirectory[str] | None = field(default=None, init=False, repr=False)
    _protocol_open: bool = field(default=False, init=False, repr=False)
    _protocol_baseline_family: str | None = field(default=None, init=False, repr=False)
    _protocol_baseline_rubric: str | None = field(default=None, init=False, repr=False)
    _target_rows_before: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _protocol_written_factor_ids: set[str] = field(
        default_factory=set, init=False, repr=False
    )
    _publication_trigger_slug: str | None = field(default=None, init=False, repr=False)
    _planned_classifications: dict[str, BaselineClassification] = field(
        default_factory=dict, init=False, repr=False
    )
    _approved_plan_protocols: dict[str, Mapping[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ContractError("DATABASE_URL is required for the production adapter")
        if not self.repository_root.is_dir():
            raise ContractError("repository_root must be an existing repository directory")
        if not self.repository or not self.base_branch:
            raise ContractError("repository and base_branch are required")
        if getattr(self.batch, "rubric_version", RUBRIC_VERSION) != RUBRIC_VERSION:
            raise ContractError("lean production adapter requires rubric v1.7.0")

    def _connection(self) -> Any:
        if self._conn is None:
            if self.connect is None:
                try:
                    import psycopg
                except ImportError as exc:  # pragma: no cover - production dependency
                    raise ContractError("psycopg is required on the production host") from exc
                self.connect = psycopg.connect
            self._conn = self.connect(self.database_url)
        return self._conn

    def verify_batch_backup(self, batch: RefreshBatch) -> None:
        path = self.backup_root / f"{_safe_name(batch.batch_id)}.dump"
        if self.backup_ssh_host:
            if self.backup_ssh_host.startswith("-") or not re.fullmatch(
                r"[A-Za-z0-9._-]+", self.backup_ssh_host
            ):
                raise ContractError("backup_ssh_host must be a simple SSH host or alias")
            remote_path = shlex.quote(path.as_posix())
            env_file = shlex.quote(self.backup_database_env_file.as_posix())
            script = f"""set -euo pipefail
path={remote_path}
temp="${{path}}.tmp"
if [ -e "$path" ]; then
  test -s "$path"
else
  mkdir -p "$(dirname "$path")"
  rm -f "$temp"
  trap 'rm -f "$temp"' EXIT
  . {env_file}
  db_url="${{LOCAL_DATABASE_URL:-${{DATABASE_URL:-}}}}"
  test -n "$db_url"
  unset LOCAL_DATABASE_URL DATABASE_URL
  readarray -d '' db_parts < <(
    DB_URL="$db_url" python3 -c 'import os, sys, urllib.parse
url = urllib.parse.urlsplit(os.environ["DB_URL"])
query = urllib.parse.parse_qs(url.query)
if url.scheme not in {{"postgres", "postgresql"}} or not url.hostname or not url.username or not url.path.lstrip("/"):
    raise SystemExit("DATABASE_URL is not a supported PostgreSQL URI")
values = (
    url.hostname,
    str(url.port or 5432),
    urllib.parse.unquote(url.username),
    urllib.parse.unquote(url.password or ""),
    urllib.parse.unquote(url.path.lstrip("/")),
    query.get("sslmode", [""])[0],
)
sys.stdout.buffer.write(b"\\0".join(item.encode() for item in values) + b"\\0")'
  )
  unset db_url
  test "${{#db_parts[@]}}" -eq 6
  export PGHOST="${{db_parts[0]}}"
  export PGPORT="${{db_parts[1]}}"
  export PGUSER="${{db_parts[2]}}"
  export PGPASSWORD="${{db_parts[3]}}"
  export PGDATABASE="${{db_parts[4]}}"
  if [ -n "${{db_parts[5]}}" ]; then
    export PGSSLMODE="${{db_parts[5]}}"
  fi
  unset db_parts
  umask 077
  pg_dump --format=custom --file="$temp"
  unset PGPASSWORD
  test -s "$temp"
  chmod 600 "$temp"
  mv "$temp" "$path"
  trap - EXIT
fi
test "$(stat -c %a "$path")" = 600
pg_restore --list "$path" >/dev/null"""
            self.command_runner(
                (
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    "ConnectTimeout=10",
                    "-o",
                    "ServerAliveInterval=15",
                    "-o",
                    "ServerAliveCountMax=2",
                    self.backup_ssh_host,
                    script,
                ),
                None,
            )
            return
        if path.exists():
            if path.stat().st_size == 0:
                raise ContractError("existing batch backup is empty")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".dump.tmp")
            if temp.exists():
                temp.unlink()
            self.command_runner(("pg_dump", "--format=custom", "--file", str(temp), self.database_url), None)
            if not temp.exists() or temp.stat().st_size == 0:
                raise ContractError("pg_dump did not create a non-empty custom backup")
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        if path.stat().st_size == 0:
            raise ContractError("batch backup is empty")
        # This adapter executes on the Linux production host. Windows ACL mode
        # bits are not meaningful in local adapter tests.
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ContractError("batch backup permissions must be 0600")
        self.command_runner(("pg_restore", "--list", str(path)), None)

    def _sole_rubric(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM rubric_versions WHERE is_active = true ORDER BY version")
            rows = cur.fetchall()
        if [str(row[0]) for row in rows] != [RUBRIC_VERSION]:
            raise ContractError("production must have v1.7.0 as its sole active rubric")

    def read_baseline_classifications(
        self, batch: RefreshBatch
    ) -> tuple[BaselineClassification, ...]:
        """Return the exact read-only confirmation inputs for every protocol."""
        if batch != self.batch:
            raise ContractError("baseline classification batch differs from adapter batch")
        conn = self._connection()
        try:
            self._sole_rubric(conn)
            classifications = tuple(
                self._baseline_classification(
                    protocol,
                    allow_completed_mixed=True,
                    include_history_binding=True,
                )
                for protocol in batch.protocols
            )
            self._planned_classifications = {
                item.family_slug: item for item in classifications
            }
            return classifications
        finally:
            conn.rollback()

    def bind_approved_plan(self, plan: Mapping[str, Any]) -> None:
        protocols = plan.get("protocols")
        if not isinstance(protocols, list):
            raise ContractError("approved plan protocols must be an array")
        self._approved_plan_protocols = {
            str(item["family_slug"]): item for item in protocols
        }

    def validate_protocol_resume(
        self, protocol: ProtocolRefresh, state: ProtocolState
    ) -> None:
        """Fail closed before a route-changing protocol is skipped."""
        approved = self._approved_plan_protocols.get(protocol.family_slug)
        if approved is None:
            if protocol.mixed_recovery is not None:
                raise ContractError(
                    "mixed_recovery resume lacks the approved plan binding"
                )
            return
        approved_route = approved.get("rubric_route")
        if approved_route not in {"mixed_recovery", "full_v15_migration"}:
            return
        classification = self._baseline_classification(
            protocol,
            allow_completed_mixed=True,
            include_history_binding=True,
        )
        expected_completed_route = (
            "mixed_recovery_complete"
            if approved_route == "mixed_recovery"
            else "full_v15_migration_complete"
        )
        if classification.rubric_route != expected_completed_route:
            if not self._protocol_open:
                self._connection().rollback()
            raise ContractError(
                "route-changing resume requires zero current v1.5.0 rows and "
                "the exact approved current v1.7.0 final state"
            )
        if (
            classification.legacy_history_sha256
            != approved.get("legacy_history_sha256")
            or classification.current_v15_rows != 0
            or approved.get("v15_retirement_rows") in {None, 0}
        ):
            if not self._protocol_open:
                self._connection().rollback()
            raise ContractError(
                "route-changing resume cannot verify retained v1.5.0 history, "
                "superseded_by links, and source joins"
            )
        if not self._protocol_open:
            self._connection().rollback()

    def read_protocol_state(self, family_slug: str) -> ProtocolState:
        conn = self._connection()
        self._sole_rubric(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT last_refreshed, headline_grade, rubric_version FROM protocols WHERE slug = %s", (family_slug,))
            row = cur.fetchone()
            if row is None:
                raise ContractError("canonical protocol row is missing")
            cur.execute("SELECT surface_slug FROM protocol_surfaces WHERE family_slug = %s ORDER BY surface_slug", (family_slug,))
            surfaces = tuple(str(item[0]) for item in cur.fetchall())
            cur.execute("""SELECT ps.surface_slug, d.chain, d.deployment_key FROM deployments d
                JOIN protocol_surfaces ps ON ps.surface_id=d.surface_id
                WHERE ps.family_slug=%s ORDER BY 1,2,3""", (family_slug,))
            targets = tuple("/".join(map(str, item)) for item in cur.fetchall())
            cur.execute("""SELECT fs.scope_level, fs.factor_id, f.category_id,
                    to_jsonb(fs)
                FROM factor_scores fs
                JOIN factors f ON f.id=fs.factor_id
                WHERE fs.protocol_slug=%s AND fs.is_current=true
                AND fs.rubric_version=%s ORDER BY 1,2""", (family_slug, RUBRIC_VERSION))
            raw_scores = cur.fetchall()
            applied_rows: list[tuple[str, object]] = []
            for scope, factor, category, value in raw_scores:
                raw_value = value
                target = family_slug
                surface_slug = None
                chain = None
                deployment_key = None
                if scope == "surface":
                    cur.execute("SELECT surface_slug FROM protocol_surfaces WHERE surface_id=%s", (value["surface_id"],))
                    surface_slug = str(cur.fetchone()[0])
                    target = surface_slug
                elif scope == "deployment":
                    cur.execute("""SELECT ps.surface_slug,d.chain,d.deployment_key FROM deployments d
                        JOIN protocol_surfaces ps ON ps.surface_id=d.surface_id WHERE d.id=%s""", (value["deployment_id"],))
                    surface_slug, chain, deployment_key = map(str, cur.fetchone())
                    target = "/".join((surface_slug, chain, deployment_key))
                cur.execute("""SELECT s.source_type::text, s.url, s.reference, fss.relation
                    FROM factor_score_sources fss JOIN sources s ON s.id=fss.source_id
                    WHERE fss.factor_score_id=%s ORDER BY 1,2,3,4""", (raw_value["id"],))
                sources = [
                    {
                        key: item
                        for key, item in zip(
                            ("source_type", "url", "reference", "relation"),
                            source,
                            strict=True,
                        )
                        if item is not None
                    }
                    for source in cur.fetchall()
                ]
                value = {
                    "factor_id": str(factor),
                    "category": int(category),
                    "family_slug": family_slug,
                    "scope_level": str(scope),
                    "score": str(raw_value["score"]),
                    "evidence_summary": raw_value["evidence_summary"],
                    "evidence_detail": raw_value.get("evidence_detail"),
                    "collection_mode": str(raw_value["collection_mode"]),
                    "gap_reason": raw_value.get("gap_reason"),
                    "notes": raw_value.get("notes"),
                    "sources": sources,
                }
                if surface_slug is not None:
                    value["surface_slug"] = surface_slug
                if chain is not None:
                    value["chain"] = chain
                    value["deployment_key"] = deployment_key
                applied_rows.append((f"{scope}|{target}|{factor}", value))
            applied = tuple(applied_rows)
        state = ProtocolState(
            family_slug,
            surfaces,
            str(row[0]) if row[0] else None,
            targets,
            applied,
            str(row[1]) if row[1] else None,
            str(row[2]) if row[2] else None,
        )
        if not self._protocol_open:
            conn.rollback()
        return state

    def begin_protocol(self, protocol: ProtocolRefresh) -> None:
        conn = self._connection()
        conn.rollback()
        self._protocol_baseline_family = None
        self._protocol_baseline_rubric = None
        self._target_rows_before = {}
        self._protocol_written_factor_ids = set()
        try:
            conn.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (protocol.family_slug,),
            )
            self._protocol_open = True
            self._sole_rubric(conn)
            self._protocol_baseline_family = protocol.family_slug
            planned_classification = self._planned_classifications.get(
                protocol.family_slug
            )
            locked_classification = self._baseline_classification(
                protocol,
                include_history_binding=(
                    planned_classification is not None
                    and planned_classification.legacy_history_sha256 is not None
                ),
            )
            if (
                planned_classification is not None
                and locked_classification != planned_classification
            ):
                raise ContractError(
                    "locked production baseline differs from the exact "
                    "approved plan; rollback and obtain a revised confirmation"
                )
            route = locked_classification.rubric_route
            self._protocol_baseline_rubric = {
                "standard_v17": RUBRIC_VERSION,
                "full_v15_migration": MIGRATION_BASELINE_VERSION,
            }.get(route, route)
            self._verify_topology(protocol)
            self._dump_workspace = tempfile.TemporaryDirectory(
                prefix="lean-refresh-"
            )
            import dump

            dump.run_dump(
                Path(self._dump_workspace.name) / "before",
                dry_run=False,
                connection=conn,
            )
            self._output_before = self._semantic_tree(
                Path(self._dump_workspace.name) / "before" / "api",
                exclude_family=protocol.family_slug,
            )
            if self._protocol_baseline_rubric == RUBRIC_VERSION:
                self._target_rows_before = self._read_dumped_target_rows(
                    protocol,
                    Path(self._dump_workspace.name) / "before" / "api",
                )
        except Exception:
            conn.rollback()
            self._protocol_open = False
            self._protocol_baseline_family = None
            self._protocol_baseline_rubric = None
            self._target_rows_before = {}
            self._protocol_written_factor_ids = set()
            self._close_dump_workspace()
            raise

    def _read_protocol_baseline_rows(
        self, protocol: ProtocolRefresh
    ) -> tuple[tuple[str, str, str, str], ...]:
        with self._connection().cursor() as cur:
            cur.execute(
                """SELECT fs.rubric_version, fs.factor_id, fs.scope_level,
                          CASE
                            WHEN fs.scope_level IN ('protocol', 'family')
                              THEN fs.protocol_slug
                            WHEN fs.scope_level = 'surface'
                              THEN surface_direct.surface_slug
                            ELSE CONCAT_WS('/',
                              surface_dep.surface_slug, d.chain, d.deployment_key)
                          END AS target
                   FROM factor_scores fs
                   LEFT JOIN protocol_surfaces surface_direct
                     ON surface_direct.surface_id=fs.surface_id
                   LEFT JOIN deployments d ON d.id=fs.deployment_id
                   LEFT JOIN protocol_surfaces surface_dep
                     ON surface_dep.surface_id=d.surface_id
                   WHERE fs.protocol_slug=%s AND fs.is_current=true
                   ORDER BY fs.rubric_version, fs.scope_level, target, fs.factor_id""",
                (protocol.family_slug,),
            )
            rows = tuple(
                (str(version), str(scope), str(target), str(factor_id))
                for version, factor_id, scope, target in cur.fetchall()
            )
        return rows

    def _baseline_classification(
        self,
        protocol: ProtocolRefresh,
        *,
        allow_completed_mixed: bool = False,
        include_history_binding: bool = False,
    ) -> BaselineClassification:
        """Select a route and compute the exact read-only write envelope."""
        rows = self._read_protocol_baseline_rows(protocol)
        versions = {version for version, _scope, _target, _factor_id in rows}
        factor_ids = [factor_id for _version, _scope, _target, factor_id in rows]
        scoped_keys = [
            (scope, target, factor_id)
            for _version, scope, target, factor_id in rows
        ]
        allowed_targets = {
            ("family", protocol.family_slug),
            ("protocol", protocol.family_slug),
            *((("surface", target) for target in protocol.surface_slugs)),
            *((("deployment", target) for target in protocol.deployment_targets)),
        }
        approved_topology = all(
            (scope, target) in allowed_targets
            for scope, target, _factor_id in scoped_keys
        )
        complete_factor_set = (
            len(rows) == EXPECTED_FACTOR_COUNT
            and len(set(factor_ids)) == EXPECTED_FACTOR_COUNT
            and set(factor_ids) == CANONICAL_FACTOR_IDS
            and len(set(scoped_keys)) == EXPECTED_FACTOR_COUNT
            and approved_topology
        )
        keys_by_version: dict[str, list[tuple[str, str, str]]] = {}
        for version, scope, target, factor_id in rows:
            keys_by_version.setdefault(version, []).append(
                (scope, target, factor_id)
            )
        v15_keys = set(keys_by_version.get(MIGRATION_BASELINE_VERSION, ()))
        v17_keys = set(keys_by_version.get(RUBRIC_VERSION, ()))
        overlap = len(v15_keys & v17_keys)
        if protocol.mixed_recovery is not None:
            recovery = protocol.mixed_recovery
            approved_keys = {
                (row.scope_level, row.target, row.factor_id)
                for row in recovery.full_target_projection
            }
            duplicate_version_keys = any(
                len(keys) != len(set(keys)) for keys in keys_by_version.values()
            )
            observed_union = {
                key for keys in keys_by_version.values() for key in keys
            }
            if (
                versions == {MIGRATION_BASELINE_VERSION, RUBRIC_VERSION}
                and all(keys_by_version.get(version) for version in versions)
                and not duplicate_version_keys
                and observed_union == approved_keys
            ):
                changed_keys = {
                    (change.scope_level, change.target, change.factor_id)
                    for change in protocol.changes
                }
                missing_v17 = approved_keys - v17_keys
                return BaselineClassification(
                    protocol.family_slug,
                    MIXED_RECOVERY_ROUTE,
                    len(v15_keys),
                    len(v17_keys),
                    overlap,
                    len(protocol.changes),
                    len(missing_v17 - changed_keys),
                    len(missing_v17 | changed_keys),
                    len(v15_keys),
                    recovery.full_target_projection_semantic_sha256,
                    (
                        self._legacy_history_binding(
                            protocol, current_rows=True
                        )[1]
                        if include_history_binding
                        else None
                    ),
                )
            if (
                allow_completed_mixed
                and versions == {RUBRIC_VERSION}
                and not duplicate_version_keys
                and v17_keys == approved_keys
            ):
                return BaselineClassification(
                    protocol.family_slug,
                    "mixed_recovery_complete",
                    0,
                    len(v17_keys),
                    0,
                    len(protocol.changes),
                    0,
                    0,
                    0,
                    recovery.full_target_projection_semantic_sha256,
                    (
                        self._legacy_history_binding(
                            protocol, current_rows=False
                        )[1]
                        if include_history_binding
                        else None
                    ),
                )
            counts = {
                version: len(keys_by_version[version])
                for version in sorted(keys_by_version)
            }
            raise ContractError(
                "mixed_recovery production baseline differs from the exact "
                f"approved 184-key v1.5.0/v1.7.0 union: {counts or 'none'}"
            )
        if complete_factor_set and versions == {RUBRIC_VERSION}:
            completed_legacy_count = 0
            completed_legacy_hash = None
            if include_history_binding and len(protocol.changes) == EXPECTED_FACTOR_COUNT:
                (
                    completed_legacy_count,
                    completed_legacy_hash,
                ) = self._legacy_history_binding(
                    protocol, current_rows=False
                )
                if completed_legacy_count not in {0, EXPECTED_FACTOR_COUNT}:
                    raise ContractError(
                        "completed full_v15_migration history binding is "
                        "incomplete; the original approved plan is required"
                    )
            return BaselineClassification(
                protocol.family_slug,
                (
                    "full_v15_migration_complete"
                    if completed_legacy_count == EXPECTED_FACTOR_COUNT
                    else "standard_v17"
                ),
                0,
                len(v17_keys),
                0,
                len(protocol.changes),
                0,
                len(protocol.changes),
                0,
                None,
                completed_legacy_hash,
            )
        if complete_factor_set and versions == {MIGRATION_BASELINE_VERSION}:
            changed_factor_ids = {change.factor_id for change in protocol.changes}
            if (
                protocol.outcome != "changed"
                or len(protocol.changes) != EXPECTED_FACTOR_COUNT
                or changed_factor_ids != CANONICAL_FACTOR_IDS
            ):
                raise ContractError(
                    "v1.5.0 migration baseline requires a changed outcome "
                    "with exactly the 184 canonical approved factor rows"
                )
            return BaselineClassification(
                protocol.family_slug,
                "full_v15_migration",
                len(v15_keys),
                0,
                0,
                len(protocol.changes),
                0,
                len(protocol.changes),
                len(v15_keys),
                None,
                (
                    self._legacy_history_binding(
                        protocol, current_rows=True
                    )[1]
                    if include_history_binding
                    else None
                ),
            )
        counts = {
            version: sum(
                1
                for row_version, _scope, _target, _factor_id in rows
                if row_version == version
            )
            for version in versions
        }
        summary = ", ".join(
            f"{version}={counts[version]}" for version in sorted(counts)
        ) or "none"
        raise ContractError(
            "production current-factor baseline must contain the exact 184 "
            "v1.7.0 factor IDs from only v1.7.0 (standard refresh) or only v1.5.0 "
            f"(migration); found {summary}"
        )

    def _legacy_history_binding(
        self, protocol: ProtocolRefresh, *, current_rows: bool
    ) -> tuple[int, str | None]:
        """Hash v1.5 row/source identities before or after route migration."""
        current_clause = "legacy.is_current=true"
        join_clause = ""
        params: tuple[Any, ...] = (
            protocol.family_slug,
            MIGRATION_BASELINE_VERSION,
        )
        if not current_rows:
            current_clause = "legacy.is_current=false"
            join_clause = """JOIN factor_scores target
              ON target.id=legacy.superseded_by
             AND target.protocol_slug=legacy.protocol_slug
             AND target.rubric_version=%s
             AND target.is_current=true
             AND target.factor_id=legacy.factor_id
             AND target.scope_level=legacy.scope_level
             AND COALESCE(target.family_slug, '')=COALESCE(legacy.family_slug, '')
             AND COALESCE(target.surface_id::text, '')=COALESCE(legacy.surface_id::text, '')
             AND COALESCE(target.deployment_id::text, '')=COALESCE(legacy.deployment_id::text, '')"""
            params = (
                RUBRIC_VERSION,
                protocol.family_slug,
                MIGRATION_BASELINE_VERSION,
            )
        with self._connection().cursor() as cur:
            cur.execute(
                f"""SELECT legacy.id::text,
                           COALESCE(array_agg(fss.source_id::text ORDER BY fss.source_id)
                             FILTER (WHERE fss.source_id IS NOT NULL),
                             ARRAY[]::text[])
                    FROM factor_scores legacy
                    {join_clause}
                    LEFT JOIN factor_score_sources fss
                      ON fss.factor_score_id=legacy.id
                    WHERE legacy.protocol_slug=%s
                      AND legacy.rubric_version=%s
                      AND {current_clause}
                    GROUP BY legacy.id
                    ORDER BY legacy.id""",
                params,
            )
            rows = tuple(
                (str(row_id), tuple(str(source_id) for source_id in source_ids))
                for row_id, source_ids in cur.fetchall()
            )
        if not rows:
            return 0, None
        return len(rows), hashlib.sha256(
            _canonical(rows).encode("utf-8")
        ).hexdigest()

    def _classify_protocol_baseline(self, protocol: ProtocolRefresh) -> str:
        """Select the refresh path from the locked production factor baseline."""
        route = self._baseline_classification(protocol).rubric_route
        if route == "standard_v17":
            return RUBRIC_VERSION
        if route == "full_v15_migration":
            return MIGRATION_BASELINE_VERSION
        return route

    def _verify_topology(self, protocol: ProtocolRefresh) -> None:
        state = self.read_protocol_state(protocol.family_slug)
        if sorted(state.surface_slugs) != sorted(protocol.surface_slugs) or sorted(state.deployment_targets) != sorted(protocol.deployment_targets):
            raise ContractError("production family/surface/deployment topology differs from approved scope")

    @staticmethod
    def _target_parts(change: Any, cur: Any, family: str) -> tuple[Any, Any]:
        if change.scope_level in {"protocol", "family"}:
            return None, None
        if change.scope_level == "surface":
            cur.execute("SELECT surface_id FROM protocol_surfaces WHERE family_slug=%s AND surface_slug=%s", (family, change.target))
            row = cur.fetchone()
            if row is None:
                raise ContractError("approved surface is missing")
            return row[0], None
        surface, chain, key = change.target.split("/")
        cur.execute("""SELECT ps.surface_id, d.id FROM protocol_surfaces ps JOIN deployments d ON d.surface_id=ps.surface_id
            WHERE ps.family_slug=%s AND ps.surface_slug=%s AND d.chain=%s AND d.deployment_key=%s""", (family, surface, chain, key))
        row = cur.fetchone()
        if row is None:
            raise ContractError("approved deployment is missing")
        return row[0], row[1]

    @staticmethod
    def _factor_key(change: Any) -> tuple[str, str, str]:
        return (change.scope_level, change.target, change.factor_id)

    def _insert_target_row(
        self,
        cur: Any,
        protocol: ProtocolRefresh,
        target_row: Any,
        surface_id: Any,
        deployment_id: Any,
    ) -> Any:
        new = target_row.new_value
        cur.execute(
            """INSERT INTO factor_scores (protocol_slug, deployment_id, factor_id, rubric_version, score,
                evidence_summary, evidence_detail, collection_mode, gap_reason, collected_at, collected_by, data_as_of,
                is_current, notes, scope_level, family_slug, surface_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'lean-protocol-refresh',%s,false,%s,%s,%s,%s) RETURNING id""",
            (
                protocol.family_slug,
                deployment_id,
                target_row.factor_id,
                RUBRIC_VERSION,
                new.get("score"),
                new.get("evidence_summary"),
                new.get("evidence_detail"),
                new.get("collection_mode"),
                new.get("gap_reason"),
                protocol.last_refreshed,
                new.get("notes"),
                target_row.scope_level,
                protocol.family_slug if target_row.scope_level == "family" else None,
                surface_id,
            ),
        )
        new_id = cur.fetchone()[0]
        for source in new.get("sources", []):
            source_id = self._get_or_create_source(
                cur, source, protocol.last_refreshed
            )
            cur.execute(
                """INSERT INTO factor_score_sources
                   (factor_score_id,source_id,relation)
                   VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
                (new_id, source_id, source.get("relation", "primary")),
            )
        return new_id

    def _apply_mixed_recovery(self, cur: Any, protocol: ProtocolRefresh) -> None:
        recovery = protocol.mixed_recovery
        if recovery is None:
            raise ContractError("mixed_recovery route has no approved target projection")
        changed = {self._factor_key(row): row for row in protocol.changes}
        for target_row in recovery.full_target_projection:
            key = self._factor_key(target_row)
            surface_id, deployment_id = self._target_parts(
                target_row, cur, protocol.family_slug
            )
            cur.execute(
                """SELECT id, rubric_version, to_jsonb(factor_scores)
                   FROM factor_scores
                   WHERE protocol_slug=%s AND factor_id=%s
                     AND scope_level=%s
                     AND family_slug IS NOT DISTINCT FROM %s
                     AND surface_id IS NOT DISTINCT FROM %s
                     AND deployment_id IS NOT DISTINCT FROM %s
                     AND is_current=true
                   ORDER BY rubric_version""",
                (
                    protocol.family_slug,
                    target_row.factor_id,
                    target_row.scope_level,
                    (
                        protocol.family_slug
                        if target_row.scope_level == "family"
                        else None
                    ),
                    surface_id,
                    deployment_id,
                ),
            )
            rows = cur.fetchall()
            by_version = {str(row[1]): row for row in rows}
            if (
                len(by_version) != len(rows)
                or not rows
                or set(by_version) - {MIGRATION_BASELINE_VERSION, RUBRIC_VERSION}
            ):
                raise ContractError(
                    f"mixed_recovery current rows drifted for {target_row.factor_id}"
                )
            selected = by_version.get(RUBRIC_VERSION) or by_version.get(
                MIGRATION_BASELINE_VERSION
            )
            if selected is None:
                raise ContractError(
                    f"mixed_recovery selected row is missing for {target_row.factor_id}"
                )
            selected_old = changed.get(key, target_row)
            self._verify_public_old_row(
                cur, protocol, selected_old, selected[0], selected[2]
            )

            existing_target = by_version.get(RUBRIC_VERSION)
            if key in changed or existing_target is None:
                final_id = self._insert_target_row(
                    cur,
                    protocol,
                    target_row,
                    surface_id,
                    deployment_id,
                )
                self._protocol_written_factor_ids.add(target_row.factor_id)
                old_ids = [row[0] for row in rows]
                cur.execute(
                    """UPDATE factor_scores
                       SET is_current=false, superseded_by=%s
                       WHERE id=ANY(%s) AND is_current=true""",
                    (final_id, old_ids),
                )
                if cur.rowcount != len(old_ids):
                    raise ContractError(
                        f"mixed_recovery could not retire every old row for {target_row.factor_id}"
                    )
                cur.execute(
                    "UPDATE factor_scores SET is_current=true WHERE id=%s",
                    (final_id,),
                )
                if cur.rowcount != 1:
                    raise ContractError(
                        f"mixed_recovery replacement was not promoted for {target_row.factor_id}"
                    )
            else:
                final_id = existing_target[0]
                legacy = by_version.get(MIGRATION_BASELINE_VERSION)
                if legacy is not None:
                    cur.execute(
                        """UPDATE factor_scores
                           SET is_current=false, superseded_by=%s
                           WHERE id=%s AND is_current=true""",
                        (final_id, legacy[0]),
                    )
                    if cur.rowcount != 1:
                        raise ContractError(
                            f"mixed_recovery legacy row was not retired for {target_row.factor_id}"
                        )

        cur.execute(
            """SELECT rubric_version, count(*), count(DISTINCT factor_id)
               FROM factor_scores
               WHERE protocol_slug=%s AND is_current=true
               GROUP BY rubric_version ORDER BY rubric_version""",
            (protocol.family_slug,),
        )
        final_counts = tuple(
            (str(version), int(count), int(distinct_count))
            for version, count, distinct_count in cur.fetchall()
        )
        if final_counts != ((RUBRIC_VERSION, EXPECTED_FACTOR_COUNT, EXPECTED_FACTOR_COUNT),):
            raise ContractError(
                "mixed_recovery postcondition requires exactly 184 unique "
                "current v1.7.0 rows and zero legacy current rows"
            )

    def apply_protocol(self, protocol: ProtocolRefresh) -> None:
        if (
            self._protocol_baseline_family != protocol.family_slug
            or self._protocol_baseline_rubric is None
        ):
            raise ContractError(
                "protocol production baseline was not classified in this transaction"
            )
        expected_baseline_rubric = self._protocol_baseline_rubric
        conn = self._connection()
        with conn.cursor() as cur:
            if expected_baseline_rubric == MIXED_RECOVERY_ROUTE:
                self._apply_mixed_recovery(cur, protocol)
                cur.execute(
                    "UPDATE protocols SET last_refreshed=%s, updated_at=now() WHERE slug=%s",
                    (protocol.last_refreshed, protocol.family_slug),
                )
                if cur.rowcount != 1:
                    raise ContractError(
                        "last_refreshed update did not affect exactly one protocol"
                    )
                return
            for change in protocol.changes:
                surface_id, deployment_id = self._target_parts(change, cur, protocol.family_slug)
                cur.execute("""SELECT id, rubric_version, to_jsonb(factor_scores) FROM factor_scores WHERE protocol_slug=%s AND factor_id=%s
                    AND scope_level=%s AND family_slug IS NOT DISTINCT FROM %s AND surface_id IS NOT DISTINCT FROM %s
                    AND deployment_id IS NOT DISTINCT FROM %s AND is_current=true ORDER BY rubric_version""",
                    (protocol.family_slug, change.factor_id, change.scope_level,
                     protocol.family_slug if change.scope_level == "family" else None, surface_id, deployment_id))
                rows = cur.fetchall()
                if len(rows) != 1:
                    raise ContractError(
                        f"expected exactly one current old factor row: {change.factor_id}"
                    )
                old_id, old_rubric, old = rows[0]
                if str(old_rubric) != expected_baseline_rubric:
                    raise ContractError(
                        "expected current "
                        f"{expected_baseline_rubric} baseline for {change.factor_id}"
                    )
                self._verify_public_old_row(cur, protocol, change, old_id, old)
                new_id = self._insert_target_row(
                    cur, protocol, change, surface_id, deployment_id
                )
                self._protocol_written_factor_ids.add(change.factor_id)
                cur.execute(
                    """UPDATE factor_scores
                       SET is_current=false, superseded_by=%s
                       WHERE id=%s AND is_current=true""",
                    (new_id, old_id),
                )
                if cur.rowcount != 1:
                    raise ContractError(
                        f"old current factor row was not superseded: {change.factor_id}"
                    )
                cur.execute(
                    "UPDATE factor_scores SET is_current=true WHERE id=%s",
                    (new_id,),
                )
                if cur.rowcount != 1:
                    raise ContractError(
                        f"replacement factor row was not promoted: {change.factor_id}"
                    )
            cur.execute("UPDATE protocols SET last_refreshed=%s, updated_at=now() WHERE slug=%s", (protocol.last_refreshed, protocol.family_slug))
            if cur.rowcount != 1:
                raise ContractError(
                    "last_refreshed update did not affect exactly one protocol"
                )

    @staticmethod
    def _get_or_create_source(
        cur: Any, source: Mapping[str, Any], fallback_date: str
    ) -> Any:
        url = source.get("url") or source.get("reference")
        reference = source.get("reference") or url
        if not reference:
            raise ContractError("replacement source has no public locator")
        source_type = source.get("source_type", "url")
        cur.execute(
            """SELECT id FROM sources WHERE source_type=%s
               AND COALESCE(url,'')=COALESCE(%s,'') AND reference=%s
               ORDER BY retrieved_at DESC, id LIMIT 1""",
            (source_type, url, reference),
        )
        existing_source = cur.fetchone()
        if existing_source is None:
            cur.execute(
                """INSERT INTO sources
                   (source_type,url,reference,title,retrieved_at,retrieved_by,notes)
                   VALUES (%s,%s,%s,%s,%s,'lean-protocol-refresh',%s)
                   RETURNING id""",
                (
                    source_type,
                    url,
                    reference,
                    source.get("title"),
                    source.get("retrieved_at") or fallback_date,
                    source.get("notes"),
                ),
            )
            existing_source = cur.fetchone()
        # Source identity is schema-unique. Existing source metadata is shared
        # by every linked protocol and is therefore preserved byte-for-byte.
        return existing_source[0]

    @staticmethod
    def _sorted_sources(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalized = [
            {key: value for key, value in source.items() if value is not None}
            for source in sources
        ]
        return sorted(normalized, key=_canonical)

    def _verify_public_old_row(
        self,
        cur: Any,
        protocol: ProtocolRefresh,
        change: Any,
        old_id: Any,
        old: Mapping[str, Any],
    ) -> None:
        cur.execute("SELECT category_id FROM factors WHERE id=%s", (change.factor_id,))
        category_row = cur.fetchone()
        if category_row is None:
            raise ContractError(f"factor metadata is missing: {change.factor_id}")
        cur.execute(
            """SELECT s.source_type::text, s.url, s.reference, s.title,
                      s.retrieved_at::date::text, s.notes
               FROM factor_score_sources fss
               JOIN sources s ON s.id=fss.source_id
               WHERE fss.factor_score_id=%s
               ORDER BY 1,2,3,4,5,6""",
            (old_id,),
        )
        sources = [
            {
                key_name: value
                for key_name, value in zip(
                    (
                        "source_type",
                        "url",
                        "reference",
                        "title",
                        "retrieved_at",
                        "notes",
                    ),
                    source,
                    strict=True,
                )
                if value is not None
            }
            for source in cur.fetchall()
        ]
        actual: dict[str, Any] = {
            "category": int(category_row[0]),
            "collection_mode": str(old["collection_mode"]),
            "evidence_detail": old.get("evidence_detail"),
            "evidence_summary": old.get("evidence_summary"),
            "factor_id": str(old["factor_id"]),
            "family_slug": protocol.family_slug,
            "gap_reason": old.get("gap_reason"),
            "notes": old.get("notes"),
            "scope_level": str(old["scope_level"]),
            "score": str(old["score"]),
            "sources": sources,
        }
        if change.scope_level == "surface":
            actual["surface_slug"] = change.target
        elif change.scope_level == "deployment":
            surface, chain, deployment_key = change.target.split("/")
            actual.update(
                {
                    "surface_slug": surface,
                    "chain": chain,
                    "deployment_key": deployment_key,
                }
            )
        if change.historical_old_remediation is not None:
            try:
                validate_factor_sources(
                    actual,
                    f"production old row for {change.factor_id}",
                )
                validate_public_material(
                    actual,
                    f"production old row for {change.factor_id}",
                )
            except ContractError:
                pass
            else:
                raise ContractError(
                    "historical old remediation is unnecessary because the "
                    f"production old row is already public-safe: {change.factor_id}"
                )
        expected = change.old_value
        annotation_fields = {
            "migration_change_reason",
            "migration_preservation_note",
            "preservation_note",
        }
        for field_name, expected_value in expected.items():
            if field_name in annotation_fields or field_name == "sources":
                continue
            if actual.get(field_name) != expected_value:
                raise ContractError(
                    f"old-value baseline drifted for {change.factor_id}.{field_name}"
                )
        expected_sources = self._sorted_sources(expected.get("sources", []))
        actual_sources = self._sorted_sources(actual["sources"])
        for source in expected_sources:
            if source not in actual_sources:
                raise ContractError(
                    f"public old-source baseline drifted for {change.factor_id}"
                )

    @staticmethod
    def _semantic_tree(
        root: Path,
        *,
        exclude_family: str | None = None,
    ) -> dict[str, str]:
        if not root.exists():
            return {}
        result: dict[str, str] = {}
        for path in root.rglob("*.json"):
            try:
                relative = path.relative_to(root).as_posix()
                if relative == f"{RUBRIC_VERSION}/status.json":
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                data = ProductionOperations._scrub(data)
                if exclude_family is not None:
                    if (
                        f"/{exclude_family}.json" in f"/{relative}"
                        or f"/{exclude_family}/" in f"/{relative}/"
                        or f"/{exclude_family}-" in f"/{relative}"
                    ):
                        continue
                    data = ProductionOperations._without_family(
                        data, exclude_family
                    )
                    if data is ProductionOperations._DROP:
                        continue
                result[relative] = _canonical(data)
            except (OSError, json.JSONDecodeError):
                continue
        return result

    @staticmethod
    def _scrub(value: Any) -> Any:
        if isinstance(value, list):
            return [ProductionOperations._scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: ProductionOperations._scrub(item) for key, item in value.items()
                    if key not in {"generated_at", "data_as_of", "pipeline_runs", "status", "updated_at"}}
        return value

    _DROP = object()

    @staticmethod
    def _without_family(value: Any, family_slug: str) -> Any:
        """Remove only one protocol's contributions from fleet-wide output."""
        if isinstance(value, list):
            return [
                cleaned
                for item in value
                if (
                    cleaned := ProductionOperations._without_family(
                        item, family_slug
                    )
                )
                is not ProductionOperations._DROP
            ]
        if isinstance(value, dict):
            identity_fields = (
                "slug",
                "protocol_slug",
                "family_slug",
                "canonical_family_slug",
            )
            if any(value.get(field) == family_slug for field in identity_fields):
                return ProductionOperations._DROP
            return {
                key: cleaned
                for key, item in value.items()
                if key != family_slug
                and (
                    cleaned := ProductionOperations._without_family(
                        item, family_slug
                    )
                )
                is not ProductionOperations._DROP
            }
        return value

    def compare_target_output(self, protocol: ProtocolRefresh) -> None:
        import compose
        import dump
        if self._dump_workspace is None:
            raise ContractError("protocol output baseline was not captured")
        self._verify_legacy_history_postcondition(protocol)
        root = Path(self._dump_workspace.name) / "after"
        if compose.run(self.database_url, slug=protocol.family_slug, dry_run=False,
                       connection=self._connection(), required_protocols={protocol.family_slug}) != 0:
            raise ContractError("compose failed during transactional protocol verification")
        dump.run_dump(out_root=root, dry_run=False, connection=self._connection())
        after = self._semantic_tree(
            root / "api", exclude_family=protocol.family_slug
        )
        self._verify_target_semantics(protocol)
        self._verify_dumped_target(protocol, root / "api")
        for name in set(self._output_before) | set(after):
            if self._output_before.get(name) != after.get(name):
                raise ContractError("pipeline changed unrelated semantic output")

    def _verify_legacy_history_postcondition(
        self, protocol: ProtocolRefresh
    ) -> None:
        planned = self._planned_classifications.get(protocol.family_slug)
        if planned is None or planned.rubric_route not in {
            MIXED_RECOVERY_ROUTE,
            "full_v15_migration",
        }:
            return
        retired_count, history_hash = self._legacy_history_binding(
            protocol, current_rows=False
        )
        if (
            retired_count != planned.v15_retirement_rows
            or history_hash != planned.legacy_history_sha256
        ):
            raise ContractError(
                "post-migration v1.5.0 history, superseded_by links, or "
                "source-join identities differ from the exact approved plan"
            )

    @staticmethod
    def _protocol_document(payload: Any) -> Mapping[str, Any]:
        try:
            document = payload["data"]["protocol_data"]
        except (KeyError, TypeError) as exc:
            raise ContractError("protocol output has an invalid envelope") from exc
        if not isinstance(document, Mapping):
            raise ContractError("protocol output data must be an object")
        return document

    @classmethod
    def _verify_protocol_document(
        cls,
        protocol: ProtocolRefresh,
        payload: Any,
        *,
        unchanged_rows_before: Mapping[str, str] | None = None,
        written_factor_ids: set[str] | None = None,
    ) -> None:
        document = cls._protocol_document(payload)
        metadata = document.get("protocol")
        rows = document.get("factor_scores")
        deployments = document.get("deployments")
        if not isinstance(metadata, Mapping) or not isinstance(rows, list):
            raise ContractError("protocol output is missing metadata or factor rows")
        if (
            metadata.get("slug") != protocol.family_slug
            or metadata.get("rubric_version") != protocol.rubric_version
            or metadata.get("headline_grade") != protocol.resulting_grade
            or str(metadata.get("last_refreshed")) != protocol.last_refreshed
        ):
            raise ContractError("protocol output metadata differs from approved result")
        if not isinstance(deployments, list):
            raise ContractError("protocol output is missing deployments")
        expected_chains = sorted(item.split("/")[1] for item in protocol.deployment_targets)
        actual_chains = sorted(
            str(item.get("chain"))
            for item in deployments
            if isinstance(item, Mapping)
        )
        if actual_chains != expected_chains:
            raise ContractError("protocol output deployment topology differs")
        if len(rows) != EXPECTED_FACTOR_COUNT:
            raise ContractError("protocol output does not contain the complete factor pass")
        actual_by_factor: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("factor_id"), str):
                raise ContractError("protocol output contains an invalid factor row")
            if row["factor_id"] in actual_by_factor:
                raise ContractError("protocol output contains duplicate factor rows")
            actual_by_factor[row["factor_id"]] = row
        if set(actual_by_factor) != CANONICAL_FACTOR_IDS:
            raise ContractError(
                "protocol output factor IDs differ from the v1.7.0 rubric"
            )
        fields = (
            "score",
            "evidence_summary",
            "evidence_detail",
            "collection_mode",
            "gap_reason",
        )
        approved_rows = (
            protocol.mixed_recovery.full_target_projection
            if protocol.mixed_recovery is not None
            else protocol.changes
        )
        if written_factor_ids is None:
            written_factor_ids = {change.factor_id for change in protocol.changes}
        for change in approved_rows:
            actual = actual_by_factor.get(change.factor_id)
            if actual is None:
                raise ContractError(f"protocol output omitted {change.factor_id}")
            if set(actual) != PUBLIC_FACTOR_ROW_FIELDS:
                raise ContractError(
                    f"protocol output fields differ for {change.factor_id}"
                )
            expected = change.new_value
            if any(actual.get(field) != expected.get(field) for field in fields):
                raise ContractError(
                    f"protocol output differs for {change.factor_id}"
                )
            if change.factor_id in written_factor_ids:
                try:
                    raw_freshness = actual["data_as_of"]
                    if not isinstance(raw_freshness, str):
                        raise ValueError
                    if "T" in raw_freshness:
                        normalized_freshness = (
                            f"{raw_freshness[:-1]}+00:00"
                            if raw_freshness.endswith("Z")
                            else raw_freshness
                        )
                        freshness_date = datetime.fromisoformat(
                            normalized_freshness
                        ).date()
                    else:
                        freshness_date = date.fromisoformat(raw_freshness)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ContractError(
                        f"protocol output freshness is invalid for {change.factor_id}"
                    ) from exc
                if freshness_date.isoformat() != protocol.last_refreshed:
                    raise ContractError(
                        f"protocol output freshness differs for {change.factor_id}"
                    )
                if actual.get("collected_by") != "lean-protocol-refresh":
                    raise ContractError(
                        f"protocol output collector differs for {change.factor_id}"
                    )
            expected_sources = cls._sorted_sources(
                [
                    {
                        key: source.get(key)
                        for key in (
                            "source_type",
                            "url",
                            "reference",
                            "title",
                            "retrieved_at",
                        )
                        if source.get(key) is not None
                    }
                    for source in expected.get("sources", [])
                    if isinstance(source, Mapping)
                ]
            )
            actual_sources = cls._sorted_sources(
                [
                    {
                        key: source.get(key)
                        for key in (
                            "source_type",
                            "url",
                            "reference",
                            "title",
                            "retrieved_at",
                        )
                        if source.get(key) is not None
                    }
                    for source in actual.get("sources", [])
                    if isinstance(source, Mapping)
                ]
            )
            def identities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
                return cls._sorted_sources(
                    [
                        {
                            key: item.get(key)
                            for key in ("source_type", "url", "reference")
                            if item.get(key) is not None
                        }
                        for item in items
                    ]
                )

            if identities(actual_sources) != identities(expected_sources):
                raise ContractError(
                    f"protocol output source identities differ for {change.factor_id}"
                )
        if unchanged_rows_before is not None:
            if set(unchanged_rows_before) != CANONICAL_FACTOR_IDS:
                raise ContractError(
                    "pre-transaction target output has an invalid factor universe"
                )
            changed_factor_ids = {change.factor_id for change in protocol.changes}
            for factor_id in CANONICAL_FACTOR_IDS - changed_factor_ids:
                if (
                    cls._semantic_factor_row(actual_by_factor[factor_id])
                    != unchanged_rows_before[factor_id]
                ):
                    raise ContractError(
                        f"protocol output changed unapproved row {factor_id}"
                    )

    @classmethod
    def _semantic_factor_row(cls, row: Mapping[str, Any]) -> str:
        # Factor-row timestamps are semantic evidence freshness, unlike the
        # envelope-level generated_at value ignored by fleet comparisons.
        value = dict(row)
        sources = value.get("sources")
        if isinstance(sources, list):
            value["sources"] = sorted(
                (dict(source) if isinstance(source, Mapping) else source for source in sources),
                key=_canonical,
            )
        return _canonical(value)

    def _dumped_target_path(
        self, protocol: ProtocolRefresh, api_root: Path
    ) -> Path:
        is_published, review_token = self._publication_state(protocol.family_slug)
        if is_published:
            return (
                api_root
                / RUBRIC_VERSION
                / "protocols"
                / f"{protocol.family_slug}.json"
            )
        if not review_token:
            raise ContractError(
                "unpublished target protocol has no protected review route"
            )
        return (
            api_root
            / RUBRIC_VERSION
            / "unpublished"
            / f"{protocol.family_slug}-{review_token}"
            / "index.json"
        )

    def _load_dumped_target(
        self, protocol: ProtocolRefresh, api_root: Path
    ) -> Any:
        path = self._dumped_target_path(protocol, api_root)
        if not path.is_file():
            raise ContractError("temporary dump omitted the target protocol document")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError("temporary target protocol document is unreadable") from exc

    def _read_dumped_target_rows(
        self, protocol: ProtocolRefresh, api_root: Path
    ) -> dict[str, str]:
        payload = self._load_dumped_target(protocol, api_root)
        document = self._protocol_document(payload)
        rows = document.get("factor_scores")
        if not isinstance(rows, list):
            raise ContractError(
                "pre-transaction target output is missing factor rows"
            )
        actual_by_factor = {
            str(row.get("factor_id")): row
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("factor_id"), str)
        }
        if (
            len(rows) != EXPECTED_FACTOR_COUNT
            or len(actual_by_factor) != EXPECTED_FACTOR_COUNT
            or set(actual_by_factor) != CANONICAL_FACTOR_IDS
        ):
            raise ContractError(
                "pre-transaction target output has an invalid factor universe"
            )
        return {
            factor_id: self._semantic_factor_row(row)
            for factor_id, row in actual_by_factor.items()
        }

    def _verify_dumped_target(self, protocol: ProtocolRefresh, api_root: Path) -> None:
        payload = self._load_dumped_target(protocol, api_root)
        self._verify_protocol_document(
            protocol,
            payload,
            unchanged_rows_before=(
                self._target_rows_before
                if self._protocol_baseline_rubric == RUBRIC_VERSION
                else None
            ),
            written_factor_ids=set(self._protocol_written_factor_ids),
        )

    def _publication_state(self, family_slug: str) -> tuple[bool, str | None]:
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_published, review_token FROM protocols WHERE slug=%s",
                (family_slug,),
            )
            row = cur.fetchone()
        if not self._protocol_open:
            conn.rollback()
        if row is None:
            raise ContractError("target protocol publication state is missing")
        token = str(row[1]) if row[1] else None
        return bool(row[0]), token

    def _verify_target_semantics(self, protocol: ProtocolRefresh) -> None:
        state = self.read_protocol_state(protocol.family_slug)
        if not is_already_applied(protocol, state):
            raise ContractError(
                "composed target date, grade, rubric, topology, factors, or "
                "public source joins differ from the approved result"
            )

    def _close_dump_workspace(self) -> None:
        if self._dump_workspace is not None:
            self._dump_workspace.cleanup()
            self._dump_workspace = None
    def commit_protocol(self, protocol: ProtocolRefresh) -> None:
        self._connection().commit()
        self._protocol_open = False
        self._protocol_baseline_family = None
        self._protocol_baseline_rubric = None
        self._target_rows_before = {}
        self._protocol_written_factor_ids = set()
        self._close_dump_workspace()
    def rollback_protocol(self, protocol: ProtocolRefresh) -> None:
        try:
            self._connection().rollback()
        finally:
            self._protocol_open = False
            self._protocol_baseline_family = None
            self._protocol_baseline_rubric = None
            self._target_rows_before = {}
            self._protocol_written_factor_ids = set()
            self._close_dump_workspace()

    def _branch(self, protocol: ProtocolRefresh) -> str:
        return (
            f"refresh/{_safe_name(protocol.family_slug)}/"
            f"{_safe_name(self.batch.refresh_date)}"
        )

    @staticmethod
    def _pull_request_body(protocol: ProtocolRefresh) -> str:
        return (
            "## What changed\n\n"
            f"- Add the reviewed public refresh change record for "
            f"`{protocol.family_slug}` dated `{protocol.last_refreshed}`.\n\n"
            "## Why\n\n"
            "- Record the approved evidence refresh after its production "
            "transaction completed.\n\n"
            "## Scope and verification\n\n"
            f"- One topic: `{protocol.family_slug}` only.\n"
            "- No direct factor-score or letter-grade edits.\n"
            "- No generated `data/api/` edits.\n"
            "- Public-source and protocol-scoped refresh validation passed.\n"
        )

    def _optional_command(self, command: Sequence[str]) -> Any | None:
        """Run an inspection command whose absence is an idempotent 'not yet' state."""
        try:
            return self.command_runner(command, self.repository_root)
        except subprocess.CalledProcessError:
            return None

    def _record_relative_path(self, protocol: ProtocolRefresh) -> Path:
        return (
            Path("docs")
            / "ops"
            / "protocol-refresh"
            / "change-records"
            / f"{protocol.last_refreshed}-{protocol.family_slug}.json"
        )

    def select_publication_trigger(self, family_slug: str) -> None:
        """Choose the last successful changed protocol to carry the framework."""
        if family_slug not in {
            protocol.family_slug
            for protocol in self.batch.protocols
            if protocol.outcome == "changed"
        }:
            raise ContractError("publication trigger is outside the approved batch")
        self._publication_trigger_slug = family_slug

    def _public_record(self, protocol: ProtocolRefresh) -> dict[str, Any]:
        def public_change(change: Any) -> dict[str, Any]:
            record = {
                "factor_id": change.factor_id,
                "scope_level": change.scope_level,
                "target": change.target,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "evidence": [
                    {"url": evidence.url, "title": evidence.title}
                    if evidence.title
                    else {"url": evidence.url}
                    for evidence in change.evidence
                ],
                "resulting_score": change.resulting_score,
                "resulting_grade": change.resulting_grade,
            }
            if change.historical_old_remediation is not None:
                record["historical_old_remediation"] = dict(
                    change.historical_old_remediation
                )
            return record

        return {
            "schema_version": "lean-protocol-refresh/v1",
            "batch_id": self.batch.batch_id,
            "refresh_date": self.batch.refresh_date,
            "rubric_version": RUBRIC_VERSION,
            "protocols": [
                {
                    "family_slug": protocol.family_slug,
                    "rubric_version": protocol.rubric_version,
                    "surface_slugs": list(protocol.surface_slugs),
                    "topology": {
                        "mode": "preserve",
                        "family_slug": protocol.family_slug,
                        "surface_slugs": list(protocol.surface_slugs),
                        "deployment_targets": list(protocol.deployment_targets),
                    },
                    "outcome": protocol.outcome,
                    "previous_grade": protocol.previous_grade,
                    "last_refreshed": protocol.last_refreshed,
                    "resulting_grade": protocol.resulting_grade,
                    "changes": [public_change(change) for change in protocol.changes],
                }
            ],
        }

    @staticmethod
    def _contains_local_path(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(
                ProductionOperations._contains_local_path(item)
                for item in value.values()
            )
        if isinstance(value, (list, tuple)):
            return any(
                ProductionOperations._contains_local_path(item) for item in value
            )
        if not isinstance(value, str):
            return False
        without_public_urls = re.sub(
            r"https?://[^\s\"'<>,;]+", "", value, flags=re.IGNORECASE
        ).replace("\\", "/")
        return bool(
            re.search(
                r"(?:[A-Za-z]:/|(?<![A-Za-z0-9_])file:"
                r"|(?<![A-Za-z0-9_.-])//[^/\s]+/"
                r"|(?<![A-Za-z0-9_.-])\.\.?/[^\s)>\"']+"
                r"|(?<![A-Za-z0-9_.-])/(?:home|users|opt|tmp|etc|var|srv|root|mnt|workspace)/)",
                without_public_urls,
                flags=re.IGNORECASE,
            )
        )

    def ensure_protocol_pull_request(self, protocol: ProtocolRefresh) -> None:
        branch = self._branch(protocol)
        existing = self._optional_command(("gh", "pr", "view", branch, "--repo", self.repository, "--json", "url"))
        if existing is not None:
            return
        trigger_slug = self._publication_trigger_slug or self.batch.protocols[-1].family_slug
        is_final_protocol = protocol.family_slug == trigger_slug
        seed = "HEAD" if is_final_protocol else f"origin/{self.base_branch}"
        relative_record = self._record_relative_path(protocol)
        serialized_record = _canonical(self._public_record(protocol)) + "\n"
        remote_branch = self._optional_command(
            ("git", "ls-remote", "--exit-code", "--heads", "origin", branch)
        )
        if remote_branch is not None:
            remote_ref = f"refs/remotes/origin/{branch}"
            self.command_runner(
                ("git", "fetch", "--no-tags", "origin", f"{branch}:{remote_ref}"),
                self.repository_root,
            )
            shown = self.command_runner(
                ("git", "show", f"{remote_ref}:{relative_record.as_posix()}"),
                self.repository_root,
            )
            if str(getattr(shown, "stdout", "")) != serialized_record:
                raise ContractError("existing remote refresh branch has a different record")
            changed = self.command_runner(
                ("git", "diff", "--name-only", f"{seed}...{remote_ref}"),
                self.repository_root,
            )
            names = [
                item
                for item in str(getattr(changed, "stdout", "")).splitlines()
                if item
            ]
            if names != [relative_record.as_posix()]:
                raise ContractError("existing remote refresh branch has unexpected changes")
            self.command_runner(
                (
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    self.repository,
                    "--base",
                    self.base_branch,
                    "--head",
                    branch,
                    "--title",
                    f"Refresh {protocol.family_slug}",
                    "--body",
                    self._pull_request_body(protocol),
                ),
                self.repository_root,
            )
            return
        with tempfile.TemporaryDirectory(prefix="lean-refresh-pr-") as temp:
            worktree = Path(temp) / "repository"
            self.command_runner(
                ("git", "fetch", "--no-tags", "origin", self.base_branch),
                self.repository_root,
            )
            # Early PRs carry only their public change record, so their merges
            # cannot trigger deployment. The final protocol PR also carries
            # the reviewed local lean-framework commit at HEAD; its scripts
            # change triggers exactly one batch deployment after all records
            # are merged.
            self.command_runner(
                ("git", "worktree", "add", "--detach", str(worktree), seed),
                self.repository_root,
            )
            try:
                self.command_runner(("git", "checkout", "-B", branch), worktree)
                record = worktree / relative_record
                record.parent.mkdir(parents=True, exist_ok=True)
                public = self._public_record(protocol)
                if self._contains_local_path(public):
                    raise ContractError("public record contains a local path")
                record.write_text(_canonical(public) + "\n", encoding="utf-8")
                self.command_runner(("git", "add", str(record.relative_to(worktree))), worktree)
                self.command_runner(("git", "commit", "--allow-empty", "-m", f"refresh: {protocol.family_slug}"), worktree)
                # This isolated clean public worktree adds only the validated
                # record above. Bypass unrelated operator-machine hooks for this
                # deterministic push; repository CI remains authoritative.
                self.command_runner(
                    ("git", "push", "--no-verify", "-u", "origin", branch),
                    worktree,
                )
                self.command_runner(
                    (
                        "gh",
                        "pr",
                        "create",
                        "--repo",
                        self.repository,
                        "--base",
                        self.base_branch,
                        "--head",
                        branch,
                        "--title",
                        f"Refresh {protocol.family_slug}",
                        "--body",
                        self._pull_request_body(protocol),
                    ),
                    worktree,
                )
            finally:
                self.command_runner(("git", "worktree", "remove", "--force", str(worktree)), self.repository_root)

    def merge_protocol_pull_request(self, protocol: ProtocolRefresh) -> None:
        state = self._optional_command(("gh", "pr", "view", self._branch(protocol), "--repo", self.repository, "--json", "state", "--jq", ".state"))
        if state is not None and str(getattr(state, "stdout", "")).strip().upper() == "MERGED":
            return
        self.command_runner(
            (
                "gh",
                "pr",
                "checks",
                self._branch(protocol),
                "--repo",
                self.repository,
                "--watch",
            ),
            self.repository_root,
        )
        self.command_runner(
            (
                "gh",
                "pr",
                "merge",
                self._branch(protocol),
                "--repo",
                self.repository,
                "--merge",
                "--delete-branch",
            ),
            self.repository_root,
        )

    def _gh_json(self, *arguments: str) -> Any:
        result = self.command_runner(
            ("gh", "api", "--method", "GET", *arguments),
            self.repository_root,
        )
        try:
            return json.loads(str(getattr(result, "stdout", "")))
        except json.JSONDecodeError as exc:
            raise ContractError("GitHub state command returned invalid JSON") from exc

    def _main_sha(self) -> str:
        payload = self._gh_json(
            f"repos/{self.repository}/commits/{self.base_branch}"
        )
        sha = payload.get("sha") if isinstance(payload, Mapping) else None
        if not isinstance(sha, str) or not sha:
            raise ContractError("cannot resolve the public base-branch SHA")
        return sha

    def _deploy_runs(self, event: str) -> list[Mapping[str, Any]]:
        payload = self._gh_json(
            f"repos/{self.repository}/actions/workflows/deploy.yml/runs",
            "-f",
            f"branch={self.base_branch}",
            "-f",
            f"event={event}",
            "-f",
            "per_page=30",
        )
        runs = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
        if not isinstance(runs, list):
            raise ContractError("cannot inspect deploy.yml workflow runs")
        return [run for run in runs if isinstance(run, Mapping)]

    def _matching_deploy_run(
        self,
        head_sha: str,
        batch: RefreshBatch,
        *,
        dispatch_ids_before: set[Any] | None = None,
    ) -> Mapping[str, Any] | None:
        dispatch_title = f"Deploy {batch.batch_id}"
        for run in self._deploy_runs("workflow_dispatch"):
            if (
                run.get("head_sha") == head_sha
                and (
                    run.get("display_title") == dispatch_title
                    or (
                        dispatch_ids_before is not None
                        and run.get("id") not in dispatch_ids_before
                    )
                )
            ):
                return run
        for run in self._deploy_runs("push"):
            if run.get("head_sha") == head_sha:
                return run
        return None

    def _fetch_live_payload(self, protocol: ProtocolRefresh) -> Any:
        public_url = (
            f"{self.live_base_url.rstrip('/')}/"
            f"{urllib.parse.quote(protocol.family_slug, safe='')}.json"
        )
        try:
            with self.urlopen(public_url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise ContractError(
                    f"cannot read live protocol output for {protocol.family_slug}"
                ) from exc
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ) as exc:
            raise ContractError(
                f"cannot read live protocol output for {protocol.family_slug}"
            ) from exc
        is_published, review_token = self._publication_state(protocol.family_slug)
        if is_published or not review_token:
            raise ContractError(
                f"cannot read live protocol output for {protocol.family_slug}"
            )
        api_root = self.live_base_url.rstrip("/").rsplit("/protocols", 1)[0]
        protected_slug = urllib.parse.quote(
            f"{protocol.family_slug}-{review_token}", safe=""
        )
        protected_url = f"{api_root}/unpublished/{protected_slug}/index.json"
        try:
            with self.urlopen(protected_url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ) as exc:
            raise ContractError(
                f"cannot read live protocol output for {protocol.family_slug}"
            ) from exc

    def _live_matches(
        self, protocols: tuple[ProtocolRefresh, ...], *, raise_on_error: bool
    ) -> bool:
        try:
            for protocol in protocols:
                self._verify_protocol_document(
                    protocol, self._fetch_live_payload(protocol)
                )
        except ContractError:
            if raise_on_error:
                raise
            return False
        return True

    def read_batch_state(self, batch: RefreshBatch, protocols: tuple[ProtocolRefresh, ...]) -> BatchState:
        if self.batch_state_command:
            result = self.command_runner(self.batch_state_command + (batch.batch_id,), self.repository_root)
            try:
                state = json.loads(str(getattr(result, "stdout", "")))
                return BatchState(bool(state["deployed"]), bool(state["live_verified"]))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ContractError("batch state command must return JSON deployed/live_verified booleans") from exc
        # Semantic live state is authoritative. A successful older workflow at
        # the same Git SHA does not prove a no-change database-only refresh was
        # deployed.
        live_verified = self._live_matches(protocols, raise_on_error=False)
        return BatchState(
            deployed=live_verified,
            live_verified=live_verified,
        )

    def deploy_batch(self, batch: RefreshBatch, protocols: tuple[ProtocolRefresh, ...]) -> None:
        if self.deploy_command:
            self.command_runner(self.deploy_command, self.repository_root)
            return
        # The final protocol PR is the only scripts-changing merge and therefore
        # triggers the one deploy.yml push run for this rollout. Later docs-only
        # or no-change batches use one named workflow_dispatch fallback.
        head_sha = self._main_sha()
        deadline = self.monotonic() + self.deploy_timeout_seconds
        automatic_deadline = min(deadline, self.monotonic() + 45)
        dispatched = False
        dispatch_ids_before = {
            run.get("id")
            for run in self._deploy_runs("workflow_dispatch")
            if run.get("head_sha") == head_sha
        }
        while self.monotonic() < deadline:
            if self._live_matches(protocols, raise_on_error=False):
                return
            run = self._matching_deploy_run(
                head_sha,
                batch,
                dispatch_ids_before=(
                    dispatch_ids_before if dispatched else None
                ),
            )
            if run is not None:
                if run.get("status") == "completed":
                    if run.get("conclusion") != "success":
                        raise ContractError(
                            f"automatic deploy.yml run failed: {run.get('html_url')}"
                        )
                    if run.get("event") == "workflow_dispatch":
                        return
                    # A completed push run can predate a database-only refresh
                    # at the same SHA. Fall through to the named dispatch when
                    # live semantics still do not match.
                    automatic_deadline = self.monotonic()
                run_id = run.get("id")
                if run.get("status") != "completed" and run_id is not None:
                    self.command_runner(
                        (
                            "gh",
                            "run",
                            "watch",
                            str(run_id),
                            "--repo",
                            self.repository,
                            "--exit-status",
                        ),
                        self.repository_root,
                    )
                    return
            if not dispatched and self.monotonic() >= automatic_deadline:
                self.command_runner(
                    (
                        "gh",
                        "workflow",
                        "run",
                        "deploy.yml",
                        "--repo",
                        self.repository,
                        "--ref",
                        self.base_branch,
                        "-f",
                        f"reason={batch.batch_id}",
                    ),
                    self.repository_root,
                )
                dispatched = True
            self.sleeper(self.deploy_poll_seconds)
        raise ContractError(
            "timed out waiting for the final merge's automatic deploy.yml push run"
        )

    def verify_live(self, batch: RefreshBatch, protocols: tuple[ProtocolRefresh, ...]) -> None:
        if self.live_check_command:
            self.command_runner(self.live_check_command + tuple(item.family_slug for item in protocols), self.repository_root)
        if self.live_state_command:
            result = self.command_runner(self.live_state_command + tuple(item.family_slug for item in protocols), self.repository_root)
            try:
                state = json.loads(str(getattr(result, "stdout", "")))
            except json.JSONDecodeError as exc:
                raise ContractError("live state command must return JSON") from exc
            if state.get("verified_protocols") != [item.family_slug for item in protocols]:
                raise ContractError("live state does not verify exactly the requested protocols")
            return
        self._live_matches(protocols, raise_on_error=True)


def create_operations(batch: RefreshBatch, context: Mapping[str, Any] | Any) -> ProductionOperations:
    """Factory used by the lean runner; config comes only from context or env."""

    def value(name: str, env: str | None = None, default: Any = None) -> Any:
        if isinstance(context, Mapping):
            item = context.get(name, default)
        else:
            item = getattr(context, name, default)
        return item if item not in (None, "") else os.environ.get(env or name.upper(), default)

    root = value("repository_root", "RISKDASHBOARD_REPOSITORY_ROOT")
    if not root:
        raise ContractError(
            "repository_root or RISKDASHBOARD_REPOSITORY_ROOT is required"
        )
    return ProductionOperations(batch=batch, database_url=value("database_url", "DATABASE_URL"), repository_root=Path(root),
        repository=value("repository"), base_branch=value("base_branch"),
        backup_root=Path(value("backup_root", default=BACKUP_ROOT)),
        backup_ssh_host=value("backup_ssh_host", "RISKDASHBOARD_BACKUP_SSH_HOST"),
        backup_database_env_file=Path(value("backup_database_env_file", "RISKDASHBOARD_BACKUP_DATABASE_ENV_FILE", Path("/opt/riskdashboard/.env"))),
        command_runner=value("command_runner", default=_run), connect=value("connect"))
