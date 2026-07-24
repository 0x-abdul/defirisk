"""Validation for the public-safe input to lean refresh Task B.

The contract is deliberately semantic. It has no authorization receipt, attempt,
agent, prompt, plan-hash, or checksum fields. Authorization is the operator's
single confirmation of the human-readable batch plan.
"""

from __future__ import annotations

import json
import ipaddress
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "lean-protocol-refresh/v1"
RUBRIC_VERSION = "v1.7.0"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FACTOR_RE = re.compile(r"^RD-F-[0-9]{3}$")
CANONICAL_FACTOR_IDS = frozenset(
    f"RD-F-{index:03d}" for index in range(1, 186) if index != 169
)
EXPECTED_FACTOR_COUNT = len(CANONICAL_FACTOR_IDS)
OUTCOMES = {"changed", "no_change"}
SCORES = {"green", "yellow", "red", "gray", "not_assessed", "not_applicable"}
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
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ContractError(f"{label} must be a public HTTP(S) URL")
    hostname = parsed.hostname.lower()
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
    return value.strip()


def _reject_unsafe_material(value: Any, label: str = "change set") -> None:
    """Reject internal references anywhere in the public handoff."""
    if isinstance(value, dict):
        forbidden_keys = {
            "local_reference",
            "internal_reference",
            "private_url",
            "review_token",
            "collected_by",
            "retrieved_by",
        }
        for key, item in value.items():
            if str(key).lower() in forbidden_keys:
                raise ContractError(f"{label}.{key} is internal-only")
            _reject_unsafe_material(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe_material(item, f"{label}[{index}]")
        return
    if not isinstance(value, str):
        return
    text = value.strip()
    lowered = text.lower().replace("\\", "/")
    parsed_text = urlparse(text)
    is_http_url = (
        parsed_text.scheme in {"http", "https"} and bool(parsed_text.hostname)
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
    ):
        raise ContractError(f"{label} contains an internal reference or local path")
    for match in re.findall(r"https?://[^\s)>\"']+", text, flags=re.IGNORECASE):
        _public_url(match.rstrip(".,;"), label)


def _evidence(value: Any, label: str) -> Evidence:
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
    if "url" not in value and "reference" not in value:
        raise ContractError(f"{label} must contain a public URL locator")
    title = value.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ContractError(f"{label}.title must be null or non-empty text")
    archive_url = value.get("archive_url")
    if archive_url is not None:
        _public_url(archive_url, f"{label}.archive_url")
    reference = value.get("reference")
    if isinstance(reference, str) and (
        reference.lower().startswith("file:")
        or re.match(r"^[A-Za-z]:[\\/]", reference)
        or reference.startswith(("/home/", "/Users/"))
    ):
        raise ContractError(f"{label}.reference contains a local path")
    locator_key = "url" if "url" in value else "reference"
    return Evidence(
        url=_public_url(value[locator_key], f"{label}.{locator_key}"),
        title=title,
    )


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
        row_sources = row["sources"]
        if not isinstance(row_sources, list):
            raise ContractError(f"{label}.{row_name}.sources must be an array")
        for source_index, source in enumerate(row_sources):
            _evidence(
                source,
                f"{label}.{row_name}.sources[{source_index}]",
            )
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
    if (
        score not in {"not_assessed", "not_applicable"}
        and not value["new_value"]["sources"]
    ):
        raise ContractError(f"{label}.new_value.sources is required for graded rows")
    grade = value["resulting_grade"]
    if not isinstance(grade, str) or grade not in {"A", "B", "C", "D", "F"}:
        raise ContractError(f"{label}.resulting_grade is invalid")
    evidence_raw = value["evidence"]
    if not isinstance(evidence_raw, list):
        raise ContractError(f"{label}.evidence must be an array")
    evidence = tuple(
        _evidence(item, f"{label}.evidence[{index}]")
        for index, item in enumerate(evidence_raw)
    )
    if score not in {"not_assessed", "not_applicable"} and not evidence:
        raise ContractError(f"{label}.evidence is required for graded rows")
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
    )


def _protocol(value: Any, label: str, rubric_version: str) -> ProtocolRefresh:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    value = dict(value)
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
    )


def validate_change_set(value: Mapping[str, Any]) -> RefreshBatch:
    """Validate and normalize one complete, public-safe batch change set."""
    value = dict(value)
    _reject_unsafe_material(value)
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
