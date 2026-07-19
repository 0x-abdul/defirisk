from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "ci" / "deploy-vps-safe.sh"
pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="POSIX integration harness runs in Linux CI"
)


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def fixture_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    for path, value in (
        ("data/api/live.txt", "old-api"),
        ("site/dist/live.txt", "old-dist"),
        (".fake_head", "old-head"),
    ):
        write(repo / path, value)
    (repo / "scripts/ci").mkdir(parents=True)
    shutil.copy2(DEPLOY, repo / "scripts/ci/deploy-vps-safe.sh")
    write(
        repo / "scripts/ci/sync-vps-checkout.sh", "#!/usr/bin/env bash\nexit 0\n", True
    )
    write(repo / "scripts/ci/use-node-22.sh", "true\n")
    write(
        repo / "scripts/dump.py",
        'from pathlib import Path; import sys; p=Path(sys.argv[sys.argv.index(\'--out-root\')+1])/\'api/v1.7.0\'; p.mkdir(parents=True); (p/\'index.json\').write_text(\'{"rubric_version":"v1.7.0","data_as_of":"x","generated_at":"x","data":{"protocols":[]}}\'); print(\'protocols     : 0 published in protocols/, 98 in unpublished/ (98 total)\')\n',
    )
    write(repo / "scripts/ci/validate-staged-published-api.py", "")
    write(repo / "scripts/ci/verify-deployment-publication-state.py", "")
    write(repo / "scripts/ci/smoke-staged-deploy.py", "")
    write(repo / ".env", "DATABASE_URL=fake\n")
    fake = tmp_path / "bin"
    fake.mkdir()
    write(
        fake / "git",
        '#!/usr/bin/env bash\nif [ "$1" = rev-parse ]; then cat .fake_head; elif [ "$1" = reset ]; then echo "$3" > .fake_head; fi\n',
        True,
    )
    write(
        fake / "curl",
        '#!/usr/bin/env bash\ntest "${SAFE_DEPLOY_CURL_FAIL:-}" != 1\n',
        True,
    )
    write(
        fake / "npm",
        '#!/usr/bin/env bash\nmkdir -p "$DEFIRISK_DIST_ROOT/api/v1.7.0"; echo ok > "$DEFIRISK_DIST_ROOT/index.html"; cp "$DEFIRISK_API_ROOT/index.json" "$DEFIRISK_DIST_ROOT/api/v1.7.0/index.json"\n',
        True,
    )
    state = tmp_path / "state"
    env = os.environ | {
        "PATH": str(fake) + ":" + os.environ["PATH"],
        "XDG_STATE_HOME": str(state),
        "DATABASE_URL": "fake",
    }
    return repo, env


@pytest.mark.parametrize(
    "point",
    [
        "after_api_rename",
        "after_api_promote",
        "after_dist_rename",
        "after_dist_promote",
        "after_smoke",
    ],
)
def test_injected_promotion_failures_restore_fixture_and_seal_rollback(
    tmp_path: Path, point: str
) -> None:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    repo, env = fixture_repo(tmp_path)
    env["SAFE_DEPLOY_FAIL_AT"] = point
    result = subprocess.run(
        [bash, "scripts/ci/deploy-vps-safe.sh", str(repo), "origin", "main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert (repo / ".fake_head").read_text().strip() == "old-head"
    assert (repo / "data/api/live.txt").read_text() == "old-api"
    assert (repo / "site/dist/live.txt").read_text() == "old-dist"
    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1, result.stdout + result.stderr
    assert json.loads(manifests[0].read_text())["state"] == "rolled_back"
    assert stat.S_IMODE(manifests[0].stat().st_mode) == 0o600
    assert "token" not in (result.stdout + result.stderr).lower()


def test_prebackup_failure_never_mutates_live_fixture(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    repo, env = fixture_repo(tmp_path)
    (repo / "site/dist").chmod(0o000)
    result = subprocess.run(
        [bash, "scripts/ci/deploy-vps-safe.sh", str(repo), "origin", "main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    (repo / "site/dist").chmod(0o700)
    assert result.returncode != 0
    assert (repo / "data/api/live.txt").read_text() == "old-api"


def test_promoted_public_trees_are_readable_while_deploy_state_stays_private(
    tmp_path: Path,
) -> None:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    repo, env = fixture_repo(tmp_path)
    result = subprocess.run(
        [bash, "scripts/ci/deploy-vps-safe.sh", str(repo), "origin", "main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for public_root in (repo / "data/api", repo / "site/dist"):
        for directory in (path for path in public_root.rglob("*") if path.is_dir()):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o755
        for artifact in (path for path in public_root.rglob("*") if path.is_file()):
            assert stat.S_IMODE(artifact.stat().st_mode) == 0o644

    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1
    run = manifests[0].parent
    assert stat.S_IMODE(run.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifests[0].stat().st_mode) == 0o600
