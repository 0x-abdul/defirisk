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


def _status_runs(value: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the bounded status run list only when it has the expected shape."""
    data = value.get("data")
    if not isinstance(data, dict):
        return None
    runs = data.get("runs")
    if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
        return None
    return runs


def _without_status_runs(
    value: dict[str, Any], *, drop_bucket_freshness: bool = False
) -> dict[str, Any] | None:
    """Drop verified derived status projections, retaining other semantics."""
    data = value.get("data")
    if not isinstance(data, dict) or "runs" not in data:
        return None
    result = dict(value)
    excluded = {"runs"}
    if drop_bucket_freshness:
        excluded.add("bucket_freshness")
    result["data"] = {key: item for key, item in data.items() if key not in excluded}
    return result


def _status_runs_window(value: dict[str, Any]) -> int | None:
    """Return the declared positive status run window when present."""
    data = value.get("data")
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    window = meta.get("runs_window")
    return window if isinstance(window, int) and not isinstance(window, bool) and window > 0 else None


def _unique_run_ids(runs: list[dict[str, Any]]) -> set[str] | None:
    """Return stable run IDs only when every row has one unique nonempty ID."""
    identifiers: set[str] = set()
    for run in runs:
        identifier = run.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            return None
        identifiers.add(identifier)
    return identifiers


def _target_run_addition_ids(
    before_runs: list[dict[str, Any]],
    after_runs: list[dict[str, Any]],
    family_slug: str,
) -> set[str] | None:
    """Return genuinely new target run IDs, rejecting malformed identities."""
    before_ids = _unique_run_ids(before_runs)
    after_ids = _unique_run_ids(after_runs)
    if before_ids is None or after_ids is None:
        return None
    return {
        run["id"]
        for run in after_runs
        if _target_pipeline_run(run, family_slug) and run["id"] not in before_ids
    }


def _expected_bucket_freshness(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rebuild the bounded-run aggregate emitted by ``dump.py``."""
    result: dict[str, dict[str, Any]] = {}
    for bucket_code in ("C", "E", "S"):
        bucket_runs = [run for run in runs if run.get("cadence_bucket") == bucket_code]
        if not bucket_runs:
            result[bucket_code] = {
                "cadence_bucket": bucket_code,
                "last_run_at": None,
                "run_count_30": 0,
                "total_errors": 0,
                "total_successes": 0,
                "success_rate_pct": None,
            }
            continue
        total_successes = sum(run.get("success_count") or 0 for run in bucket_runs)
        total_errors = sum(run.get("error_count") or 0 for run in bucket_runs)
        total_operations = total_successes + total_errors
        result[bucket_code] = {
            "cadence_bucket": bucket_code,
            "last_run_at": bucket_runs[0].get("run_at"),
            "run_count_30": len(bucket_runs),
            "total_errors": total_errors,
            "total_successes": total_successes,
            "success_rate_pct": (
                round((total_successes / total_operations) * 100, 1)
                if total_operations
                else None
            ),
        }
    return result


def _status_bucket_freshness_is_derived(
    before_value: dict[str, Any], after_value: dict[str, Any]
) -> bool:
    """Accept bucket freshness only when both sides derive it from their runs."""
    before_data = before_value.get("data")
    after_data = after_value.get("data")
    if not isinstance(before_data, dict) or not isinstance(after_data, dict):
        return False
    before_has_bucket = "bucket_freshness" in before_data
    after_has_bucket = "bucket_freshness" in after_data
    if before_has_bucket != after_has_bucket:
        return False
    if not before_has_bucket:
        return True
    before_runs = _status_runs(before_value)
    after_runs = _status_runs(after_value)
    return (
        before_runs is not None
        and after_runs is not None
        and before_data["bucket_freshness"] == _expected_bucket_freshness(before_runs)
        and after_data["bucket_freshness"] == _expected_bucket_freshness(after_runs)
    )


def _status_run_window_is_isolated(
    before_value: dict[str, Any],
    after_value: dict[str, Any],
    family_slug: str,
) -> bool:
    """Allow only target-run insertions to evict unrelated tail rows.

    ``status.json`` exposes a newest-first bounded projection. A target refresh
    can legitimately insert target-owned audit rows and push older unrelated
    rows beyond that window. Stable run IDs must prove that the retained prior
    rows form an exact prefix and that every new row belongs to the target.
    The full-window tail can contain prior target rows as well as unrelated
    rows, so a target insertion need not evict an unrelated row one-for-one.
    """
    before_runs = _status_runs(before_value)
    after_runs = _status_runs(after_value)
    if before_runs is None or after_runs is None:
        return False
    before_window = _status_runs_window(before_value)
    after_window = _status_runs_window(after_value)
    if before_window is None or before_window != after_window:
        return False
    new_target_ids = _target_run_addition_ids(before_runs, after_runs, family_slug)
    if new_target_ids is None:
        return False
    before_ids = _unique_run_ids(before_runs)
    if before_ids is None:
        return False
    new_runs = [run for run in after_runs if run["id"] not in before_ids]
    if any(not _target_pipeline_run(run, family_slug) for run in new_runs):
        return False
    retained_runs = [run for run in after_runs if run["id"] in before_ids]
    if canonical_sha256(retained_runs) != canonical_sha256(before_runs[: len(retained_runs)]):
        return False
    expected_after_count = min(before_window, len(before_runs) + len(new_target_ids))
    return (
        len(before_runs) <= before_window
        and len(after_runs) == expected_after_count
    )


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
        if (
            relative == "status.json"
            and _status_run_window_is_isolated(before_value, after_value, family_slug)
            and _status_bucket_freshness_is_derived(before_value, after_value)
        ):
            before_status = _without_status_runs(
                before_value, drop_bucket_freshness=True
            )
            after_status = _without_status_runs(
                after_value, drop_bucket_freshness=True
            )
            if before_status is None or after_status is None:
                unrelated_changes.append(safe_relative)
                continue
            before_unrelated = _without_target(before_status, family_slug)
            after_unrelated = _without_target(after_status, family_slug)
        else:
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
