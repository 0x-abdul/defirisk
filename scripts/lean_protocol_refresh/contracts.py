"""Validation for the public-safe input to lean refresh Task B.

The contract is deliberately semantic. It has no authorization receipt, attempt,
agent, prompt, plan-hash, or checksum fields. Authorization is the operator's
single confirmation of the human-readable batch plan.
"""

from __future__ import annotations

import hashlib
import json
import ipaddress
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "lean-protocol-refresh/v1"
HISTORICAL_OLD_REMEDIATION_SCHEMA = (
    "lean-protocol-refresh/historical-old-remediation/v1"
)
MIXED_RECOVERY_SCHEMA = "lean-protocol-refresh/mixed-recovery/v1"
HISTORICAL_UNAVAILABLE_SUMMARY = (
    "No public-safe evidence can substantiate the retained historical score; "
    "it is shown only as immutable baseline state."
)
HISTORICAL_UNAVAILABLE_EXPLANATION = (
    "The retained score is immutable historical state and is not presented "
    "as a publicly substantiated claim."
)
RUBRIC_VERSION = "v1.7.0"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FACTOR_RE = re.compile(r"^RD-F-[0-9]{3}$")
CANONICAL_FACTOR_IDS = frozenset(
    f"RD-F-{index:03d}" for index in range(1, 186) if index != 169
)
EXPECTED_FACTOR_COUNT = len(CANONICAL_FACTOR_IDS)
OUTCOMES = {"changed", "no_change"}
SCORES = {"green", "yellow", "red", "gray", "not_assessed", "not_applicable"}
SOURCE_OPTIONAL_SCORES = {"not_assessed", "not_applicable"}
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
URL_REQUIRED_SOURCE_TYPES = {
    "url",
    "github",
    "etherscan",
    "transaction",
    "audit_report",
    "governance_post",
    "docs",
    "partner_feed",
}
CONDITIONAL_SOURCE_TYPES = {"curator_note", "partner_feed"}
COMPLETE_ROW_FIELDS = {
    "factor_id",
    "category",
    "family_slug",
    "scope_level",
    "surface_slug",
    "chain",
    "deployment_key",
    "score",
    "evidence_summary",
    "evidence_detail",
    "collection_mode",
    "gap_reason",
    "notes",
    "sources",
    "migration_change_reason",
    "migration_preservation_note",
    "preservation_note",
}


class ContractError(ValueError):
    """Raised before any external operation when a change set is unsafe."""


@dataclass(frozen=True)
class Evidence:
    url: str
    title: str | None = None


@dataclass(frozen=True)
class FactorChange:
    factor_id: str
    scope_level: str
    target: str
    old_value: Any
    new_value: Any
    evidence: tuple[Evidence, ...]
    resulting_score: str
    resulting_grade: str
    historical_old_remediation: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MixedRecovery:
    schema_version: str
    source_rubric_version: str
    target_rubric_version: str
    selection_policy: str
    full_target_projection: tuple[FactorChange, ...]
    full_target_projection_semantic_sha256: str
    protocol_change_semantic_sha256: str


@dataclass(frozen=True)
class ProtocolRefresh:
    family_slug: str
    surface_slugs: tuple[str, ...]
    deployment_targets: tuple[str, ...]
    outcome: str
    last_refreshed: str
    resulting_grade: str
    rubric_version: str
    changes: tuple[FactorChange, ...]
    previous_grade: str | None = None
    mixed_recovery: MixedRecovery | None = None


@dataclass(frozen=True)
class RefreshBatch:
    batch_id: str
    refresh_date: str
    rubric_version: str
    protocols: tuple[ProtocolRefresh, ...]


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _semantic_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read change set {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("change set must contain one JSON object")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ContractError(f"{label} fields invalid (missing={missing}, extra={extra})")


def _iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be an ISO date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO date") from exc
    return value


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SLUG_RE.fullmatch(value):
        raise ContractError(f"{label} is not a canonical slug")
    return value


def _public_url(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a public HTTP(S) URL")
    try:
        parsed = urlparse(value.strip())
        hostname_value = parsed.hostname
    except ValueError as exc:
        raise ContractError(f"{label} must be a public HTTP(S) URL") from exc
    if parsed.scheme not in {"http", "https"} or not hostname_value:
        raise ContractError(f"{label} must be a public HTTP(S) URL")
    hostname = hostname_value.lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if (
        parsed.username
        or parsed.password
        or hostname in {"localhost", "localhost.localdomain"}
        or hostname.endswith((".local", ".internal", ".localhost"))
        or (
            address is not None
            and (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
                or address.is_unspecified
            )
        )
    ):
        raise ContractError(f"{label} points to a private or credentialed location")
    if re.search(
        r"(?:^|[?&])(?:access_?token|api_?key|password|review_?token|secret|token)=",
        parsed.query,
        flags=re.IGNORECASE,
    ):
        raise ContractError(f"{label} contains a credential or review token")
    return value.strip()


def _reject_unsafe_material(value: Any, label: str = "change set") -> None:
    """Reject internal references anywhere in the public handoff."""
    if isinstance(value, dict):
        forbidden_keys = {
            "local_reference",
            "internal_reference",
            "private_url",
            "review_token",
            "api_token",
            "access_token",
            "token",
            "credentials",
            "collected_by",
            "retrieved_by",
        }
        scoped_label = label
        factor_id = value.get("factor_id")
        if isinstance(factor_id, str) and FACTOR_RE.fullmatch(factor_id):
            scoped_label = f"{label} ({factor_id})"
        for key, item in value.items():
            if str(key).lower() in forbidden_keys:
                raise ContractError(f"{scoped_label}.{key} is internal-only")
            _reject_unsafe_material(item, f"{scoped_label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe_material(item, f"{label}[{index}]")
        return
    if not isinstance(value, str):
        return
    text = value.strip()
    lowered = text.lower().replace("\\", "/")
    if re.search(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"|\b(?:gh[opsu]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
        r"|\bAKIA[0-9A-Z]{16}\b"
        r"|\b(?:postgres(?:ql)?|mysql|redis)://[^\s:/]+:[^\s@]+@",
        text,
        flags=re.IGNORECASE,
    ):
        raise ContractError(f"{label} contains a credential or secret-like value")
    bearer_placeholders = {
        "token",
        "<token>",
        "none",
        "null",
        "redacted",
        "example",
        "placeholder",
    }
    for bearer in re.finditer(
        r"\bAuthorization\s*:\s*Bearer\s+(?P<value>[^\s,;]+)",
        text,
        flags=re.IGNORECASE,
    ):
        bearer_value = bearer.group("value").strip("'\".").lower()
        if bearer_value not in bearer_placeholders:
            raise ContractError(f"{label} contains a bearer credential")
    credential_assignments = re.finditer(
        r"\b(?:access_?token|api_?key|api_?token|password|review_?token|secret)"
        r"\s*[:=]\s*(?P<value>[^\s,;]+)",
        text,
        flags=re.IGNORECASE,
    )
    harmless_values = {
        "none",
        "null",
        "redacted",
        "example",
        "placeholder",
        "not-set",
        "unset",
    }
    for assignment in credential_assignments:
        assigned_value = assignment.group("value").strip("'\".").lower()
        if assigned_value not in harmless_values:
            raise ContractError(f"{label} contains a credential or review token")
    if (
        "github.com/0x-abdul/defirisk-internal" in lowered
        or "api.github.com/repos/0x-abdul/defirisk-internal" in lowered
        or "raw.githubusercontent.com/0x-abdul/defirisk-internal" in lowered
    ):
        raise ContractError(f"{label} contains a private repository reference")
    try:
        parsed_text = urlparse(text)
        parsed_hostname = parsed_text.hostname
    except ValueError as exc:
        raise ContractError(f"{label} contains a malformed URL") from exc
    is_http_url = (
        parsed_text.scheme in {"http", "https"} and bool(parsed_hostname)
    )
    without_public_urls = re.sub(
        r"https?://[^\s)>\"',;]+", "", lowered, flags=re.IGNORECASE
    )
    if (
        re.search(r"(?:^|[\s('\"`])file:", without_public_urls)
        or re.search(r"(?<![a-z0-9])[a-z]:/", without_public_urls)
        or re.search(
            r"(?<![a-z0-9_.-])//[^/\s]+/",
            without_public_urls,
        )
        or re.search(
            r"(?<![a-z0-9_.-])\.\.?/[^\s)>\"']+",
            without_public_urls,
        )
        or re.search(
            r"(?<![a-z0-9_.-])/(?:home|users|opt|tmp|etc|var|srv|root|mnt|workspace)/",
            without_public_urls,
        )
        or re.search(r"(?<![a-z0-9_.-])\.research/", lowered)
        or (
            not is_http_url
            and re.search(
                r"(?<![a-z0-9_.-])(?:docs|scripts|data|db|research)/"
                r"[a-z0-9_./-]+\.(?:md|json|txt|ya?ml|csv)\b",
                lowered,
            )
        )
        or "local_reference" in lowered
        or "internal_reference" in lowered
        or "review_token" in lowered
        or lowered.startswith("unpublished/")
        or "/unpublished/" in lowered
        or re.search(
            r"\bunpublished\s+(?:analyst\s+)?(?:artifact|material|review|evidence)\b",
            lowered,
        )
        or re.search(
            r"\b(?:internal|private|data)[- ](?:cache|packet|baseline|"
            r"working evidence|working material|process reference)\b",
            lowered,
        )
        or re.search(
            r"\b(?:internal cache|internal process|working evidence|"
            r"curator working file|specialist handoff|reviewer handoff)\b",
            lowered,
        )
    ):
        raise ContractError(f"{label} contains an internal reference or local path")
    for match in re.findall(r"https?://[^\s)>\"']+", text, flags=re.IGNORECASE):
        _public_url(match.rstrip(".,;"), label)


def validate_public_material(value: Any, label: str = "public material") -> None:
    """Apply the portable handoff's recursive public-safety boundary."""
    _reject_unsafe_material(value, label)


def _source_type(value: Mapping[str, Any], label: str) -> str:
    source_type = value.get("source_type", "url")
    if source_type == "local_reference":
        raise ContractError(f"{label} has internal-only source_type 'local_reference'")
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        raise ContractError(
            f"{label}.source_type {source_type!r} is invalid or forbidden"
        )
    return source_type


def _validate_source(value: Any, label: str) -> tuple[str, str | None, str | None]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    supported = {
        "url",
        "reference",
        "title",
        "source_type",
        "relation",
        "retrieved_at",
        "archive_url",
        "notes",
        "score_id",
    }
    extra = sorted(set(value) - supported)
    if extra:
        raise ContractError(f"{label} contains unsupported fields: {extra}")
    source_type = _source_type(value, label)
    _reject_unsafe_material(value, label)
    for field in (
        "title",
        "reference",
        "relation",
        "retrieved_at",
        "notes",
        "score_id",
    ):
        field_value = value.get(field)
        if field_value is not None and (
            not isinstance(field_value, str) or not field_value.strip()
        ):
            raise ContractError(f"{label}.{field} must be null or non-empty text")
    retrieved_at = value.get("retrieved_at")
    if retrieved_at is not None:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved_at):
                date.fromisoformat(retrieved_at)
            elif re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T.+",
                retrieved_at,
            ):
                datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
            else:
                raise ValueError
        except ValueError as exc:
            raise ContractError(
                f"{label}.retrieved_at must be an ISO-8601 date or datetime"
            ) from exc
    title = value.get("title")
    archive_url = value.get("archive_url")
    if archive_url is not None:
        _public_url(archive_url, f"{label}.archive_url")
    reference = value.get("reference")
    if source_type in {"curator_note", "commit_sha"} and reference is None:
        raise ContractError(
            f"{label}.reference must be non-empty text for {source_type}"
        )
    if isinstance(reference, str) and (
        reference.lower().startswith("file:")
        or re.match(r"^[A-Za-z]:[\\/]", reference)
        or reference.startswith(("/home/", "/Users/"))
    ):
        raise ContractError(f"{label}.reference contains a local path")
    url = value.get("url")
    if source_type in URL_REQUIRED_SOURCE_TYPES:
        url = _public_url(url, f"{label}.url")
    elif url is not None:
        url = _public_url(url, f"{label}.url")
    return source_type, url, title


def source_public_errors(source: Any) -> list[str]:
    """Return stable public-handoff errors for one source record."""
    try:
        _validate_source(source, "source")
    except ContractError as exc:
        return [str(exc)]
    return []


def source_has_genuine_public_http(source: Any) -> bool:
    """Whether a source can substantiate a graded factor row."""
    try:
        source_type, url, _title = _validate_source(source, "source")
    except ContractError:
        return False
    return bool(url) and source_type not in CONDITIONAL_SOURCE_TYPES


def validate_factor_sources(row: Any, label: str) -> None:
    """Validate all source records and the evidence floor for one factor row."""
    if not isinstance(row, dict):
        raise ContractError(f"{label} must be a complete factor row")
    score = row.get("score")
    if score not in SCORES:
        raise ContractError(f"{label}.score is invalid")
    sources = row.get("sources")
    if not isinstance(sources, list):
        raise ContractError(f"{label}.sources must be an array")
    for index, source in enumerate(sources):
        _validate_source(source, f"{label}.sources[{index}]")
    if score not in SOURCE_OPTIONAL_SCORES and not any(
        source_has_genuine_public_http(source) for source in sources
    ):
        factor_id = row.get("factor_id", "<missing-factor>")
        raise ContractError(
            f"{label} ({factor_id}, {score}) requires at least one genuine "
            "public HTTP(S) evidence source; curator_note, partner_feed, and "
            "URL-less auxiliary records cannot satisfy a graded row"
        )


def _evidence(value: Any, label: str) -> Evidence | None:
    _source_type_value, url, title = _validate_source(value, label)
    if url is None:
        return None
    return Evidence(url=url, title=title)


def _change(
    value: Any,
    label: str,
    *,
    family_slug: str,
    surface_slugs: tuple[str, ...],
    deployment_targets: tuple[str, ...],
) -> FactorChange:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    value = dict(value)
    aliases = {
        "before": "old_value",
        "after": "new_value",
        "public_sources": "evidence",
        "score": "resulting_score",
        "grade": "resulting_grade",
    }
    for source, target in aliases.items():
        if source in value:
            if target in value:
                raise ContractError(f"{label} contains both {source} and {target}")
            value[target] = value.pop(source)
    scope_level = value.pop("scope_level", "surface")
    target = value.pop(
        "target",
        family_slug if scope_level == "family" else surface_slugs[0],
    )
    if scope_level not in {"protocol", "family", "surface", "deployment"}:
        raise ContractError(f"{label}.scope_level is invalid")
    if isinstance(target, dict):
        target_family = target.get("family_slug")
        target_surface = target.get("surface_slug")
        if target_family is not None and target_family != family_slug:
            raise ContractError(f"{label}.target names another family")
        if scope_level in {"protocol", "family"}:
            target = target_family or family_slug
        elif scope_level == "surface":
            target = target_surface
        else:
            deployment_key = target.get("deployment_key")
            chain = target.get("chain")
            target = (
                f"{target_surface}/{chain}/{deployment_key}"
                if target_surface and chain and deployment_key
                else None
            )
    if not isinstance(target, str) or not target:
        raise ContractError(f"{label}.target is invalid")
    if scope_level in {"protocol", "family"} and target != family_slug:
        raise ContractError(f"{label}.target names another family")
    if scope_level == "surface" and target not in surface_slugs:
        raise ContractError(f"{label}.target names another surface")
    if scope_level == "deployment":
        if target not in deployment_targets:
            raise ContractError(f"{label}.target is outside the approved deployments")

    historical_old_remediation = value.pop("historical_old_remediation", None)

    # The internal exporter retains complete public-safe old/new factor rows.
    # Their sources are validated here and the semantic values remain intact.
    if "old" in value or "new" in value:
        if "old" not in value or "new" not in value:
            raise ContractError(f"{label} must contain both old and new")
        if "old_value" in value or "new_value" in value:
            raise ContractError(f"{label} mixes old/new change formats")
        old_row = value.pop("old")
        new_row = value.pop("new")
        if not isinstance(old_row, dict) or not isinstance(new_row, dict):
            raise ContractError(f"{label}.old and .new must be objects")
        sources: list[Any] = []
        for row_name, row in (("old", old_row), ("new", new_row)):
            row_sources = row.get("sources", [])
            if not isinstance(row_sources, list):
                raise ContractError(f"{label}.{row_name}.sources must be an array")
            sources.extend(row_sources)
        if isinstance(historical_old_remediation, dict):
            remediation_sources = historical_old_remediation.get("sources", [])
            if not isinstance(remediation_sources, list):
                raise ContractError(
                    f"{label}.historical_old_remediation.sources must be an array"
                )
            sources.extend(remediation_sources)
        if (
            value.get("resulting_score") not in {"not_assessed", "not_applicable"}
            and not new_row.get("sources")
        ):
            raise ContractError(f"{label}.new.sources is required for graded rows")
        value["old_value"] = old_row
        value["new_value"] = new_row
        value["evidence"] = sources
    _exact_fields(
        value,
        {
            "factor_id",
            "old_value",
            "new_value",
            "evidence",
            "resulting_score",
            "resulting_grade",
        },
        label,
    )
    factor_id = value["factor_id"]
    if (
        not isinstance(factor_id, str)
        or not FACTOR_RE.fullmatch(factor_id)
        or factor_id not in CANONICAL_FACTOR_IDS
    ):
        raise ContractError(f"{label}.factor_id is invalid")
    unavailable_historical_evidence = False
    if historical_old_remediation is not None:
        remediation_label = f"{label}.historical_old_remediation"
        if not isinstance(historical_old_remediation, dict):
            raise ContractError(f"{remediation_label} must be an object")
        _exact_fields(
            historical_old_remediation,
            {
                "schema_version",
                "mode",
                "specialist",
                "baseline_fragment_semantic_sha256",
                "baseline_row_semantic_sha256",
                "explanation",
                "evidence_summary",
                "evidence_detail",
                "notes",
                "sources",
            },
            remediation_label,
        )
        if (
            historical_old_remediation["schema_version"]
            != HISTORICAL_OLD_REMEDIATION_SCHEMA
        ):
            raise ContractError(f"{remediation_label}.schema_version is invalid")
        mode = historical_old_remediation["mode"]
        if mode not in {"public_evidence", "historical_evidence_unavailable"}:
            raise ContractError(f"{remediation_label}.mode is invalid")
        specialist = historical_old_remediation["specialist"]
        if (
            not isinstance(specialist, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", specialist)
        ):
            raise ContractError(f"{remediation_label}.specialist is invalid")
        for field in (
            "baseline_fragment_semantic_sha256",
            "baseline_row_semantic_sha256",
        ):
            if not isinstance(historical_old_remediation[field], str) or not re.fullmatch(
                r"[0-9a-f]{64}", historical_old_remediation[field]
            ):
                raise ContractError(f"{remediation_label}.{field} is invalid")
        explanation = historical_old_remediation["explanation"]
        if not isinstance(explanation, str) or not explanation.strip():
            raise ContractError(f"{remediation_label}.explanation is required")
        _reject_unsafe_material(explanation, f"{remediation_label}.explanation")
        unavailable_historical_evidence = mode == "historical_evidence_unavailable"
        evidence_summary = historical_old_remediation["evidence_summary"]
        evidence_detail = historical_old_remediation["evidence_detail"]
        notes = historical_old_remediation["notes"]
        remediation_sources = historical_old_remediation["sources"]
        if not isinstance(evidence_summary, str) or not evidence_summary.strip():
            raise ContractError(f"{remediation_label}.evidence_summary is required")
        for field, field_value in (
            ("evidence_detail", evidence_detail),
            ("notes", notes),
        ):
            if field_value is not None and (
                not isinstance(field_value, str) or not field_value.strip()
            ):
                raise ContractError(
                    f"{remediation_label}.{field} must be null or non-empty text"
                )
        old_value_for_remediation = value.get("old_value")
        if not isinstance(old_value_for_remediation, dict):
            raise ContractError(
                f"{label}.old_value must be a complete factor row"
            )
        remediation_row = {
            "factor_id": factor_id,
            "score": old_value_for_remediation.get("score"),
            "sources": remediation_sources,
        }
        if mode == "public_evidence":
            validate_factor_sources(remediation_row, remediation_label)
            if not any(
                source_has_genuine_public_http(source)
                for source in remediation_sources
            ):
                raise ContractError(
                    f"{remediation_label}.sources must include genuine public "
                    "HTTP(S) evidence for public_evidence mode"
                )

    for row_name in ("old_value", "new_value"):
        row = value[row_name]
        if not isinstance(row, dict):
            raise ContractError(f"{label}.{row_name} must be a complete factor row")
        missing_row_fields = {"factor_id", "score", "sources"} - set(row)
        if missing_row_fields:
            raise ContractError(
                f"{label}.{row_name} is missing complete-row fields: "
                f"{sorted(missing_row_fields)}"
            )
        extra_row_fields = sorted(set(row) - COMPLETE_ROW_FIELDS)
        if extra_row_fields:
            raise ContractError(
                f"{label}.{row_name} contains unsupported fields: "
                f"{extra_row_fields}"
            )
        if row["factor_id"] != factor_id:
            raise ContractError(f"{label}.{row_name}.factor_id differs from wrapper")
        if row["score"] not in SCORES:
            raise ContractError(f"{label}.{row_name}.score is invalid")
        if row_name == "old_value" and historical_old_remediation is not None:
            if row.get("sources") != []:
                raise ContractError(
                    f"{label}.old_value.sources must be empty for an honest "
                    "historical evidence unavailable disposition"
                )
            if unavailable_historical_evidence and (
                evidence_summary != HISTORICAL_UNAVAILABLE_SUMMARY
                or evidence_detail is not None
                or notes is not None
                or explanation != HISTORICAL_UNAVAILABLE_EXPLANATION
                or remediation_sources != []
            ):
                raise ContractError(
                    f"{label}.historical_old_remediation must use the canonical "
                    "no-claim historical disposition text"
                )
        else:
            validate_factor_sources(row, f"{label}.{row_name}")
        row_scope = row.get("scope_level") or row.get("scope")
        if row_scope is not None and row_scope != scope_level:
            raise ContractError(f"{label}.{row_name}.scope_level differs from wrapper")
        row_family = row.get("family_slug")
        if row_family is not None and row_family != family_slug:
            raise ContractError(f"{label}.{row_name}.family_slug differs from wrapper")
        if scope_level == "surface":
            row_surface = row.get("surface_slug")
            if row_surface is not None and row_surface != target:
                raise ContractError(
                    f"{label}.{row_name}.surface_slug differs from wrapper"
                )
        if scope_level == "deployment":
            expected_surface, expected_chain, expected_key = target.split("/")
            expected_identity = {
                "surface_slug": expected_surface,
                "chain": expected_chain,
                "deployment_key": expected_key,
            }
            for field, expected_value in expected_identity.items():
                row_value = row.get(field)
                if row_value is not None and row_value != expected_value:
                    raise ContractError(
                        f"{label}.{row_name}.{field} differs from wrapper"
                    )
    score = value["resulting_score"]
    if score not in SCORES:
        raise ContractError(f"{label}.resulting_score is invalid")
    grade = value["resulting_grade"]
    if not isinstance(grade, str) or grade not in {"A", "B", "C", "D", "F"}:
        raise ContractError(f"{label}.resulting_grade is invalid")
    evidence_raw = value["evidence"]
    if not isinstance(evidence_raw, list):
        raise ContractError(f"{label}.evidence must be an array")
    evidence = tuple(
        parsed
        for index, item in enumerate(evidence_raw)
        if (parsed := _evidence(item, f"{label}.evidence[{index}]")) is not None
    )
    if isinstance(value["new_value"], dict):
        new_score = value["new_value"].get("score")
        if new_score != score:
            raise ContractError(f"{label}.resulting_score differs from new.score")
    return FactorChange(
        factor_id=factor_id,
        scope_level=scope_level,
        target=target,
        old_value=value["old_value"],
        new_value=value["new_value"],
        evidence=evidence,
        resulting_score=score,
        resulting_grade=grade,
        historical_old_remediation=historical_old_remediation,
    )


def _mixed_recovery(
    value: Any,
    label: str,
    *,
    family_slug: str,
    surface_slugs: tuple[str, ...],
    deployment_targets: tuple[str, ...],
    resulting_grade: str,
    changes: tuple[FactorChange, ...],
    protocol_change_semantic_sha256: str,
) -> MixedRecovery:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    _exact_fields(
        value,
        {
            "schema_version",
            "source_rubric_version",
            "target_rubric_version",
            "selection_policy",
            "full_target_projection",
            "full_target_projection_semantic_sha256",
            "protocol_change_semantic_sha256",
        },
        label,
    )
    if value["schema_version"] != MIXED_RECOVERY_SCHEMA:
        raise ContractError(f"{label}.schema_version is invalid")
    if (
        value["source_rubric_version"] != "v1.5.0"
        or value["target_rubric_version"] != RUBRIC_VERSION
    ):
        raise ContractError(
            f"{label} must declare the supported v1.5.0 to {RUBRIC_VERSION} route"
        )
    if value["selection_policy"] != "prefer_target_then_source":
        raise ContractError(f"{label}.selection_policy is invalid")

    projection = value["full_target_projection"]
    if not isinstance(projection, list):
        raise ContractError(f"{label}.full_target_projection must be an array")
    expected_projection_hash = value["full_target_projection_semantic_sha256"]
    if (
        not isinstance(expected_projection_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_projection_hash)
        or _semantic_sha256(projection) != expected_projection_hash
    ):
        raise ContractError(
            f"{label}.full_target_projection_semantic_sha256 is invalid"
        )
    expected_protocol_hash = value["protocol_change_semantic_sha256"]
    if (
        not isinstance(expected_protocol_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_protocol_hash)
        or expected_protocol_hash != protocol_change_semantic_sha256
    ):
        raise ContractError(f"{label}.protocol_change_semantic_sha256 is invalid")

    parsed_rows: list[FactorChange] = []
    sort_keys: list[tuple[str, str, str]] = []
    for index, item in enumerate(projection):
        row_label = f"{label}.full_target_projection[{index}]"
        if not isinstance(item, dict):
            raise ContractError(f"{row_label} must be an object")
        _exact_fields(item, {"factor_id", "scope_level", "target", "value"}, row_label)
        target_value = item["value"]
        if not isinstance(target_value, dict):
            raise ContractError(f"{row_label}.value must be a complete factor row")
        parsed = _change(
            {
                "factor_id": item["factor_id"],
                "scope_level": item["scope_level"],
                "target": item["target"],
                "old": target_value,
                "new": target_value,
                "resulting_score": target_value.get("score"),
                "resulting_grade": resulting_grade,
            },
            row_label,
            family_slug=family_slug,
            surface_slugs=surface_slugs,
            deployment_targets=deployment_targets,
        )
        parsed_rows.append(parsed)
        sort_keys.append((parsed.scope_level, parsed.target, parsed.factor_id))
    if sort_keys != sorted(sort_keys):
        raise ContractError(f"{label}.full_target_projection must be canonically sorted")
    if (
        len(parsed_rows) != EXPECTED_FACTOR_COUNT
        or {row.factor_id for row in parsed_rows} != CANONICAL_FACTOR_IDS
        or len(set(sort_keys)) != EXPECTED_FACTOR_COUNT
    ):
        raise ContractError(
            f"{label}.full_target_projection must contain the exact 184 canonical scoped rows"
        )
    projected = {
        (row.scope_level, row.target, row.factor_id): row.new_value
        for row in parsed_rows
    }
    for change in changes:
        key = (change.scope_level, change.target, change.factor_id)
        if projected.get(key) != change.new_value:
            raise ContractError(
                f"{label} target projection differs from approved change {change.factor_id}"
            )
    return MixedRecovery(
        schema_version=value["schema_version"],
        source_rubric_version=value["source_rubric_version"],
        target_rubric_version=value["target_rubric_version"],
        selection_policy=value["selection_policy"],
        full_target_projection=tuple(parsed_rows),
        full_target_projection_semantic_sha256=expected_projection_hash,
        protocol_change_semantic_sha256=expected_protocol_hash,
    )


def _protocol(value: Any, label: str, rubric_version: str) -> ProtocolRefresh:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    value = dict(value)
    mixed_recovery_raw = value.pop("mixed_recovery", None)
    protocol_change_semantic_sha256 = _semantic_sha256(value)
    previous_grade = value.pop("previous_grade", None)
    if previous_grade is not None and previous_grade not in {"A", "B", "C", "D", "F"}:
        raise ContractError(f"{label}.previous_grade is invalid")
    if "factor_changes" in value:
        if "changes" in value:
            raise ContractError(f"{label} contains both changes and factor_changes")
        value["changes"] = value.pop("factor_changes")
    if "effective_refresh_date" in value:
        effective = value.pop("effective_refresh_date")
        if effective != value.get("last_refreshed"):
            raise ContractError(
                f"{label}.effective_refresh_date differs from last_refreshed"
            )
    _exact_fields(
        value,
        {
            "family_slug",
            "surface_slugs",
            "topology",
            "outcome",
            "last_refreshed",
            "resulting_grade",
            "rubric_version",
            "changes",
        },
        label,
    )
    family_slug = _slug(value["family_slug"], f"{label}.family_slug")
    surfaces_raw = value["surface_slugs"]
    if not isinstance(surfaces_raw, list) or not surfaces_raw:
        raise ContractError(f"{label}.surface_slugs must be a non-empty array")
    surface_slugs = tuple(_slug(item, f"{label}.surface_slugs") for item in surfaces_raw)
    if len(set(surface_slugs)) != len(surface_slugs):
        raise ContractError(f"{label}.surface_slugs must be unique")
    topology = value["topology"]
    if not isinstance(topology, dict):
        raise ContractError(f"{label}.topology must be an object")
    _exact_fields(
        topology,
        {"mode", "family_slug", "surface_slugs", "deployment_targets"},
        f"{label}.topology",
    )
    if topology["mode"] != "preserve":
        raise ContractError(f"{label}.topology.mode must be preserve")
    if topology["family_slug"] != family_slug:
        raise ContractError(f"{label}.topology changes the canonical family")
    if topology["surface_slugs"] != list(surface_slugs):
        raise ContractError(f"{label}.topology changes canonical surfaces")
    deployment_targets_raw = topology["deployment_targets"]
    if not isinstance(deployment_targets_raw, list) or any(
        not isinstance(item, str)
        or len(item.split("/")) != 3
        or not all(item.split("/"))
        for item in deployment_targets_raw
    ):
        raise ContractError(
            f"{label}.topology.deployment_targets must contain surface/chain/key strings"
        )
    deployment_targets = tuple(deployment_targets_raw)
    if len(set(deployment_targets)) != len(deployment_targets):
        raise ContractError(
            f"{label}.topology.deployment_targets must be unique"
        )
    if any(item.split("/", 1)[0] not in surface_slugs for item in deployment_targets):
        raise ContractError(
            f"{label}.topology.deployment_targets names another surface"
        )
    outcome = value["outcome"]
    if outcome not in OUTCOMES:
        raise ContractError(f"{label}.outcome must be changed or no_change")
    last_refreshed = _iso_date(value["last_refreshed"], f"{label}.last_refreshed")
    resulting_grade = value["resulting_grade"]
    if resulting_grade not in {"A", "B", "C", "D", "F"}:
        raise ContractError(f"{label}.resulting_grade is invalid")
    protocol_rubric_version = value["rubric_version"]
    if protocol_rubric_version != RUBRIC_VERSION:
        raise ContractError(f"{label}.rubric_version must be {RUBRIC_VERSION}")
    if protocol_rubric_version != rubric_version:
        raise ContractError(f"{label}.rubric_version differs from batch rubric_version")
    changes_raw = value["changes"]
    if not isinstance(changes_raw, list):
        raise ContractError(f"{label}.changes must be an array")
    changes = tuple(
        _change(
            item,
            f"{label}.changes[{index}]",
            family_slug=family_slug,
            surface_slugs=surface_slugs,
            deployment_targets=deployment_targets,
        )
        for index, item in enumerate(changes_raw)
    )
    factor_keys = [
        (item.scope_level, item.target, item.factor_id) for item in changes
    ]
    if len(set(factor_keys)) != len(factor_keys):
        raise ContractError(f"{label}.changes contains duplicate factor rows")
    if outcome == "changed" and not changes:
        raise ContractError(f"{label} declares changed but has no changes")
    if outcome == "no_change" and changes:
        raise ContractError(f"{label} declares no_change but includes changes")
    if any(change.resulting_grade != resulting_grade for change in changes):
        raise ContractError(
            f"{label}.changes resulting_grade differs from protocol resulting_grade"
        )
    mixed_recovery = (
        _mixed_recovery(
            mixed_recovery_raw,
            f"{label}.mixed_recovery",
            family_slug=family_slug,
            surface_slugs=surface_slugs,
            deployment_targets=deployment_targets,
            resulting_grade=resulting_grade,
            changes=changes,
            protocol_change_semantic_sha256=protocol_change_semantic_sha256,
        )
        if mixed_recovery_raw is not None
        else None
    )
    return ProtocolRefresh(
        family_slug=family_slug,
        surface_slugs=surface_slugs,
        deployment_targets=deployment_targets,
        outcome=outcome,
        last_refreshed=last_refreshed,
        resulting_grade=resulting_grade,
        rubric_version=protocol_rubric_version,
        changes=changes,
        previous_grade=previous_grade,
        mixed_recovery=mixed_recovery,
    )


def validate_change_set(value: Mapping[str, Any]) -> RefreshBatch:
    """Validate and normalize one complete, public-safe batch change set."""
    value = dict(value)
    _reject_unsafe_material(value)
    has_rubric_migration = "rubric_migration" in value
    rubric_migration = value.pop("rubric_migration", None)
    if has_rubric_migration:
        if not isinstance(rubric_migration, dict):
            raise ContractError("rubric_migration must be an object")
        _exact_fields(
            rubric_migration,
            {"migration", "source_rubric_version", "target_rubric_version"},
            "rubric_migration",
        )
        if rubric_migration != {
            "migration": True,
            "source_rubric_version": "v1.5.0",
            "target_rubric_version": RUBRIC_VERSION,
        }:
            raise ContractError(
                "rubric_migration must declare the supported v1.5.0 to "
                f"{RUBRIC_VERSION} route"
            )
    # Task A may export one protocol directly. Normalize it to a one-item batch;
    # this remains intentionally independent rather than recreating campaigns.
    if "protocols" not in value and "family_slug" in value:
        schema_version = value.pop("schema_version", SCHEMA_VERSION)
        if schema_version != SCHEMA_VERSION:
            raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
        batch_id = value.pop("batch_id", value.get("refresh_id", "single-protocol"))
        value.pop("refresh_id", None)
        refresh_date = value.pop(
            "refresh_date", value.get("effective_refresh_date")
        )
        value = {
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_id,
            "refresh_date": refresh_date,
            "rubric_version": value.get("rubric_version"),
            "protocols": [value],
        }
    _exact_fields(
        value,
        {"schema_version", "batch_id", "refresh_date", "rubric_version", "protocols"},
        "change set",
    )
    if value["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
    rubric_version = value["rubric_version"]
    if rubric_version != RUBRIC_VERSION:
        raise ContractError(f"rubric_version must be {RUBRIC_VERSION}")
    batch_id = value["batch_id"]
    refresh_date = _iso_date(value["refresh_date"], "refresh_date")
    if batch_id is None:
        batch_id = f"refresh-{refresh_date}"
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ContractError("batch_id must be null or non-empty text")
    protocols_raw = value["protocols"]
    if not isinstance(protocols_raw, list) or not protocols_raw:
        raise ContractError("protocols must be a non-empty array")
    protocols = tuple(
        _protocol(item, f"protocols[{index}]", rubric_version)
        for index, item in enumerate(protocols_raw)
    )
    families = [item.family_slug for item in protocols]
    if len(set(families)) != len(families):
        raise ContractError("a batch may contain each family only once")
    return RefreshBatch(
        batch_id=batch_id.strip(),
        refresh_date=refresh_date,
        rubric_version=rubric_version,
        protocols=protocols,
    )


def load_change_set(path: Path | str) -> RefreshBatch:
    return validate_change_set(_load_json(Path(path)))
