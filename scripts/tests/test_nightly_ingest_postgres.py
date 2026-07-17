from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

psycopg = pytest.importorskip("psycopg")

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "refresh-continuous.py"
SPEC = importlib.util.spec_from_file_location("refresh_continuous_postgres", SCRIPT_PATH)
refresh = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = refresh
SPEC.loader.exec_module(refresh)


def runtime_url() -> str:
    value = os.environ.get("TEST_RUNTIME_DATABASE_URL")
    if not value:
        pytest.skip("TEST_RUNTIME_DATABASE_URL is not configured")
    return value


def pipeline_run_count(url: str) -> int:
    with psycopg.connect(url) as conn:
        return int(conn.execute("SELECT count(*) FROM pipeline_runs").fetchone()[0])


def test_mixed_failure_rolls_back_real_runtime_transaction(monkeypatch) -> None:
    url = runtime_url()
    before = pipeline_run_count(url)
    exported = False

    def post_refresh(**_kwargs):
        nonlocal exported
        exported = True
        return 0

    monkeypatch.setattr(
        refresh,
        "process_protocols",
        lambda **_kwargs: [
            refresh.ProtocolResult(slug="ok", status="updated", db_updates=1),
            refresh.ProtocolResult(slug="bad", status="error", error="forced failure"),
        ],
    )
    monkeypatch.setattr(refresh, "_post_refresh_steps", post_refresh)

    assert refresh.run(
        conn_str=url,
        all_protocols=True,
        protocol_slug=None,
        dry_run=False,
    ) == 1
    assert pipeline_run_count(url) == before
    assert exported is False


def test_compose_failure_rolls_back_real_runtime_transaction(monkeypatch) -> None:
    url = runtime_url()
    before = pipeline_run_count(url)
    exported = False

    def post_refresh(**_kwargs):
        nonlocal exported
        exported = True
        return 0

    monkeypatch.setattr(
        refresh,
        "process_protocols",
        lambda **_kwargs: [
            refresh.ProtocolResult(
                slug="fixture-family",
                status="updated",
                db_updates=1,
                factor_updates=1,
            )
        ],
    )
    monkeypatch.setattr(
        refresh,
        "_load_sibling_script",
        lambda _name, _filename: SimpleNamespace(run=lambda *_args, **_kwargs: 1),
    )
    monkeypatch.setattr(refresh, "_post_refresh_steps", post_refresh)

    assert refresh.run(
        conn_str=url,
        all_protocols=False,
        protocol_slug="fixture-family",
        dry_run=False,
    ) == 1
    assert pipeline_run_count(url) == before
    assert exported is False
