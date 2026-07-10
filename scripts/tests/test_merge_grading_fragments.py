from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "merge-grading-fragments.py"
SPEC = importlib.util.spec_from_file_location("merge_grading_fragments", SCRIPT_PATH)
merge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = merge
SPEC.loader.exec_module(merge)


def test_surface_normalisation_preserves_explicit_zero_tvs() -> None:
    grading = {
        "protocol": {"slug": "fixture-family", "display_name": "Fixture"},
        "surfaces": [
            {
                "surface_slug": "core",
                "tvs_usd": 0,
                "total_value_secured_usd": 99,
                "is_primary": True,
            }
        ],
    }
    family = {
        "family_slug": "fixture-family",
        "display_name": "Fixture",
        "primary_chain": "ethereum",
    }

    assert merge.normalise_surfaces(grading, family)[0]["tvs_usd"] == 0


def test_deployment_scope_key_includes_chain_and_deployment_key() -> None:
    family = {"family_slug": "fixture-family"}
    surfaces = [{"surface_slug": "core", "is_primary": True}]
    ethereum = {
        "scope_level": "deployment",
        "surface_slug": "core",
        "chain": "ethereum",
        "deployment_key": "primary",
    }
    arbitrum = {**ethereum, "chain": "arbitrum"}

    assert merge.score_scope_key(ethereum, family, surfaces) != merge.score_scope_key(
        arbitrum, family, surfaces
    )
