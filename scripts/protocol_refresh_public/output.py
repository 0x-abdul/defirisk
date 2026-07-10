"""Semantic before/after verification for generated public API trees."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import ContractError, canonical_sha256, load_json_strict


VOLATILE_KEYS = {"generated_at", "data_as_of"}


def _json_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ContractError(f"API output root is not a directory: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*.json"))
        if path.is_file()
    }


def _target_owned_path(relative: str, family_slug: str) -> bool:
    parts = PurePosixPath(relative).parts
    if len(parts) < 2 or parts[0] != "protocols":
        return False
    return parts[1] == family_slug or parts[1] == f"{family_slug}.json"


def _target_record(value: dict[str, Any], family_slug: str) -> bool:
    if value.get("protocol_slug") == family_slug:
        return True
    if value.get("family_slug") == family_slug:
        return True
    if value.get("slug") == family_slug:
        return True
    return _target_pipeline_run(value, family_slug)


def _target_pipeline_run(value: dict[str, Any], family_slug: str) -> bool:
    if not isinstance(value.get("script_name"), str) or "triggered_by" not in value:
        return False
    if value.get("triggered_by") == f"compose.py:{family_slug}":
        return True
    notes = value.get("notes")
    if isinstance(notes, str):
        try:
            notes = json.loads(notes)
        except json.JSONDecodeError:
            return False
    return isinstance(notes, dict) and notes.get("family_slug") == family_slug


def _without_target(value: Any, family_slug: str) -> Any:
    if isinstance(value, list):
        return [
            _without_target(item, family_slug)
            for item in value
            if not (isinstance(item, dict) and _target_record(item, family_slug))
        ]
    if isinstance(value, dict):
        return {
            key: _without_target(item, family_slug)
            for key, item in value.items()
            if key not in VOLATILE_KEYS and key != family_slug
        }
    return value


def verify_output_isolation(
    before_root: Path | str,
    after_root: Path | str,
    family_slug: str,
) -> dict[str, Any]:
    """Prove every semantic delta belongs to one target protocol family."""
    before = _json_files(Path(before_root))
    after = _json_files(Path(after_root))
    all_paths = sorted(set(before) | set(after))
    unrelated_changes: list[str] = []
    target_changes: list[str] = []

    for relative in all_paths:
        before_path = before.get(relative)
        after_path = after.get(relative)
        target_owned = _target_owned_path(relative, family_slug)
        if before_path is None or after_path is None:
            (target_changes if target_owned else unrelated_changes).append(relative)
            continue
        before_value = load_json_strict(before_path)
        after_value = load_json_strict(after_path)
        if canonical_sha256(before_value) != canonical_sha256(after_value):
            target_changes.append(relative)
        if target_owned:
            continue
        before_unrelated = _without_target(before_value, family_slug)
        after_unrelated = _without_target(after_value, family_slug)
        if canonical_sha256(before_unrelated) != canonical_sha256(after_unrelated):
            unrelated_changes.append(relative)

    return {
        "family_slug": family_slug,
        "before_json_files": len(before),
        "after_json_files": len(after),
        "target_changed_files": sorted(set(target_changes) - set(unrelated_changes)),
        "unrelated_changed_files": sorted(set(unrelated_changes)),
        "isolated": not unrelated_changes,
    }
