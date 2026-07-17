from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

psycopg = pytest.importorskip("psycopg")
dict_row = pytest.importorskip("psycopg.rows").dict_row

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


def admin_url() -> str:
    value = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not value:
        pytest.skip("TEST_ADMIN_DATABASE_URL is not configured")
    return value


NIGHTLY_WRITE_TABLES = (
    "protocols",
    "deployments",
    "sources",
    "factor_scores",
    "factor_score_sources",
    "protocol_families",
    "protocol_surfaces",
    "pipeline_runs",
    "grade_history",
    "protocol_grade_history",
    "factor_score_history",
    "grade_changes",
)


def nightly_write_state(url: str) -> dict[str, str]:
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(
                f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]')::text FROM {table} AS t"
            ).fetchone()[0]
            for table in NIGHTLY_WRITE_TABLES
        }


def topology_state(url: str) -> tuple:
    with psycopg.connect(url) as conn:
        return conn.execute(
            """SELECT p.total_value_secured_usd,
                      pf.total_value_secured_usd,
                      ps.tvs_usd,
                      p.headline_grade,
                      pf.headline_grade,
                      ps.headline_grade
               FROM protocols AS p
               JOIN protocol_families AS pf ON pf.family_slug = p.slug
               JOIN protocol_surfaces AS ps ON ps.surface_id = pf.primary_surface_id
               WHERE p.slug = 'fixture-family'"""
        ).fetchone()


def fixture_grade_metadata(url: str) -> tuple[str, str, str]:
    with psycopg.connect(url) as conn:
        surface_id, rubric_version, current_grade = conn.execute(
            """SELECT pf.primary_surface_id::text,
                      rv.version,
                      COALESCE(ps.headline_grade, 'B')
               FROM protocol_families AS pf
               JOIN protocol_surfaces AS ps ON ps.surface_id = pf.primary_surface_id
               CROSS JOIN LATERAL (
                 SELECT version
                 FROM rubric_versions
                 WHERE is_active = true
                 ORDER BY version
                 LIMIT 1
               ) AS rv
               WHERE pf.family_slug = 'fixture-family'"""
        ).fetchone()
    next_grade = "A" if current_grade != "A" else "B"
    return surface_id, rubric_version, next_grade


def test_mixed_failure_rolls_back_real_runtime_transaction(monkeypatch) -> None:
    url = runtime_url()
    before_writes = nightly_write_state(url)
    before_state = topology_state(url)
    exported = False

    def post_refresh(**_kwargs):
        nonlocal exported
        exported = True
        return 0

    def mixed_process(*, repo, **_kwargs):
        with repo.transaction():
            repo.update_protocol_tvl("fixture-family", Decimal("987654.32"))
        return [
            refresh.ProtocolResult(slug="ok", status="updated", db_updates=1),
            refresh.ProtocolResult(slug="bad", status="error", error="forced failure"),
        ]

    monkeypatch.setattr(refresh, "process_protocols", mixed_process)
    monkeypatch.setattr(refresh, "_post_refresh_steps", post_refresh)

    assert refresh.run(
        conn_str=url,
        all_protocols=True,
        protocol_slug=None,
        dry_run=False,
    ) == 1
    assert nightly_write_state(url) == before_writes
    assert topology_state(url) == before_state
    assert exported is False


def test_compose_failure_rolls_back_real_runtime_transaction(monkeypatch) -> None:
    url = runtime_url()
    before_writes = nightly_write_state(url)
    before_state = topology_state(url)
    surface_id, rubric_version, next_grade = fixture_grade_metadata(url)
    exported = False

    def post_refresh(**_kwargs):
        nonlocal exported
        exported = True
        return 0

    def successful_process(*, repo, **_kwargs):
        with repo.transaction():
            repo.update_protocol_tvl("fixture-family", Decimal("876543.21"))
            repo.update_deployment_tvl(
                "00000000-0000-0000-0000-000000000101",
                Decimal("876543.21"),
                Decimal("1"),
            )
            with repo.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM factor_scores WHERE id = %s::uuid",
                    ("00000000-0000-0000-0000-000000000201",),
                )
                existing = cur.fetchone()
            assert existing is not None
            repo.replace_factor_score(
                existing,
                refresh.FactorUpdate(
                    factor_id="RD-F-001",
                    score="yellow",
                    evidence_summary="Synthetic rollback evidence.",
                    evidence_detail="Written only inside the forced-failure transaction.",
                    data_as_of=datetime.now(tz=timezone.utc),
                    sources=[
                        refresh.SourceRef(
                            source_type="url",
                            url="https://example.invalid/nightly-rollback",
                            reference="nightly-rollback-fixture",
                            title="Synthetic rollback source",
                        )
                    ],
                ),
                datetime.now(tz=timezone.utc),
            )
        return [
            refresh.ProtocolResult(
                slug="fixture-family",
                status="updated",
                db_updates=1,
                factor_updates=1,
            )
        ]

    def failing_compose(_conn_str, *, connection, **_kwargs):
        connection.execute(
            "UPDATE grade_history SET notes = 'forced rollback' WHERE id = %s::uuid",
            ("00000000-0000-0000-0000-000000000301",),
        )
        connection.execute(
            "UPDATE protocol_grade_history SET grade_letter = 'A' WHERE id = %s::uuid",
            ("00000000-0000-0000-0000-000000000401",),
        )
        connection.execute(
            "UPDATE factor_score_history SET score_color = 'red' WHERE id = %s::uuid",
            ("00000000-0000-0000-0000-000000000501",),
        )
        connection.execute(
            "UPDATE grade_changes SET from_grade = 'A' WHERE id = %s::uuid",
            ("00000000-0000-0000-0000-000000000601",),
        )
        connection.execute(
            """SELECT public.refresh_update_surface_grade(
                 %s, %s::uuid, %s, %s, now(), %s, %s::jsonb, NULL, NULL
               )""",
            (
                "fixture-family",
                surface_id,
                next_grade,
                rubric_version,
                Decimal("42.00"),
                '{"1": 42}',
            ),
        )
        return 1

    monkeypatch.setattr(refresh, "process_protocols", successful_process)
    monkeypatch.setattr(
        refresh,
        "_load_sibling_script",
        lambda _name, _filename: SimpleNamespace(run=failing_compose),
    )
    monkeypatch.setattr(refresh, "_post_refresh_steps", post_refresh)

    assert refresh.run(
        conn_str=url,
        all_protocols=False,
        protocol_slug="fixture-family",
        dry_run=False,
    ) == 1
    assert nightly_write_state(url) == before_writes
    assert topology_state(url) == before_state
    assert exported is False


@pytest.mark.parametrize(
    "query",
    (
        "SELECT public.refresh_sync_family_tvl('', 1)",
        "SELECT public.refresh_sync_family_tvl('fixture-family', -1)",
        "SELECT public.refresh_sync_family_tvl('fixture-family', 'Infinity'::numeric)",
        "SELECT public.refresh_update_surface_grade('fixture-family', (SELECT primary_surface_id FROM protocol_families WHERE family_slug='fixture-family'), 'Z', (SELECT version FROM rubric_versions WHERE is_active ORDER BY version LIMIT 1), now(), 1, '{}'::jsonb, NULL, NULL)",
        "SELECT public.refresh_update_surface_grade('fixture-family', (SELECT primary_surface_id FROM protocol_families WHERE family_slug='fixture-family'), 'B', (SELECT version FROM rubric_versions WHERE is_active ORDER BY version LIMIT 1), now(), 101, '{}'::jsonb, NULL, NULL)",
        "SELECT public.refresh_update_surface_grade('fixture-family', (SELECT primary_surface_id FROM protocol_families WHERE family_slug='fixture-family'), 'B', (SELECT version FROM rubric_versions WHERE is_active ORDER BY version LIMIT 1), now(), 1, '[]'::jsonb, NULL, NULL)",
    ),
)
def test_invalid_runtime_function_inputs_leave_topology_unchanged(query: str) -> None:
    url = runtime_url()
    before = topology_state(url)
    with pytest.raises(psycopg.Error):
        with psycopg.connect(url) as conn:
            conn.execute(query)
    assert topology_state(url) == before


def test_topology_functions_use_family_then_surface_lock_order() -> None:
    runtime = runtime_url()
    admin = admin_url()
    surface_id, rubric_version, next_grade = fixture_grade_metadata(runtime)
    started = threading.Event()
    backend_pid: list[int] = []
    errors: list[BaseException] = []

    def update_grade() -> None:
        conn = psycopg.connect(runtime)
        try:
            backend_pid.append(conn.info.backend_pid)
            started.set()
            conn.execute(
                """SELECT public.refresh_update_surface_grade(
                     'fixture-family', %s::uuid, %s, %s, now(), 20, '{}'::jsonb, NULL, NULL
                   )""",
                (surface_id, next_grade, rubric_version),
            )
            conn.rollback()
        except BaseException as exc:  # pragma: no cover - asserted in the main thread
            errors.append(exc)
            conn.rollback()
        finally:
            conn.close()

    locker = psycopg.connect(admin)
    monitor = psycopg.connect(admin, autocommit=True)
    worker = threading.Thread(target=update_grade, daemon=True)
    try:
        locker.execute("SET LOCAL lock_timeout = '2s'")
        locker.execute(
            "SELECT 1 FROM protocol_families WHERE family_slug='fixture-family' FOR UPDATE"
        )
        worker.start()
        assert started.wait(timeout=2)

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            waiting = monitor.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                (backend_pid[0],),
            ).fetchone()
            if waiting and waiting[0] == "Lock":
                break
            time.sleep(0.05)
        else:
            pytest.fail("runtime function did not block on the family lock")

        locker.execute(
            "SELECT 1 FROM protocol_surfaces WHERE surface_id=%s::uuid FOR UPDATE",
            (surface_id,),
        )
        locker.rollback()
        worker.join(timeout=5)
        assert worker.is_alive() is False
        assert errors == []
    finally:
        locker.rollback()
        locker.close()
        monitor.close()
        if worker.is_alive():
            worker.join(timeout=1)
