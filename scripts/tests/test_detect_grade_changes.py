from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "detect-grade-changes.py"
SPEC = importlib.util.spec_from_file_location("detect_grade_changes", SCRIPT_PATH)
detect = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = detect
SPEC.loader.exec_module(detect)


class FakeCursor:
    def __init__(self, fetches=None) -> None:
        self.fetches = list(fetches or [])
        self.executed = []

    def execute(self, sql, params=None) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return self.fetches.pop(0) if self.fetches else None

    def fetchall(self):
        return self.fetches.pop(0) if self.fetches else []


def test_is_upgrade_uses_grade_order() -> None:
    assert detect.is_upgrade("C", "B") is True
    assert detect.is_upgrade("B", "C") is False
    assert detect.is_upgrade("A", "A") is False


def test_find_grade_changes_defaults_to_one_snapshot_date() -> None:
    cur = FakeCursor(fetches=[[{"protocol_slug": "aave-v3"}]])

    rows = detect.find_grade_changes(
        cur,
        snapshot_date="2026-07-03",
        backfill=False,
    )

    sql, params = cur.executed[0]
    assert "AND snapshot_date = %s" in sql
    assert params == ("2026-07-03",)
    assert rows == [{"protocol_slug": "aave-v3"}]


def test_find_grade_changes_backfill_scans_all_history() -> None:
    cur = FakeCursor(fetches=[[]])

    detect.find_grade_changes(cur, snapshot_date="2026-07-03", backfill=True)

    sql, params = cur.executed[0]
    assert "AND snapshot_date = %s" not in sql
    assert params is None


def test_insert_grade_changes_dry_run_does_not_write() -> None:
    cur = FakeCursor()
    rows = [
        {
            "protocol_slug": "aave-v3",
            "from_grade": "C",
            "to_grade": "B",
            "rubric_version": "v1.7.0",
            "snapshot_date_before": "2026-06-01",
            "snapshot_date_after": "2026-06-02",
            "source_run_id": "run-id",
        }
    ]

    assert detect.insert_grade_changes(cur, rows, dry_run=True) == 1
    assert cur.executed == []


def test_insert_grade_changes_counts_only_inserted_rows() -> None:
    cur = FakeCursor(fetches=[{"id": "new-id"}, None])
    rows = [
        {
            "protocol_slug": "aave-v3",
            "from_grade": "C",
            "to_grade": "B",
            "rubric_version": "v1.7.0",
            "snapshot_date_before": "2026-06-01",
            "snapshot_date_after": "2026-06-02",
            "source_run_id": "run-id",
        },
        {
            "protocol_slug": "aave-v3",
            "from_grade": "B",
            "to_grade": "C",
            "rubric_version": "v1.7.0",
            "snapshot_date_before": "2026-06-02",
            "snapshot_date_after": "2026-06-03",
            "source_run_id": "run-id",
        },
    ]

    assert detect.insert_grade_changes(cur, rows, dry_run=False) == 1
    assert len(cur.executed) == 2
