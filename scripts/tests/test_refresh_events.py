from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "refresh-events.py"
SPEC = importlib.util.spec_from_file_location("refresh_events", SCRIPT_PATH)
events = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = events
SPEC.loader.exec_module(events)


class FakeRepo:
    def __init__(self) -> None:
        self.updates: list[tuple[str, bool]] = []

    def update_protocol_incident_flag(self, slug: str, has_active_incident: bool) -> None:
        self.updates.append((slug, has_active_incident))


def test_refresh_protocol_updates_changed_incident_flag() -> None:
    repo = FakeRepo()
    result = events.refresh_protocol(
        repo,
        {
            "slug": "aave-v3",
            "has_active_incident": False,
            "computed_has_active_incident": True,
        },
        dry_run=False,
    )

    assert result.status == "updated"
    assert result.db_updates == 1
    assert repo.updates == [("aave-v3", True)]


def test_refresh_protocol_dry_run_does_not_write() -> None:
    repo = FakeRepo()
    result = events.refresh_protocol(
        repo,
        {
            "slug": "aave-v3",
            "has_active_incident": False,
            "computed_has_active_incident": True,
        },
        dry_run=True,
    )

    assert result.status == "updated"
    assert result.db_updates == 1
    assert repo.updates == []


def test_refresh_protocol_unchanged_when_incident_flag_matches() -> None:
    repo = FakeRepo()
    result = events.refresh_protocol(
        repo,
        {
            "slug": "aave-v3",
            "has_active_incident": True,
            "computed_has_active_incident": True,
        },
        dry_run=False,
    )

    assert result.status == "unchanged"
    assert result.db_updates == 0
    assert repo.updates == []


def test_all_mode_keeps_protocol_errors_nonfatal() -> None:
    class PartlyBrokenRepo(FakeRepo):
        def update_protocol_incident_flag(self, slug: str, has_active_incident: bool) -> None:
            if slug == "broken":
                raise RuntimeError("db unavailable")
            super().update_protocol_incident_flag(slug, has_active_incident)

    repo = PartlyBrokenRepo()
    results = events.process_protocols(
        repo,
        [
            {
                "slug": "broken",
                "has_active_incident": False,
                "computed_has_active_incident": True,
            },
            {
                "slug": "ok",
                "has_active_incident": False,
                "computed_has_active_incident": True,
            },
        ],
        dry_run=False,
        all_protocols=True,
    )

    assert len(results) == 2
    assert results[0].slug == "broken"
    assert results[0].error == "db unavailable"
    assert results[1].slug == "ok"
    assert results[1].error is None
    assert repo.updates == [("ok", True)]
