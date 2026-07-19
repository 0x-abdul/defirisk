#!/usr/bin/env python3
"""Verify deployment publication policy with SELECT-only database evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


SUMMARY_RE = re.compile(
    r"protocols\s+:\s+(?P<published>\d+) published in protocols/,\s+"
    r"(?P<unpublished>\d+) in unpublished/ \((?P<total>\d+) total\)"
)


class PublicationStateError(ValueError):
    """The dump or database differs from the approved publication policy."""


def load_policy(path: Path) -> dict[str, int]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        database = payload["database"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PublicationStateError(f"invalid deployment publication policy: {path}") from exc
    required = (
        "protocol_count",
        "published_protocol_count",
        "unpublished_protocol_count",
        "family_count",
        "published_family_count",
        "publication_parity_mismatches",
    )
    if not isinstance(database, dict) or any(not isinstance(database.get(key), int) for key in required):
        raise PublicationStateError("deployment database policy requires integer counts")
    return {key: database[key] for key in required}


def parse_dump_summary(path: Path) -> tuple[int, int, int]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PublicationStateError(f"cannot read dump log: {path}") from exc
    match = SUMMARY_RE.search(contents)
    if match is None:
        raise PublicationStateError("dump did not report the protocol publication summary")
    return tuple(int(match.group(key)) for key in ("published", "unpublished", "total"))


def inspect_database(database_url: str) -> tuple[int, int, int, int, int, int]:
    import psycopg

    query = """
        SELECT
          (SELECT count(*) FROM protocols),
          (SELECT count(*) FROM protocols WHERE is_published),
          (SELECT count(*) FROM protocols WHERE NOT is_published),
          (SELECT count(*) FROM protocol_families),
          (SELECT count(*) FROM protocol_families WHERE is_published),
          (SELECT count(*)
             FROM protocols p
             FULL OUTER JOIN protocol_families pf ON pf.family_slug = p.slug
            WHERE p.is_published IS DISTINCT FROM pf.is_published)
    """
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
    if row is None or len(row) != 6 or not all(isinstance(value, int) for value in row):
        raise PublicationStateError("database publication projection is malformed")
    return tuple(row)


def verify(policy: dict[str, int], dump_counts: tuple[int, int, int], database_counts: tuple[int, int, int, int, int, int]) -> None:
    published, unpublished, total = dump_counts
    if (published, unpublished, total) != (
        policy["published_protocol_count"],
        policy["unpublished_protocol_count"],
        policy["protocol_count"],
    ):
        raise PublicationStateError("dump publication summary does not match approved policy")
    expected_database = (
        policy["protocol_count"],
        policy["published_protocol_count"],
        policy["unpublished_protocol_count"],
        policy["family_count"],
        policy["published_family_count"],
        policy["publication_parity_mismatches"],
    )
    if database_counts != expected_database:
        raise PublicationStateError("database publication projection does not match approved policy")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--dump-log", type=Path, required=True)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise PublicationStateError("DATABASE_URL is required")
    verify(load_policy(args.policy), parse_dump_summary(args.dump_log), inspect_database(database_url))


if __name__ == "__main__":
    main()
