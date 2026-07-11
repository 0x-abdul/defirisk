"""Pure contracts for scoped production protocol-refresh application.

The four public receipt helpers in this module are stable integration APIs:

``validate_backup_receipt`` / ``load_backup_receipt``
    Validate backup identity, integrity metadata, restore instructions, and
    successful restore-test evidence.

``validate_production_authorization_receipt`` /
``load_production_authorization_receipt``
    Validate a separate, artifact-bound authorization receipt.  A sanitized
    handoff is deliberately never treated as authorization.

The ``validate_*`` functions are pure and accept mappings.  The ``load_*``
wrappers only decode a local JSON file and then call the pure validator.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

PROTOCOL_FIELDS = {
    "display_name",
    "description",
    "homepage_url",
    "github_org",
    "defillama_slug",
    "protocol_type",
    "primary_chain",
    "launched_at",
    "status",
    "has_active_incident",
    "total_value_secured_usd",
}
FAMILY_FIELDS = {
    "display_name",
    "description",
    "homepage_url",
    "protocol_type",
    "primary_chain",
    "status",
    "has_active_incident",
    "legacy_caveat",
    "total_value_secured_usd",
}
SURFACE_FIELDS = {
    "display_name",
    "status",
    "launched_at",
    "primary_chain",
    "tvs_usd",
    "scope_note",
}
DEPLOYMENT_FIELDS = {
    "anchor_address",
    "display_name",
    "tvs_usd",
    "tvs_share",
    "deployed_at",
}
SOURCE_FIELDS = {
    "source_type",
    "url",
    "reference",
    "title",
    "retrieved_at",
    "retrieved_by",
    "is_archived",
    "archive_url",
    "notes",
    "relation",
}
FACTOR_SCORES = {
    "green",
    "yellow",
    "red",
    "gray",
    "not_assessed",
    "not_applicable",
}
COLLECTION_MODES = {"programmatic", "manual", "hybrid"}
SOURCE_TYPES = {
    "url",
    "github",
    "etherscan",
    "transaction",
    "audit_report",
    "governance_post",
    "docs",
    "partner_feed",
    "commit_sha",
}
SOURCE_RELATIONS = {"primary"}


@dataclass(frozen=True)
class PublicHandoff:
    """Verified non-authorizing handoff plus its exact accepted payload."""

    artifact: dict[str, Any]
    payload: dict[str, Any]
    artifact_sha256: str


class ContractError(ValueError):
    """Raised when an apply artifact or operator receipt fails closed."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic ASCII JSON bytes suitable for fingerprints."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("ascii")


def canonical_sha256(value: Any) -> str:
    """Return the canonical SHA-256 digest for a JSON-compatible value."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: str | Path) -> dict[str, Any]:
    """Load one JSON object while rejecting duplicate keys."""
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle, object_pairs_hook=_object_pairs_no_duplicates)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"could not load JSON object {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{source} must contain a JSON object")
    return value


def _public_contracts() -> Any:
    try:
        from protocol_refresh_public import contracts as public_contracts
    except ImportError:  # Imported as scripts.protocol_refresh_apply in tests.
        from scripts.protocol_refresh_public import contracts as public_contracts
    return public_contracts


def _validate_apply_scope(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scope = payload.get("scope")
    changes = payload.get("changes")
    if not isinstance(scope, dict) or not isinstance(changes, dict):
        return ["handoff payload scope and changes must be objects"]

    declared_and_supported = (
        ("protocol", "allowed_protocol_fields", PROTOCOL_FIELDS),
        ("family", "allowed_family_fields", FAMILY_FIELDS),
        ("surface", "allowed_surface_fields", SURFACE_FIELDS),
        ("deployment", "allowed_deployment_fields", DEPLOYMENT_FIELDS),
    )
    declared: dict[str, set[str]] = {}
    for label, key, supported in declared_and_supported:
        value = scope.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"payload.scope.{key} must be an array of field names")
            declared[label] = set()
            continue
        if len(value) != len(set(value)):
            errors.append(f"payload.scope.{key} must contain unique fields")
        declared[label] = set(value)
        unsupported = declared[label] - supported
        if unsupported:
            errors.append(f"payload.scope.{key} contains unsupported fields: {sorted(unsupported)}")

    def check_fields(label: str, fields: Any, kind: str, supported: set[str]) -> None:
        if not isinstance(fields, dict):
            errors.append(f"{label} must be an object")
            return
        unsupported = set(fields) - supported
        undeclared = set(fields) - declared.get(kind, set())
        if unsupported:
            errors.append(f"{label} contains unsupported fields: {sorted(unsupported)}")
        if undeclared:
            errors.append(f"{label} contains undeclared fields: {sorted(undeclared)}")

    check_fields(
        "payload.changes.protocol_fields",
        changes.get("protocol_fields"),
        "protocol",
        PROTOCOL_FIELDS,
    )
    check_fields(
        "payload.changes.family_fields",
        changes.get("family_fields"),
        "family",
        FAMILY_FIELDS,
    )
    for index, entry in enumerate(changes.get("surfaces", [])):
        if isinstance(entry, dict):
            check_fields(
                f"payload.changes.surfaces[{index}].fields",
                entry.get("fields"),
                "surface",
                SURFACE_FIELDS,
            )
    for index, entry in enumerate(changes.get("deployments", [])):
        if isinstance(entry, dict):
            check_fields(
                f"payload.changes.deployments[{index}].fields",
                entry.get("fields"),
                "deployment",
                DEPLOYMENT_FIELDS,
            )
    for index, entry in enumerate(changes.get("factor_scores", [])):
        if not isinstance(entry, dict):
            continue
        fingerprint = entry.get("expected_current_sha256")
        if fingerprint is not None and (
            not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint)
        ):
            errors.append(
                f"payload.changes.factor_scores[{index}].expected_current_sha256 is invalid"
            )
        if entry.get("score") not in FACTOR_SCORES:
            errors.append(
                f"payload.changes.factor_scores[{index}].score must be one of "
                f"{sorted(FACTOR_SCORES)}"
            )
        if entry.get("collection_mode") not in COLLECTION_MODES:
            errors.append(
                f"payload.changes.factor_scores[{index}].collection_mode must be one of "
                f"{sorted(COLLECTION_MODES)}"
            )
        evidence_summary = entry.get("evidence_summary")
        if not isinstance(evidence_summary, str) or not evidence_summary.strip():
            errors.append(
                f"payload.changes.factor_scores[{index}].evidence_summary must be non-empty"
            )
        try:
            normalize_data_as_of(entry.get("data_as_of"), payload["effective_refresh_date"])
        except ContractError as exc:
            errors.append(f"payload.changes.factor_scores[{index}]: {exc}")
        sources = entry.get("sources")
        if not isinstance(sources, list):
            errors.append(f"payload.changes.factor_scores[{index}].sources must be an array")
            continue
        if not sources:
            errors.append(
                f"payload.changes.factor_scores[{index}].sources must be non-empty"
            )
        for source_index, source in enumerate(sources):
            if not isinstance(source, dict):
                errors.append(
                    f"payload.changes.factor_scores[{index}].sources[{source_index}] must be an object"
                )
                continue
            unsupported = set(source) - SOURCE_FIELDS
            if unsupported:
                errors.append(
                    f"payload.changes.factor_scores[{index}].sources[{source_index}] "
                    f"contains unsupported fields: {sorted(unsupported)}"
                )
            if source.get("source_type") not in SOURCE_TYPES:
                errors.append(
                    f"payload.changes.factor_scores[{index}].sources[{source_index}]."
                    f"source_type must be one of {sorted(SOURCE_TYPES)}"
                )
            reference = source.get("reference")
            if not isinstance(reference, str) or not reference.strip():
                errors.append(
                    f"payload.changes.factor_scores[{index}].sources[{source_index}] "
                    "reference must be non-empty"
                )
            relation = source.get("relation", "primary")
            if relation not in SOURCE_RELATIONS:
                errors.append(
                    f"payload.changes.factor_scores[{index}].sources[{source_index}]."
                    f"relation must be one of {sorted(SOURCE_RELATIONS)}"
                )

    baseline = payload.get("baseline")
    if not isinstance(baseline, dict):
        errors.append("payload.baseline must be an object")
    else:
        for name in ("target_sha256", "other_protocols_sha256"):
            value = baseline.get(name)
            if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                errors.append(f"payload.baseline.{name} must be a SHA-256 digest")
    return errors


def validate_apply_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Independently validate the database-facing payload contract."""
    if not isinstance(payload, Mapping):
        raise ContractError("apply payload must be an object")
    document = deepcopy(dict(payload))
    errors = _validate_apply_scope(document)
    if errors:
        raise ContractError("invalid apply payload: " + "; ".join(errors))
    return document


def validate_public_handoff(handoff: Mapping[str, Any]) -> PublicHandoff:
    """Verify the producer's sanitized artifact and apply-specific scope."""
    if not isinstance(handoff, Mapping):
        raise ContractError("public handoff must be an object")
    artifact = deepcopy(dict(handoff))
    public = _public_contracts()
    try:
        errors = public.verify_public_handoff(artifact)
    except public.ContractError as exc:
        raise ContractError(str(exc)) from exc
    payload = artifact.get("payload")
    if not isinstance(payload, dict):
        raise ContractError("public handoff payload must be an object")
    try:
        validate_apply_payload(payload)
    except ContractError as exc:
        errors.append(str(exc))
    if errors:
        raise ContractError("invalid public handoff: " + "; ".join(errors))
    artifact_sha256 = artifact["integrity"]["artifact_sha256"]
    return PublicHandoff(artifact, deepcopy(payload), artifact_sha256)


def load_public_handoff(path: str | Path) -> PublicHandoff:
    """Load and verify a sanitized, explicitly non-authorizing handoff."""
    public = _public_contracts()
    try:
        document = public.load_json_strict(path)
    except public.ContractError as exc:
        raise ContractError(str(exc)) from exc
    return validate_public_handoff(document)


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _require_sha256(value: Any, label: str) -> str:
    value = _require_text(value, label).lower()
    if not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _parse_timestamp(value: Any, label: str) -> str:
    text = _require_text(value, label)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_data_as_of(value: Any, effective_refresh_date: str) -> str:
    """Return an explicit UTC factor evidence timestamp.

    Omitted values use UTC midnight on the approved effective date. Naive
    timestamps are rejected instead of inheriting the database session zone.
    """
    if value is not None:
        return _parse_timestamp(value, "factor.data_as_of")
    try:
        effective = date.fromisoformat(effective_refresh_date)
    except (TypeError, ValueError) as exc:
        raise ContractError("effective_refresh_date must be YYYY-MM-DD") from exc
    return datetime.combine(effective, time.min, tzinfo=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _alias(receipt: Mapping[str, Any], canonical: str, *aliases: str) -> Any:
    names = (canonical, *aliases)
    present = [name for name in names if name in receipt]
    if len(present) > 1:
        values = {json.dumps(receipt[name], sort_keys=True, default=str) for name in present}
        if len(values) > 1:
            raise ContractError(f"conflicting aliases for {canonical}: {present}")
    return receipt[present[0]] if present else None


def validate_backup_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_operation: str | None = None,
    plan_sha256: str | None = None,
    artifact_sha256: str | None = None,
    database_identity: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize a production backup receipt.

    Required evidence is a backup path and ID, SHA-256, positive byte size,
    timezone-aware creation timestamp, database identity, a concrete restore
    command, and successful restore-test evidence with its own timestamp.
    Validation never opens the backup path or connects to a database.
    """
    if not isinstance(receipt, Mapping):
        raise ContractError("backup receipt must be an object")
    schema_version = _require_text(receipt.get("schema_version"), "backup.schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ContractError(f"backup.schema_version must be {SCHEMA_VERSION}")
    receipt_type = _require_text(receipt.get("receipt_type"), "backup.receipt_type")
    if receipt_type not in {"database_backup_receipt", "protocol_refresh_backup"}:
        raise ContractError("backup.receipt_type is not a supported backup receipt")

    operation = _require_text(receipt.get("operation"), "backup.operation")
    if operation not in {"apply_protocol_refresh", "apply_refresh_migrations"}:
        raise ContractError("backup.operation is not supported")
    if expected_operation is not None and operation != expected_operation:
        raise ContractError(
            "backup operation does not match the apply request: "
            f"{operation!r} != {expected_operation!r}"
        )
    actual_plan_sha = _require_sha256(receipt.get("plan_sha256"), "backup.plan_sha256")
    if plan_sha256 is not None and actual_plan_sha != plan_sha256:
        raise ContractError("backup plan_sha256 does not match the apply request")
    actual_artifact_sha: str | None = None
    if operation == "apply_protocol_refresh":
        actual_artifact_sha = _require_sha256(
            receipt.get("artifact_sha256"), "backup.artifact_sha256"
        )
        if artifact_sha256 is not None and actual_artifact_sha != artifact_sha256:
            raise ContractError("backup artifact_sha256 does not match the apply request")
    elif artifact_sha256 is not None:
        raise ContractError("migration backup cannot satisfy protocol artifact authority")

    backup_id = _require_text(_alias(receipt, "backup_id", "id"), "backup.backup_id")
    backup_path = _require_text(_alias(receipt, "backup_path", "path"), "backup.backup_path")
    digest = _require_sha256(receipt.get("sha256"), "backup.sha256")
    size = _alias(receipt, "size_bytes", "size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ContractError("backup.size_bytes must be a positive integer")
    created_at = _parse_timestamp(
        _alias(receipt, "created_at", "timestamp"), "backup.created_at"
    )
    db_identity = _require_text(
        _alias(receipt, "database_identity", "db_identity", "target_db_identity"),
        "backup.database_identity",
    )
    if database_identity is not None and db_identity != database_identity:
        raise ContractError(
            "backup database identity does not match the apply target: "
            f"{db_identity!r} != {database_identity!r}"
        )
    restore_command = _require_text(receipt.get("restore_command"), "backup.restore_command")

    restore_test = receipt.get("restore_test")
    if not isinstance(restore_test, Mapping):
        raise ContractError("backup.restore_test must be an object")
    success = restore_test.get("success") is True or restore_test.get("status") in {
        "success",
        "succeeded",
        "passed",
    }
    if not success:
        raise ContractError("backup.restore_test must record a successful restore test")
    tested_at = _parse_timestamp(
        _alias(restore_test, "tested_at", "timestamp"), "backup.restore_test.tested_at"
    )
    evidence = restore_test.get("evidence")
    if evidence is None or evidence == "" or evidence == {} or evidence == []:
        raise ContractError("backup.restore_test.evidence is required")

    return {
        "schema_version": schema_version,
        "receipt_type": "database_backup_receipt",
        "operation": operation,
        "plan_sha256": actual_plan_sha,
        "artifact_sha256": actual_artifact_sha,
        "backup_id": backup_id,
        "backup_path": backup_path,
        "sha256": digest,
        "size_bytes": size,
        "created_at": created_at,
        "database_identity": db_identity,
        "restore_command": restore_command,
        "restore_test": {
            "status": "succeeded",
            "tested_at": tested_at,
            "evidence": evidence,
        },
    }


def load_backup_receipt(
    path: str | Path,
    *,
    expected_operation: str | None = None,
    plan_sha256: str | None = None,
    artifact_sha256: str | None = None,
    database_identity: str | None = None,
) -> dict[str, Any]:
    """Load a bound receipt and verify the accessible backup bytes."""
    receipt_path = Path(path).resolve()
    normalized = validate_backup_receipt(
        load_json_strict(receipt_path),
        expected_operation=expected_operation,
        plan_sha256=plan_sha256,
        artifact_sha256=artifact_sha256,
        database_identity=database_identity,
    )
    backup_path = Path(normalized["backup_path"])
    if not backup_path.is_absolute():
        backup_path = receipt_path.parent / backup_path
    backup_path = backup_path.resolve()
    try:
        stat = backup_path.stat()
    except OSError as exc:
        raise ContractError(f"backup file is not accessible: {backup_path}: {exc}") from exc
    if not backup_path.is_file():
        raise ContractError(f"backup path is not a file: {backup_path}")
    if stat.st_size != normalized["size_bytes"]:
        raise ContractError(
            f"backup file size mismatch: expected {normalized['size_bytes']}, got {stat.st_size}"
        )
    digest = hashlib.sha256()
    try:
        with backup_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"backup file could not be read: {backup_path}: {exc}") from exc
    actual_sha = digest.hexdigest()
    if actual_sha != normalized["sha256"]:
        raise ContractError(
            f"backup file SHA-256 mismatch: expected {normalized['sha256']}, got {actual_sha}"
        )
    normalized["verified_backup_path"] = str(backup_path)
    return normalized


def validate_production_authorization_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_operation: str | None = "apply_protocol_refresh",
    artifact_sha256: str | None = None,
    plan_sha256: str | None = None,
    allowed_migrations: list[str] | tuple[str, ...] | None = None,
    refresh_id: str | None = None,
    family_slug: str | None = None,
    database_identity: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and normalize a separate production authorization receipt.

    Protocol receipts bind one exact sanitized artifact, refresh ID, canonical
    family, and database. Migration receipts instead bind one exact migration
    plan SHA and ordered allowlist. ``expected_operation`` defaults to protocol
    apply so the protocol CLI remains fail-closed; pass
    ``"apply_refresh_migrations"`` for a migration plan, or ``None`` when a
    generic caller will inspect the normalized operation itself.
    """
    if not isinstance(receipt, Mapping):
        raise ContractError("production authorization receipt must be an object")
    schema_version = _require_text(
        receipt.get("schema_version"), "authorization.schema_version"
    )
    if schema_version != SCHEMA_VERSION:
        raise ContractError(f"authorization.schema_version must be {SCHEMA_VERSION}")
    receipt_type = _require_text(receipt.get("receipt_type"), "authorization.receipt_type")
    if receipt_type not in {
        "protocol_refresh_production_authorization",
        "production_authorization_receipt",
    }:
        raise ContractError("authorization.receipt_type is not a production authorization")
    operation_value = _require_text(receipt.get("operation"), "authorization.operation")
    operation_aliases = {
        "apply_protocol_refresh": "apply_protocol_refresh",
        "protocol_refresh_apply": "apply_protocol_refresh",
        "apply_refresh_migrations": "apply_refresh_migrations",
    }
    operation = operation_aliases.get(operation_value)
    if operation is None:
        raise ContractError("authorization.operation is not supported")
    if expected_operation is not None:
        canonical_expected = operation_aliases.get(expected_operation)
        if canonical_expected is None:
            raise ContractError(f"unsupported expected_operation {expected_operation!r}")
        if operation != canonical_expected:
            raise ContractError(
                "authorization operation does not match the requested operation: "
                f"{operation!r} != {canonical_expected!r}"
            )

    authorization_id = _require_text(
        _alias(receipt, "authorization_id", "receipt_id", "id"),
        "authorization.authorization_id",
    )
    if not ID_RE.fullmatch(authorization_id):
        raise ContractError("authorization.authorization_id has invalid characters")
    actual_refresh_id: str | None = None
    actual_family: str | None = None
    actual_artifact_sha: str | None = None
    actual_plan_sha: str | None = None
    actual_migrations: list[str] | None = None
    if operation == "apply_protocol_refresh":
        actual_refresh_id = _require_text(
            receipt.get("refresh_id"), "authorization.refresh_id"
        )
        actual_family = _require_text(
            receipt.get("family_slug"), "authorization.family_slug"
        )
        if not SLUG_RE.fullmatch(actual_family):
            raise ContractError("authorization.family_slug is invalid")
        actual_artifact_sha = _require_sha256(
            _alias(receipt, "artifact_sha256", "authorized_artifact_sha256"),
            "authorization.artifact_sha256",
        )
        actual_plan_sha = _require_sha256(
            receipt.get("plan_sha256"), "authorization.plan_sha256"
        )
        if receipt.get("allowed_migrations") is not None:
            raise ContractError("protocol authorization cannot contain migration allowlists")
    else:
        actual_plan_sha = _require_sha256(
            receipt.get("plan_sha256"), "authorization.plan_sha256"
        )
        migrations = receipt.get("allowed_migrations")
        if not isinstance(migrations, list) or not migrations:
            raise ContractError("authorization.allowed_migrations must be a non-empty array")
        if any(not isinstance(item, str) or not item.strip() for item in migrations):
            raise ContractError("authorization.allowed_migrations contains an invalid path")
        if len(migrations) != len(set(migrations)):
            raise ContractError("authorization.allowed_migrations must contain unique paths")
        actual_migrations = list(migrations)
        if receipt.get("artifact_sha256") is not None or receipt.get("refresh_id") is not None:
            raise ContractError("migration authorization cannot contain protocol-artifact authority")
    db_identity = _require_text(
        _alias(receipt, "database_identity", "db_identity", "target_db_identity"),
        "authorization.database_identity",
    )
    authorized_by = _require_text(receipt.get("authorized_by"), "authorization.authorized_by")
    authorized_at = _parse_timestamp(receipt.get("authorized_at"), "authorization.authorized_at")

    expected = {"database_identity": (db_identity, database_identity)}
    if operation == "apply_protocol_refresh":
        expected.update(
            {
                "refresh_id": (actual_refresh_id, refresh_id),
                "family_slug": (actual_family, family_slug),
                "artifact_sha256": (actual_artifact_sha, artifact_sha256),
                "plan_sha256": (actual_plan_sha, plan_sha256),
            }
        )
        if allowed_migrations is not None:
            raise ContractError("migration allowlists cannot validate protocol authorization")
    else:
        expected["plan_sha256"] = (actual_plan_sha, plan_sha256)
        if artifact_sha256 is not None or refresh_id is not None or family_slug is not None:
            raise ContractError("protocol expectations cannot validate migration authorization")
        if allowed_migrations is not None and actual_migrations != list(allowed_migrations):
            raise ContractError(
                "authorization allowed_migrations do not match the migration plan exactly"
            )
    for label, (actual, wanted) in expected.items():
        if wanted is not None and actual != wanted:
            raise ContractError(
                f"authorization {label} does not match the apply request: {actual!r} != {wanted!r}"
            )

    expires_value = receipt.get("expires_at")
    expires_at = _parse_timestamp(expires_value, "authorization.expires_at") if expires_value else None
    if expires_at is not None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ContractError("authorization comparison time must include a timezone")
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if current.astimezone(timezone.utc) >= expiry:
            raise ContractError("production authorization receipt has expired")

    return {
        "schema_version": schema_version,
        "receipt_type": "protocol_refresh_production_authorization",
        "authorization_id": authorization_id,
        "operation": operation,
        "refresh_id": actual_refresh_id,
        "family_slug": actual_family,
        "artifact_sha256": actual_artifact_sha,
        "plan_sha256": actual_plan_sha,
        "allowed_migrations": actual_migrations,
        "database_identity": db_identity,
        "authorized_by": authorized_by,
        "authorized_at": authorized_at,
        "expires_at": expires_at,
    }


def load_production_authorization_receipt(
    path: str | Path,
    **expected: Any,
) -> dict[str, Any]:
    """Load and validate a separate production authorization receipt."""
    return validate_production_authorization_receipt(load_json_strict(path), **expected)


# Readable compatibility aliases for callers that already name the object by
# its shorter operator-facing label.  The longer names above are canonical.
validate_authorization_receipt = validate_production_authorization_receipt
load_authorization_receipt = load_production_authorization_receipt
