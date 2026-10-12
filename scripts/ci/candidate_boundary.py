#!/usr/bin/env python3
"""Fail-closed checks for the public code-and-data repository boundary."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import html
import ipaddress
import json
import os
import re
import stat
import zlib
import subprocess
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote, urlsplit


CURRENT_VERSION = "v1.7.0"
RETIRABLE_API_VERSIONS = ("v1.5.0", "v1.6.0")
RETIREMENT_FIELD_CLASSIFICATION = {
    "classification": "git-versioned-publication-policy",
    "json_field_names": ["retired_api_versions"],
    "update_rule": "reviewed-public-pull-request-only",
}
MANIFEST_RELATIVE = Path("data/api/MANIFEST.sha256")
BASELINE_RELATIVE = Path("data/api/publication-baseline.json")
FIELD_REGISTRY_RELATIVE = Path("data/api/public-field-classification.json")

PROHIBITED_PREFIXES = (
    "tmp/",
    ".research/",
    ".private/",
    "_local/",
    "db/",
    "docs/ops/",
    "receipts/",
    "release-manifests/",
    "site/.astro/",
    "site/dist/",
    "site/test-results/",
    "site/playwright-report/",
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
    "access_token",
    "refresh_token",
    "api_token",
    "api_key",
    "api-key",
    "approval",
    "approval_identity",
    "approval_receipt",
    "collected_by",
    "collector",
    "curator",
    "backup_path",
    "client_secret",
    "credentials",
    "database_id",
    "database_row_id",
    "deployment_receipt",
    "do_not_publish",
    "internal_path",
    "private_url",
    "private_key",
    "password",
    "merged_by",
    "receipt",
    "review_token",
    "review_url",
    "reviewer",
    "rollback_reference",
    "signature",
    "specialist",
    "support_statement",
    "specialist_attested",
    "transaction_id",
}
PROHIBITED_API_KEYS.update({
    "retrieved_by", "reviewer_id", "reviewer_identity", "approved_by", "reviewed_by",
    "researcher", "researcher_id", "review", "review_notes", "review_material",
    "local_reference", "internal_reference", "approval_receipts", "approvals",
    "approval_metadata", "approval_signature", "receipts", "signatures", "private_snapshot",
})
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
    "authorization",
    "credential",
    "credentials",
    "key",
    "review_token",
    "reviewtoken",
    "secret",
    "signature",
    "sig",
    "token",
    "password",
    "jwt",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
}
PROHIBITED_SOURCE_TYPES = {"curator_note", "internal", "local_reference", "partner_feed", "private"}
PUBLIC_SOURCE_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PUBLIC_SCORES = {"green", "yellow", "red", "gray", "not_assessed", "not_applicable"}
SOURCE_OPTIONAL_SCORES = {"not_assessed", "not_applicable"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
API_VERSION = re.compile(r"^v\d+\.\d+\.\d+$")
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
API_ENDPOINTS = {"index.json", "factors.json", "hacks.json", "rubric.json", "history.json", "changes.json", "incidents.json", "status.json", "openapi.json", "schema/envelope.json", "schemas/envelope.json"}
API_METADATA = {"MANIFEST.sha256", "publication-baseline.json", "public-field-classification.json"}
HELD_PUBLICATION_STATES = {"held", "do_not_publish", "unpublished", "private_review", "draft"}
TEXT_SUFFIXES = {".json", ".html", ".htm", ".js", ".mjs", ".cjs", ".map", ".css", ".svg", ".xml", ".txt", ".yaml", ".yml"}
TEXT_FILENAMES = {"_headers", "_redirects", "robots.txt", "MANIFEST.sha256"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".mp3", ".mp4", ".webm", ".ogg", ".wav"}
BUILD_RECEIPT_SCHEMA = "defirisk.private.public-build-receipt/v1"
BUILD_RECEIPT_FIELDS = {"schema", "build_inputs", "api_files", "output_files"}
_ROBOTS_FIXED_DENIES = {"/dev/", "/data/api/", "/api/", "/_canonical_", "/unpublished/", "/control/"}
_PROTECTED_HEADER_ROUTES = {"/api/*/unpublished/*", "/unpublished/*", "/control/*"}
_WORKTREE_METADATA = {".git", "node_modules", "__pycache__", ".astro", ".venv", ".pytest_cache", ".gstack", "tmp", ".claire", ".clone", ".backups", "_local", ".worktrees", "dist", "test-results", "playwright-report"}
_HTTP_URL = re.compile(r"(?i)\bhttps?://[^\s\"'<>`]+")
_FILE_URL = re.compile(r"(?i)\bfile\s*://")
_WINDOWS_PATH = re.compile(r"(?:^|[\s\"'`({=:])(?:[a-zA-Z]:[\\/]|\\\\)[^\s\"'`<>]*")
_POSIX_PATH = re.compile(r"(?:^|[\s\"'`({=:])(?:~[\\/]|/(?:Users|home|root|tmp|var|private|mnt|etc|usr|opt|proc|sys|run|srv)/)[^\s\"'`<>]*", re.IGNORECASE)
_PRIVATE_REPOSITORY = re.compile(r"(?i)(?:github\.com[/.:]|raw\.githubusercontent\.com/|api\.github\.com/repos/)0x-abdul/defirisk-internal(?:\.git)?(?:[/?#\s]|$)")
_PRIVATE_REPOSITORY_PATH = re.compile(r"(?:^|[\s\"'`({=:])(?:\.research|\.private|_local|RiskProduct|risk-dashboard|defirisk-internal)[\\/]", re.IGNORECASE)
_RELATIVE_REPOSITORY_PATH = re.compile(r"(?:^|[\s\"'`(])(?:research|docs|scripts|data|db|site)[\\/]|(?:^|[\s\"'`(])(?:docs[\\/]ops|research[\\/]|\.\.[\\/])", re.IGNORECASE)
_WORKING_CONTEXT = re.compile(r"\b(?:local(?:-only)?\s+(?:db|database|packet|evidence|baseline|profile|review|derivation|factual|preservation|migration|green\s+threshold|inclusion\s+threshold|working\s+artifact|source)|current\s+local\s+[a-z0-9_-]+\s+row|(?:migration|baseline|working|internal|private|grading|accepted|remediation)\s+packet|(?:specialist|reviewer|agent)\s+(?:handoff|prompt|task|turn|context)|linked\s+locally|local-only|data[- ]cache|process[- ]learnings|00-(?:data-cache\.json|profile(?:\.meta)?\.(?:md|json)))\b", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:gh[opsu]_[a-zA-Z0-9_]{20,}|github_pat_[a-zA-Z0-9_]{20,}|AKIA[0-9A-Z]{16})\b|(?:postgres(?:ql)?|mysql|redis)://[^\s:/]+:[^\s@]+@", re.IGNORECASE)
_CREDENTIAL_ASSIGNMENT = re.compile(r"\b(?:api[_-]?key|access[_-]?token|review[_-]?token|authorization|password|client[_-]?secret)\s*[\"']?\s*[:=]\s*[\"']?[^\s\"'<>;,}]+", re.IGNORECASE)
_TOKEN_ASSIGNMENT = re.compile(r"(?i)(?<![A-Za-z0-9_])token(?![A-Za-z0-9_])=(?![=])['\"]?[A-Za-z0-9._~+/-]{8,}|(?<![A-Za-z0-9_])token(?![A-Za-z0-9_])\s+=\s*(?![=])['\"]?[A-Za-z0-9._~+/-]{24,}")
_ENCODING_DAMAGE = ("\ufffd", "â€”", "â€“", "â†’", "â†", "â‰¥", "â‰¤", "â€¦", "â€™", "â€œ", "â€")
_SENSITIVE_API_FIELD = re.compile(r"(?:^|[_\-.])(?:password|passwd|secret|secrets|token|tokens|credential|credentials|private[_-]?key|api[_-]?key|access[_-]?key|client[_-]?secret|authorization|bearer|cookie|dsn|connection[_-]?(?:string|uri)|(?:production|local|postgres|pg|database|db)[_-]?(?:url|dsn|uri))(?:$|[_\-.])", re.IGNORECASE)
_NON_SECRET_FIELD_NAMES = {"authorization_required", "state_tokens"}
_URL_INSPECTION_DEPTH = 6
_URL_INSPECTION_COUNT = 64
_URL_INSPECTION_CHARS = 65536
_HTTP_START = re.compile(r"(?i)(?=https?://)")
_JS_TOKENS = re.compile(
    r"(?P<comment>//[^\r\n]*|/\*.*?\*/)"
    r"|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)"
    r"|(?P<identifier>(?:[A-Za-z_$]|\\u(?:[0-9a-fA-F]{4}|\{[0-9a-fA-F]{1,6}\}))(?:[A-Za-z0-9_$]|\\u(?:[0-9a-fA-F]{4}|\{[0-9a-fA-F]{1,6}\}))*)"
    r"|(?P<number>0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)"
    r"|(?P<punct>===|!==|==|!=|=>|\+=|-=|\?\?|&&|\|\||[^\s])",
    re.DOTALL,
)
_JS_ESCAPES = re.compile(r"\\(?:u\{([0-9a-fA-F]{1,6})\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|([\s\S]))")
_JS_SCRIPT_MIMES = {
    "", "module", "application/ecmascript", "application/javascript",
    "application/x-ecmascript", "application/x-javascript", "text/ecmascript",
    "text/javascript", "text/javascript1.0", "text/javascript1.1",
    "text/javascript1.2", "text/javascript1.3", "text/javascript1.4",
    "text/javascript1.5", "text/jscript", "text/livescript",
    "text/x-ecmascript", "text/x-javascript",
}


def _decoded_text(value: str, *, decode_css: bool = True) -> str:
    """Decode transport encodings without evaluating JavaScript or markup."""
    decoded = value
    for _ in range(5):
        expanded = html.unescape(unquote(decoded))
        expanded = re.sub(r"\\u\{([0-9a-fA-F]{1,6})\}", lambda match: chr(int(match.group(1), 16)) if int(match.group(1), 16) <= 0x10FFFF else match.group(0), expanded)
        expanded = re.sub(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1) or match.group(2), 16)), expanded)
        if decode_css:
            expanded = re.sub(r"\\([0-9a-fA-F]{2,6})(?:\s|(?=[^0-9a-fA-F])|$)", lambda match: chr(int(match.group(1), 16)) if int(match.group(1), 16) <= 0x10FFFF else match.group(0), expanded)
        expanded = expanded.replace("\\/", "/")
        # Fold only adjacent static string literals. Never execute/evaluate code.
        expanded = re.sub(r"([\"'`])([^\"'`\r\n]*)\1\s*\+\s*([\"'`])([^\"'`\r\n]*)\3", lambda match: match.group(1) + match.group(2) + match.group(4) + match.group(1), expanded)
        if expanded == decoded:
            break
        decoded = expanded
    return decoded


def _normal_key(value: Any) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", _decoded_text(str(value))).casefold().replace("-", "_")


def _private_field(value: Any) -> bool:
    normalized = _normal_key(value)
    return normalized not in _NON_SECRET_FIELD_NAMES and (normalized in PROHIBITED_API_KEYS or bool(_SENSITIVE_API_FIELD.search(normalized)))


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BoundaryError("duplicate JSON object key is prohibited")
        result[key] = value
    return result


def _parse_json(value: str) -> Any:
    def reject_constant(_value: str) -> Any:
        raise BoundaryError("non-finite JSON number is prohibited")
    return json.loads(value, object_pairs_hook=_json_object, parse_constant=reject_constant)


def _display_source(value: str | Path) -> str:
    """Keep diagnostics logical; never echo operator paths or rejected keys."""
    text = str(value)
    checked = re.sub(r"^(?:data/api|site/dist)/", "", text)
    if len(text) > 240 or re.fullmatch(r"[A-Za-z0-9_./<>-]+", text) is None or scalar_material_reasons(checked):
        return f"<artifact-{hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:12]}>"
    return text


def _pointer_child(pointer: str, key: Any) -> str:
    text = str(key)
    if scalar_material_reasons(text) or len(text) > 120:
        text = f"<key-{hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:12]}>"
    return f"{pointer}/{text.replace('~', '~0').replace('/', '~1')}"


def _url_candidate(value: str) -> str:
    candidate = value.rstrip(".,;:!?)}")
    if candidate.endswith("]") and "[" not in candidate:
        candidate = candidate.rstrip("]")
    return candidate


def _url_component_is_safe(value: str, *, depth: int, budget: list[int]) -> bool:
    """Inspect query/fragment text while preserving genuine public URL paths."""
    decoded = _decoded_text(value, decode_css=False)
    views = {value, decoded}
    if any(_FILE_URL.search(view) or _WINDOWS_PATH.search(view) or _PRIVATE_REPOSITORY.search(view) for view in views):
        return False
    for view in views:
        outside_urls = _HTTP_URL.sub("<public-url>", view)
        if _POSIX_PATH.search(outside_urls) or _PRIVATE_REPOSITORY_PATH.search(outside_urls) or re.search(r"(?:^|[\s\"'`])\.\.[\\/]", outside_urls):
            return False
        if PRIVATE_ROUTE.search(outside_urls):
            return False
    # Use raw percent escapes for syntax. Decoding the enclosing URL before
    # parsing would turn a legitimate nested %20 filename into raw whitespace.
    for start in _HTTP_START.finditer(value):
        match = _HTTP_URL.match(value, start.start())
        if match and not _public_url_is_safe(_url_candidate(match.group(0)), https_only=False, _depth=depth + 1, _budget=budget):
            return False
    # A whole encoded locator may lack a raw HTTP start; inspect its decoded
    # form too, but do not replace an already recognized public URI value.
    if not _HTTP_START.search(value):
        for start in _HTTP_START.finditer(decoded):
            match = _HTTP_URL.match(decoded, start.start())
            if match and not _public_url_is_safe(_url_candidate(match.group(0)), https_only=False, _depth=depth + 1, _budget=budget):
                return False
    return True


def _public_url_is_safe(value: str, *, https_only: bool, _depth: int = 0, _budget: list[int] | None = None) -> bool:
    budget = _budget if _budget is not None else [_URL_INSPECTION_COUNT]
    if _depth > _URL_INSPECTION_DEPTH or budget[0] <= 0 or len(value) > _URL_INSPECTION_CHARS:
        return False
    budget[0] -= 1
    try:
        parsed = urlsplit(value.strip())
        raw_host = _decoded_text(parsed.hostname or "", decode_css=False).casefold()
        host = (raw_host if ":" in raw_host else raw_host.encode("idna").decode("ascii")).casefold().rstrip(".")
        _ = parsed.port  # Invalid/out-of-range ports fail closed too.
        if parsed.scheme not in ({"https"} if https_only else {"http", "https"}) or not host or parsed.username or parsed.password or "\\" in value or re.search(r"\s", value.strip()):
            return False
        labels = set(host.split("."))
        if host in {"localhost", "localhost.localdomain"} or labels & {"internal", "private", "local", "localhost"}:
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Browsers interpret decimal, octal, and hexadecimal IPv4 forms.
            # If strict ipaddress rejects an IP-like host, it must not fall
            # through as a DNS name (including IDNA width-normalized labels).
            last_label = host.split(".")[-1]
            if "." not in host or re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", last_label, re.IGNORECASE):
                return False
        else:
            if not address.is_global:
                return False
        query_rows = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=_URL_INSPECTION_COUNT)
        fragment_rows = parse_qsl(parsed.fragment, keep_blank_values=True, max_num_fields=_URL_INSPECTION_COUNT)
        query_keys = {re.sub(r"[_-]", "", _decoded_text(key, decode_css=False).casefold()) for key, _ in [*query_rows, *fragment_rows]}
        prohibited = {re.sub(r"[_-]", "", key) for key in PROHIBITED_URL_QUERY_KEYS} | {"refreshtoken", "apitoken"}
        if query_keys & prohibited or _PRIVATE_REPOSITORY.search(_decoded_text(value)):
            return False
        if PRIVATE_ROUTE.search(_decoded_text(value)) or any(part.casefold() in {"_local", ".research", ".private"} for part in _decoded_text(parsed.path, decode_css=False).split("/")):
            return False
        for key, item in [*query_rows, *fragment_rows]:
            if not _url_component_is_safe(key, depth=_depth, budget=budget) or not _url_component_is_safe(item, depth=_depth, budget=budget):
                return False
        # Fragment-only locators and HTTP addresses embedded in a public URL's
        # path are inspected as locators; ordinary path words stay permitted.
        if parsed.fragment and not fragment_rows and not _url_component_is_safe(parsed.fragment, depth=_depth, budget=budget):
            return False
        for start in _HTTP_START.finditer(parsed.path):
            match = _HTTP_URL.match(parsed.path, start.start())
            if match and not _public_url_is_safe(_url_candidate(match.group(0)), https_only=False, _depth=_depth + 1, _budget=budget):
                return False
        return True
    except (ValueError, UnicodeError):
        return False


def scalar_material_reasons(value: str) -> list[str]:
    """Return reasons, never rejected data. Public URL path words are allowed."""
    decoded = _decoded_text(value)
    locator_views = {value, _decoded_text(value, decode_css=False), decoded}
    reasons: set[str] = set()
    if any(_FILE_URL.search(view) for view in locator_views):
        reasons.add("file locator is prohibited")
    if any(_WINDOWS_PATH.search(view) for view in locator_views):
        reasons.add("private filesystem locator is prohibited")
    # Absolute public URLs are checked separately, avoiding docs/home/internal
    # path-word false positives while rejecting encoded private URL contents.
    without_urls = _HTTP_URL.sub("<public-url>", decoded)
    if any(_POSIX_PATH.search(_HTTP_URL.sub("<public-url>", view)) or _PRIVATE_REPOSITORY_PATH.search(_HTTP_URL.sub("<public-url>", view)) or _RELATIVE_REPOSITORY_PATH.search(_HTTP_URL.sub("<public-url>", view)) for view in locator_views):
        reasons.add("private filesystem or repository locator is prohibited")
    if PRIVATE_ROUTE.search(decoded) or re.search(r"(?:^|[\s\"'`])unpublished/", decoded, re.IGNORECASE):
        reasons.add("private review route is prohibited")
    if _PRIVATE_REPOSITORY.search(decoded):
        reasons.add("private repository URL is prohibited")
    for match in _HTTP_URL.finditer(decoded):
        candidate = _url_candidate(match.group(0))
        if not _public_url_is_safe(candidate, https_only=False):
            reasons.add("private, credentialed, or tokenized URL is prohibited")
    if _SECRET_VALUE.search(decoded) or _CREDENTIAL_ASSIGNMENT.search(decoded) or _TOKEN_ASSIGNMENT.search(decoded):
        reasons.add("secret-like material is prohibited")
    if _WORKING_CONTEXT.search(without_urls):
        reasons.add("private working-evidence wording is prohibited")
    if any(marker in decoded for marker in _ENCODING_DAMAGE):
        reasons.add("text encoding damage is prohibited")
    return sorted(reasons)


class BoundaryError(ValueError):
    """The selected tree violates the public repository boundary."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = _parse_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise BoundaryError("invalid or unreadable public JSON artifact") from None
    if not isinstance(value, dict):
        raise BoundaryError("public JSON artifact must be an object")
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


def _citation_errors(citation: Any, source: str, pointer: str) -> list[str]:
    label = f"{_display_source(source)}{pointer}"
    if (
        not isinstance(citation, dict)
        or not set(citation).issubset(PUBLIC_SOURCE_FIELDS)
        or not isinstance(citation.get("source_type"), str)
        or not PUBLIC_SOURCE_TYPE.fullmatch(citation["source_type"])
        or citation["source_type"].casefold() in PROHIBITED_SOURCE_TYPES
    ):
        return [f"{label}: citation shape is not public-safe"]
    failures: list[str] = []
    url = citation.get("url")
    if not isinstance(url, str) or not url.strip():
        failures.append(f"{label}: citation needs a public HTTPS URL")
    elif not public_source_url_is_safe(url):
        failures.append(f"{label}: citation URL is not public-safe")
    retrieved_at = citation.get("retrieved_at")
    if retrieved_at is not None:
        valid = isinstance(retrieved_at, str)
        if valid:
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved_at):
                    date.fromisoformat(retrieved_at)
                elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", retrieved_at):
                    datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
                else:
                    valid = False
            except ValueError:
                valid = False
        if not valid:
            failures.append(f"{label}: citation retrieved_at is invalid")
    return failures


def _factor_errors(factor: dict[str, Any], source: str, pointer: str) -> list[str]:
    label = f"{_display_source(source)}{pointer}"
    failures: list[str] = []
    if not isinstance(factor.get("score"), str) or factor["score"] not in PUBLIC_SCORES:
        failures.append(f"{label}: factor score is invalid")
    if not isinstance(factor.get("evidence_summary"), str) or not factor["evidence_summary"].strip():
        failures.append(f"{label}: evidence_summary is required")
    sources = factor.get("sources")
    if not isinstance(sources, list):
        failures.append(f"{label}: sources must be an array")
    elif not (isinstance(factor.get("score"), str) and factor["score"] in SOURCE_OPTIONAL_SCORES) and not sources:
        failures.append(f"{label}: assessed factor requires a public citation")
    return failures


def _held_markers(value: dict[str, Any]) -> bool:
    expected = {"editorial_status": "published", "assessment_eligibility": "eligible", "assessment_grade_status": "rated", "publication_exception": "none", "projection_visibility": "public", "is_published": True, "protocol_is_published": True, "family_is_published": True}
    return any(key in value and ((value[key] is not required) if isinstance(required, bool) else value[key] != required) for key, required in expected.items()) or value.get("do_not_publish") is True


def _registered_schema(source: str, value: Any) -> bool:
    known_path = source == "site/dist/openapi.json" or bool(re.fullmatch(r"(?:data/api|site/dist/api)/v\d+\.\d+\.\d+/(?:(?:schema|schemas)/envelope|openapi)\.json", source))
    return known_path and isinstance(value, dict) and ("$schema" in value or "openapi" in value)


def _source_map_reference_is_safe(value: str) -> bool:
    decoded = _decoded_text(value).replace("\\", "/")
    parts = decoded.split("/")
    if not decoded or "\x00" in decoded or _WINDOWS_PATH.search(decoded) or decoded.startswith("/") or ":" in decoded or any(part in {"_local", ".research", ".private", ".git", "receipts", "release-manifests"} for part in parts):
        return False
    while decoded.startswith(("../", "./")):
        decoded = decoded.split("/", 1)[1]
    return decoded.startswith(("src/", "site/src/", "public/", "node_modules/")) or "/" not in decoded


def scan_api_value(value: Any, source: str, pointer: str = "", *, validate_citations: bool = True, documentary_role: str | None = None) -> list[str]:
    """Check every scalar/key and citation, regardless of endpoint or scope."""
    failures: list[str] = []
    source = _display_source(source)
    if not pointer and documentary_role is None and _registered_schema(source, value):
        documentary_role = "openapi" if "openapi" in value else "schema"
    if isinstance(value, dict):
        actual_data_context = bool(re.search(r"/(?:example|examples|default)(?:/|$)", pointer))
        property_map = documentary_role in {"schema", "openapi"} and pointer.endswith("/properties") and not actual_data_context
        if not property_map and _held_markers(value):
            failures.append(f"{source}{pointer}: held or ineligible assessment markers are prohibited")
        if not property_map and value.get("assessment_available") is False and (any(value.get(key) is not None for key in ("headline_grade", "risk_score")) or any(value.get(key) for key in ("category_severities", "factor_scores", "grade_history", "deployment_factor_scores"))):
            failures.append(f"{source}{pointer}: unavailable assessment may not expose grades or evidence")
        illustrative_example = documentary_role in {"schema", "openapi"} and bool(re.search(r"/(?:example|examples)(?:/|$)", pointer))
        if not property_map and not illustrative_example and "score" in value and ("factor_id" in value or "evidence_summary" in value):
            failures.extend(_factor_errors(value, source, pointer))
        for key, child in value.items():
            normalized = _normal_key(key)
            child_pointer = _pointer_child(pointer, key)
            for reason in scalar_material_reasons(str(key)):
                failures.append(f"{source}{child_pointer}: unsafe object key ({reason})")
            property_definition = property_map and isinstance(child, dict) and any(field in child for field in ("type", "$ref", "properties", "allOf", "anyOf", "oneOf"))
            if not property_definition and _private_field(key):
                failures.append(f"{source}{child_pointer}: prohibited private field")
            if not property_definition and normalized in OPERATIONAL_STATUS_KEYS:
                failures.append(f"{source}{child_pointer}: live telemetry field is not versioned API data")
            if not property_definition and normalized in RAW_DATABASE_TIMESTAMP_KEYS:
                failures.append(f"{source}{child_pointer}: raw database timestamp is prohibited")
            if not property_definition and normalized == "is_published" and child is not True:
                failures.append(f"{source}{child_pointer}: only published protocol data is allowed")
            if normalized in {"status", "publication_status", "lifecycle_status", "activation_status"} and isinstance(child, str) and child.casefold() in HELD_PUBLICATION_STATES:
                failures.append(f"{source}{child_pointer}: held or private lifecycle state is prohibited")
            if validate_citations and normalized == "sources" and isinstance(child, list):
                for index, citation in enumerate(child):
                    failures.extend(_citation_errors(citation, source, f"{child_pointer}/{index}"))
            if validate_citations and normalized == "source_type" and isinstance(child, str):
                failures.extend(_citation_errors(value, source, pointer))
            # This exact registry locator documents the denied destination. It
            # grants no exemption to keys, siblings, schema examples, or text.
            registry_sources = {FIELD_REGISTRY_RELATIVE.as_posix(), f"site/dist/api/{FIELD_REGISTRY_RELATIVE.name}"}
            if source in registry_sources and child_pointer == "/live_operational_telemetry/never_committed_under" and child == "data/api/**":
                continue
            failures.extend(scan_api_value(child, source, child_pointer, validate_citations=validate_citations, documentary_role=documentary_role))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            failures.extend(scan_api_value(child, source, f"{pointer}/{index}", validate_citations=validate_citations, documentary_role=documentary_role))
    elif isinstance(value, str):
        reasons = scalar_material_reasons(value)
        if documentary_role == "source-map" and re.fullmatch(r"/sources/\d+", pointer) and _source_map_reference_is_safe(value):
            reasons = [reason for reason in reasons if reason != "private filesystem or repository locator is prohibited"]
        failures.extend(f"{source}{pointer}: {reason}" for reason in reasons)
    return sorted(set(failures))


def public_source_url_is_safe(value: str) -> bool:
    return _public_url_is_safe(value, https_only=True) and not scalar_material_reasons(value)


def validate_protocol_citations(detail: dict[str, Any], source: str) -> list[str]:
    source = _display_source(source)
    failures: list[str] = scan_api_value(detail, source)
    factors = detail.get("data", {}).get("protocol_data", {}).get("factor_scores")
    if not isinstance(factors, list):
        return [f"{source}: data.protocol_data.factor_scores must be an array"]
    seen: set[tuple[Any, ...]] = set()
    for index, factor in enumerate(factors):
        pointer = f"{source}/data/protocol_data/factor_scores/{index}"
        if not isinstance(factor, dict):
            failures.append(f"{pointer}: factor score must be an object")
            continue
        factor_id = factor.get("factor_id")
        scope_key = tuple(json.dumps(factor.get(key), sort_keys=True) for key in ("factor_id", "scope_level", "family_slug", "surface_id", "surface_slug", "deployment_id", "deployment_key", "chain"))
        if not isinstance(factor_id, str) or not factor_id or scope_key in seen:
            failures.append(f"{pointer}: scoped factor_id must be non-empty and unique")
        else:
            seen.add(scope_key)
    return sorted(set(failures))


def slug_digest(slugs: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(slugs)).encode("utf-8")).hexdigest()


def file_manifest(root: Path) -> str:
    api_root = root / "data" / "api"
    return _api_manifest(api_root)


def _api_manifest(api_root: Path) -> str:
    rows: list[str] = []
    for path in sorted(api_root.rglob("*"), key=lambda entry: entry.relative_to(api_root).as_posix()):
        if _is_link(path):
            raise BoundaryError("symlinks are prohibited in public API data")
        if not path.is_file() or path == api_root / MANIFEST_RELATIVE.name:
            continue
        relative = f"data/api/{path.relative_to(api_root).as_posix()}"
        content = path.read_bytes()
        if b"\x00" not in content:
            content = content.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(content).hexdigest()
        rows.append(f"{digest}  {relative}")
    return "\n".join(rows) + "\n"


def validate_manifest(root: Path, *, api_root: Path | None = None) -> list[str]:
    selected_api = api_root or root / "data" / "api"
    expected_path = selected_api / MANIFEST_RELATIVE.name
    if not expected_path.is_file():
        return [f"{MANIFEST_RELATIVE.as_posix()}: missing"]
    try:
        expected = expected_path.read_text(encoding="utf-8")
        actual = _api_manifest(selected_api)
    except (OSError, UnicodeError, BoundaryError):
        return [f"{MANIFEST_RELATIVE.as_posix()}: unreadable or unsafe public API tree"]
    if expected != actual:
        return [f"{MANIFEST_RELATIVE.as_posix()}: does not match committed data/api tree"]
    return []


def validate_status_registry(root: Path, *, api_root: Path | None = None) -> list[str]:
    failures: list[str] = []
    selected_api = api_root or root / "data" / "api"
    registry = load_json(selected_api / FIELD_REGISTRY_RELATIVE.name)
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
    for status_path in sorted(selected_api.glob("v*/status.json")):
        status = load_json(status_path)
        actual = json_leaf_pointers(status)
        if actual != expected:
            failures.append(
                f"data/api/{status_path.relative_to(selected_api).as_posix()}: status classification mismatch "
                f"(missing={len(expected - actual)}, unexpected={len(actual - expected)})"
            )
        snapshot = status.get("data", {}).get("assessment_snapshot", {})
        index = load_json(status_path.parent / "index.json")
        rows = index.get("data", {}).get("protocols")
        if (
            status.get("rubric_version") != status_path.parent.name
            or snapshot.get("rubric_version") != status.get("rubric_version")
            or snapshot.get("data_as_of") != status.get("data_as_of")
            or snapshot.get("projection_timestamp") != status.get("generated_at")
            or not isinstance(rows, list)
            or type(snapshot.get("published_protocol_count")) is not int
            or snapshot.get("published_protocol_count") != len(rows)
        ):
            failures.append(f"data/api/{status_path.parent.name}/status.json: assessment snapshot binding mismatch")
    return failures


def validate_api_version(root: Path, version_root: Path, *, api_root: Path | None = None) -> list[str]:
    failures: list[str] = []
    selected_api = api_root or root / "data" / "api"
    relative_root = f"data/api/{version_root.relative_to(selected_api).as_posix()}"
    if (version_root / "unpublished").exists():
        failures.append(f"{relative_root}/unpublished: private review subtree is prohibited")
    for endpoint in sorted(API_ENDPOINTS):
        if not (version_root / endpoint).is_file():
            failures.append(f"{relative_root}/{endpoint}: required public endpoint is missing")

    index = load_json(version_root / "index.json")
    rows = index.get("data", {}).get("protocols")
    if not isinstance(rows, list):
        return [f"{relative_root}/index.json: data.protocols must be an array"]
    slugs = [row.get("slug") for row in rows if isinstance(row, dict)]
    if len(slugs) != len(rows) or not all(isinstance(slug, str) and SLUG.fullmatch(slug) for slug in slugs):
        failures.append(f"{relative_root}/index.json: every protocol needs a stable slug")
    slugs = [slug for slug in slugs if isinstance(slug, str) and SLUG.fullmatch(slug)]
    if len(set(slugs)) != len(slugs):
        failures.append(f"{relative_root}/index.json: duplicate protocol slug")

    protocol_root = version_root / "protocols"
    detail_paths = set(protocol_root.glob("*.json")) if protocol_root.is_dir() else set()
    expected_paths = {protocol_root / f"{slug}.json" for slug in slugs}
    aliases: dict[str, tuple[str, str]] = {}
    for detail_path in sorted(expected_paths):
        if detail_path.is_file():
            detail = load_json(detail_path)
            failures.extend(validate_protocol_citations(detail, f"{relative_root}/protocols/{detail_path.name}"))
            for surface in detail.get("data", {}).get("protocol_data", {}).get("surfaces", []):
                if not isinstance(surface, dict):
                    continue
                alias = surface.get("legacy_slug")
                surface_slug = surface.get("surface_slug")
                if isinstance(alias, str) and SLUG.fullmatch(alias) and alias not in slugs and isinstance(surface_slug, str) and SLUG.fullmatch(surface_slug) and surface.get("assessment_available") is True:
                    target = (detail_path.stem, surface_slug)
                    if alias in aliases and aliases[alias] != target:
                        failures.append(f"{relative_root}/protocols: ambiguous compatibility alias")
                    aliases[alias] = target
    for alias, (canonical, surface_slug) in aliases.items():
        alias_path = protocol_root / f"{alias}.json"
        expected_paths.add(alias_path)
        if alias_path.is_file():
            detail = load_json(alias_path)
            protocol = detail.get("data", {}).get("protocol_data", {}).get("protocol", {})
            if protocol.get("canonical_family_slug") != canonical or protocol.get("selected_surface_slug") != surface_slug:
                failures.append(f"{relative_root}/protocols: compatibility alias identity mismatch")
            failures.extend(validate_protocol_citations(detail, f"{relative_root}/protocols/{alias}.json"))
    nested_paths = {path for path in protocol_root.rglob("*") if path.is_file()} - detail_paths if protocol_root.is_dir() else set()
    allowed_histories = {protocol_root / slug / "history.json" for slug in [*slugs, *aliases]}
    if detail_paths != expected_paths or nested_paths - allowed_histories:
        failures.append(f"{relative_root}/protocols: detail files must match published identities exactly")

    published = set(slugs) | set(aliases)
    for directory, payload_key in (("factors", "factors"), ("hacks", "hacks")):
        index_rows = load_json(version_root / f"{directory}.json").get("data", {}).get(payload_key)
        if not isinstance(index_rows, list):
            failures.append(f"{relative_root}/{directory}.json: invalid definition index")
            continue
        identifiers = [row.get("id") for row in index_rows if isinstance(row, dict)]
        if len(identifiers) != len(index_rows) or not all(isinstance(identifier, str) and IDENTITY.fullmatch(identifier) for identifier in identifiers):
            failures.append(f"{relative_root}/{directory}.json: invalid definition identity")
            continue
        if len(set(identifiers)) != len(identifiers):
            failures.append(f"{relative_root}/{directory}.json: duplicate definition identity")
        expected = {version_root / directory / f"{identifier}.json" for identifier in identifiers}
        actual = {path for path in (version_root / directory).rglob("*") if path.is_file()}
        if expected != actual:
            failures.append(f"{relative_root}/{directory}: definition files must match the index exactly")
    for factor_path in sorted((version_root / "factors").glob("*.json")):
        factor = load_json(factor_path)
        scored = factor.get("data", {}).get("factor_data", {}).get("scored_protocols")
        if not isinstance(scored, list):
            failures.append(f"{relative_root}/factors/{factor_path.name}: scored_protocols must be an array")
            continue
        for row in scored:
            slug = row.get("protocol_slug") if isinstance(row, dict) else None
            if slug and slug not in published:
                failures.append(
                    f"{relative_root}/factors/{factor_path.name}: score exposes non-published slug"
                )
        scored_surfaces = factor.get("data", {}).get("factor_data", {}).get("scored_surfaces", [])
        if not isinstance(scored_surfaces, list):
            failures.append(f"{relative_root}/factors/{factor_path.name}: scored_surfaces must be an array")
        else:
            for row in scored_surfaces:
                slug = (row.get("protocol_slug") or row.get("family_slug")) if isinstance(row, dict) else None
                if slug not in published:
                    failures.append(f"{relative_root}/factors/{factor_path.name}: surface score exposes non-published identity")

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


def _is_link(path: Path) -> bool:
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            return True
    return False


def _iter_tree(root: Path, *, worktree: bool = False, ignored_roots: frozenset[str] = frozenset()) -> Iterable[Path]:
    ignored = set(ignored_roots)
    qualified_worktree = False
    if worktree and (root / ".git").exists() and not _is_link(root / ".git"):
        try:
            result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, check=False, timeout=10)
            qualified_worktree = result.returncode == 0 and result.stdout.strip() == b"true"
        except (OSError, subprocess.TimeoutExpired):
            pass

    def is_ignored(path: Path) -> bool:
        relative = path.relative_to(root).as_posix()
        if relative in ignored:
            return True
        if not qualified_worktree or path.name not in _WORKTREE_METADATA:
            return False
        if relative == ".git":
            ignored.add(relative)
            return True
        try:
            tracked = subprocess.run(["git", "ls-files", "--cached", "--", relative], cwd=root, capture_output=True, check=False, timeout=10)
            ignore = subprocess.run(["git", "check-ignore", "-q", "--", relative], cwd=root, capture_output=True, check=False, timeout=10)
            if tracked.returncode == 0 and not tracked.stdout and ignore.returncode == 0:
                ignored.add(relative)
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False

    def unreadable(_error: OSError) -> None:
        raise BoundaryError("unreadable public artifact tree") from None

    for directory, dirnames, filenames in os.walk(root, followlinks=False, onerror=unreadable):
        current = Path(directory)
        for name in sorted(dirnames):
            path = current / name
            if not _is_link(path) and is_ignored(path):
                continue
            yield path
        dirnames[:] = sorted(name for name in dirnames if not _is_link(current / name) and not is_ignored(current / name))
        for name in sorted(filenames):
            if not _is_link(current / name) and is_ignored(current / name):
                continue
            yield current / name


def _supported_api_path(relative: str) -> bool:
    if relative in API_METADATA:
        return True
    parts = relative.split("/")
    if not parts or not API_VERSION.fullmatch(parts[0]):
        return False
    tail = "/".join(parts[1:])
    if tail in API_ENDPOINTS or tail == "openapi.yaml":
        return True
    if len(parts) == 3 and parts[1] in {"protocols", "factors", "hacks"}:
        return parts[2].endswith(".json") and bool(IDENTITY.fullmatch(parts[2][:-5]))
    return len(parts) == 4 and parts[1] == "protocols" and bool(IDENTITY.fullmatch(parts[2])) and parts[3] == "history.json"


def _path_failures(path: Path, relative: str) -> list[str]:
    label = _display_source(relative)
    failures: list[str] = []
    if _is_link(path):
        failures.append(f"{label}: symlinks or junctions are prohibited in the public tree")
    if any(relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in PROHIBITED_PREFIXES):
        failures.append(f"{label}: private path is prohibited")
    if relative in PROHIBITED_EXACT_PATHS:
        failures.append(f"{label}: retired control-plane path is prohibited")
    parts = relative.replace("\\", "/").split("/")
    if any(part in {".git", ".research", ".private", "_local", ".worktrees", ".astro", ".venv", ".pytest_cache", ".gstack", ".claire", ".clone", ".backups", "__pycache__", "node_modules"} or part == ".env" or part.startswith(".env.") for part in parts):
        failures.append(f"{label}: private or workspace-only artifact path is prohibited")
    if "/unpublished/" in f"/{relative}/" or relative.endswith("/unpublished"):
        failures.append(f"{label}: unpublished path is prohibited")
    return failures


def validate_retired_api_versions(baseline: dict, *, present_versions=None) -> tuple[str, ...]:
    value = baseline.get("retired_api_versions", [])
    if (not isinstance(value, list)
        or any(not isinstance(v, str) or v not in RETIRABLE_API_VERSIONS for v in value)
        or value != sorted(set(value)) or baseline.get("current_api_version") in value):
        raise BoundaryError("invalid_retired_api_versions")
    if present_versions is not None and set(value).intersection(present_versions):
        raise BoundaryError("retired_api_version_artifacts_present")
    return tuple(value)


def validate_api_tree(api_root: Path, *, check_manifest: bool = True) -> list[str]:
    """Validate a complete API tree, including all retained version directories."""
    if _is_link(api_root) or not api_root.is_dir():
        return ["data/api: missing or unsafe public API tree"]
    failures: list[str] = []
    try:
        paths = list(_iter_tree(api_root))
    except (BoundaryError, OSError):
        return ["data/api: unreadable artifact tree"]
    for path in paths:
        relative = path.relative_to(api_root).as_posix()
        failures.extend(_path_failures(path, relative))
        if _is_link(path) or not path.is_file():
            continue
        logical = f"data/api/{relative}"
        if not _supported_api_path(relative):
            failures.append(f"{_display_source(logical)}: unlisted public API endpoint path")
        if path.suffix == ".json":
            try:
                failures.extend(scan_api_value(load_json(path), logical))
            except BoundaryError:
                failures.append(f"{_display_source(logical)}: invalid or unreadable JSON artifact")
        elif path.name != MANIFEST_RELATIVE.name:
            if path.suffix.casefold() not in {".yaml", ".yml"}:
                failures.append(f"{_display_source(logical)}: unsupported public API artifact type")
            failures.extend(_scan_text_file(path, logical))
    versions = sorted(path for path in api_root.iterdir() if path.is_dir() and not _is_link(path))
    for version_root in versions:
        if not API_VERSION.fullmatch(version_root.name):
            failures.append("data/api: unsupported directory outside versioned API roster")
            continue
        try:
            failures.extend(validate_api_version(api_root.parent.parent, version_root, api_root=api_root))
        except (BoundaryError, AttributeError, TypeError, KeyError):
            failures.append(f"data/api/{version_root.name}: incomplete or invalid versioned API tree")
    if not versions:
        failures.append("data/api: no versioned public API trees found")
    try:
        baseline = load_json(api_root / BASELINE_RELATIVE.name)
        current_version = baseline.get("current_api_version")
        try:
            retired = validate_retired_api_versions(baseline, present_versions=[p.name for p in versions])
        except BoundaryError as exc:
            failures.append(f"{BASELINE_RELATIVE.as_posix()}: {exc}")
            retired = ()
        if retired:
            registry = load_json(api_root / FIELD_REGISTRY_RELATIVE.name)
            if registry.get("version_lifecycle") != RETIREMENT_FIELD_CLASSIFICATION:
                failures.append(f"{FIELD_REGISTRY_RELATIVE.as_posix()}: retirement_field_classification_mismatch")
        if not isinstance(current_version, str) or not API_VERSION.fullmatch(current_version):
            raise BoundaryError("invalid current API version")
        expected = baseline.get("published_protocols", {})
        current_index = load_json(api_root / current_version / "index.json")
        current_rows = current_index.get("data", {}).get("protocols", [])
        current_slugs = [row.get("slug") for row in current_rows if isinstance(row, dict)]
        if not all(isinstance(slug, str) for slug in current_slugs):
            raise BoundaryError("invalid protocol roster")
        if expected.get("count") != len(current_slugs):
            failures.append(f"{BASELINE_RELATIVE.as_posix()}: published count mismatch")
        if expected.get("slug_sha256") != slug_digest(current_slugs):
            failures.append(f"{BASELINE_RELATIVE.as_posix()}: published slug digest mismatch")
        if not current_rows and baseline.get("legacy_model", {}).get("verified_published_baseline") == "empty":
            for retained_version in versions:
                retained_index = load_json(retained_version / "index.json")
                if retained_version.name != current_version and retained_index.get("data", {}).get("protocols"):
                    failures.append(f"data/api/{retained_version.name}/index.json: legacy grades lack current release eligibility")
    except (BoundaryError, AttributeError, TypeError):
        failures.append(f"{BASELINE_RELATIVE.as_posix()}: invalid or missing publication binding")
    try:
        failures.extend(validate_status_registry(api_root.parent.parent, api_root=api_root))
    except (BoundaryError, AttributeError, TypeError):
        failures.append(f"{FIELD_REGISTRY_RELATIVE.as_posix()}: invalid or missing status registry")
    if check_manifest:
        failures.extend(validate_manifest(api_root.parent.parent, api_root=api_root))
    return sorted(set(failures))



def _validate_frozen_source(root: Path, immutable: Any, *, check_manifest: bool = True) -> list[str]:
    """Retain main API checks; prune only verified ignored worktree runtimes."""
    root = root.resolve()
    failures: list[str] = []
    for path in _iter_tree(root, worktree=True):
        if ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            failures.append(f"{relative}: symlinks are prohibited in the public tree")
        if any(relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in immutable.PROHIBITED_PREFIXES):
            failures.append(f"{relative}: private path is prohibited")
        if relative in immutable.PROHIBITED_EXACT_PATHS:
            failures.append(f"{relative}: retired control-plane path is prohibited")
        if "/unpublished/" in f"/{relative}/" or relative.endswith("/unpublished"):
            failures.append(f"{relative}: unpublished path is prohibited")

    api_root = root / "data" / "api"
    versions = sorted(path for path in api_root.glob("v*") if path.is_dir())
    if not versions:
        failures.append("data/api: no versioned public API trees found")
    for version_root in versions:
        failures.extend(immutable.validate_api_version(root, version_root))

    baseline = immutable.load_json(root / immutable.BASELINE_RELATIVE)
    current_version = baseline.get("current_api_version")
    expected = baseline.get("published_protocols", {})
    current_index = immutable.load_json(api_root / str(current_version) / "index.json")
    current_rows = current_index.get("data", {}).get("protocols", [])
    current_slugs = [row.get("slug") for row in current_rows if isinstance(row, dict)]
    if expected.get("count") != len(current_slugs):
        failures.append(f"{immutable.BASELINE_RELATIVE.as_posix()}: published count mismatch")
    if expected.get("slug_sha256") != immutable.slug_digest(current_slugs):
        failures.append(f"{immutable.BASELINE_RELATIVE.as_posix()}: published slug digest mismatch")

    for json_path in sorted(api_root.rglob("*.json")):
        relative = json_path.relative_to(root).as_posix()
        failures.extend(immutable.scan_api_value(immutable.load_json(json_path), relative))

    failures.extend(immutable.validate_status_registry(root))
    failures.extend(immutable.validate_v1_api_preservation(root))
    if check_manifest:
        failures.extend(immutable.validate_manifest(root))
    return sorted(set(failures))



def validate_selected_api(root: Path, api_root: Path, *, check_manifest: bool = True) -> list[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("immutable_public_boundary", Path(__file__).with_name("public_boundary.py"))
    immutable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(immutable)
    committed = root / "data/api"
    if (root / "scripts/ci/v1-api-preservation.json").is_file() and committed.is_dir() and hash_public_tree(api_root) == hash_public_tree(committed):
        # Frozen serving snapshot: retain every current main assertion, including v1 preservation.
        return _validate_frozen_source(root, immutable, check_manifest=check_manifest)
    # A distinct candidate must satisfy the full strict candidate contract.
    return validate_api_tree(api_root, check_manifest=check_manifest)

def validate_tree(root: Path, *, check_manifest: bool = True, api_root: Path | None = None) -> list[str]:
    """Strict candidate source/output checks; immutable v1 checks live in public_boundary."""
    failures = []
    try:
        for path in _iter_tree(root, worktree=True):
            failures.extend(_path_failures(path, path.relative_to(root).as_posix()))
    except (BoundaryError, OSError):
        failures.append("public source tree contains unreadable artifacts")
    failures.extend(validate_selected_api(root, api_root or root / "data/api", check_manifest=check_manifest))
    return sorted(set(failures))


def _decode_astro_props(value: Any) -> dict[str, Any]:
    """Decode the installed Astro JSON-compatible property transport.

    Assessment/browser data uses Value (0) and Array (1). Other runtime object
    tags cannot satisfy public JSON record contracts and are rejected, rather
    than coercing them into genuine citations or assessment strings.
    """
    if not isinstance(value, dict):
        raise BoundaryError("Astro hydration properties must be an object")

    def decode(item: Any) -> Any:
        if not isinstance(item, list) or not item or type(item[0]) is not int:
            raise BoundaryError("malformed Astro hydration transport")
        tag = item[0]
        if tag == 0:
            if len(item) == 1:
                return None  # Undefined retains its key for private-field checks.
            if len(item) != 2:
                raise BoundaryError("malformed Astro value transport")
            payload = item[1]
            if isinstance(payload, dict):
                return _decode_astro_props(payload)
            if isinstance(payload, list):
                raise BoundaryError("array requires Astro array transport")
            return payload
        if tag == 1:
            if len(item) != 2 or not isinstance(item[1], list):
                raise BoundaryError("malformed Astro array transport")
            return [decode(child) for child in item[1]]
        raise BoundaryError("unsupported Astro hydration transport tag")

    return {key: decode(child) for key, child in value.items()}


def _js_string(raw: str) -> str:
    """Decode JavaScript string escapes without evaluating code or URLs."""
    def replace(match: re.Match[str]) -> str:
        number = match.group(1) or match.group(2) or match.group(3)
        if number is not None:
            code = int(number, 16)
            return chr(code) if code <= 0x10FFFF else "\ufffd"
        character = match.group(4)
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\n": "", "\r": ""}.get(character, character)
    return _JS_ESCAPES.sub(replace, raw[1:-1])


def _js_static_string(tokens: list[tuple[str, str]], start: int) -> tuple[str | None, int]:
    parts: list[str] = []
    position = start
    while position < len(tokens) and tokens[position][0] == "string":
        raw = tokens[position][1]
        if "${" in raw:
            return None, start
        parts.append(_js_string(raw))
        position += 1
        if position < len(tokens) and tokens[position][1] == "+":
            position += 1
        else:
            return "".join(parts), position
    return None, start


def _scan_javascript_fields(text: str, logical: str) -> list[str]:
    """Inspect actual static property/assignment keys, never execute JS."""
    label = _display_source(logical)
    tokens = [(match.lastgroup or "punct", match.group(0)) for match in _JS_TOKENS.finditer(text) if match.lastgroup != "comment"]
    frames: list[str] = []
    type_pending = False
    failures: list[str] = []
    for index, (kind, raw) in enumerate(tokens):
        previous = tokens[index - 1][1] if index else ""
        following = tokens[index + 1][1] if index + 1 < len(tokens) else ""
        in_type = type_pending or "type" in frames
        if kind == "identifier" and raw in {"type", "interface"} and (not previous or previous in {";", "}", "export", "declare", "{"}) and index + 1 < len(tokens) and tokens[index + 1][0] == "identifier":
            type_pending = True
            in_type = True
        if raw == "{":
            frame = "type" if in_type else "object" if not previous or previous in {"=", "(", "[", ",", ":", "return", "yield"} else "block"
            if frame == "object" and previous == "(" and any(value == "function" for _kind, value in tokens[max(0, index - 4):index]):
                frame = "block"
            if frame == "object" and previous == "(":
                level, position = 1, index + 1
                while position < len(tokens) and level:
                    level += (tokens[position][1] == "{") - (tokens[position][1] == "}")
                    position += 1
                if position + 1 < len(tokens) and tokens[position][1] == ")" and tokens[position + 1][1] == "=>":
                    frame = "block"
            frames.append(frame)
            type_pending = False
            continue
        if raw == "}":
            if frames:
                frames.pop()
            continue
        if raw == ";":
            type_pending = False
        if in_type:
            continue
        if kind == "string":
            value = _js_string(raw)
            if value.lstrip().startswith(("{", "[")):
                try:
                    decoded = _parse_json(value)
                except (ValueError, RecursionError):
                    pass
                else:
                    failures.extend(scan_api_value(decoded, logical, "/javascript-data"))
        key = _js_string(raw) if kind == "string" else _decoded_text(raw, decode_css=False)
        key_position = previous in {"{", ","} or (previous in {"get", "set"} and index > 1 and tokens[index - 2][1] in {"{", ","})
        property_key = bool(frames and frames[-1] == "object" and key_position and following in {":", ",", "}", "("} and kind in {"identifier", "string"})
        assignment = kind == "identifier" and following in {"=", "+="}
        value_index = index + 2
        if raw == "[":
            computed, position = _js_static_string(tokens, index + 1)
            if computed is not None and position + 1 < len(tokens) and tokens[position][1] == "]":
                delimiter = tokens[position + 1][1]
                if frames and frames[-1] == "object" and previous in {"{", ",", "get", "set"} and delimiter in {":", "("}:
                    key, property_key, value_index = computed, True, position + 2
                elif delimiter in {"=", "+="}:
                    key, assignment, value_index = computed, True, position + 2
        if (property_key or assignment) and (_private_field(key) or _normal_key(key) in OPERATIONAL_STATUS_KEYS | RAW_DATABASE_TIMESTAMP_KEYS):
            failures.append(f"{label}: private, raw timestamp, or telemetry field in emitted JavaScript")
        if property_key and _normal_key(key) == "source_type":
            source_type, _after = _js_static_string(tokens, value_index)
            if source_type is not None and _decoded_text(source_type, decode_css=False).casefold() in PROHIBITED_SOURCE_TYPES:
                failures.append(f"{label}: prohibited source type in emitted JavaScript")
    return sorted(set(failures))


class _EmbeddedPayloads(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.failures: list[str] = []
        self._json_script = False
        self._script_chunks: list[str] = []
        self._js_script = False
        self._js_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            mime = (values.get("type") or "").split(";", 1)[0].strip().casefold()
            self._json_script = mime in {"application/json", "application/ld+json"}
            self._js_script = mime in _JS_SCRIPT_MIMES
            self._script_chunks = []
            self._js_chunks = []
        for name, value in attrs:
            if value is None:
                continue
            self.failures.extend(f"{self.source}: {reason}" for reason in scalar_material_reasons(value))
            # HTMLParser has already decoded character references exactly once.
            # Privacy inspection may decode scalar strings, but must never
            # rewrite JSON syntax, literal quotes, or percent-encoded citations.
            if name == "props" or value.lstrip().startswith(("{", "[")):
                try:
                    payload = _parse_json(value)
                    if tag == "astro-island" and name == "props":
                        payload = _decode_astro_props(payload)
                except (ValueError, TypeError):
                    if name == "props":
                        self.failures.append(f"{self.source}: invalid embedded browser payload")
                else:
                    self.failures.extend(scan_api_value(payload, self.source, "/embedded"))

    def handle_data(self, data: str) -> None:
        if self._json_script:
            self._script_chunks.append(data)
        else:
            if self._js_script:
                self._js_chunks.append(data)
            self.failures.extend(f"{self.source}: {reason}" for reason in scalar_material_reasons(data))

    def handle_endtag(self, tag: str) -> None:
        if tag != "script":
            return
        if self._js_script:
            self.failures.extend(_scan_javascript_fields("".join(self._js_chunks), self.source))
            self._js_script = False
        if not self._json_script:
            return
        try:
            payload = _parse_json("".join(self._script_chunks))
        except ValueError:
            self.failures.append(f"{self.source}: invalid embedded browser payload")
        else:
            self.failures.extend(scan_api_value(payload, self.source, "/embedded"))
        self._json_script = False


def _png_inflate(parts: list[bytes], limit: int) -> bytes:
    """Decode one bounded zlib stream; never accept hidden trailing streams."""
    decoder = zlib.decompressobj()
    result: list[bytes] = []
    size = 0
    for part in parts:
        decoded = decoder.decompress(part, limit - size + 1)
        size += len(decoded)
        if size > limit or decoder.unconsumed_tail or decoder.unused_data:
            raise ValueError("invalid PNG compressed stream")
        result.append(decoded)
    tail = decoder.flush(limit - size + 1)
    if size + len(tail) > limit or not decoder.eof or decoder.unused_data:
        raise ValueError("invalid PNG compressed stream")
    result.append(tail)
    return b"".join(result)


def _png_keyword(data: bytes) -> tuple[bytes, bytes]:
    keyword, separator, rest = data.partition(b"\x00")
    if not separator or not 1 <= len(keyword) <= 79 or keyword.strip(b" ") != keyword or b"  " in keyword:
        raise ValueError("invalid PNG keyword")
    if any(value < 32 or 126 < value < 161 for value in keyword):
        raise ValueError("invalid PNG keyword")
    return keyword, rest


def _png_inspection_parts(raw: bytes) -> tuple[list[bytes], list[str]]:
    """Validate PNG framing and pixels; expose metadata, never pixels, as prose.

    Chunk framing, text encoding and ordering follow the W3C PNG specification.
    A bounded image decode proves IDAT is one complete scanline stream, so an
    arbitrary payload cannot obtain the pixel exemption by using an IDAT tag.
    """
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    position = 8
    seen: set[bytes] = set()
    metadata: list[bytes] = []
    texts: list[str] = []
    image: list[bytes] = []
    image_closed = False
    palette_entries = 0
    width = height = depth = color = interlace = 0
    before_palette = {b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB", b"cICP", b"mDCV", b"cLLI"}
    before_image = before_palette | {b"PLTE", b"tRNS", b"bKGD", b"hIST", b"pHYs", b"sPLT"}
    singletons = before_image - {b"sPLT"} | {b"IHDR", b"IEND", b"tIME", b"eXIf"}
    fixed_lengths = {b"IHDR": 13, b"IEND": 0, b"cHRM": 32, b"gAMA": 4, b"sRGB": 1, b"pHYs": 9, b"tIME": 7, b"cICP": 4, b"mDCV": 24, b"cLLI": 8}
    ended = False
    while position < len(raw):
        if len(raw) - position < 12:
            raise ValueError("truncated PNG chunk")
        length = int.from_bytes(raw[position:position + 4], "big")
        kind = raw[position + 4:position + 8]
        if length > 0x7fffffff or length > len(raw) - position - 12 or re.fullmatch(rb"[A-Za-z]{4}", kind) is None or not 65 <= kind[2] <= 90:
            raise ValueError("invalid PNG chunk framing")
        data = raw[position + 8:position + 8 + length]
        crc = int.from_bytes(raw[position + 8 + length:position + 12 + length], "big")
        if binascii.crc32(kind + data) & 0xffffffff != crc:
            raise ValueError("invalid PNG CRC")
        position += length + 12
        if not seen and kind != b"IHDR" or kind in singletons and kind in seen:
            raise ValueError("invalid PNG chunk order")
        if kind in fixed_lengths and length != fixed_lengths[kind]:
            raise ValueError("invalid PNG chunk length")
        if kind[0] < 97 and kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}:
            raise ValueError("unknown PNG critical chunk")
        if b"IDAT" in seen and kind != b"IDAT":
            image_closed = True
        if kind in before_image and b"IDAT" in seen or kind in before_palette and b"PLTE" in seen:
            raise ValueError("invalid PNG metadata order")
        if kind == b"PLTE" and seen & {b"tRNS", b"bKGD", b"hIST"} or kind in {b"iCCP", b"sRGB"} and seen & {b"iCCP", b"sRGB"}:
            raise ValueError("invalid PNG metadata order")
        if kind == b"IHDR":
            width, height = int.from_bytes(data[:4], "big"), int.from_bytes(data[4:8], "big")
            depth, color, compression, filtering, interlace = data[8:]
            allowed = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if not 0 < width <= 0x7fffffff or not 0 < height <= 0x7fffffff or depth not in allowed.get(color, set()) or compression or filtering or interlace not in {0, 1}:
                raise ValueError("invalid PNG image header")
        elif kind == b"PLTE":
            palette_entries = length // 3
            if not length or length % 3 or palette_entries > 256 or color in {0, 4} or color == 3 and palette_entries > 2 ** depth:
                raise ValueError("invalid PNG palette")
        elif kind == b"IDAT":
            if image_closed or color == 3 and not palette_entries:
                raise ValueError("invalid PNG image order")
            image.append(data)
        elif kind == b"IEND":
            if b"IDAT" not in seen or position != len(raw):
                raise ValueError("invalid PNG trailer")
            ended = True
        elif kind == b"tRNS":
            if color == 3 and not 0 < length <= palette_entries or color in {0, 2} and length != {0: 2, 2: 6}[color] or color in {4, 6}:
                raise ValueError("invalid PNG transparency")
        elif kind == b"hIST":
            if not palette_entries or length != 2 * palette_entries:
                raise ValueError("invalid PNG histogram")
        elif kind == b"bKGD":
            if length != {0: 2, 2: 6, 3: 1, 4: 2, 6: 6}[color] or color == 3 and (not palette_entries or data[0] >= palette_entries):
                raise ValueError("invalid PNG background")
        elif kind == b"pHYs" and data[-1] not in {0, 1}:
            raise ValueError("invalid PNG physical units")
        elif kind == b"sRGB" and data[0] > 3 or kind == b"gAMA" and not int.from_bytes(data, "big"):
            raise ValueError("invalid PNG color metadata")
        elif kind == b"sBIT":
            if length != {0: 1, 2: 3, 3: 3, 4: 2, 6: 4}[color] or any(not 0 < value <= (8 if color == 3 else depth) for value in data):
                raise ValueError("invalid PNG significant bits")
        if kind in {b"tEXt", b"zTXt", b"iTXt", b"iCCP"}:
            keyword, content = _png_keyword(data)
            texts.append(keyword.decode("latin-1"))
            if kind == b"tEXt":
                if b"\x00" in content:
                    raise ValueError("invalid PNG text")
                texts.append(content.decode("latin-1"))
            elif kind in {b"zTXt", b"iCCP"}:
                if not content or content[0] != 0:
                    raise ValueError("invalid PNG compression method")
                decoded = _png_inflate([content[1:]], 8 * 1024 * 1024)
                if kind == b"zTXt":
                    if b"\x00" in decoded:
                        raise ValueError("invalid PNG text")
                    texts.append(decoded.decode("latin-1"))
                else:
                    metadata.append(decoded)
            else:
                if len(content) < 2 or content[0] not in {0, 1} or content[1] != 0:
                    raise ValueError("invalid PNG international text")
                compressed = content[0]
                fields = content[2:].split(b"\x00", 2)
                if len(fields) != 3 or re.fullmatch(rb"[A-Za-z0-9-]*", fields[0]) is None:
                    raise ValueError("invalid PNG language fields")
                translated = fields[1].decode("utf-8")
                content = _png_inflate([fields[2]], 8 * 1024 * 1024) if compressed else fields[2]
                if b"\x00" in content:
                    raise ValueError("invalid PNG international text")
                texts.extend([fields[0].decode("ascii"), translated, content.decode("utf-8")])
        if kind != b"IDAT":
            metadata.append(data)
        seen.add(kind)
    if not ended:
        raise ValueError("missing PNG trailer")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if not interlace else [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    rows = []
    for x, y, dx, dy in passes:
        columns, count = max(0, (width - x + dx - 1) // dx), max(0, (height - y + dy - 1) // dy)
        if columns and count:
            rows.append((1 + (columns * channels * depth + 7) // 8, count))
    expected = sum(stride * count for stride, count in rows)
    if expected > 128 * 1024 * 1024:
        raise ValueError("PNG decoded image exceeds validation bound")
    pixels = _png_inflate(image, expected)
    if len(pixels) != expected:
        raise ValueError("invalid PNG scanline length")
    offset = 0
    for stride, count in rows:
        if any(pixels[index] > 4 for index in range(offset, offset + stride * count, stride)):
            raise ValueError("invalid PNG row filter")
        offset += stride * count
    return metadata, texts


def _scan_text_file(path: Path, logical: str) -> list[str]:
    label = _display_source(logical)
    if path.suffix.casefold() in BINARY_SUFFIXES:
        try:
            raw = path.read_bytes()
        except OSError:
            return [f"{label}: unreadable emitted binary artifact"]
        parts, texts, failures = [raw], [], []
        if path.suffix.casefold() == ".png":
            try:
                parts, texts = _png_inspection_parts(raw)
            except (ValueError, zlib.error):
                failures.append(f"{label}: invalid emitted PNG artifact")
        for part in parts:
            for run in re.findall(rb"[\x20-\x7e]{8,}", part):
                failures.extend(f"{label}: {reason}" for reason in scalar_material_reasons(run.decode("ascii")))
        for value in texts:
            failures.extend(f"{label}: {reason}" for reason in scalar_material_reasons(value))
            failures.extend(_scan_javascript_fields(value, logical))
        return sorted(set(failures))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [f"{label}: unreadable emitted text artifact"]
    if path.name == MANIFEST_RELATIVE.name:
        if logical != "site/dist/api/MANIFEST.sha256":
            return [f"{label}: manifest is outside the registered API boundary"]
        seen: set[str] = set()
        for line in text.splitlines():
            record = re.fullmatch(r"[0-9a-f]{64}  data/api/([A-Za-z0-9_./-]+)", line)
            relative = record.group(1) if record else ""
            if not record or relative == MANIFEST_RELATIVE.name or relative in seen or any(part in {"", ".", ".."} for part in relative.split("/")) or not _supported_api_path(relative):
                return [f"{label}: invalid registered API manifest record"]
            seen.add(relative)
        if not seen:
            return [f"{label}: registered API manifest is empty"]
        # Only these hash-bound public locator records are documentary. Source
        # manifest equality, copied bytes, and receipt roster checks remain
        # mandatory in the complete output verifier.
        return []
    if path.suffix.casefold() in {".json", ".jsonld", ".webmanifest", ".map"}:
        try:
            payload = _parse_json(text)
        except ValueError:
            return [f"{label}: invalid emitted JSON artifact"]
        if logical == "site/dist/openapi.json" and (not isinstance(payload, dict) or not isinstance(payload.get("openapi"), str) or not isinstance(payload.get("paths"), dict)):
            return [f"{label}: invalid public OpenAPI document"]
        failures = scan_api_value(payload, logical, validate_citations=path.suffix.casefold() != ".map", documentary_role="source-map" if path.suffix.casefold() == ".map" else None)
        if path.suffix.casefold() == ".map":
            pending = [payload]
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    contents = item.get("sourcesContent", [])
                    if isinstance(contents, list):
                        for content in contents:
                            if isinstance(content, str):
                                failures.extend(_scan_javascript_fields(content, logical))
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
        return sorted(set(failures))
    inspected, policy_failures = _policy_inspection_text(text, logical)
    failures = [*policy_failures, *(f"{label}: {reason}" for reason in scalar_material_reasons(inspected))]
    if path.suffix.casefold() in {".yaml", ".yml"}:
        return sorted(set([*failures, *_scan_yaml_fields(text, logical)]))
    # Encoded hydration/JSON objects in markup and chunks must not bypass field
    # restrictions simply because the original artifact is not a .json file.
    decoded = _decoded_text(inspected)
    if path.suffix.casefold() in {".js", ".mjs", ".cjs"}:
        failures.extend(_scan_javascript_fields(text, logical))
    else:
        key_pattern = re.compile(r"(?:[\"']([A-Za-z_$][A-Za-z0-9_$-]*)[\"']|(?<=[{,])\s*([A-Za-z_$][A-Za-z0-9_$-]*))\s*:")
        if any(_private_field(match.group(1) or match.group(2)) or _normal_key(match.group(1) or match.group(2)) in OPERATIONAL_STATUS_KEYS | RAW_DATABASE_TIMESTAMP_KEYS for match in key_pattern.finditer(decoded)):
            failures.append(f"{label}: private, raw timestamp, or telemetry field in emitted payload")
    if path.suffix.casefold() in {".html", ".htm", ".svg"}:
        parser = _EmbeddedPayloads(label)
        try:
            parser.feed(text)
            parser.close()
        except (ValueError, TypeError):
            failures.append(f"{label}: invalid emitted markup")
        failures.extend(parser.failures)
    return sorted(set(failures))


def _policy_inspection_text(text: str, logical: str) -> tuple[str, list[str]]:
    """Recognize fixed public deny policy without rewriting emitted bytes."""
    label = _display_source(logical)
    if logical == "site/dist/robots.txt":
        inspected: list[str] = []
        failures: list[str] = []
        for line in text.splitlines(keepends=True):
            directive = re.fullmatch(r"\s*Disallow\s*:\s*([^\r\n]*)[\r\n]*", line, re.IGNORECASE)
            if directive and directive.group(1).strip() in _ROBOTS_FIXED_DENIES:
                inspected.append("Disallow: <fixed-public-deny>\n")
                continue
            inspected.append(line)
            if directive:
                value = directive.group(1).strip()
                if value and (not value.startswith("/") or re.search(r"(?:[?#]|\s)", value)):
                    failures.append(f"{label}: malformed or dynamic robots deny directive")
                if re.search(r"(?:^|/)control(?:/|$)", _decoded_text(value), re.IGNORECASE):
                    failures.append(f"{label}: unqualified private control path in robots policy")
        combined = "".join(inspected)
        if re.search(r"(?:^|[\s\"'`])/(?:control)(?:/|$)", _decoded_text(combined), re.IGNORECASE):
            failures.append(f"{label}: private control path outside a fixed policy directive")
        return combined, failures
    if logical != "site/dist/_headers":
        return text, []

    lines = text.splitlines(keepends=True)
    inspected = list(lines)
    failures = []
    route_indices = [index for index, line in enumerate(lines) if line.startswith("/")]
    for position, route_index in enumerate(route_indices):
        route = lines[route_index].strip()
        end = route_indices[position + 1] if position + 1 < len(route_indices) else len(lines)
        values: dict[str, list[str]] = {}
        for line in lines[route_index + 1:end]:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"\s+([!#$%&'*+.^_`|~0-9A-Za-z-]+)\s*:\s*([^\r\n]*)[\r\n]*", line)
            if not match:
                failures.append(f"{label}: malformed header policy directive")
                continue
            key, value = match.group(1).casefold(), match.group(2).strip()
            values.setdefault(key, []).append(value)
            check_key = key.removeprefix("x-")
            if _private_field(check_key) or _normal_key(check_key) in OPERATIONAL_STATUS_KEYS | RAW_DATABASE_TIMESTAMP_KEYS:
                failures.append(f"{label}: private header field is prohibited")
            # Header values/comments are never replaced in the inspection view.
            if re.search(r"(?:^|[\s\"'`])/(?:control)(?:/|$)", _decoded_text(value), re.IGNORECASE):
                failures.append(f"{label}: private control path in header value")
        if route not in _PROTECTED_HEADER_ROUTES:
            continue
        cache = values.get("cache-control", [])
        robots = values.get("x-robots-tag", [])
        cache_tokens = {part.strip().casefold().split("=", 1)[0] for value in cache for part in value.split(",")}
        robot_tokens = {part.strip().casefold() for value in robots for part in value.split(",")}
        guarded = len(cache) == 1 and len(robots) == 1 and {"private", "no-store"}.issubset(cache_tokens) and "noindex" in robot_tokens and "public" not in cache_tokens and not robot_tokens & {"index", "all"}
        if guarded:
            inspected[route_index] = "/<fixed-public-deny-policy>\n"
        else:
            failures.append(f"{label}: private route policy requires unique private/no-store/noindex guards")
    combined = "".join(inspected)
    if re.search(r"(?:^|[\s\"'`])/(?:control)(?:/|$)", _decoded_text(combined), re.IGNORECASE):
        failures.append(f"{label}: private control path outside a guarded fixed route directive")
    return combined, failures


class _FlowYamlParser:
    """Bounded YAML flow collections used by deterministic OpenAPI artifacts.

    No constructors, tags, anchors, aliases, or merge keys are evaluated. Block
    structure remains checked by the contract scanner below; flow collections
    become ordinary values for the same recursive public-record checks.
    """
    def __init__(self, text: str) -> None:
        if len(text) > 262144:
            raise BoundaryError("YAML flow collection exceeds the inspection bound")
        self.text = text
        self.position = 0
        self.nodes = 0

    def skip(self) -> None:
        while self.position < len(self.text):
            if self.text[self.position].isspace():
                self.position += 1
            elif self.text[self.position] == "#":
                newline = self.text.find("\n", self.position)
                self.position = len(self.text) if newline < 0 else newline + 1
            else:
                break

    def quoted(self) -> str:
        quote = self.text[self.position]
        start = self.position
        self.position += 1
        single: list[str] = []
        while self.position < len(self.text):
            character = self.text[self.position]
            if character == quote:
                if quote == "'" and self.position + 1 < len(self.text) and self.text[self.position + 1] == "'":
                    single.append("'")
                    self.position += 2
                    continue
                self.position += 1
                if quote == "'":
                    return "".join(single)
                try:
                    return _parse_json(self.text[start:self.position])
                except ValueError:
                    raise BoundaryError("unsupported YAML quoted scalar") from None
            if quote == '"' and character == "\\":
                self.position += 2
                continue
            single.append(character)
            self.position += 1
        raise BoundaryError("unterminated YAML quoted scalar")

    def key(self) -> str:
        self.skip()
        if self.position >= len(self.text):
            raise BoundaryError("missing YAML flow key")
        if self.text[self.position] in "\"'":
            result = self.quoted()
        else:
            start = self.position
            while self.position < len(self.text) and self.text[self.position] not in ":,{}[]\n\r":
                self.position += 1
            result = self.text[start:self.position].strip()
        if not result or result == "<<" or result.startswith(("!", "&", "*", "?")):
            raise BoundaryError("unsupported YAML flow key")
        self.skip()
        if self.position >= len(self.text) or self.text[self.position] != ":":
            raise BoundaryError("YAML flow mapping requires a separator")
        self.position += 1
        return result

    def value(self, depth: int = 0) -> Any:
        self.nodes += 1
        if depth > 32 or self.nodes > 8192:
            raise BoundaryError("YAML flow collection exceeds the inspection bound")
        self.skip()
        if self.position >= len(self.text):
            raise BoundaryError("missing YAML flow value")
        character = self.text[self.position]
        if character == "{":
            self.position += 1
            result: dict[str, Any] = {}
            self.skip()
            if self.position < len(self.text) and self.text[self.position] == "}":
                self.position += 1
                return result
            while True:
                key = self.key()
                if key in result:
                    raise BoundaryError("duplicate YAML flow mapping key")
                result[key] = self.value(depth + 1)
                self.skip()
                if self.position >= len(self.text) or self.text[self.position] not in ",}":
                    raise BoundaryError("malformed YAML flow mapping")
                delimiter = self.text[self.position]
                self.position += 1
                if delimiter == "}":
                    return result
                self.skip()
                if self.position < len(self.text) and self.text[self.position] == "}":
                    self.position += 1
                    return result
        if character == "[":
            self.position += 1
            result_list: list[Any] = []
            self.skip()
            if self.position < len(self.text) and self.text[self.position] == "]":
                self.position += 1
                return result_list
            while True:
                result_list.append(self.value(depth + 1))
                self.skip()
                if self.position >= len(self.text) or self.text[self.position] not in ",]":
                    raise BoundaryError("malformed YAML flow sequence")
                delimiter = self.text[self.position]
                self.position += 1
                if delimiter == "]":
                    return result_list
                self.skip()
                if self.position < len(self.text) and self.text[self.position] == "]":
                    self.position += 1
                    return result_list
        if character in "\"'":
            return self.quoted()
        if character in "!&*":
            raise BoundaryError("YAML tags and aliases are unsupported")
        start = self.position
        while self.position < len(self.text) and self.text[self.position] not in ",]}\n\r":
            if self.text[self.position] in "{[":
                raise BoundaryError("unsupported YAML plain flow scalar")
            if self.text[self.position] == "#" and (self.position == start or self.text[self.position - 1].isspace()):
                break
            self.position += 1
        scalar = self.text[start:self.position].strip()
        if not scalar:
            return None
        if scalar.casefold() in {"null", "~"}:
            return None
        if scalar.casefold() in {"true", "false"}:
            return scalar.casefold() == "true"
        if scalar.casefold() in {".nan", ".inf", "-.inf", "+.inf", "nan", "infinity", "-infinity"}:
            raise BoundaryError("non-finite YAML scalar is prohibited")
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", scalar):
            return _parse_json(scalar)
        return scalar


def _yaml_flow_region(lines: list[str], start: int, first: str) -> tuple[str, int]:
    """Find one bounded collection while respecting quotes and comments."""
    accumulated = first
    end = start
    stack: list[str] = []
    quote: str | None = None
    position = 0
    while True:
        if len(accumulated) > 262144:
            raise BoundaryError("YAML flow collection exceeds the inspection bound")
        while position < len(accumulated):
            character = accumulated[position]
            if quote:
                if quote == '"' and character == "\\":
                    position += 2
                    continue
                if character == quote:
                    if quote == "'" and position + 1 < len(accumulated) and accumulated[position + 1] == "'":
                        position += 2
                        continue
                    quote = None
            elif character in "\"'":
                quote = character
            elif character == "#" and (position == 0 or accumulated[position - 1].isspace()):
                newline = accumulated.find("\n", position)
                position = len(accumulated) if newline < 0 else newline
            elif character in "{[":
                stack.append(character)
            elif character in "}]":
                if not stack or (stack.pop(), character) not in {("{", "}"), ("[", "]")}:
                    raise BoundaryError("malformed YAML flow collection")
                if not stack:
                    suffix = accumulated[position + 1:].strip()
                    if suffix and not suffix.startswith("#"):
                        raise BoundaryError("unsupported YAML flow suffix")
                    return accumulated[:position + 1], end
            position += 1
        end += 1
        if end >= len(lines):
            raise BoundaryError("unterminated YAML flow collection")
        accumulated += "\n" + lines[end]


def _scan_yaml_fields(text: str, logical: str) -> list[str]:
    """Check emitted YAML mappings without executing tags or resolving aliases.

    Public OpenAPI YAML is documentary input. Named property definitions may
    document legacy fields; examples, defaults, nested scalars, and all actual
    mappings remain checked. Duplicate mappings are rejected before projection.
    """
    label = _display_source(logical)
    failures: list[str] = []
    registered = bool(re.fullmatch(r"(?:data/api|site/dist/api)/v\d+\.\d+\.\d+/openapi\.ya?ml", logical)) and bool(re.search(r"^openapi:\s", text, re.MULTILINE))
    stack: list[tuple[int, str]] = []
    sequences: dict[tuple[Any, ...], int] = {}
    active_sequences: dict[int, int] = {}
    seen: dict[tuple[Any, ...], set[str]] = {}
    key_line = re.compile(r"^( *)(-\s+)?(?:[\"']([^\"']+)[\"']|([^:#\n]+?)):\s*(.*)$")
    lines = text.splitlines()
    skipped_until = -1
    for line_number, line in enumerate(lines):
        if line_number <= skipped_until:
            continue
        if line.lstrip().startswith(("!", "&", "*", "<<")):
            failures.append(f"{label}: YAML tags, anchors, aliases, or merge keys are unsupported")
            continue
        if line.startswith("\t"):
            failures.append(f"{label}: invalid YAML indentation")
            continue
        item = re.fullmatch(r"( *)-\s*(?:#.*)?", line)
        if item:
            base_indent = len(item.group(1))
            while stack and stack[-1][0] >= base_indent:
                stack.pop()
            active_sequences = {depth: number for depth, number in active_sequences.items() if depth <= base_indent}
            sequence_context = tuple(stack) + ((base_indent, "sequence"),)
            sequences[sequence_context] = sequences.get(sequence_context, 0) + 1
            active_sequences[base_indent] = sequences[sequence_context]
            continue
        match = key_line.match(line)
        if line.lstrip().startswith(("{", "[")):
            try:
                region, skipped_until = _yaml_flow_region(lines, line_number, line.lstrip())
                parser = _FlowYamlParser(region)
                parsed = parser.value()
                parser.skip()
                if parser.position != len(region):
                    raise BoundaryError("unsupported YAML flow suffix")
                json_logical = str(Path(logical).with_suffix(".json")).replace("\\", "/")
                failures.extend(scan_api_value(parsed, json_logical))
            except (BoundaryError, ValueError, TypeError, RecursionError):
                failures.append(f"{label}: invalid or unsupported YAML flow collection")
            continue
        if not match:
            continue
        base_indent = len(match.group(1))
        sequence_item = bool(match.group(2))
        indent = base_indent + (len(match.group(2)) if sequence_item else 0)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        active_sequences = {depth: number for depth, number in active_sequences.items() if depth <= base_indent}
        if sequence_item:
            sequence_context = tuple(stack) + ((base_indent, "sequence"),)
            sequences[sequence_context] = sequences.get(sequence_context, 0) + 1
            active_sequences[base_indent] = sequences[sequence_context]
        parent = tuple(stack) + tuple(sorted(active_sequences.items()))
        key = (match.group(3) or match.group(4)).strip()
        normalized = _normal_key(key)
        if key in seen.setdefault(parent, set()):
            failures.append(f"{label}: duplicate YAML mapping key is prohibited")
        seen[parent].add(key)
        actual_data_context = any(name in {"example", "examples", "default"} for _indent, name in stack)
        schema_property = registered and not actual_data_context and bool(stack and stack[-1][1] == "properties")
        if not schema_property and (_private_field(key) or normalized in OPERATIONAL_STATUS_KEYS | RAW_DATABASE_TIMESTAMP_KEYS):
            failures.append(f"{label}: private, raw timestamp, or telemetry field in emitted YAML")
        failures.extend(f"{label}: unsafe YAML key ({reason})" for reason in scalar_material_reasons(key))
        flow_value = match.group(5).strip()
        if flow_value.startswith(("!", "&", "*")) or key == "<<":
            failures.append(f"{label}: YAML tags, anchors, aliases, or merge keys are unsupported")
        if flow_value.startswith(("{", "[")):
            try:
                region, skipped_until = _yaml_flow_region(lines, line_number, flow_value)
                parser = _FlowYamlParser(region)
                parsed = parser.value()
                parser.skip()
                if parser.position != len(region):
                    raise BoundaryError("unsupported YAML flow suffix")
                pointer = ""
                for _indent, parent_name in stack:
                    pointer = _pointer_child(pointer, parent_name)
                pointer = _pointer_child(pointer, key)
                json_logical = str(Path(logical).with_suffix(".json")).replace("\\", "/")
                failures.extend(scan_api_value(parsed, json_logical, pointer, documentary_role="openapi" if registered else None))
            except (BoundaryError, ValueError, TypeError, RecursionError):
                failures.append(f"{label}: invalid or unsupported YAML flow collection")
        stack.append((indent, key))
    return failures


def hash_public_tree(root: Path) -> dict[str, str]:
    if _is_link(root) or not root.is_dir():
        raise BoundaryError("missing or unsafe public artifact tree")
    result: dict[str, str] = {}
    for path in _iter_tree(root):
        if _is_link(path):
            raise BoundaryError("symlinks or junctions are prohibited in public output")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _validate_og_roster(api_root: Path, dist: Path, *, source_root: Path) -> list[str]:
    failures: list[str] = []
    expected = {"default.png", "analytics.png"}
    try:
        source_svg = source_root / "site/public/og/default.svg"
        emitted_svg = dist / "og/default.svg"
        if source_svg.is_file() or emitted_svg.is_file():
            expected.add("default.svg")
            if source_svg.is_file() and (_is_link(source_svg) or not emitted_svg.is_file() or source_svg.read_bytes() != emitted_svg.read_bytes()):
                failures.append("site/dist/og/default.svg: differs from the bound public source asset")
        for endpoint, name, key in (("index", "protocols", "slug"), ("factors", "factors", "id"), ("hacks", "hacks", "id")):
            rows = load_json(api_root / CURRENT_VERSION / f"{endpoint}.json").get("data", {}).get(name)
            if not isinstance(rows, list):
                raise BoundaryError("invalid OG input index")
            for row in rows:
                if not isinstance(row, dict) or _held_markers(row):
                    raise BoundaryError("held or invalid OG input")
                identifier = row.get(key)
                if not isinstance(identifier, str) or not IDENTITY.fullmatch(identifier):
                    raise BoundaryError("invalid OG identity")
                if name == "protocols" and row.get("headline_grade") is None:
                    continue  # Multi-surface family metadata has no inferred grade.
                if name == "protocols" and row.get("headline_grade") not in {"A", "B", "C", "D", "F"}:
                    raise BoundaryError("invalid OG assessment grade")
                path = f"{name}/{identifier}.png"
                if path in expected:
                    raise BoundaryError("duplicate OG identity")
                expected.add(path)
        actual = set(hash_public_tree(dist / "og"))
        if actual != expected:
            failures.append("site/dist/og: file roster differs from validated graded API inputs")
    except (BoundaryError, AttributeError, TypeError, OSError):
        failures.append("site/dist/og: missing, unsafe, or invalid validated card roster")
    return failures


def _hash_map_is_safe(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(
        isinstance(path, str) and bool(re.fullmatch(r"[A-Za-z0-9_./@\[\]-]+", path))
        and not path.startswith("/") and all(part not in {"", ".", ".."} for part in path.split("/"))
        and isinstance(digest, str) and bool(re.fullmatch(r"[0-9a-f]{64}", digest))
        for path, digest in value.items()
    )


def _curator_input_hashes(root: Path, curator_root: Path | None) -> dict[str, str]:
    selected = curator_root if curator_root is not None else root / "data/curator"
    if _is_link(selected):
        raise BoundaryError("unsafe bound curator input tree")
    if not selected.exists():
        if curator_root is not None:
            raise BoundaryError("explicit curator input tree is missing")
        return {}
    if not selected.is_dir():
        raise BoundaryError("bound curator input tree must be a directory")
    return {f"data/curator/{relative}": digest for relative, digest in hash_public_tree(selected).items()}


def _check_build_receipt(root: Path, api_root: Path, dist: Path, receipt: Path | dict[str, Any], *, compare_inputs: bool, curator_root: Path | None = None) -> list[str]:
    try:
        if isinstance(receipt, Path):
            if _is_link(receipt) or receipt.resolve().is_relative_to(dist.resolve()) or receipt.resolve().is_relative_to(api_root.resolve()):
                raise BoundaryError("receipt must remain outside public output and API data")
            value = load_json(receipt)
        else:
            value = receipt
        if not isinstance(value, dict) or set(value) != BUILD_RECEIPT_FIELDS or value.get("schema") != BUILD_RECEIPT_SCHEMA or not all(_hash_map_is_safe(value.get(key)) for key in ("build_inputs", "api_files", "output_files")):
            raise BoundaryError("invalid private build receipt")
        if value["api_files"] != hash_public_tree(api_root) or value["output_files"] != hash_public_tree(dist):
            return ["site/dist: complete output roster or bytes differ from the frozen private build receipt"]
        expected_curator = {name: digest for name, digest in value["build_inputs"].items() if name.startswith("data/curator/")}
        if expected_curator != _curator_input_hashes(root, curator_root):
            return ["site/dist: complete curator input state differs from the private build receipt"]
        if compare_inputs:
            for relative, digest in value["build_inputs"].items():
                if relative.startswith("data/api/"):
                    path = api_root / relative[len("data/api/"):]
                elif relative.startswith("data/curator/"):
                    path = (curator_root or root / "data/curator") / relative[len("data/curator/"):]
                else:
                    path = root / relative
                if _is_link(path) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    return ["site/dist: build source bytes differ from the private build receipt"]
    except (BoundaryError, OSError, TypeError, ValueError):
        return ["site/dist: invalid, missing, or unsafe external private build receipt"]
    return []


def validate_output_tree(root: Path, dist: Path, *, api_root: Path | None = None, expected_output_files: Iterable[str] | None = None, build_receipt: Path | dict[str, Any] | None = None, require_build_receipt: bool = False, curator_root: Path | None = None) -> list[str]:
    """Check every emitted text artifact and exact copied API bytes/roster."""
    selected_api = api_root or root / "data" / "api"
    failures = validate_selected_api(root, selected_api)
    try:
        _curator_input_hashes(root, curator_root)
    except BoundaryError:
        failures.append("site/dist: missing or unsafe bound curator input tree")
    if _is_link(dist) or not dist.is_dir():
        return sorted(set([*failures, "site/dist: missing or unsafe output tree"]))
    try:
        paths = list(_iter_tree(dist))
    except (BoundaryError, OSError):
        paths = []
        failures.append("site/dist: unreadable output artifact tree")
    for path in paths:
        relative = path.relative_to(dist).as_posix()
        failures.extend(_path_failures(path, relative))
        if not _is_link(path) and path.is_file():
            failures.extend(_scan_text_file(path, f"site/dist/{relative}"))
    try:
        source_hashes = hash_public_tree(selected_api)
        output_hashes = hash_public_tree(dist / "api")
        if output_hashes.pop("index.html", None) is None:
            failures.append("site/dist/api: deterministic API landing artifact is missing")
        if source_hashes != output_hashes:
            failures.append("site/dist/api: file roster or bytes differ from the validated public API")
        if expected_output_files is not None and set(hash_public_tree(dist)) != set(expected_output_files):
            failures.append("site/dist: output file roster differs from the bound build roster")
    except (BoundaryError, OSError):
        failures.append("site/dist: missing, unreadable, or unsafe artifact tree")
    failures.extend(_validate_og_roster(selected_api, dist, source_root=root))
    if build_receipt is not None:
        failures.extend(_check_build_receipt(root, selected_api, dist, build_receipt, compare_inputs=True, curator_root=curator_root))
    elif require_build_receipt:
        failures.append("site/dist: completed output requires a frozen external private build receipt")
    return sorted(set(failures))


def create_output_manifest(api_root: Path, dist: Path, *, build_inputs: dict[str, str], source_root: Path | None = None, curator_root: Path | None = None) -> dict[str, Any]:
    """Return a private receipt only after independent complete output checks.

    The build runner owns fresh-stage execution and matching input snapshots.
    This helper performs no writes and cannot authorize a publication.
    """
    api_before = hash_public_tree(api_root)
    output_before = hash_public_tree(dist)
    selected_source = source_root or api_root.parent.parent
    failures = validate_output_tree(selected_source, dist, api_root=api_root, curator_root=curator_root)
    if failures or not _hash_map_is_safe(build_inputs):
        raise BoundaryError("cannot capture a private build receipt from unqualified output or inputs")
    ordered_inputs = dict(sorted(build_inputs.items()))
    curator_inputs = {name: digest for name, digest in ordered_inputs.items() if name.startswith("data/curator/")}
    if curator_inputs != _curator_input_hashes(selected_source, curator_root):
        raise BoundaryError("curator input state is not bound to the supplied source snapshot")
    api_after = hash_public_tree(api_root)
    output_after = hash_public_tree(dist)
    if api_before != api_after or output_before != output_after:
        raise BoundaryError("cannot capture a private build receipt from changing artifacts")
    source_svg_hash = ordered_inputs.get("site/public/og/default.svg")
    emitted_svg_hash = output_after.get("og/default.svg")
    if source_svg_hash != emitted_svg_hash:
        raise BoundaryError("public fallback SVG is not bound to its unchanged source asset")
    return {
        "schema": BUILD_RECEIPT_SCHEMA,
        "build_inputs": ordered_inputs,
        "api_files": dict(sorted(api_after.items())),
        "output_files": dict(sorted(output_after.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--api-root", type=Path, help="Complete candidate API tree including controls and all retained versions")
    parser.add_argument("--dist", type=Path, help="Validate the completed browser/static build against the same candidate API")
    parser.add_argument("--curator-root", type=Path, help="Trusted frozen base for logical data/curator source inputs")
    parser.add_argument("--build-receipt", "--expected-output-manifest", dest="build_receipt", type=Path, help="Frozen private build receipt outside the emitted tree (required with --dist)")
    args = parser.parse_args()
    failures = validate_tree(args.root, api_root=args.api_root)
    import importlib.util
    spec = importlib.util.spec_from_file_location("source_preservation", Path(__file__).with_name("public_boundary.py"))
    immutable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(immutable)
    failures.extend(immutable.validate_v1_api_preservation(args.root))
    try:
        _curator_input_hashes(args.root, args.curator_root)
    except BoundaryError:
        failures.append("source inputs: missing or unsafe bound curator input tree")
    if args.dist is not None:
        failures.extend(validate_output_tree(args.root, args.dist, api_root=args.api_root, build_receipt=args.build_receipt, require_build_receipt=True, curator_root=args.curator_root))
    if failures:
        print("Public boundary validation failed:")
        unique = sorted(set(failures))
        for failure in unique[:100]:
            print(f"- {failure}")
        if len(unique) > 100:
            print(f"- {len(unique) - 100} additional boundary failures (details withheld)")
        return 1
    print("OK: complete public source/output boundary is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
