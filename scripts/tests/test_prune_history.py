from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "prune-history.py"
SPEC = importlib.util.spec_from_file_location("prune_history", SCRIPT_PATH)
prune = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = prune
SPEC.loader.exec_module(prune)


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self, *args, **kwargs):
        return self

    def close(self) -> None:
        self.closed = True

    def __iter__(self):
        return iter(())


def test_run_dry_run_counts_without_deleting(monkeypatch) -> None:
    conn = FakeConn()
    calls: list[str] = []
    monkeypatch.setattr(prune, "connect", lambda conn_str: conn)
    monkeypatch.setattr(prune, "create_pipeline_run", lambda cur: "run-id")
    monkeypatch.setattr(prune, "count_protocol_rows_to_prune", lambda cur: calls.append("count-protocol") or 2)
    monkeypatch.setattr(prune, "count_factor_rows_to_prune", lambda cur: calls.append("count-factor") or 3)
    monkeypatch.setattr(prune, "prune_protocol_rows", lambda cur: calls.append("delete-protocol") or 0)
    monkeypatch.setattr(prune, "prune_factor_rows", lambda cur: calls.append("delete-factor") or 0)

    assert prune.run("postgres://example", dry_run=True) == 0
    assert calls == ["count-protocol", "count-factor"]
    assert conn.closed is True


def test_run_prunes_and_updates_pipeline_run(monkeypatch) -> None:
    conn = FakeConn()
    calls: list[tuple] = []
    monkeypatch.setattr(prune, "connect", lambda conn_str: conn)
    monkeypatch.setattr(prune, "create_pipeline_run", lambda cur: "run-id")
    monkeypatch.setattr(prune, "prune_protocol_rows", lambda cur: calls.append(("delete-protocol",)) or 2)
    monkeypatch.setattr(prune, "prune_factor_rows", lambda cur: calls.append(("delete-factor",)) or 3)
    monkeypatch.setattr(
        prune,
        "update_pipeline_run",
        lambda cur, run_id, **kwargs: calls.append(("update", run_id, kwargs)),
    )

    assert prune.run("postgres://example", dry_run=False) == 0
    assert calls[0:2] == [("delete-protocol",), ("delete-factor",)]
    assert calls[2][0] == "update"
    assert calls[2][1] == "run-id"
    assert calls[2][2]["deleted_protocol_rows"] == 2
    assert calls[2][2]["deleted_factor_rows"] == 3
    assert conn.closed is True
