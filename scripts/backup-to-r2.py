#!/usr/bin/env python3
"""Create an encrypted Postgres backup and upload it to Cloudflare R2."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_NAME = "backup-to-r2.py"
DEFAULT_BUCKET = "riskdashboard-backups"
WEEKLY_KEY_RE = re.compile(r"^db/(\d{4}-\d{2}-\d{2})-[a-z]+\.sql\.gpg$")


@dataclass(frozen=True)
class BackupConfig:
    database_url: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_endpoint: str
    backup_gpg_recipient: str
    r2_bucket: str = DEFAULT_BUCKET

    @classmethod
    def from_env(cls) -> "BackupConfig":
        missing = [
            name
            for name in (
                "DATABASE_URL",
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
                "R2_ENDPOINT",
                "BACKUP_GPG_RECIPIENT",
            )
            if not os.environ.get(name)
        ]
        if missing:
            raise SystemExit(
                "ERROR: missing required environment variable(s): "
                + ", ".join(missing)
            )
        return cls(
            database_url=os.environ["DATABASE_URL"],
            r2_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            r2_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            r2_endpoint=os.environ["R2_ENDPOINT"],
            backup_gpg_recipient=os.environ["BACKUP_GPG_RECIPIENT"],
            r2_bucket=os.environ.get("R2_BUCKET") or DEFAULT_BUCKET,
        )


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def backup_keys(now: datetime) -> tuple[str, str | None]:
    day = now.date()
    weekday = day.strftime("%A").lower()
    weekly_key = f"db/{day.isoformat()}-{weekday}.sql.gpg"
    monthly_key = f"db/monthly/{day.strftime('%Y-%m')}.sql.gpg" if day.day == 1 else None
    return weekly_key, monthly_key


def run_checked(args: list[str], *, runner: Any = subprocess.run) -> None:
    printable = " ".join(args)
    print(f"Running: {printable}")
    completed = runner(args, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {printable}")


def run_pg_dump(database_url: str, output_path: Path, *, runner: Any = subprocess.run) -> None:
    run_checked(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(output_path),
            database_url,
        ],
        runner=runner,
    )


def encrypt_backup(
    input_path: Path,
    output_path: Path,
    recipient: str,
    *,
    runner: Any = subprocess.run,
) -> None:
    run_checked(
        [
            "gpg",
            "--batch",
            "--yes",
            "--trust-model",
            "always",
            "--recipient",
            recipient,
            "--output",
            str(output_path),
            "--encrypt",
            str(input_path),
        ],
        runner=runner,
    )


def create_r2_client(config: BackupConfig) -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - CLI dependency guard
        raise SystemExit("ERROR: boto3 is not installed. Run: pip install boto3") from exc

    return boto3.client(
        "s3",
        endpoint_url=config.r2_endpoint,
        aws_access_key_id=config.r2_access_key_id,
        aws_secret_access_key=config.r2_secret_access_key,
        region_name="auto",
    )


def upload_backup(client: Any, bucket: str, source_path: Path, key: str) -> None:
    print(f"Uploading encrypted backup to s3://{bucket}/{key}")
    client.upload_file(str(source_path), bucket, key)


def _iter_objects(client: Any, bucket: str, prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        objects.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            return objects
        token = response.get("NextContinuationToken")
        if not token:
            return objects


def prune_weekly_backups(
    client: Any,
    bucket: str,
    *,
    retention_weeks: int,
    now: datetime,
) -> list[str]:
    cutoff = now.date() - timedelta(weeks=retention_weeks)
    delete_keys: list[str] = []
    for obj in _iter_objects(client, bucket, "db/"):
        key = str(obj.get("Key", ""))
        match = WEEKLY_KEY_RE.match(key)
        if not match:
            continue
        backup_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if backup_date < cutoff:
            delete_keys.append(key)

    if not delete_keys:
        print("No old weekly backups to prune.")
        return []

    print(f"Pruning {len(delete_keys)} old weekly backup object(s).")
    client.delete_objects(
        Bucket=bucket,
        Delete={"Objects": [{"Key": key} for key in delete_keys], "Quiet": True},
    )
    return delete_keys


def perform_backup(
    config: BackupConfig,
    *,
    retention_weeks: int,
    dry_run: bool,
    now: datetime | None = None,
    runner: Any = subprocess.run,
    client: Any | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    weekly_key, monthly_key = backup_keys(now)

    if dry_run:
        print(f"[dry-run] would create weekly backup: s3://{config.r2_bucket}/{weekly_key}")
        if monthly_key:
            print(f"[dry-run] would also create monthly copy: s3://{config.r2_bucket}/{monthly_key}")
        return {"weekly_key": weekly_key, "monthly_key": monthly_key, "pruned": []}

    with tempfile.TemporaryDirectory(prefix="defirisk-backup-") as tmp:
        tmpdir = Path(tmp)
        dump_path = tmpdir / "risk-dashboard.sql"
        encrypted_path = tmpdir / "risk-dashboard.sql.gpg"

        run_pg_dump(config.database_url, dump_path, runner=runner)
        encrypt_backup(
            dump_path,
            encrypted_path,
            config.backup_gpg_recipient,
            runner=runner,
        )

        r2 = client or create_r2_client(config)
        upload_backup(r2, config.r2_bucket, encrypted_path, weekly_key)
        if monthly_key:
            upload_backup(r2, config.r2_bucket, encrypted_path, monthly_key)
        pruned = prune_weekly_backups(
            r2,
            config.r2_bucket,
            retention_weeks=retention_weeks,
            now=now,
        )
        return {"weekly_key": weekly_key, "monthly_key": monthly_key, "pruned": pruned}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up Postgres to encrypted R2 object storage")
    parser.add_argument(
        "--retention-weeks",
        type=int,
        default=8,
        help="Number of weekly backup objects to keep before pruning",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config and print planned keys")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.retention_weeks < 1:
        print("ERROR: --retention-weeks must be >= 1", file=sys.stderr)
        return 1
    result = perform_backup(
        BackupConfig.from_env(),
        retention_weeks=args.retention_weeks,
        dry_run=args.dry_run,
    )
    print(f"Backup complete: {result['weekly_key']}")
    if result["monthly_key"]:
        print(f"Monthly copy complete: {result['monthly_key']}")
    if result["pruned"]:
        print("Pruned weekly objects:")
        for key in result["pruned"]:
            print(f"  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
