"""Injectable local process adapters used by the protocol refresh CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractError


@dataclass(frozen=True)
class CommandResult:
    """Subprocess result with an optional generated-output root."""

    returncode: int
    stdout: str
    stderr: str
    output_path: Path | None = None

    def __str__(self) -> str:
        return str(self.output_path) if self.output_path is not None else self.stdout.strip()


def _environment(db_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env.pop("LOCAL_DATABASE_URL", None)
    return env


def make_compose_runner(repo_root: Path) -> Callable[..., CommandResult]:
    """Create the CLI's injectable, protocol-scoped compose runner."""
    script = repo_root / "scripts" / "compose.py"

    def run(*, db_url: str, family_slug: str) -> CommandResult:
        result = subprocess.run(
            [sys.executable, str(script), "--protocol", family_slug],
            cwd=repo_root,
            env=_environment(db_url),
            text=True,
            capture_output=True,
            check=False,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)

    return run


def make_dump_runner(repo_root: Path, out_root: Path) -> Callable[..., CommandResult]:
    """Create the CLI's injectable disposable-output dump runner."""
    script = repo_root / "scripts" / "dump.py"

    def run(*, db_url: str, family_slug: str) -> CommandResult:
        del family_slug
        result = subprocess.run(
            [sys.executable, str(script), "--out-root", str(out_root)],
            cwd=repo_root,
            env=_environment(db_url),
            text=True,
            capture_output=True,
            check=False,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr, out_root)

    return run


def _protocol_payload(document: dict[str, Any]) -> dict[str, Any]:
    data = document.get("data")
    if not isinstance(data, dict):
        raise ContractError("generated protocol output has no data object")
    protocol_data = data.get("protocol_data")
    if not isinstance(protocol_data, dict):
        raise ContractError("generated protocol output has no protocol_data object")
    return protocol_data


def make_semantic_verifier(
    *,
    rubric_version: str,
    expected_surfaces: tuple[str, ...],
    effective_refresh_date: str,
) -> Callable[..., bool]:
    """Create a verifier for family identity, surface scope, and refresh date."""

    def verify(
        *,
        db_url: str,
        family_slug: str,
        before_dump_result: Any,
        dump_result: Any,
    ) -> bool:
        del db_url
        before_output_path = getattr(before_dump_result, "output_path", None)
        output_path = getattr(dump_result, "output_path", None)
        if not isinstance(before_output_path, Path) or not isinstance(output_path, Path):
            raise ContractError("before/after dump runners did not return their output paths")
        protocol_path = output_path / "api" / rubric_version / "protocols" / f"{family_slug}.json"
        try:
            document = json.loads(protocol_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot verify generated protocol output {protocol_path}: {exc}") from exc
        protocol_data = _protocol_payload(document)
        protocol = protocol_data.get("protocol")
        if not isinstance(protocol, dict) or protocol.get("slug") != family_slug:
            raise ContractError("generated output does not describe the target canonical family")
        if str(protocol.get("last_refreshed")) != effective_refresh_date:
            raise ContractError("generated output last_refreshed does not match the approved artifact")
        surfaces = protocol_data.get("surfaces")
        if not isinstance(surfaces, list):
            raise ContractError("generated family output has no surface array")
        actual = tuple(sorted(str(item.get("surface_slug")) for item in surfaces if isinstance(item, dict)))
        if actual != tuple(sorted(expected_surfaces)):
            raise ContractError(
                f"generated surface scope mismatch: expected {sorted(expected_surfaces)}, got {list(actual)}"
            )
        try:
            from protocol_refresh_public.output import verify_output_isolation
        except ImportError:
            from scripts.protocol_refresh_public.output import verify_output_isolation
        report = verify_output_isolation(
            before_output_path / "api" / rubric_version,
            output_path / "api" / rubric_version,
            family_slug,
        )
        if not report["isolated"]:
            raise ContractError(
                "generated output changed unrelated protocol semantics: "
                f"{report['unrelated_changed_files']}"
            )
        return True

    return verify
