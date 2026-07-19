"""Strict contracts for a non-mutating public protocol refresh handoff."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PUBLIC_SCHEMA_VERSION = "1.1"
REISSUE_SCHEMA_VERSION = "1.2"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FACTOR_RE = re.compile(r"^RD-F-(?!169$)[0-9]{3}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
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
    "curator_note",
    "commit_sha",
}
SOURCE_OPTIONAL_SCORES = {"not_assessed", "not_applicable"}
CONDITIONAL_SOURCE_TYPES = {"curator_note", "partner_feed"}
PUBLIC_HTTP_SOURCE_TYPES = SOURCE_TYPES - CONDITIONAL_SOURCE_TYPES
# Migration 0000 declares text NOT NULL DEFAULT 'primary' and no other relation value.
SOURCE_RELATIONS = {"primary"}
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


class ContractError(ValueError):
    """Raised when an artifact cannot cross the public refresh boundary."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ContractError(f"non-JSON numeric constant: {value}")


def load_json_strict(path: Path | str) -> dict[str, Any]:
    """Load one UTF-8 JSON object while rejecting ambiguous JSON constructs."""
    source = Path(path)
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{source} must contain one JSON object")
    return value


def _assert_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{path} contains a non-string object key")
            _assert_json_value(item, f"{path}.{key}")
        return
    raise ContractError(f"{path} contains non-JSON value {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the sole canonical byte representation used by this boundary."""
    _assert_json_value(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_surface_fingerprint(family_slug: str, surface_slugs: list[str]) -> str:
    return canonical_sha256(
        {"family_slug": family_slug, "surface_slugs": sorted(surface_slugs)}
    )


def _has_public_http_locator(source: dict[str, Any]) -> bool:
    for field in ("url", "reference"):
        value = source.get(field)
        if not isinstance(value, str):
            continue
        parsed = urlparse(value.strip())
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return True
    return False


def _require_object(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def _require_unique_slugs(value: Any, label: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty array")
        return set()
    if len(value) != len(set(value)):
        errors.append(f"{label} must contain unique values")
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not SLUG_RE.fullmatch(item):
            errors.append(f"{label} contains invalid slug {item!r}")
        else:
            result.add(item)
    return result


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_declared_fields(
    value: Any,
    label: str,
    supported: set[str],
    errors: list[str],
) -> set[str]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return set()
    if len(value) != len(set(value)):
        errors.append(f"{label} must contain unique values")
    fields = set(value)
    unsupported = fields - supported
    if unsupported:
        errors.append(f"{label} contains unsupported fields {sorted(unsupported)}")
    return fields & supported


def _validate_field_changes(
    value: Any,
    label: str,
    declared: set[str],
    supported: set[str],
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    fields = set(value)
    unsupported = fields - supported
    undeclared = fields - declared
    if unsupported:
        errors.append(f"{label} contains unsupported fields {sorted(unsupported)}")
    if undeclared:
        errors.append(f"{label} contains fields outside declared scope {sorted(undeclared)}")


def validate_accepted_changes(document: dict[str, Any]) -> list[str]:
    """Validate one family envelope and every surface/factor target in it."""
    errors: list[str] = []
    required = {
        "schema_version",
        "batch_id",
        "refresh_id",
        "family_slug",
        "protocol_slug",
        "surface_slugs",
        "refresh_type",
        "rubric_version",
        "effective_refresh_date",
        "topology_contract",
        "scope",
        "baseline",
        "expected_result",
        "changes",
    }
    missing = sorted(required - set(document))
    if missing:
        return [f"accepted changes missing fields: {missing}"]
    extra = sorted(set(document) - required)
    if extra:
        errors.append(f"accepted changes contains unsupported fields: {extra}")
    if document.get("schema_version") != "1.0":
        errors.append("accepted changes schema_version must be 1.0")
    expected_result = document.get("expected_result")
    if not isinstance(expected_result, dict):
        errors.append("expected_result must be an object")
    else:
        expected_fields = {
            "headline_grade", "risk_score", "cap_state", "active_factor_count", "surface_results"
        }
        if set(expected_result) != expected_fields:
            errors.append("expected_result has an invalid field set")
        if expected_result.get("headline_grade") not in {"A", "B", "C", "D", "F"}:
            errors.append("expected_result.headline_grade is invalid")
        risk_score = expected_result.get("risk_score")
        if not isinstance(risk_score, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", risk_score):
            errors.append("expected_result.risk_score must be a two-decimal string")
        if expected_result.get("cap_state") not in {"none", "cap"}:
            errors.append("expected_result.cap_state is invalid")
        count = expected_result.get("active_factor_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            errors.append("expected_result.active_factor_count is invalid")
        if not isinstance(expected_result.get("surface_results"), dict):
            errors.append("expected_result.surface_results must be an object")
        else:
            surface_results = expected_result["surface_results"]
            if set(surface_results) != set(document.get("surface_slugs", [])):
                errors.append("expected_result.surface_results must exactly match surface_slugs")
            for slug, result in surface_results.items():
                if not isinstance(result, dict) or set(result) != {"headline_grade", "risk_score", "cap_state"}:
                    errors.append(f"expected_result.surface_results[{slug!r}] is invalid")
                    continue
                if result.get("headline_grade") not in {"A", "B", "C", "D", "F"}:
                    errors.append(f"expected_result.surface_results[{slug!r}].headline_grade is invalid")
                if not isinstance(result.get("risk_score"), str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", result["risk_score"]):
                    errors.append(f"expected_result.surface_results[{slug!r}].risk_score must be a two-decimal string")
                if result.get("cap_state") not in {"none", "cap"}:
                    errors.append(f"expected_result.surface_results[{slug!r}].cap_state is invalid")
    for name in ("batch_id", "refresh_id"):
        value = document.get(name)
        if not isinstance(value, str) or not ID_RE.fullmatch(value):
            errors.append(f"{name} is invalid")

    family = document.get("family_slug")
    protocol = document.get("protocol_slug")
    if not isinstance(family, str) or not SLUG_RE.fullmatch(family):
        errors.append("family_slug is invalid")
    if protocol != family:
        errors.append("protocol_slug must exactly equal the one canonical family_slug")
    surfaces = _require_unique_slugs(document.get("surface_slugs"), "surface_slugs", errors)
    if document.get("refresh_type") not in {"full_family_refresh", "targeted_surface_update"}:
        errors.append("refresh_type is invalid")
    if not isinstance(document.get("rubric_version"), str) or not document["rubric_version"]:
        errors.append("rubric_version is required")
    if not _valid_date(document.get("effective_refresh_date")):
        errors.append("effective_refresh_date must be a valid YYYY-MM-DD date")

    topology = _require_object(document.get("topology_contract"), "topology_contract", errors)
    topology_fields = {
        "mode",
        "canonical_surface_slugs",
        "canonical_surface_fingerprint",
        "operator_approval_artifact_sha256",
    }
    if set(topology) != topology_fields:
        errors.append(f"topology_contract fields must exactly equal {sorted(topology_fields)}")
    canonical_surfaces = _require_unique_slugs(
        topology.get("canonical_surface_slugs"),
        "topology_contract.canonical_surface_slugs",
        errors,
    )
    canonical_surface_values = topology.get("canonical_surface_slugs")
    if (
        isinstance(canonical_surface_values, list)
        and all(isinstance(item, str) for item in canonical_surface_values)
        and canonical_surface_values != sorted(canonical_surface_values)
    ):
        errors.append("topology_contract canonical surfaces must be sorted")
    if topology.get("mode") != "preserve_canonical":
        errors.append("public refresh topology_contract.mode must be preserve_canonical")
    if topology.get("operator_approval_artifact_sha256") is not None:
        errors.append("public refresh cannot carry a topology migration approval")
    if isinstance(family, str) and canonical_surfaces:
        expected_fingerprint = canonical_surface_fingerprint(
            family, sorted(canonical_surfaces)
        )
        if topology.get("canonical_surface_fingerprint") != expected_fingerprint:
            errors.append("topology_contract canonical surface fingerprint is invalid")
    if document.get("refresh_type") == "full_family_refresh":
        if canonical_surfaces != surfaces:
            errors.append("full family refresh must exactly match canonical topology")
    elif not surfaces <= canonical_surfaces:
        errors.append("targeted refresh cannot broaden canonical topology")

    scope = _require_object(document.get("scope"), "scope", errors)
    scope_keys = {
        "allowed_surfaces",
        "allowed_factor_ids",
        "allowed_protocol_fields",
        "allowed_family_fields",
        "allowed_surface_fields",
        "allowed_deployment_fields",
    }
    if set(scope) != scope_keys:
        errors.append(f"scope fields must exactly equal {sorted(scope_keys)}")
    allowed_surfaces = _require_unique_slugs(
        scope.get("allowed_surfaces"), "scope.allowed_surfaces", errors
    )
    if allowed_surfaces != surfaces:
        errors.append("scope.allowed_surfaces must exactly match surface_slugs")

    allowed_factors_value = scope.get("allowed_factor_ids")
    allowed_factors: set[str] = set()
    if not isinstance(allowed_factors_value, list) or not allowed_factors_value:
        errors.append("scope.allowed_factor_ids must be a non-empty array")
    else:
        if len(allowed_factors_value) != len(set(allowed_factors_value)):
            errors.append("scope.allowed_factor_ids must contain unique values")
        for factor_id in allowed_factors_value:
            if not isinstance(factor_id, str) or not FACTOR_RE.fullmatch(factor_id):
                errors.append(f"invalid allowed factor ID {factor_id!r}")
            else:
                allowed_factors.add(factor_id)

    declared_fields = {
        "protocol": _validate_declared_fields(
            scope.get("allowed_protocol_fields"),
            "scope.allowed_protocol_fields",
            PROTOCOL_FIELDS,
            errors,
        ),
        "family": _validate_declared_fields(
            scope.get("allowed_family_fields"),
            "scope.allowed_family_fields",
            FAMILY_FIELDS,
            errors,
        ),
        "surface": _validate_declared_fields(
            scope.get("allowed_surface_fields"),
            "scope.allowed_surface_fields",
            SURFACE_FIELDS,
            errors,
        ),
        "deployment": _validate_declared_fields(
            scope.get("allowed_deployment_fields"),
            "scope.allowed_deployment_fields",
            DEPLOYMENT_FIELDS,
            errors,
        ),
    }

    baseline = _require_object(document.get("baseline"), "baseline", errors)
    if set(baseline) != {"target_sha256", "other_protocols_sha256"}:
        errors.append("baseline fields must exactly match target and other protocol hashes")
    for name in ("target_sha256", "other_protocols_sha256"):
        value = baseline.get(name)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            errors.append(f"baseline.{name} must be strict lowercase SHA-256")

    changes = _require_object(document.get("changes"), "changes", errors)
    change_keys = {"protocol_fields", "family_fields", "surfaces", "deployments", "factor_scores"}
    if set(changes) != change_keys:
        errors.append(f"changes fields must exactly equal {sorted(change_keys)}")
    _validate_field_changes(
        changes.get("protocol_fields"),
        "changes.protocol_fields",
        declared_fields["protocol"],
        PROTOCOL_FIELDS,
        errors,
    )
    _validate_field_changes(
        changes.get("family_fields"),
        "changes.family_fields",
        declared_fields["family"],
        FAMILY_FIELDS,
        errors,
    )
    surface_changes = changes.get("surfaces", [])
    if not isinstance(surface_changes, list):
        errors.append("changes.surfaces must be an array")
    else:
        seen: set[str] = set()
        for index, change in enumerate(surface_changes):
            if not isinstance(change, dict):
                errors.append(f"changes.surfaces[{index}] must be an object")
                continue
            target = change.get("surface_slug")
            if target not in surfaces:
                errors.append(f"changes.surfaces[{index}] targets out-of-scope surface")
            if target in seen:
                errors.append(f"duplicate surface change for {target}")
            seen.add(target)
            _validate_field_changes(
                change.get("fields"),
                f"changes.surfaces[{index}].fields",
                declared_fields["surface"],
                SURFACE_FIELDS,
                errors,
            )

    deployment_changes = changes.get("deployments", [])
    if not isinstance(deployment_changes, list):
        errors.append("changes.deployments must be an array")
    else:
        seen_deployments: set[tuple[Any, Any, Any]] = set()
        for index, change in enumerate(deployment_changes):
            if not isinstance(change, dict):
                errors.append(f"changes.deployments[{index}] must be an object")
                continue
            target = change.get("surface_slug")
            key = (target, change.get("chain"), change.get("deployment_key"))
            if target not in surfaces:
                errors.append(f"changes.deployments[{index}] targets out-of-scope surface")
            if not key[1] or not key[2]:
                errors.append(f"changes.deployments[{index}] requires chain and deployment_key")
            if key in seen_deployments:
                errors.append(f"duplicate deployment change {key}")
            seen_deployments.add(key)
            _validate_field_changes(
                change.get("fields"),
                f"changes.deployments[{index}].fields",
                declared_fields["deployment"],
                DEPLOYMENT_FIELDS,
                errors,
            )

    factor_changes = changes.get("factor_scores", [])
    if not isinstance(factor_changes, list):
        errors.append("changes.factor_scores must be an array")
    else:
        seen_factors: set[tuple[Any, Any, Any, Any, Any]] = set()
        for index, change in enumerate(factor_changes):
            label = f"changes.factor_scores[{index}]"
            if not isinstance(change, dict):
                errors.append(f"{label} must be an object")
                continue
            factor_id = change.get("factor_id")
            if factor_id not in allowed_factors:
                errors.append(f"{label} targets out-of-scope factor {factor_id!r}")
            level = change.get("scope_level")
            surface = change.get("surface_slug")
            chain = change.get("chain")
            deployment = change.get("deployment_key")
            if level == "family":
                if any(value is not None for value in (surface, chain, deployment)):
                    errors.append(f"{label} has invalid family scope")
            elif level == "surface":
                if surface not in surfaces:
                    errors.append(f"{label} targets out-of-scope surface {surface!r}")
                if chain is not None or deployment is not None:
                    errors.append(f"{label} has invalid surface scope")
            elif level == "deployment":
                if surface not in surfaces:
                    errors.append(f"{label} targets out-of-scope surface {surface!r}")
                if not chain or not deployment:
                    errors.append(f"{label} has invalid deployment scope")
            else:
                errors.append(f"{label}.scope_level is invalid")
            target = (factor_id, level, surface, chain, deployment)
            if target in seen_factors:
                errors.append(f"duplicate factor target {target}")
            seen_factors.add(target)
            expected = change.get("expected_current_sha256")
            if expected is not None and (
                not isinstance(expected, str) or not SHA256_RE.fullmatch(expected)
            ):
                errors.append(f"{label}.expected_current_sha256 is invalid")
            score = change.get("score")
            if not isinstance(score, str) or score not in FACTOR_SCORES:
                errors.append(f"{label}.score is invalid")
            collection_mode = change.get("collection_mode")
            if not isinstance(collection_mode, str) or collection_mode not in COLLECTION_MODES:
                errors.append(f"{label}.collection_mode is invalid")
            evidence_summary = change.get("evidence_summary")
            if not isinstance(evidence_summary, str) or not evidence_summary.strip():
                errors.append(f"{label}.evidence_summary must be a non-empty string")
            sources = change.get("sources")
            if not isinstance(sources, list):
                errors.append(f"{label}.sources must be an array")
                continue
            if not sources and score not in SOURCE_OPTIONAL_SCORES:
                errors.append(f"{label}.sources must contain at least one citation")
                continue
            for source_index, source in enumerate(sources):
                source_label = f"{label}.sources[{source_index}]"
                if not isinstance(source, dict):
                    errors.append(f"{source_label} must be an object")
                    continue
                source_type = source.get("source_type")
                if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
                    errors.append(
                        f"{source_label}.source_type {source_type!r} is invalid or forbidden"
                    )
                reference = source.get("reference")
                if not isinstance(reference, str) or not reference.strip():
                    errors.append(f"{source_label}.reference must be a non-empty string")
                if source_type in PUBLIC_HTTP_SOURCE_TYPES and not _has_public_http_locator(
                    source
                ):
                    errors.append(
                        f"{source_label} requires a public HTTP(S) locator"
                    )
                if "relation" in source:
                    relation = source.get("relation")
                    if not isinstance(relation, str) or relation not in SOURCE_RELATIONS:
                        errors.append(f"{source_label}.relation is invalid")
            if score in {"green", "yellow", "red"} and not any(
                isinstance(source, dict)
                and source.get("source_type") not in CONDITIONAL_SOURCE_TYPES
                and _has_public_http_locator(source)
                for source in sources
            ):
                errors.append(
                    f"{label} requires an independently verifiable public source"
                )

    return errors


def _has_semantic_changes(document: dict[str, Any]) -> bool:
    changes = document.get("changes", {})
    return isinstance(changes, dict) and any(
        bool(changes.get(key))
        for key in ("protocol_fields", "family_fields", "surfaces", "deployments", "factor_scores")
    )


def verify_approved_status(
    document: dict[str, Any], status: dict[str, Any]
) -> list[str]:
    """Require an exact locally approved state without production authority."""
    errors: list[str] = []
    expected_pairs = {
        "batch_id": document.get("batch_id"),
        "refresh_id": document.get("refresh_id"),
        "family_slug": document.get("family_slug"),
        "protocol_slug": document.get("protocol_slug"),
        "surface_slugs": document.get("surface_slugs"),
    }
    for name, expected in expected_pairs.items():
        if status.get(name) != expected:
            errors.append(f"status.{name} does not exactly match accepted changes")
    if status.get("local_state") != "local_ready_for_review":
        errors.append("status.local_state must be local_ready_for_review")
    expected_outcome = "changed" if _has_semantic_changes(document) else "no_change"
    if status.get("local_outcome") != expected_outcome:
        errors.append(f"status.local_outcome must be {expected_outcome}")
    if status.get("approval_state") != "approved":
        errors.append("status.approval_state must be exactly approved")
    if not status.get("reviewed_by") or not status.get("reviewed_at"):
        errors.append("status must contain its local approval reviewer and timestamp")
    if status.get("production_authorized") is not False:
        errors.append("status.production_authorized must be false")
    if status.get("production_state") not in {"not_started", "not_authorized"}:
        errors.append("status.production_state must remain non-authorized")

    checksums = status.get("checksums")
    approved_hash = checksums.get("accepted_changes_sha256") if isinstance(checksums, dict) else None
    actual_hash = canonical_sha256(document)
    if not isinstance(approved_hash, str) or not SHA256_RE.fullmatch(approved_hash):
        errors.append("status accepted_changes_sha256 is not strict lowercase SHA-256")
    elif approved_hash != actual_hash:
        errors.append("status accepted_changes_sha256 does not match canonical accepted changes")
    return errors


def _require_valid(errors: list[str]) -> None:
    if errors:
        raise ContractError("; ".join(errors))


def build_public_handoff(
    document: dict[str, Any],
    status: dict[str, Any],
    *,
    source_document: dict[str, Any] | None = None,
    reissue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a checksummed JSON handoff that cannot authorize production."""
    from .sanitizer import find_private_material, sanitize_accepted_changes

    _require_valid(validate_accepted_changes(document))
    source_document = document if source_document is None else source_document
    if source_document is not document:
        expected_source = deepcopy(document)
        if reissue is not None:
            prior_refresh_id = reissue.get("prior_refresh_id")
            if not isinstance(prior_refresh_id, str) or not ID_RE.fullmatch(prior_refresh_id):
                raise ContractError("reissue prior_refresh_id is invalid")
            if prior_refresh_id == document.get("refresh_id"):
                raise ContractError("reissue refresh_id must differ from the prior refresh_id")
            expected_source["refresh_id"] = prior_refresh_id
        legacy_expected_source = deepcopy(expected_source)
        legacy_expected_source.pop("expected_result")
        source_bytes = canonical_json_bytes(source_document)
        if source_bytes not in {
            canonical_json_bytes(expected_source),
            canonical_json_bytes(legacy_expected_source),
        }:
            # JSON bytes are used above only to compare nested dictionaries without
            # relying on Python's permissive numeric equality (for example 1 == 1.0).
            # The source document is still retained verbatim for its approval hash.
            raise ContractError(
                "source accepted changes must exactly equal the public payload before "
                "expected_result enrichment and an authorized reissue refresh_id"
            )
    _require_valid(verify_approved_status(source_document, status))
    if reissue is not None:
        expected_reissue = {
            "reason": "compensated_production_attempt",
            "prior_refresh_id": source_document["refresh_id"],
            "prior_artifact_sha256": reissue.get("prior_artifact_sha256"),
            "compensation_proof_sha256": reissue.get("compensation_proof_sha256"),
        }
        if reissue != expected_reissue:
            raise ContractError("reissue binding has an invalid field set or reason")
        for name in ("prior_artifact_sha256", "compensation_proof_sha256"):
            value = reissue.get(name)
            if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                raise ContractError(f"reissue {name} is invalid")
    sanitized = sanitize_accepted_changes(document)
    _require_valid(find_private_material(sanitized))

    accepted_hash = canonical_sha256(source_document)
    payload_hash = canonical_sha256(sanitized)
    core: dict[str, Any] = {
        "schema_version": REISSUE_SCHEMA_VERSION if reissue is not None else PUBLIC_SCHEMA_VERSION,
        "artifact_type": "protocol_refresh_public_handoff",
        "refresh_id": document["refresh_id"],
        "family_slug": document["family_slug"],
        "surface_slugs": deepcopy(document["surface_slugs"]),
        "authorization": {
            "production_authorized": False,
            "explicit_production_approval_required": True,
        },
        "source_approval": {
            "approval_state": "approved",
            "accepted_changes_sha256": accepted_hash,
            "status_sha256": canonical_sha256(status),
            **({"reissue": deepcopy(reissue)} if reissue is not None else {}),
        },
        "payload": sanitized,
        "integrity": {
            "algorithm": "sha256",
            "canonicalization": "sorted-keys-compact-ascii-json-v1",
            "payload_sha256": payload_hash,
        },
    }
    artifact_hash = canonical_sha256(core)
    core["integrity"]["artifact_sha256"] = artifact_hash
    return core


def verify_public_handoff(handoff: dict[str, Any]) -> list[str]:
    """Verify the self-contained public artifact and its non-authorizing state."""
    from .sanitizer import find_private_material, sanitize_accepted_changes

    errors: list[str] = []
    handoff_fields = {
        "schema_version",
        "artifact_type",
        "refresh_id",
        "family_slug",
        "surface_slugs",
        "authorization",
        "source_approval",
        "payload",
        "integrity",
    }
    if set(handoff) != handoff_fields:
        errors.append(f"handoff fields must exactly equal {sorted(handoff_fields)}")
    schema_version = handoff.get("schema_version")
    if schema_version not in {PUBLIC_SCHEMA_VERSION, REISSUE_SCHEMA_VERSION}:
        errors.append(
            f"handoff schema_version must be {PUBLIC_SCHEMA_VERSION} or {REISSUE_SCHEMA_VERSION}"
        )
    if handoff.get("artifact_type") != "protocol_refresh_public_handoff":
        errors.append("handoff artifact_type is invalid")
    authorization = handoff.get("authorization")
    if authorization != {
        "production_authorized": False,
        "explicit_production_approval_required": True,
    }:
        errors.append("handoff authorization block must remain exactly non-authorizing")

    payload = handoff.get("payload")
    if not isinstance(payload, dict):
        return errors + ["handoff payload must be an object"]
    errors.extend(validate_accepted_changes(payload))
    try:
        sanitized = sanitize_accepted_changes(payload)
    except ContractError as exc:
        errors.append(str(exc))
    else:
        if sanitized != payload:
            errors.append("handoff payload contains fields outside the sanitized public shape")
    errors.extend(find_private_material(payload))
    if handoff.get("refresh_id") != payload.get("refresh_id"):
        errors.append("handoff refresh_id does not match payload")
    if handoff.get("family_slug") != payload.get("family_slug"):
        errors.append("handoff family_slug does not match payload")
    if handoff.get("surface_slugs") != payload.get("surface_slugs"):
        errors.append("handoff surface_slugs do not match payload")

    integrity = handoff.get("integrity")
    if not isinstance(integrity, dict):
        return errors + ["handoff integrity must be an object"]
    integrity_fields = {"algorithm", "canonicalization", "payload_sha256", "artifact_sha256"}
    if set(integrity) != integrity_fields:
        errors.append(f"handoff integrity fields must exactly equal {sorted(integrity_fields)}")
    payload_hash = canonical_sha256(payload)
    if integrity.get("algorithm") != "sha256":
        errors.append("handoff integrity algorithm must be sha256")
    if integrity.get("canonicalization") != "sorted-keys-compact-ascii-json-v1":
        errors.append("handoff canonicalization is invalid")
    if integrity.get("payload_sha256") != payload_hash:
        errors.append("handoff payload_sha256 mismatch")
    source_approval = handoff.get("source_approval")
    if not isinstance(source_approval, dict):
        errors.append("handoff source_approval must be an object")
    else:
        source_fields = {"approval_state", "accepted_changes_sha256", "status_sha256"}
        if schema_version == REISSUE_SCHEMA_VERSION:
            source_fields.add("reissue")
        if set(source_approval) != source_fields:
            errors.append(f"handoff source_approval fields must exactly equal {sorted(source_fields)}")
        if source_approval.get("approval_state") != "approved":
            errors.append("handoff source approval is not approved")
        accepted_hash = source_approval.get("accepted_changes_sha256")
        if not isinstance(accepted_hash, str) or not SHA256_RE.fullmatch(accepted_hash):
            errors.append("handoff accepted_changes_sha256 is invalid")
        status_hash = source_approval.get("status_sha256")
        if not isinstance(status_hash, str) or not SHA256_RE.fullmatch(status_hash):
            errors.append("handoff status_sha256 is invalid")
        if schema_version == REISSUE_SCHEMA_VERSION:
            reissue = source_approval.get("reissue")
            expected_fields = {
                "reason",
                "prior_refresh_id",
                "prior_artifact_sha256",
                "compensation_proof_sha256",
            }
            if not isinstance(reissue, dict) or set(reissue) != expected_fields:
                errors.append("handoff reissue binding has an invalid field set")
            else:
                if reissue.get("reason") != "compensated_production_attempt":
                    errors.append("handoff reissue reason is invalid")
                prior_refresh_id = reissue.get("prior_refresh_id")
                if not isinstance(prior_refresh_id, str) or not ID_RE.fullmatch(prior_refresh_id):
                    errors.append("handoff reissue prior_refresh_id is invalid")
                elif prior_refresh_id == handoff.get("refresh_id"):
                    errors.append("handoff reissue refresh_id must differ from prior_refresh_id")
                for name in ("prior_artifact_sha256", "compensation_proof_sha256"):
                    value = reissue.get(name)
                    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                        errors.append(f"handoff reissue {name} is invalid")

    artifact_hash = integrity.get("artifact_sha256")
    unsigned = deepcopy(handoff)
    unsigned_integrity = unsigned.get("integrity")
    if isinstance(unsigned_integrity, dict):
        unsigned_integrity.pop("artifact_sha256", None)
    if not isinstance(artifact_hash, str) or not SHA256_RE.fullmatch(artifact_hash):
        errors.append("handoff artifact_sha256 is invalid")
    elif artifact_hash != canonical_sha256(unsigned):
        errors.append("handoff artifact_sha256 mismatch")
    return errors


def write_json(path: Path | str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
