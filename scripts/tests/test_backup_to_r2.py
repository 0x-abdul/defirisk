from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "backup-to-r2.py"
SPEC = importlib.util.spec_from_file_location("backup_to_r2", SCRIPT_PATH)
backup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backup
SPEC.loader.exec_module(backup)


def config() -> backup.BackupConfig:
    return backup.BackupConfig(
        database_url="postgres://example",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_endpoint="https://r2.example",
        backup_gpg_recipient="backup@example.com",
        r2_bucket="bucket",
    )


class FakeR2:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []

    def upload_file(self, source: str, bucket: str, key: str) -> None:
        self.uploads.append((source, bucket, key))

    def list_objects_v2(self, **kwargs):
        return {
            "Contents": [
                {"Key": "db/2026-04-01-wednesday.sql.gpg"},
                {"Key": "db/2026-06-20-saturday.sql.gpg"},
                {"Key": "db/monthly/2026-04.sql.gpg"},
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, **kwargs) -> None:
        self.deleted.extend(item["Key"] for item in kwargs["Delete"]["Objects"])


def test_backup_keys_include_monthly_copy_on_first_of_month() -> None:
    weekly, monthly = backup.backup_keys(datetime(2026, 7, 1, tzinfo=timezone.utc))

    assert weekly == "db/2026-07-01-wednesday.sql.gpg"
    assert monthly == "db/monthly/2026-07.sql.gpg"


def test_perform_backup_uploads_and_prunes_without_real_services() -> None:
    calls: list[list[str]] = []

    def runner(args, check=False):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    fake_r2 = FakeR2()
    result = backup.perform_backup(
        config(),
        retention_weeks=8,
        dry_run=False,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        runner=runner,
        client=fake_r2,
    )

    assert calls[0][0] == "pg_dump"
    assert calls[1][0] == "gpg"
    assert result["weekly_key"] == "db/2026-07-01-wednesday.sql.gpg"
    assert result["monthly_key"] == "db/monthly/2026-07.sql.gpg"
    assert [upload[2] for upload in fake_r2.uploads] == [
        "db/2026-07-01-wednesday.sql.gpg",
        "db/monthly/2026-07.sql.gpg",
    ]
    assert fake_r2.deleted == ["db/2026-04-01-wednesday.sql.gpg"]


def test_run_checked_raises_on_nonzero_exit() -> None:
    def runner(args, check=False):
        return SimpleNamespace(returncode=7)

    try:
        backup.run_checked(["false"], runner=runner)
    except RuntimeError as exc:
        assert "exit code 7" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
