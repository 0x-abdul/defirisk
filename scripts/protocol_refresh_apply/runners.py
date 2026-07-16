"""Injectable local process adapters used by the protocol refresh CLI."""

from __future__ import annotations

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
    expected_result: dict[str, Any],
) -> Callable[..., bool]:
    """Create a verifier for family identity, surface scope, and refresh date."""

    def verify(
        *,
        db_url: str,
        family_slug: str,
        before_dump_result: Any,
        dump_result: Any,
        runtime_factor_score_ids: tuple[str, ...] = (),
    ) -> bool:
        del db_url
        before_output_path = getattr(before_dump_result, "output_path", None)
        output_path = getattr(dump_result, "output_path", None)
        if not isinstance(before_output_path, Path) or not isinstance(output_path, Path):
            raise ContractError("before/after dump runners did not return their output paths")
        before_api_root = before_output_path / "api" / rubric_version
        api_root = output_path / "api" / rubric_version
        try:
            from protocol_refresh_public.contracts import (
                ContractError as OutputContractError,
            )
            from protocol_refresh_public.output import (
                resolve_protocol_output,
                verify_output_isolation,
            )
        except ImportError:
            from scripts.protocol_refresh_public.contracts import (
                ContractError as OutputContractError,
            )
            from scripts.protocol_refresh_public.output import (
                resolve_protocol_output,
                verify_output_isolation,
            )
        try:
            before_target = resolve_protocol_output(before_api_root, family_slug)
            target = resolve_protocol_output(api_root, family_slug)
        except OutputContractError as exc:
            raise ContractError(str(exc)) from None
        if before_target.relative_path != target.relative_path:
            raise ContractError(
                "generated output changed the target publication location or review token"
            )
        document = target.document
        protocol_data = _protocol_payload(document)
        protocol = protocol_data.get("protocol")
        if not isinstance(protocol, dict) or protocol.get("slug") != family_slug:
            raise ContractError("generated output does not describe the target canonical family")
        if protocol.get("headline_grade") != expected_result["headline_grade"]:
            raise ContractError("generated output headline grade does not match expected_result")
        risk_score = protocol.get("risk_score")
        if not isinstance(risk_score, (int, float)) or isinstance(risk_score, bool) or f"{risk_score:.2f}" != expected_result["risk_score"]:
            raise ContractError("generated output risk score does not match expected_result")
        cap = protocol.get("cap_applied")
        normalized_cap = "none" if cap in {None, "none", False} else "cap"
        if normalized_cap != expected_result["cap_state"]:
            raise ContractError("generated output cap state does not match expected_result")
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
        expected_surface_results = expected_result["surface_results"]
        if set(expected_surface_results) != set(expected_surfaces):
            raise ContractError("expected_result surface scope does not match the handoff")
        output_ids: list[str] = []
        output_ids: list[str] = []
        for surface in surfaces:
            if not isinstance(surface, dict):
                continue
            expected_surface = expected_surface_results.get(str(surface.get("surface_slug")))
            if not isinstance(expected_surface, dict):
                raise ContractError("generated surface is absent from expected_result")
            for key in ("headline_grade",):
                if surface.get(key) != expected_surface.get(key):
                    raise ContractError("generated surface grade does not match expected_result")
            surface_risk = surface.get("risk_score")
            if not isinstance(surface_risk, (int, float)) or isinstance(surface_risk, bool) or f"{surface_risk:.2f}" != expected_surface.get("risk_score"):
                raise ContractError("generated surface risk score does not match expected_result")
            surface_cap = surface.get("cap_applied")
            if ("none" if surface_cap in {None, "none", False} else "cap") != expected_surface.get("cap_state"):
                raise ContractError("generated surface cap state does not match expected_result")
            factor_scores = surface.get("factor_scores", [])
            if not isinstance(factor_scores, list):
                raise ContractError("generated surface factor_scores must be an array")
            output_ids.extend(str(item["score_id"]) for item in factor_scores if isinstance(item, dict) and item.get("score_id") is not None)
        if len(set(output_ids)) != expected_result["active_factor_count"]:
            raise ContractError("generated active factor count does not match expected_result")
        if len(runtime_factor_score_ids) != len(set(runtime_factor_score_ids)):
            raise ContractError("runtime factor-score receipt contains duplicate UUIDs")
        if runtime_factor_score_ids and not set(runtime_factor_score_ids) <= set(output_ids):
            raise ContractError("generated target output is missing a runtime-created factor-score UUID")
        try:
            report = verify_output_isolation(
                before_api_root,
                api_root,
                family_slug,
            )
        except OutputContractError as exc:
            raise ContractError(str(exc)) from None
        if not report["isolated"]:
            raise ContractError(
                "generated output changed unrelated protocol semantics: "
                f"{report['unrelated_changed_files']}"
            )
        return True

    return verify
