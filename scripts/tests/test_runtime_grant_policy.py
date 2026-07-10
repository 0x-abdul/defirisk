from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "verify-runtime-grant-policy.py"
SPEC = importlib.util.spec_from_file_location("verify_runtime_grant_policy", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def policy() -> dict:
    return {
        "schema_version": "1.0",
        "runtime_role": "rdapp",
        "known_public_tables": ["family", "protocol"],
        "managed_table_privileges": {"family": ["SELECT"]},
    }


def test_policy_accepts_exact_inventory_and_managed_grants() -> None:
    assert MODULE.validate_policy(
        policy(), {"family", "protocol"}, {"family": {"SELECT"}}
    ) == []


def test_policy_rejects_unclassified_table_and_grant_drift() -> None:
    errors = MODULE.validate_policy(
        policy(), {"family", "protocol", "new_table"}, {"family": {"SELECT", "UPDATE"}}
    )
    assert any("classification drift" in error for error in errors)
    assert any("runtime grants" in error for error in errors)
