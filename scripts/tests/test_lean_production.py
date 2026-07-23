from __future__ import annotations

from pathlib import Path
import json
import subprocess
from types import SimpleNamespace

import pytest

from lean_protocol_refresh.contracts import (
    ContractError,
    Evidence,
    FactorChange,
    ProtocolRefresh,
    RefreshBatch,
)
from lean_protocol_refresh.production import ProductionOperations, _run, create_operations


def batch() -> RefreshBatch:
    return RefreshBatch("batch / unsafe", "2026-07-23", "v1.7.0", ())


def test_process_runner_decodes_public_records_as_utf8(tmp_path: Path) -> None:
    result = _run(
        (
            __import__("sys").executable,
            "-c",
            "import sys; sys.stdout.buffer.write('public — evidence'.encode('utf-8'))",
        ),
        tmp_path,
    )
    assert result.stdout == "public — evidence"


def test_factory_requires_repository_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RISKDASHBOARD_REPOSITORY_ROOT", raising=False)
    with pytest.raises(ContractError, match="repository_root"):
        create_operations(batch(), {"database_url": "postgresql://x", "repository": "o/r", "base_branch": "main"})


def test_backup_is_atomic_private_and_idempotent(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    def runner(command, cwd):
        calls.append(tuple(command))
        if command[0] == "pg_dump":
            Path(command[command.index("--file") + 1]).write_bytes(b"custom")
    ops = ProductionOperations(batch(), "postgresql://x", tmp_path, "o/r", "main", (), (), backup_root=tmp_path / "backups", command_runner=runner)
    ops.verify_batch_backup(batch())
    backup = tmp_path / "backups" / "batch-unsafe.dump"
    assert backup.read_bytes() == b"custom"
    if __import__("os").name != "nt":
        assert backup.stat().st_mode & 0o077 == 0
    ops.verify_batch_backup(batch())
    assert [call[0] for call in calls].count("pg_dump") == 1
    assert [call[0] for call in calls].count("pg_restore") == 2


def test_backup_can_run_on_production_host_while_github_runs_locally(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    ops = ProductionOperations(
        batch(),
        "postgresql://tunnel",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        backup_ssh_host="riskdash-app",
        command_runner=lambda command, _cwd: calls.append(tuple(command)),
    )
    ops.verify_batch_backup(batch())
    assert len(calls) == 1
    command = calls[0]
    assert command[:3] == ("ssh", "-o", "BatchMode=yes")
    assert ("-o", "StrictHostKeyChecking=yes") == command[3:5]
    assert ("-o", "ConnectTimeout=10") == command[5:7]
    assert ("-o", "ServerAliveInterval=15") == command[7:9]
    assert ("-o", "ServerAliveCountMax=2") == command[9:11]
    assert command[11] == "riskdash-app"
    script = command[12]
    assert "readarray -d '' db_parts" in script
    assert 'export PGPASSWORD="${db_parts[3]}"' in script
    assert "pg_dump --format=custom" in script
    assert 'pg_dump --format=custom --file="$temp" "$DATABASE_URL"' not in script
    assert 'PGDATABASE="$db_url"' not in script
    assert "pg_restore --list" in script
    assert "/opt/riskdashboard/.backups/protocol-refresh/batch-unsafe.dump" in script
    assert "postgresql://tunnel" not in script


def test_backup_ssh_host_rejects_option_injection(tmp_path: Path) -> None:
    ops = ProductionOperations(
        batch(),
        "postgresql://tunnel",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        backup_ssh_host="-oProxyCommand=bad",
        command_runner=lambda *_: None,
    )
    with pytest.raises(ContractError, match="backup_ssh_host"):
        ops.verify_batch_backup(batch())


def test_public_record_refuses_local_paths(tmp_path: Path) -> None:
    ops = ProductionOperations(batch(), "postgresql://x", tmp_path, "o/r", "main", (), (), command_runner=lambda *_: None)
    # The adapter's path guard is intentionally public-artifact specific; no network call occurs here.
    protocol = type(
        "P",
        (),
        {"family_slug": "aave-v3", "last_refreshed": "2026-07-22"},
    )()
    assert ops._branch(protocol) == "refresh/aave-v3/2026-07-23"
    body = ops._pull_request_body(protocol)
    assert "One topic: `aave-v3` only." in body
    assert "No direct factor-score or letter-grade edits." in body
    assert "No generated `data/api/` edits." in body
    assert not ops._contains_local_path(
        {
            "notes": "profile: verified",
            "url": "https://example.org/users/public/file.json",
        }
    )
    assert ops._contains_local_path({"notes": "see file:///tmp/private.json"})
    assert ops._contains_local_path({"notes": r"see C:\Users\private.json"})
    assert ops._contains_local_path(
        {"notes": r"see \\private-server\share\secret.json"}
    )
    assert ops._contains_local_path({"notes": r"see ..\private\secret.json"})
    assert ops._contains_local_path({"notes": "see ./private/secret.json"})
    assert ops._contains_local_path(
        {"notes": r"path=\\private-server\share\secret.json"}
    )
    assert ops._contains_local_path({"notes": r"path=..\private\secret.json"})
    assert ops._contains_local_path({"notes": "path:../private/secret.json"})
    assert ops._contains_local_path({"notes": "path=/etc/secret.conf"})
    assert ops._contains_local_path(
        {"notes": "https://example.org,local=/etc/secret.conf"}
    )
    for root in ("/etc/", "/var/", "/srv/", "/root/", "/mnt/", "/workspace/"):
        assert ops._contains_local_path({"notes": f"see {root}private.json"})


def test_factory_uses_builtin_resume_deploy_and_live_operations(tmp_path: Path) -> None:
    operations = create_operations(
        batch(),
        {
            "database_url": "postgresql://x",
            "repository_root": str(tmp_path),
            "repository": "o/r",
            "base_branch": "main",
        },
    )
    assert operations.deploy_command == ()
    assert operations.live_check_command == ()


def test_factory_accepts_remote_backup_host(tmp_path: Path) -> None:
    operations = create_operations(
        batch(),
        {
            "database_url": "postgresql://tunnel",
            "repository_root": str(tmp_path),
            "repository": "o/r",
            "base_branch": "main",
            "backup_ssh_host": "riskdash-app",
        },
    )
    assert operations.backup_ssh_host == "riskdash-app"


def test_semantic_tree_ignores_export_noise(tmp_path: Path) -> None:
    path = tmp_path / "api" / "v1.7.0"
    path.mkdir(parents=True)
    (path / "one.json").write_text('{"generated_at":"a","data_as_of":"b","status":"ok","data":{"x":1}}')
    (path / "status.json").write_text('{"data":{"run":"before"}}')
    nested_status = path / "protocols" / "maple" / "status.json"
    nested_status.parent.mkdir(parents=True)
    nested_status.write_text('{"data":{"protocol":"stable"}}')
    first = ProductionOperations._semantic_tree(tmp_path / "api")
    assert "v1.7.0/status.json" not in first
    assert "v1.7.0/protocols/maple/status.json" in first
    (path / "one.json").write_text('{"generated_at":"c","data_as_of":"d","status":"different","data":{"x":1}}')
    (path / "status.json").write_text('{"data":{"run":"after"}}')
    assert first == ProductionOperations._semantic_tree(tmp_path / "api")


def test_unrelated_output_error_never_exposes_protected_path(tmp_path: Path) -> None:
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        command_runner=lambda *_: None,
    )
    protected = "v1.7.0/unpublished/other-private-token/index.json"
    ops._output_before = {protected: '{"before":true}'}
    ops._conn = object()
    ops._dump_workspace = __import__("tempfile").TemporaryDirectory()
    root = Path(ops._dump_workspace.name) / "after" / "api"
    target = root / protected
    target.parent.mkdir(parents=True)
    target.write_text('{"after":true}', encoding="utf-8")
    ops._verify_target_semantics = lambda _protocol: None
    ops._verify_dumped_target = lambda _protocol, _root: None

    import compose
    import dump

    original_compose = compose.run
    original_dump = dump.run_dump
    compose.run = lambda *_args, **_kwargs: 0
    dump.run_dump = lambda *_args, **_kwargs: None
    try:
        with pytest.raises(ContractError) as caught:
            ops.compare_target_output(
                ProtocolRefresh(
                    "maple",
                    ("default",),
                    (),
                    "no_change",
                    "2026-07-23",
                    "A",
                    "v1.7.0",
                    (),
                    "A",
                )
            )
    finally:
        compose.run = original_compose
        dump.run_dump = original_dump
        ops._close_dump_workspace()
    assert str(caught.value) == "pipeline changed unrelated semantic output"
    assert "private-token" not in str(caught.value)


def test_no_change_live_document_requires_184_rows_and_freshness() -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "maple",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "A",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": [
                    {"factor_id": f"RD-F-{index:03d}"}
                    for index in range(1, 186)
                    if index != 169
                ],
            }
        }
    }
    ProductionOperations._verify_protocol_document(protocol, payload)
    payload["data"]["protocol_data"]["protocol"]["last_refreshed"] = "2026-07-22"
    with pytest.raises(ContractError, match="metadata"):
        ProductionOperations._verify_protocol_document(protocol, payload)


def test_unpublished_target_uses_protected_route_without_exposing_token(
    tmp_path: Path,
) -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "maple",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "A",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": [
                    {"factor_id": f"RD-F-{index:03d}"}
                    for index in range(1, 185)
                ],
            }
        }
    }

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql, _params):
            return None

        def fetchone(self):
            return (False, "private-token")

    class Connection:
        def cursor(self):
            return Cursor()

        def rollback(self):
            return None

    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        connect=lambda _url: Connection(),
    )
    path = (
        tmp_path
        / "api"
        / "v1.7.0"
        / "unpublished"
        / "maple-private-token"
        / "index.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    ops._verify_dumped_target(protocol, tmp_path / "api")

    seen: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(payload).encode()

    def urlopen(request_url, **_kwargs):
        seen.append(request_url)
        if "/protocols/" in request_url:
            raise __import__("urllib").error.HTTPError(
                request_url, 404, "not found", None, None
            )
        return Response()

    ops.urlopen = urlopen
    assert ops._fetch_live_payload(protocol) == payload
    assert seen == [
        "https://defirisk.co/api/v1.7.0/protocols/maple.json",
        "https://defirisk.co/api/v1.7.0/unpublished/"
        "maple-private-token/index.json"
    ]


def test_source_identity_collision_reuses_one_row_without_global_metadata_write() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls = []
            self.rows = [None, ("source-id",), ("source-id",)]

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return self.rows.pop(0)

    cursor = Cursor()
    first = {
        "source_type": "docs",
        "url": "https://example.org/shared",
        "reference": "Shared source",
        "title": "First title",
        "retrieved_at": "2026-07-22",
    }
    second = {**first, "title": "Different per-factor title", "retrieved_at": "2026-07-23"}
    assert ProductionOperations._get_or_create_source(cursor, first, "2026-07-23") == "source-id"
    assert ProductionOperations._get_or_create_source(cursor, second, "2026-07-23") == "source-id"
    statements = [sql for sql, _params in cursor.calls]
    assert sum("INSERT INTO sources" in sql for sql in statements) == 1
    assert sum("UPDATE sources" in sql for sql in statements) == 0


def test_remote_branch_without_pr_resumes_by_creating_pr(tmp_path: Path) -> None:
    change = FactorChange(
        "RD-F-001",
        "surface",
        "default",
        {"factor_id": "RD-F-001", "score": "yellow", "sources": []},
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "sources": [{"url": "https://example.org/new"}],
        },
        (Evidence("https://example.org/new"),),
        "green",
        "B",
    )
    protocol = ProtocolRefresh(
        "falcon",
        ("default",),
        (),
        "changed",
        "2026-07-23",
        "B",
        "v1.7.0",
        (change,),
        "C",
    )
    refresh_batch = RefreshBatch(
        "batch-2", "2026-07-23", "v1.7.0", (protocol,)
    )
    calls = []
    holder = {}

    def runner(command, cwd):
        command = tuple(command)
        calls.append(command)
        if command[:3] == ("gh", "pr", "view"):
            raise subprocess.CalledProcessError(1, command)
        if command[:3] == ("git", "ls-remote", "--exit-code"):
            return SimpleNamespace(stdout="abc refs/heads/branch\n")
        if command[:2] == ("git", "show"):
            record = holder["ops"]._public_record(protocol)
            return SimpleNamespace(
                stdout=json.dumps(
                    record,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
        if command[:3] == ("git", "diff", "--name-only"):
            return SimpleNamespace(
                stdout="docs/ops/protocol-refresh/change-records/"
                "2026-07-23-falcon.json\n"
            )
        return SimpleNamespace(stdout="")

    ops = ProductionOperations(
        refresh_batch,
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        command_runner=runner,
    )
    holder["ops"] = ops
    ops.ensure_protocol_pull_request(protocol)
    create = next(command for command in calls if command[:3] == ("gh", "pr", "create"))
    assert "--body" in create
    assert "--fill" not in create
    assert "One topic: `falcon` only." in create[create.index("--body") + 1]
    assert not any(command[:2] == ("git", "push") for command in calls)


def test_generated_publication_push_bypasses_unrelated_local_hook(
    tmp_path: Path,
) -> None:
    source = Path(__file__).parents[2]
    production_source = (
        source / "scripts" / "lean_protocol_refresh" / "production.py"
    ).read_text(encoding="utf-8")
    assert '("git", "push", "--no-verify", "-u", "origin", branch)' in production_source


def test_docs_only_or_no_change_batch_dispatches_once_without_new_run_name(
    tmp_path: Path,
) -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    refresh_batch = RefreshBatch(
        "later-batch", "2026-07-23", "v1.7.0", (protocol,)
    )
    calls = []
    dispatched = False
    clock = iter((0, 0, 1, 50, 60, 70, 80))

    def runner(command, cwd):
        nonlocal dispatched
        command = tuple(command)
        calls.append(command)
        if command[:4] == ("gh", "api", "--method", "GET"):
            endpoint = command[4]
            if "/commits/" in endpoint:
                return SimpleNamespace(stdout='{"sha":"main-sha"}')
            event = next(
                (
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("event=")
                ),
                "",
            )
            if event == "workflow_dispatch" and dispatched:
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "workflow_runs": [
                                {
                                    "id": 22,
                                    "head_sha": "main-sha",
                                    "display_title": "Deploy to VPS",
                                    "event": "workflow_dispatch",
                                    "status": "completed",
                                    "conclusion": "success",
                                }
                            ]
                        }
                    )
                )
            return SimpleNamespace(stdout='{"workflow_runs":[]}')
        if command[:3] == ("gh", "workflow", "run"):
            dispatched = True
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="")

    def no_live(*_args, **_kwargs):
        raise OSError("not deployed")

    ops = ProductionOperations(
        refresh_batch,
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        command_runner=runner,
        urlopen=no_live,
        sleeper=lambda _seconds: None,
        monotonic=lambda: next(clock),
    )
    ops.deploy_batch(refresh_batch, (protocol,))
    dispatches = [
        command for command in calls if command[:3] == ("gh", "workflow", "run")
    ]
    assert len(dispatches) == 1
    assert "reason=later-batch" in dispatches[0]
