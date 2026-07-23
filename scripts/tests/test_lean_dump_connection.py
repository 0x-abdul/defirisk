from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_dump_module():
    pytest.importorskip("psycopg")
    spec = importlib.util.spec_from_file_location("lean_dump_under_test", ROOT / "scripts" / "dump.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Connection:
    def __init__(self) -> None:
        self.cursor_calls = []
        self.entered = self.closed = self.committed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_args):
        self.committed = True
        return False

    def cursor(self, **kwargs):
        self.cursor_calls.append(kwargs)
        return Cursor()

    def close(self):
        self.closed = True


def test_run_dump_uses_supplied_connection_without_ending_its_transaction(monkeypatch) -> None:
    dump = load_dump_module()
    connection = Connection()
    monkeypatch.setattr(dump, "fetch_active_rubric", lambda _cur: {"version": dump.RUBRIC_VERSION})
    monkeypatch.setattr(dump, "fetch_data_as_of", lambda *_args: "2026-01-01T00:00:00Z")
    for name in (
        "fetch_protocols", "fetch_hacks", "fetch_factors", "fetch_active_incidents", "fetch_pipeline_runs", "fetch_grade_changes",
    ):
        monkeypatch.setattr(dump, name, lambda _cur: [])
    for name in (
        "fetch_families_by_slug", "fetch_surfaces_by_family", "fetch_deployments_by_protocol", "fetch_factor_scores_by_protocol",
        "fetch_grade_history_by_protocol", "fetch_hack_factor_links", "fetch_factor_scores_by_factor",
        "fetch_hack_factor_links_by_factor", "fetch_all_grade_snapshots", "fetch_grade_snapshots_by_surface",
    ):
        monkeypatch.setattr(dump, name, lambda *_args: {})

    dump.run_dump(Path("."), dry_run=True, connection=connection)

    assert connection.entered is False
    assert connection.committed is False
    assert connection.closed is False
    assert connection.cursor_calls == [{"row_factory": dump.dict_row}]
