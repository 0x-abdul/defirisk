"""Semantic before/after verification for generated public API trees."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import ContractError, canonical_sha256, load_json_strict


VOLATILE_KEYS = {"generated_at", "data_as_of"}
REDACTED_UNPUBLISHED_SEGMENT = "<review>"


@dataclass(frozen=True)
class ProtocolOutput:
    """One generated protocol document and its repository-relative location."""

    relative_path: str
    document: dict[str, Any]


def _json_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ContractError(f"API output root is not a directory: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*.json"))
        if path.is_file()
    }


def _redact_relative_path(relative: str) -> str:
    parts = list(PurePosixPath(relative).parts)
    if len(parts) >= 2 and parts[0] == "unpublished":
        parts[1] = REDACTED_UNPUBLISHED_SEGMENT
    return PurePosixPath(*parts).as_posix()


def _load_generated_json(path: Path, relative: str) -> dict[str, Any]:
    try:
        return load_json_strict(path)
    except ContractError:
        safe_path = _redact_relative_path(relative)
        raise ContractError(f"cannot load generated JSON {safe_path}") from None


def _document_family_slug(document: dict[str, Any]) -> str | None:
    data = document.get("data")
    if not isinstance(data, dict):
        return None
    protocol_data = data.get("protocol_data")
    if not isinstance(protocol_data, dict):
        return None
    protocol = protocol_data.get("protocol")
    if not isinstance(protocol, dict):
        return None
    slug = protocol.get("slug")
    return slug if isinstance(slug, str) else None


def resolve_protocol_output(
    root: Path | str,
    family_slug: str,
) -> ProtocolOutput:
    """Resolve one published or unpublished target without exposing review tokens."""
    output_root = Path(root)
    if not output_root.is_dir():
        raise ContractError("generated API output root is not a directory")

    candidates: list[tuple[str, Path]] = []
    published_relative = f"protocols/{family_slug}.json"
    published_root = output_root / "protocols"
    if published_root.is_dir():
        for path in sorted(published_root.glob("*.json")):
            if path.is_file():
                candidates.append((path.relative_to(output_root).as_posix(), path))

    unpublished_root = output_root / "unpublished"
    if unpublished_root.is_dir():
        for path in sorted(unpublished_root.glob("*/index.json")):
            if path.is_file():
                candidates.append((path.relative_to(output_root).as_posix(), path))

    matches: list[ProtocolOutput] = []
    for relative, path in candidates:
        document = _load_generated_json(path, relative)
        if _document_family_slug(document) == family_slug:
            matches.append(ProtocolOutput(relative, document))

    if len(matches) != 1:
        raise ContractError(
            "generated API output must contain exactly one document for the "
            f"target canonical family; found {len(matches)}"
        )
    if (
        matches[0].relative_path.startswith("protocols/")
        and matches[0].relative_path != published_relative
    ):
        raise ContractError(
            "generated target protocol document is not at its canonical published path"
        )
    return matches[0]


def _target_owned_path(
    relative: str,
    family_slug: str,
    target_output_relative: str,
) -> bool:
    target_parts = PurePosixPath(target_output_relative).parts
    if len(target_parts) >= 3 and target_parts[0] == "unpublished":
        target_directory = PurePosixPath(target_output_relative).parent
        allowed = {
            PurePosixPath(target_output_relative).as_posix(),
            (target_directory / "history.json").as_posix(),
        }
    else:
        allowed = {
            f"protocols/{family_slug}.json",
            f"protocols/{family_slug}/history.json",
        }
    return relative in allowed


def _target_history_path(target_output_relative: str, family_slug: str) -> str:
    target_parts = PurePosixPath(target_output_relative).parts
    if len(target_parts) >= 3 and target_parts[0] == "unpublished":
        return (PurePosixPath(target_output_relative).parent / "history.json").as_posix()
    return f"protocols/{family_slug}/history.json"


def _validate_target_history(document: dict[str, Any], family_slug: str) -> None:
    data = document.get("data")
    if not isinstance(data, dict) or data.get("protocol_slug") != family_slug:
        raise ContractError(
            "generated target history does not describe the target canonical family"
        )


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
    before_root = Path(before_root)
    after_root = Path(after_root)
    before_target = resolve_protocol_output(before_root, family_slug)
    after_target = resolve_protocol_output(after_root, family_slug)
    before = _json_files(before_root)
    after = _json_files(after_root)
    all_paths = sorted(set(before) | set(after))
    unrelated_changes: list[str] = []
    target_changes: list[str] = []
    target_history_paths = {
        _target_history_path(before_target.relative_path, family_slug),
        _target_history_path(after_target.relative_path, family_slug),
    }

    if before_target.relative_path != after_target.relative_path:
        unrelated_changes.append("target-publication-location")

    for relative in all_paths:
        before_path = before.get(relative)
        after_path = after.get(relative)
        target_owned = _target_owned_path(
            relative,
            family_slug,
            before_target.relative_path,
        ) or _target_owned_path(
            relative,
            family_slug,
            after_target.relative_path,
        )
        safe_relative = _redact_relative_path(relative)
        if before_path is None or after_path is None:
            if relative in target_history_paths:
                existing_path = before_path if before_path is not None else after_path
                if existing_path is not None:
                    _validate_target_history(
                        _load_generated_json(existing_path, relative),
                        family_slug,
                    )
            (target_changes if target_owned else unrelated_changes).append(safe_relative)
            continue
        before_value = _load_generated_json(before_path, relative)
        after_value = _load_generated_json(after_path, relative)
        if relative in target_history_paths:
            _validate_target_history(before_value, family_slug)
            _validate_target_history(after_value, family_slug)
        if canonical_sha256(before_value) != canonical_sha256(after_value):
            target_changes.append(safe_relative)
        if target_owned:
            continue
        before_unrelated = _without_target(before_value, family_slug)
        after_unrelated = _without_target(after_value, family_slug)
        if canonical_sha256(before_unrelated) != canonical_sha256(after_unrelated):
            unrelated_changes.append(safe_relative)

    return {
        "family_slug": family_slug,
        "before_json_files": len(before),
        "after_json_files": len(after),
        "target_changed_files": sorted(set(target_changes) - set(unrelated_changes)),
        "unrelated_changed_files": sorted(set(unrelated_changes)),
        "isolated": not unrelated_changes,
    }
