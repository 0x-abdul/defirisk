#!/usr/bin/env python3
"""Fail-closed checks for the public code-and-data repository boundary."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlsplit


CURRENT_VERSION = "v1.7.0"
MANIFEST_RELATIVE = Path("data/api/MANIFEST.sha256")
BASELINE_RELATIVE = Path("data/api/publication-baseline.json")
FIELD_REGISTRY_RELATIVE = Path("data/api/public-field-classification.json")

PROHIBITED_PREFIXES = (
    ".research/",
    ".private/",
    "db/",
    "docs/ops/",
    "receipts/",
    "release-manifests/",
)
PROHIBITED_EXACT_PATHS = {
    ".github/workflows/backup-r2.yml",
    ".github/workflows/deploy.yml",
    ".github/workflows/history-prune.yml",
    ".github/workflows/ingest.yml",
    ".github/workflows/ingest-events.yml",
    ".github/workflows/protocol-refresh-foundation.yml",
    "scripts/backup-to-r2.py",
    "scripts/ci/deploy-vps-safe.sh",
    "scripts/ci/sync-vps-checkout.sh",
    "scripts/compose.py",
    "scripts/dump.py",
    "scripts/import-protocol-assessment.py",
    "scripts/apply-lean-protocol-refresh.py",
    "scripts/lean_protocol_refresh/execution.py",
    "scripts/lean_protocol_refresh/planning.py",
    "scripts/lean_protocol_refresh/production.py",
    "scripts/set_published.py",
}
PROHIBITED_API_KEYS = {
    "approval",
    "approval_identity",
    "approval_receipt",
    "backup_path",
    "database_id",
    "database_row_id",
    "deployment_receipt",
    "internal_path",
    "private_url",
    "receipt",
    "review_token",
    "review_url",
    "reviewer",
    "rollback_reference",
    "signature",
    "specialist",
    "transaction_id",
}
OPERATIONAL_STATUS_KEYS = {
    "availability_health",
    "bucket_freshness",
    "days_stale",
    "deployment_health",
    "duration_seconds",
    "error_count",
    "error_summary",
    "fleet_freshness",
    "live_incident_banner",
    "monitoring_state",
    "pipeline_runs",
    "runs",
    "success_count",
}
RAW_DATABASE_TIMESTAMP_KEYS = {"created_at", "updated_at"}
PRIVATE_ROUTE = re.compile(r"/(?:api/[^/]+/)?unpublished(?:/|$)", re.IGNORECASE)
PUBLIC_SOURCE_FIELDS = {
    "source_type",
    "url",
    "retrieved_at",
}
PROHIBITED_URL_QUERY_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "key",
    "review_token",
    "signature",
    "token",
}
PROHIBITED_SOURCE_TYPES = {"curator_note", "internal", "partner_feed", "private"}
PUBLIC_SOURCE_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class BoundaryError(ValueError):
    """The selected tree violates the public repository boundary."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoundaryError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BoundaryError(f"JSON object required: {path}")
    return value


def json_leaf_pointers(value: Any, pointer: str = "") -> set[str]:
    if isinstance(value, dict):
        result: set[str] = set()
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            result.update(json_leaf_pointers(child, f"{pointer}/{escaped}"))
        return result
    if isinstance(value, list):
        result = set()
        for index, child in enumerate(value):
            result.update(json_leaf_pointers(child, f"{pointer}/{index}"))
        return result
    return {pointer or "/"}


def scan_api_value(value: Any, source: str, pointer: str = "") -> list[str]:
    failures: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            child_pointer = f"{pointer}/{key}"
            if normalized in PROHIBITED_API_KEYS:
                failures.append(f"{source}{child_pointer}: prohibited private field")
            if normalized in OPERATIONAL_STATUS_KEYS:
                failures.append(f"{source}{child_pointer}: live telemetry field is not versioned API data")
            if normalized in RAW_DATABASE_TIMESTAMP_KEYS:
                failures.append(f"{source}{child_pointer}: raw database timestamp is prohibited")
            if normalized == "is_published" and child is not True:
                failures.append(f"{source}{child_pointer}: only published protocol data is allowed")
            failures.extend(scan_api_value(child, source, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            failures.extend(scan_api_value(child, source, f"{pointer}/{index}"))
    elif isinstance(value, str) and PRIVATE_ROUTE.search(value):
        failures.append(f"{source}{pointer}: private review route is prohibited")
    return failures


def public_source_url_is_safe(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or host.casefold() in {"localhost", "localhost.localdomain"}
            or host.casefold().endswith((".internal", ".local", ".localhost"))
        ):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                return False
        query_keys = {key.casefold() for key, _value in parse_qsl(parsed.query)}
        return not (query_keys & PROHIBITED_URL_QUERY_KEYS)
    except ValueError:
        return False


def validate_protocol_citations(detail: dict[str, Any], source: str) -> list[str]:
    failures: list[str] = []
    factors = detail.get("data", {}).get("protocol_data", {}).get("factor_scores")
    if not isinstance(factors, list):
        return [f"{source}: data.protocol_data.factor_scores must be an array"]
    seen: set[str] = set()
    for index, factor in enumerate(factors):
        pointer = f"{source}/data/protocol_data/factor_scores/{index}"
        if not isinstance(factor, dict):
            failures.append(f"{pointer}: factor score must be an object")
            continue
        factor_id = factor.get("factor_id")
        if not isinstance(factor_id, str) or not factor_id or factor_id in seen:
            failures.append(f"{pointer}: factor_id must be non-empty and unique")
        else:
            seen.add(factor_id)
        if not isinstance(factor.get("evidence_summary"), str) or not factor[
            "evidence_summary"
        ].strip():
            failures.append(f"{pointer}: evidence_summary is required")
        sources = factor.get("sources")
        if not isinstance(sources, list):
            failures.append(f"{pointer}: sources must be an array")
            continue
        if factor.get("score") != "not_assessed" and not sources:
            failures.append(f"{pointer}: assessed factor requires a public citation")
        for source_index, citation in enumerate(sources):
            citation_pointer = f"{pointer}/sources/{source_index}"
            if (
                not isinstance(citation, dict)
                or not set(citation).issubset(PUBLIC_SOURCE_FIELDS)
                or not isinstance(citation.get("source_type"), str)
                or not citation["source_type"].strip()
                or not PUBLIC_SOURCE_TYPE.fullmatch(citation["source_type"])
                or citation["source_type"].casefold() in PROHIBITED_SOURCE_TYPES
            ):
                failures.append(
                    f"{citation_pointer}: citation shape is not public-safe"
                )
                continue
            url = citation.get("url")
            if not isinstance(url, str) or not url.strip():
                failures.append(
                    f"{citation_pointer}: citation needs a public HTTPS URL"
                )
            elif not public_source_url_is_safe(url):
                failures.append(f"{citation_pointer}: citation URL is not public-safe")
            retrieved_at = citation.get("retrieved_at")
            if retrieved_at is not None and (
                not isinstance(retrieved_at, str)
                or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?",
                    retrieved_at,
                )
            ):
                failures.append(
                    f"{citation_pointer}: citation retrieved_at is invalid"
                )
    return failures


def slug_digest(slugs: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(slugs)).encode("utf-8")).hexdigest()


def file_manifest(root: Path) -> str:
    api_root = root / "data" / "api"
    rows: list[str] = []
    for path in sorted(api_root.rglob("*")):
        if not path.is_file() or path == root / MANIFEST_RELATIVE:
            continue
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        if b"\x00" not in content:
            content = content.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(content).hexdigest()
        rows.append(f"{digest}  {relative}")
    return "\n".join(rows) + "\n"


def validate_manifest(root: Path) -> list[str]:
    expected_path = root / MANIFEST_RELATIVE
    if not expected_path.is_file():
        return [f"{MANIFEST_RELATIVE.as_posix()}: missing"]
    expected = expected_path.read_text(encoding="utf-8")
    actual = file_manifest(root)
    if expected != actual:
        return [f"{MANIFEST_RELATIVE.as_posix()}: does not match committed data/api tree"]
    return []


def validate_status_registry(root: Path) -> list[str]:
    failures: list[str] = []
    registry = load_json(root / FIELD_REGISTRY_RELATIVE)
    configured = registry.get("versioned_assessment_status", {}).get("leaf_json_pointers")
    if not isinstance(configured, list) or not all(isinstance(row, str) for row in configured):
        return [f"{FIELD_REGISTRY_RELATIVE.as_posix()}: invalid status pointer registry"]
    expected = set(configured)
    families = registry.get("versioned_assessment_field_families", {})
    versioned_fields = families.get("json_field_names")
    raw_fields = families.get("raw_database_fields_prohibited")
    telemetry_fields = registry.get("live_operational_telemetry", {}).get("json_field_names")
    if not isinstance(versioned_fields, list) or set(versioned_fields) != {
        "rubric_version",
        "data_as_of",
        "generated_at",
        "graded_at",
        "retrieved_at",
        "collected_at",
        "assessment_timestamp",
        "projection_timestamp",
        "history_timestamp",
        "effective_at",
        "recorded_at",
        "changed_at",
        "added_at",
        "status",
        "incident_state",
        "has_active_incident",
    }:
        failures.append(f"{FIELD_REGISTRY_RELATIVE.as_posix()}: incomplete versioned field classification")
    if not isinstance(raw_fields, list) or set(raw_fields) != RAW_DATABASE_TIMESTAMP_KEYS:
        failures.append(f"{FIELD_REGISTRY_RELATIVE.as_posix()}: incomplete raw timestamp prohibition")
    if not isinstance(telemetry_fields, list) or set(telemetry_fields) != OPERATIONAL_STATUS_KEYS:
        failures.append(f"{FIELD_REGISTRY_RELATIVE.as_posix()}: incomplete telemetry classification")
    for status_path in sorted((root / "data" / "api").glob("v*/status.json")):
        actual = json_leaf_pointers(load_json(status_path))
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            failures.append(
                f"{status_path.relative_to(root).as_posix()}: status classification mismatch "
                f"(missing={missing}, unexpected={unexpected})"
            )
    return failures


def validate_api_version(root: Path, version_root: Path) -> list[str]:
    failures: list[str] = []
    relative_root = version_root.relative_to(root).as_posix()
    if (version_root / "unpublished").exists():
        failures.append(f"{relative_root}/unpublished: private review subtree is prohibited")

    index = load_json(version_root / "index.json")
    rows = index.get("data", {}).get("protocols")
    if not isinstance(rows, list):
        return [f"{relative_root}/index.json: data.protocols must be an array"]
    slugs = [row.get("slug") for row in rows if isinstance(row, dict)]
    if len(slugs) != len(rows) or not all(isinstance(slug, str) and slug for slug in slugs):
        failures.append(f"{relative_root}/index.json: every protocol needs a stable slug")
    if len(set(slugs)) != len(slugs):
        failures.append(f"{relative_root}/index.json: duplicate protocol slug")

    protocol_root = version_root / "protocols"
    detail_paths = set(protocol_root.glob("*.json")) if protocol_root.is_dir() else set()
    expected_paths = {protocol_root / f"{slug}.json" for slug in slugs}
    nested_paths = (
        {path for path in protocol_root.rglob("*") if path.is_file()} - detail_paths
        if protocol_root.is_dir()
        else set()
    )
    if detail_paths != expected_paths or nested_paths:
        failures.append(f"{relative_root}/protocols: detail files must match the published index exactly")
    for detail_path in sorted(expected_paths):
        if detail_path.is_file():
            failures.extend(
                validate_protocol_citations(
                    load_json(detail_path), detail_path.relative_to(root).as_posix()
                )
            )

    published = set(slugs)
    for factor_path in sorted((version_root / "factors").glob("*.json")):
        factor = load_json(factor_path)
        scored = factor.get("data", {}).get("factor_data", {}).get("scored_protocols")
        if not isinstance(scored, list):
            failures.append(f"{factor_path.relative_to(root).as_posix()}: scored_protocols must be an array")
            continue
        for row in scored:
            slug = row.get("protocol_slug") if isinstance(row, dict) else None
            if slug and slug not in published:
                failures.append(
                    f"{factor_path.relative_to(root).as_posix()}: score exposes non-published slug"
                )

    for filename, key in (
        ("history.json", "history"),
        ("changes.json", "changes"),
        ("incidents.json", "incidents"),
    ):
        envelope = load_json(version_root / filename)
        values = envelope.get("data", {}).get(key)
        if not isinstance(values, list):
            failures.append(f"{relative_root}/{filename}: data.{key} must be an array")
            continue
        for row in values:
            slug = row.get("protocol_slug") if isinstance(row, dict) else None
            if slug and slug not in published:
                failures.append(f"{relative_root}/{filename}: exposes non-published protocol")
    return failures


def validate_tree(root: Path, *, check_manifest: bool = True) -> list[str]:
    root = root.resolve()
    failures: list[str] = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            failures.append(f"{relative}: symlinks are prohibited in the public tree")
        if any(relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in PROHIBITED_PREFIXES):
            failures.append(f"{relative}: private path is prohibited")
        if relative in PROHIBITED_EXACT_PATHS:
            failures.append(f"{relative}: retired control-plane path is prohibited")
        if "/unpublished/" in f"/{relative}/" or relative.endswith("/unpublished"):
            failures.append(f"{relative}: unpublished path is prohibited")

    api_root = root / "data" / "api"
    versions = sorted(path for path in api_root.glob("v*") if path.is_dir())
    if not versions:
        failures.append("data/api: no versioned public API trees found")
    for version_root in versions:
        failures.extend(validate_api_version(root, version_root))

    baseline = load_json(root / BASELINE_RELATIVE)
    current_version = baseline.get("current_api_version")
    expected = baseline.get("published_protocols", {})
    current_index = load_json(api_root / str(current_version) / "index.json")
    current_rows = current_index.get("data", {}).get("protocols", [])
    current_slugs = [row.get("slug") for row in current_rows if isinstance(row, dict)]
    if expected.get("count") != len(current_slugs):
        failures.append(f"{BASELINE_RELATIVE.as_posix()}: published count mismatch")
    if expected.get("slug_sha256") != slug_digest(current_slugs):
        failures.append(f"{BASELINE_RELATIVE.as_posix()}: published slug digest mismatch")

    for json_path in sorted(api_root.rglob("*.json")):
        relative = json_path.relative_to(root).as_posix()
        failures.extend(scan_api_value(load_json(json_path), relative))

    failures.extend(validate_status_registry(root))
    if check_manifest:
        failures.extend(validate_manifest(root))
    return sorted(set(failures))
