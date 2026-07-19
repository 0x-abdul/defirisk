#!/usr/bin/env python3
"""Fail closed unless a staged public API matches its approved publication policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ValidationError(ValueError):
    """The staged API does not match the explicit deployment policy."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON object required: {path}")
    return value


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"nonempty string required for {field}")
    return value


def published_slug_digest(slugs: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(slugs)).encode("utf-8")).hexdigest()


def validate(api_root: Path, policy_path: Path) -> None:
    policy = load_json(policy_path)
    expected_rubric = require_string(policy.get("rubric_version"), "policy.rubric_version")
    expected = policy.get("published_protocols")
    if not isinstance(expected, dict):
        raise ValidationError("object required for policy.published_protocols")
    expected_count = expected.get("count")
    expected_digest = require_string(expected.get("slug_sha256"), "policy.published_protocols.slug_sha256")
    if not isinstance(expected_count, int) or expected_count < 0:
        raise ValidationError("nonnegative integer required for policy.published_protocols.count")

    index = load_json(api_root / "index.json")
    if require_string(index.get("rubric_version"), "index.rubric_version") != expected_rubric:
        raise ValidationError("index rubric_version does not match policy")
    require_string(index.get("data_as_of"), "index.data_as_of")
    require_string(index.get("generated_at"), "index.generated_at")
    data = index.get("data")
    if not isinstance(data, dict):
        raise ValidationError("object required for index.data")
    rows = data.get("protocols")
    if not isinstance(rows, list):
        raise ValidationError("list required for index.data.protocols")

    slugs: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("object required for every index protocol row")
        slug = row.get("slug")
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            raise ValidationError(f"invalid published protocol slug: {slug!r}")
        slugs.append(slug)
    if len(set(slugs)) != len(slugs):
        raise ValidationError("published protocol slugs must be unique")
    if len(slugs) != expected_count:
        raise ValidationError(f"published protocol count {len(slugs)} does not match approved count {expected_count}")
    if published_slug_digest(slugs) != expected_digest:
        raise ValidationError("published protocol roster digest does not match approved policy")

    detail_dir = api_root / "protocols"
    detail_paths = set(detail_dir.rglob("*")) if detail_dir.is_dir() else set()
    if not slugs:
        if detail_paths:
            raise ValidationError("empty approved roster must have an absent or empty protocols directory")
        return

    expected_details = {detail_dir / f"{slug}.json" for slug in slugs}
    if detail_paths != expected_details:
        raise ValidationError("published protocol detail files do not match index roster")
    for slug in slugs:
        detail = load_json(detail_dir / f"{slug}.json")
        if require_string(detail.get("rubric_version"), f"protocols/{slug}.rubric_version") != expected_rubric:
            raise ValidationError(f"protocol detail rubric_version mismatch: {slug}")
        require_string(detail.get("data_as_of"), f"protocols/{slug}.data_as_of")
        require_string(detail.get("generated_at"), f"protocols/{slug}.generated_at")
        if not isinstance(detail.get("data"), dict):
            raise ValidationError(f"object required for protocol detail data: {slug}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    validate(args.api_root, args.policy)


if __name__ == "__main__":
    main()
