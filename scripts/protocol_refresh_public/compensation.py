"""Public-safe proof for a compensated, failed protocol-refresh attempt.

The proof intentionally contains only immutable identifiers and hashes.  It
never exports database URLs, run IDs, exception text, backup locations, or
local research paths.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import ContractError, ID_RE, SHA256_RE, SLUG_RE, canonical_sha256


COMPENSATION_PROOF_SCHEMA_VERSION = "1.0"
COMPENSATION_PROOF_TYPE = "protocol_refresh_compensation_proof"


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def build_compensation_proof(
    *,
    prior_refresh_id: str,
    family_slug: str,
    prior_artifact_sha256: str,
    restored_target_sha256: str,
) -> dict[str, Any]:
    """Return a minimal, self-checksumming proof of a proved compensation."""
    if not isinstance(prior_refresh_id, str) or not ID_RE.fullmatch(prior_refresh_id):
        raise ContractError("compensation proof prior_refresh_id is invalid")
    if not isinstance(family_slug, str) or not SLUG_RE.fullmatch(family_slug):
        raise ContractError("compensation proof family_slug is invalid")
    core = {
        "schema_version": COMPENSATION_PROOF_SCHEMA_VERSION,
        "receipt_type": COMPENSATION_PROOF_TYPE,
        "outcome": "compensated",
        "prior_refresh_id": prior_refresh_id,
        "family_slug": family_slug,
        "prior_artifact_sha256": _require_sha256(
            prior_artifact_sha256, "compensation proof prior_artifact_sha256"
        ),
        "restored_target_sha256": _require_sha256(
            restored_target_sha256, "compensation proof restored_target_sha256"
        ),
        "integrity": {
            "algorithm": "sha256",
            "canonicalization": "sorted-keys-compact-ascii-json-v1",
        },
    }
    core["integrity"]["proof_sha256"] = canonical_sha256(core)
    return core


def verify_compensation_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one proof and return a detached copy or fail closed."""
    if not isinstance(proof, Mapping):
        raise ContractError("compensation proof must be an object")
    value = deepcopy(dict(proof))
    required = {
        "schema_version",
        "receipt_type",
        "outcome",
        "prior_refresh_id",
        "family_slug",
        "prior_artifact_sha256",
        "restored_target_sha256",
        "integrity",
    }
    if set(value) != required:
        raise ContractError("compensation proof has an invalid field set")
    if value.get("schema_version") != COMPENSATION_PROOF_SCHEMA_VERSION:
        raise ContractError("compensation proof schema_version is invalid")
    if value.get("receipt_type") != COMPENSATION_PROOF_TYPE:
        raise ContractError("compensation proof receipt_type is invalid")
    if value.get("outcome") != "compensated":
        raise ContractError("compensation proof outcome must be compensated")
    if not isinstance(value.get("prior_refresh_id"), str) or not ID_RE.fullmatch(value["prior_refresh_id"]):
        raise ContractError("compensation proof prior_refresh_id is invalid")
    if not isinstance(value.get("family_slug"), str) or not SLUG_RE.fullmatch(value["family_slug"]):
        raise ContractError("compensation proof family_slug is invalid")
    _require_sha256(value.get("prior_artifact_sha256"), "compensation proof prior_artifact_sha256")
    _require_sha256(value.get("restored_target_sha256"), "compensation proof restored_target_sha256")
    integrity = value.get("integrity")
    if not isinstance(integrity, dict) or set(integrity) != {
        "algorithm", "canonicalization", "proof_sha256"
    }:
        raise ContractError("compensation proof integrity has an invalid field set")
    if integrity.get("algorithm") != "sha256" or integrity.get("canonicalization") != "sorted-keys-compact-ascii-json-v1":
        raise ContractError("compensation proof integrity metadata is invalid")
    supplied = _require_sha256(integrity.get("proof_sha256"), "compensation proof proof_sha256")
    unsigned = deepcopy(value)
    unsigned["integrity"].pop("proof_sha256")
    if supplied != canonical_sha256(unsigned):
        raise ContractError("compensation proof checksum mismatch")
    return value
