from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "cleanup-multiversion-runtime-artifacts.py"
SPEC = importlib.util.spec_from_file_location("cleanup_multiversion_runtime_artifacts", SCRIPT_PATH)
cleanup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = cleanup
SPEC.loader.exec_module(cleanup)


def args(**overrides):
    values = {
        "expected_database": "fixture_staging",
        "allow_nonlocal": False,
        "i_understand_nonlocal": False,
        "allow_protected_database": False,
        "i_understand_protected_database": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_cleanup_requires_exact_database_name() -> None:
    url = "postgresql://user:pass@localhost:5432/fixture_staging"
    target = cleanup.require_local_database(url, args())

    assert target["database"] == "fixture_staging"


def test_cleanup_blocks_production_without_double_guard() -> None:
    url = "postgresql://user:pass@localhost:5432/risk_dashboard"

    try:
        cleanup.require_local_database(
            url,
            args(expected_database="risk_dashboard"),
        )
    except cleanup.CleanupError as exc:
        assert "protected database" in str(exc)
    else:
        raise AssertionError("expected protected database guard")


def test_fk_discovery_pairs_composite_columns_by_position() -> None:
    class Cursor:
        sql = ""

        def execute(self, sql, params=()):
            self.sql = sql

        def fetchall(self):
            return [
                {
                    "table_name": "protocol_families",
                    "column_name": "primary_surface_id",
                    "foreign_table_name": "protocol_surfaces",
                    "foreign_column_name": "surface_id",
                    "delete_rule": "NO ACTION",
                }
            ]

    cur = Cursor()
    edges = cleanup.fetch_fk_edges(cur)

    assert edges[0]["column_name"] == "primary_surface_id"
    assert "WITH ORDINALITY" in cur.sql
    assert "target_key.position = source_key.position" in cur.sql
