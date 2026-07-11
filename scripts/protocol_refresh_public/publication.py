"""Static validation for proposed GitHub publication metadata."""

from __future__ import annotations

import re
from typing import Any

from .contracts import SHA256_RE, canonical_sha256


ISSUE_URL_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/issues/[1-9][0-9]*/?$")
ISSUE_REF_RE = re.compile(r"^(?:[^/#\s]+/[^/#\s]+)?#[1-9][0-9]*$")
ATTRIBUTION_PATTERNS = (
    re.compile(
        r"(?i)(?<![a-z0-9])(?:codex|chatgpt|openai|claude|anthropic|gemini|copilot)(?![a-z0-9])"
    ),
    re.compile(
        r"(?i)\b(?:ai[- ]generated|generated\s+(?:with|by)\s+(?:an?\s+)?"
        r"(?:ai(?:\s+assistant)?|assistant|tool|model))\b"
    ),
    re.compile(
        r"(?i)\b(?:written|authored|created|produced)\s+by\s+(?:an?\s+)?"
        r"(?:ai(?:\s+assistant)?|assistant|tool|model)\b"
    ),
    re.compile(r"(?im)^\s*co-authored-by\s*:"),
)
PUBLICATION_FIELDS = {
    "issue",
    "branch_name",
    "worktree_name",
    "commit_message",
    "pull_request",
    "comments",
}


def _has_changes(payload: dict[str, Any]) -> bool:
    changes = payload.get("changes", {})
    return isinstance(changes, dict) and any(
        bool(changes.get(key))
        for key in ("protocol_fields", "family_fields", "surfaces", "deployments", "factor_scores")
    )


def _publication_texts(proposal: dict[str, Any]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for name in ("branch_name", "worktree_name", "commit_message"):
        value = proposal.get(name)
        if isinstance(value, str):
            texts.append((name, value))
    for parent in ("issue", "pull_request"):
        value = proposal.get(parent)
        if isinstance(value, dict):
            for name in ("title", "body"):
                text = value.get(name)
                if isinstance(text, str):
                    texts.append((f"{parent}.{name}", text))
    comments = proposal.get("comments")
    if isinstance(comments, list):
        for index, value in enumerate(comments):
            if isinstance(value, str):
                texts.append((f"comments[{index}]", value))
            elif isinstance(value, dict) and isinstance(value.get("body"), str):
                texts.append((f"comments[{index}].body", value["body"]))
    return texts


def validate_publication_metadata(
    handoff: dict[str, Any], proposal: dict[str, Any]
) -> list[str]:
    """Validate a local proposal without reading or mutating GitHub."""
    errors: list[str] = []
    payload = handoff.get("payload")
    if not isinstance(payload, dict):
        return ["handoff payload must be an object before publication validation"]
    if proposal.get("schema_version") != "1.0":
        errors.append("publication schema_version must be 1.0")
    for name in ("refresh_id", "family_slug"):
        if proposal.get(name) != handoff.get(name):
            errors.append(f"publication {name} does not match handoff")

    payload_hash = canonical_sha256(payload)
    approved_hash = proposal.get("approved_public_payload_sha256")
    if not isinstance(approved_hash, str) or not SHA256_RE.fullmatch(approved_hash):
        errors.append("approved_public_payload_sha256 must be strict lowercase SHA-256")
    elif approved_hash != payload_hash:
        errors.append("approved_public_payload_sha256 does not match the public payload")

    changed = _has_changes(payload)
    if not changed:
        present = sorted(field for field in PUBLICATION_FIELDS if proposal.get(field) not in (None, "", [], {}))
        if present:
            errors.append(f"no-change refresh rejects issue/PR publication metadata: {present}")
        return errors

    if proposal.get("approval_state") != "approved":
        errors.append("changed refresh publication proposal must be approved")
    issue = proposal.get("issue")
    if not isinstance(issue, dict):
        errors.append("changed refresh requires issue metadata")
    else:
        url = issue.get("url")
        reference = issue.get("reference")
        if not (
            isinstance(url, str)
            and ISSUE_URL_RE.fullmatch(url)
            or isinstance(reference, str)
            and ISSUE_REF_RE.fullmatch(reference)
        ):
            errors.append("changed refresh requires a valid GitHub issue URL or reference")

    for path, text in _publication_texts(proposal):
        for pattern in ATTRIBUTION_PATTERNS:
            match = pattern.search(text)
            if match:
                errors.append(
                    f"publication {path} contains forbidden attribution {match.group(0)!r}"
                )
                break
    return errors
