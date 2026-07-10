from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_public.readiness import (
    APPLY_FILES,
    FOUNDATION_FILES,
    MIGRATIONS,
    ROLLOUT_EVIDENCE,
    evaluate_readiness,
)


SCRIPT = Path(__file__).resolve().parents[1] / "verify-protocol-refresh-public.py"
SPEC = importlib.util.spec_from_file_location("verify_protocol_refresh_public", SCRIPT)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def write(root, relative: str, content: str = "present") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_foundation(root) -> None:
    for relative in FOUNDATION_FILES:
        write(root, relative)
    for relative, markers in MIGRATIONS:
        write(root, relative, "\n".join(markers))


def test_readiness_keeps_apply_and_rollout_separate(tmp_path) -> None:
    make_foundation(tmp_path)

    report = evaluate_readiness(tmp_path)

    assert report["foundation_ready"] is True
    assert report["apply_ready"] is False
    assert report["rollout_ready"] is False
    assert report["production_ready"] is False


def test_rollout_requires_apply_parity_and_pilot_evidence(tmp_path) -> None:
    make_foundation(tmp_path)
    for relative in APPLY_FILES:
        write(tmp_path, relative)
    write(
        tmp_path,
        "scripts/dump.py",
        "def fetch_protocols(cur):\n    cur.execute('SELECT last_refreshed FROM protocols')\n",
    )

    apply_report = evaluate_readiness(tmp_path)
    assert apply_report["apply_ready"] is True
    assert apply_report["rollout_ready"] is False

    write(
        tmp_path,
        ROLLOUT_EVIDENCE,
        json.dumps(
            {
                "family_import_cleanup_complete": True,
                "family_parity_verified": True,
                "pilot_refreshes_verified": True,
                "pilot_refresh_ids": ["pilot-one"],
            }
        ),
    )
    rollout_report = evaluate_readiness(tmp_path)
    assert rollout_report["rollout_ready"] is True
    assert rollout_report["production_ready"] is True


def test_apply_readiness_requires_last_refreshed_in_dump_export(tmp_path) -> None:
    make_foundation(tmp_path)
    for relative in APPLY_FILES:
        write(tmp_path, relative)
    write(
        tmp_path,
        "scripts/dump.py",
        "def fetch_protocols(cur):\n    cur.execute('SELECT slug FROM protocols')\n",
    )

    report = evaluate_readiness(tmp_path)

    assert report["apply_ready"] is False
    assert any("protocols.last_refreshed" in item for item in report["apply_blockers"])


def test_missing_last_refreshed_guard_blocks_foundation(tmp_path) -> None:
    make_foundation(tmp_path)
    migration = tmp_path / "db/migrations/0009_protocol_last_refreshed.sql"
    migration.write_text("ADD COLUMN IF NOT EXISTS last_refreshed", encoding="utf-8")

    report = evaluate_readiness(tmp_path)

    assert report["foundation_ready"] is False
    assert any("WHERE last_refreshed IS NULL" in item for item in report["foundation_blockers"])


def test_readiness_cli_gates_only_the_selected_level(tmp_path, capsys) -> None:
    make_foundation(tmp_path)

    assert CLI.main(["--repo-root", str(tmp_path)]) == 0
    default_report = json.loads(capsys.readouterr().out)
    assert default_report["ok"] is True
    assert default_report["readiness"]["rollout_ready"] is False

    assert CLI.main(["--repo-root", str(tmp_path), "--foundation-only"]) == 0
    foundation_report = json.loads(capsys.readouterr().out)
    assert foundation_report["selected_readiness"] == "foundation_ready"

    assert CLI.main(["--repo-root", str(tmp_path), "--apply-ready"]) == 1
    apply_report = json.loads(capsys.readouterr().err)
    assert apply_report["contract_valid"] is True
    assert apply_report["readiness_requirement_met"] is False


def test_publication_metadata_schema_is_valid_json() -> None:
    schema = (
        Path(__file__).resolve().parents[2]
        / "docs/ops/protocol-refresh/schemas/publication-metadata.schema.json"
    )
    document = json.loads(schema.read_text(encoding="utf-8"))
    assert document["title"] == "Protocol refresh publication metadata proposal"
    assert "approved_public_payload_sha256" in document["required"]
