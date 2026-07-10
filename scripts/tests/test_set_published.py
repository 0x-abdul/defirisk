from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "set_published.py"
SPEC = importlib.util.spec_from_file_location("set_published", SCRIPT_PATH)
published = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = published
SPEC.loader.exec_module(published)


class FakeCursor:
    def __init__(self, *, family_table: bool, aliases: dict[str, str] | None = None) -> None:
        self.family_table = family_table
        self.aliases = aliases or {}
        self.executed: list[tuple[str, object]] = []
        self.last_sql = ""
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, sql, params=None) -> None:
        self.executed.append((sql, params))
        self.last_sql = sql
        self.last_params = params

    def fetchall(self):
        if "SELECT legacy_slug, family_slug" in self.last_sql:
            return [
                {"legacy_slug": legacy, "family_slug": family}
                for legacy, family in self.aliases.items()
            ]
        if "SELECT slug, is_published" in self.last_sql:
            return [
                {"slug": slug, "is_published": False}
                for slug in (self.last_params[0] if self.last_params else ["example"])
            ]
        if "SELECT slug FROM protocols WHERE slug = ANY" in self.last_sql:
            return [{"slug": slug} for slug in self.last_params[0]]
        return [{"slug": "example"}]

    def fetchone(self):
        return {"present": self.family_table}


class FakeConn:
    def __init__(self, *, family_table: bool, aliases: dict[str, str] | None = None) -> None:
        self.cur = FakeCursor(family_table=family_table, aliases=aliases)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_publish_mirrors_family_table(monkeypatch) -> None:
    conn = FakeConn(family_table=True)
    monkeypatch.setattr(published.psycopg, "connect", lambda *args, **kwargs: conn)

    assert published.run(
        "postgres://example",
        slugs=["example"],
        publish=True,
        all_protocols=False,
        list_only=False,
        run_dump=False,
    ) == 0

    sql = "\n".join(statement for statement, _ in conn.cur.executed)
    assert "UPDATE protocols SET is_published" in sql
    assert "UPDATE protocol_families" in sql
    assert conn.committed is True
    assert conn.closed is True


def test_publish_remains_compatible_before_family_migration(monkeypatch) -> None:
    conn = FakeConn(family_table=False)
    monkeypatch.setattr(published.psycopg, "connect", lambda *args, **kwargs: conn)

    assert published.run(
        "postgres://example",
        slugs=["example"],
        publish=False,
        all_protocols=False,
        list_only=False,
        run_dump=False,
    ) == 0

    sql = "\n".join(statement for statement, _ in conn.cur.executed)
    assert "UPDATE protocol_families" not in sql


def test_publish_resolves_legacy_alias_to_canonical_family(monkeypatch) -> None:
    conn = FakeConn(family_table=True, aliases={"legacy-v2": "example"})
    monkeypatch.setattr(published.psycopg, "connect", lambda *args, **kwargs: conn)

    assert published.run(
        "postgres://example",
        slugs=["legacy-v2"],
        publish=True,
        all_protocols=False,
        list_only=False,
        run_dump=False,
    ) == 0

    protocol_update = next(
        params
        for statement, params in conn.cur.executed
        if "UPDATE protocols SET is_published" in statement
    )
    assert protocol_update == (True, ["example"])


def test_publish_all_excludes_retained_alias_rows_in_family_mode(monkeypatch) -> None:
    conn = FakeConn(family_table=True)
    monkeypatch.setattr(published.psycopg, "connect", lambda *args, **kwargs: conn)

    assert published.run(
        "postgres://example",
        slugs=[],
        publish=True,
        all_protocols=True,
        list_only=False,
        run_dump=False,
    ) == 0

    sql = "\n".join(statement for statement, _ in conn.cur.executed)
    assert "NOT EXISTS" in sql
    assert "ps.legacy_slug = p.slug" in sql


def test_unpublish_alias_turns_off_alias_and_canonical(monkeypatch) -> None:
    conn = FakeConn(family_table=True, aliases={"legacy-v2": "example"})
    monkeypatch.setattr(published.psycopg, "connect", lambda *args, **kwargs: conn)

    assert published.run(
        "postgres://example",
        slugs=["legacy-v2"],
        publish=False,
        all_protocols=False,
        list_only=False,
        run_dump=False,
    ) == 0

    protocol_update = next(
        params
        for statement, params in conn.cur.executed
        if "UPDATE protocols SET is_published" in statement
    )
    assert protocol_update == (False, ["legacy-v2", "example"])


def test_unpublish_all_includes_every_protocol(monkeypatch) -> None:
    conn = FakeConn(family_table=True)
    monkeypatch.setattr(published.psycopg, "connect", lambda *args, **kwargs: conn)

    assert published.run(
        "postgres://example",
        slugs=[],
        publish=False,
        all_protocols=True,
        list_only=False,
        run_dump=False,
    ) == 0

    target_query = next(
        statement
        for statement, _ in conn.cur.executed
        if "SELECT slug FROM protocols ORDER BY slug" in statement
    )
    assert "NOT EXISTS" not in target_query
