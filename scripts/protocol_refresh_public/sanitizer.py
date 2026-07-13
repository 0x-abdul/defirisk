"""Fail-closed public-material checks for protocol refresh JSON."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .contracts import ContractError


FORBIDDEN_KEYS = {
    "access_token",
    "api_key",
    "approved_at",
    "approved_by",
    "collected_by",
    "curator_note",
    "internal_path",
    "local_path",
    "password",
    "private_key",
    "refresh_token",
    "retrieved_by",
    "review_note",
    "review_token",
    "reviewed_at",
    "reviewed_by",
    "secret",
}

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:postgres(?:ql)?|mysql|redis)://[^\s:/]+:[^\s@]+@", re.IGNORECASE),
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?:^|[\s'\"(])(?:[A-Za-z]:[\\/]|\\\\)[^\s'\"]*"),
    re.compile(r"(?:^|[\s'\"(])/(?:Users|home|tmp|var/tmp)/[^\s'\"]*"),
    re.compile(r"\bfile://", re.IGNORECASE),
    re.compile(r"(?:^|[/\\])\.research(?:[/\\]|$)", re.IGNORECASE),
)
UNPUBLISHED_PATTERNS = (
    re.compile(r"(?:^|[/\\])unpublished(?:[/\\]|$)", re.IGNORECASE),
    re.compile(r"[?&](?:review_?token|token)=", re.IGNORECASE),
)
CURATOR_ONLY_PATTERNS = (
    re.compile(r"\bcurator[-_ ]only\b", re.IGNORECASE),
    re.compile(r"\binternal[-_ ]only\b", re.IGNORECASE),
    re.compile(r"\bprivate review\b", re.IGNORECASE),
)

TOP_LEVEL_FIELDS = {
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
    "changes",
}
TOPOLOGY_FIELDS = {
    "mode",
    "canonical_surface_slugs",
    "canonical_surface_fingerprint",
    "operator_approval_artifact_sha256",
}
SCOPE_FIELDS = {
    "allowed_surfaces",
    "allowed_factor_ids",
    "allowed_protocol_fields",
    "allowed_family_fields",
    "allowed_surface_fields",
    "allowed_deployment_fields",
}
BASELINE_FIELDS = {"target_sha256", "other_protocols_sha256"}
CHANGE_FIELDS = {"protocol_fields", "family_fields", "surfaces", "deployments", "factor_scores"}
SURFACE_CHANGE_FIELDS = {"surface_slug", "fields"}
DEPLOYMENT_CHANGE_FIELDS = {"surface_slug", "chain", "deployment_key", "fields"}
PUBLIC_FACTOR_FIELDS = {
    "factor_id",
    "scope_level",
    "surface_slug",
    "chain",
    "deployment_key",
    "expected_current_sha256",
    "score",
    "evidence_summary",
    "evidence_detail",
    "collection_mode",
    "gap_reason",
    "data_as_of",
    "sources",
}
STRIPPED_FACTOR_FIELDS = {"collected_by"}
REQUIRED_FACTOR_FIELDS = {
    "factor_id",
    "scope_level",
    "surface_slug",
    "chain",
    "deployment_key",
    "expected_current_sha256",
    "score",
    "evidence_summary",
    "collection_mode",
    "sources",
}
PUBLIC_SOURCE_FIELDS = {
    "source_type",
    "url",
    "reference",
    "title",
    "retrieved_at",
    "is_archived",
    "archive_url",
    "relation",
}
STRIPPED_SOURCE_FIELDS = {"retrieved_by", "notes"}
REQUIRED_SOURCE_FIELDS = {"source_type", "reference"}


def _exact_or_known_fields(
    value: Any,
    *,
    label: str,
    public: set[str],
    stripped: set[str] | None = None,
    required: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    stripped = stripped or set()
    unknown = set(value) - public - stripped
    if unknown:
        raise ContractError(f"{label} contains unsupported fields: {sorted(unknown)}")
    missing = (required or set()) - set(value)
    if missing:
        raise ContractError(f"{label} is missing required fields: {sorted(missing)}")
    return {key: deepcopy(item) for key, item in value.items() if key in public}


def sanitize_accepted_changes(document: dict[str, Any]) -> dict[str, Any]:
    """Strip only known private fields and reject every unknown payload shape."""
    result = _exact_or_known_fields(document, label="$", public=TOP_LEVEL_FIELDS)
    result["topology_contract"] = _exact_or_known_fields(
        document.get("topology_contract"),
        label="$.topology_contract",
        public=TOPOLOGY_FIELDS,
        required=TOPOLOGY_FIELDS,
    )
    result["scope"] = _exact_or_known_fields(
        document.get("scope"), label="$.scope", public=SCOPE_FIELDS, required=SCOPE_FIELDS
    )
    result["baseline"] = _exact_or_known_fields(
        document.get("baseline"),
        label="$.baseline",
        public=BASELINE_FIELDS,
        required=BASELINE_FIELDS,
    )
    changes = _exact_or_known_fields(
        document.get("changes"), label="$.changes", public=CHANGE_FIELDS, required=CHANGE_FIELDS
    )
    changes["protocol_fields"] = deepcopy(document["changes"]["protocol_fields"])
    changes["family_fields"] = deepcopy(document["changes"]["family_fields"])

    surface_changes = document["changes"].get("surfaces")
    if not isinstance(surface_changes, list):
        raise ContractError("$.changes.surfaces must be an array")
    changes["surfaces"] = [
        _exact_or_known_fields(
            item,
            label=f"$.changes.surfaces[{index}]",
            public=SURFACE_CHANGE_FIELDS,
            required=SURFACE_CHANGE_FIELDS,
        )
        for index, item in enumerate(surface_changes)
    ]

    deployment_changes = document["changes"].get("deployments")
    if not isinstance(deployment_changes, list):
        raise ContractError("$.changes.deployments must be an array")
    changes["deployments"] = [
        _exact_or_known_fields(
            item,
            label=f"$.changes.deployments[{index}]",
            public=DEPLOYMENT_CHANGE_FIELDS,
            required=DEPLOYMENT_CHANGE_FIELDS,
        )
        for index, item in enumerate(deployment_changes)
    ]

    factor_changes = document["changes"].get("factor_scores")
    if not isinstance(factor_changes, list):
        raise ContractError("$.changes.factor_scores must be an array")
    sanitized_factors = []
    for factor_index, factor in enumerate(factor_changes):
        label = f"$.changes.factor_scores[{factor_index}]"
        sanitized_factor = _exact_or_known_fields(
            factor,
            label=label,
            public=PUBLIC_FACTOR_FIELDS,
            stripped=STRIPPED_FACTOR_FIELDS,
            required=REQUIRED_FACTOR_FIELDS,
        )
        sources = factor.get("sources") if isinstance(factor, dict) else None
        if not isinstance(sources, list):
            raise ContractError(f"{label}.sources must be an array")
        sanitized_sources = []
        for source_index, source in enumerate(sources):
            source_label = f"{label}.sources[{source_index}]"
            sanitized_source = _exact_or_known_fields(
                source,
                label=source_label,
                public=PUBLIC_SOURCE_FIELDS,
                stripped=STRIPPED_SOURCE_FIELDS,
                required=REQUIRED_SOURCE_FIELDS,
            )
            sanitized_sources.append(sanitized_source)
        sanitized_factor["sources"] = sanitized_sources
        sanitized_factors.append(sanitized_factor)
    changes["factor_scores"] = sanitized_factors
    result["changes"] = changes
    return result


def find_private_material(value: Any) -> list[str]:
    """Return precise rejection reasons; never redact or reinterpret input."""
    errors: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            if item.get("is_published") is False:
                errors.append(f"{path}.is_published exposes unpublished material")
            for key, child in item.items():
                normalized = key.casefold()
                if normalized in FORBIDDEN_KEYS:
                    errors.append(f"{path}.{key} is a forbidden private field")
                if "review_token" in normalized or "unpublished" in normalized:
                    errors.append(f"{path}.{key} is a forbidden review/unpublished field")
                if any(token in normalized for token in ("password", "private_key", "api_key")):
                    errors.append(f"{path}.{key} is a forbidden secret field")
                visit(child, f"{path}.{key}")
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(item, str):
            return
        for pattern in SECRET_PATTERNS:
            if pattern.search(item):
                errors.append(f"{path} contains secret-like material")
                break
        for pattern in LOCAL_PATH_PATTERNS:
            if pattern.search(item):
                errors.append(f"{path} contains a local filesystem path")
                break
        for pattern in UNPUBLISHED_PATTERNS:
            if pattern.search(item):
                errors.append(f"{path} contains unpublished/review-token material")
                break
        for pattern in CURATOR_ONLY_PATTERNS:
            if pattern.search(item):
                errors.append(f"{path} contains curator-only material")
                break

    visit(value, "$")
    return errors
