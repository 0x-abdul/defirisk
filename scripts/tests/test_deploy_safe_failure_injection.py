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


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def fixture_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    seed = tmp_path / "seed"
    seed.mkdir()
    for path, value in (
        ("data/api/live.txt", "old-api"),
        ("site/dist/live.txt", "old-dist"),
    ):
        write(seed / path, value)
    (seed / "scripts/ci").mkdir(parents=True)
    shutil.copy2(DEPLOY, seed / "scripts/ci/deploy-vps-safe.sh")
    write(seed / "scripts/ci/use-node-22.sh", "true\n")
    write(
        seed / "scripts/dump.py",
        "from pathlib import Path; import sys; p=Path(sys.argv[sys.argv.index('--out-root')+1])/'api/v1.7.0'; p.mkdir(parents=True); (p/'index.json').write_text('{\"rubric_version\":\"v1.7.0\",\"data_as_of\":\"x\",\"generated_at\":\"x\",\"data\":{\"protocols\":[]}}'); print('protocols     : 0 published in protocols/, 98 in unpublished/ (98 total)')\n",
    )
    write(seed / "scripts/ci/validate-staged-published-api.py", "")
    write(seed / "scripts/ci/verify-deployment-publication-state.py", "")
    write(seed / "scripts/ci/smoke-staged-deploy.py", "")
    write(seed / "scripts/ci/deploy-publication-policy.json", "{}\n")
    git(seed, "init")
    git(seed, "checkout", "-b", "main")
    git(seed, "config", "user.email", "test@example.invalid")
    git(seed, "config", "user.name", "Test")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "initial fixture")

    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")

    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--branch", "main", remote, repo],
        check=True,
        capture_output=True,
    )
    write(repo / ".env", "DATABASE_URL=fake\n")

    fake = tmp_path / "bin"
    fake.mkdir()
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
        "PATH": str(fake) + os.pathsep + os.environ["PATH"],
        "XDG_STATE_HOME": str(state),
        "DATABASE_URL": "fake",
    }
    return repo, seed, env


def run_deploy(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    return subprocess.run(
        [bash, "scripts/ci/deploy-vps-safe.sh", str(repo), "origin", "main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def advance_target(seed: Path) -> str:
    write(seed / "scripts/target-marker.txt", "target\n")
    git(seed, "add", "scripts/target-marker.txt")
    git(seed, "commit", "-m", "target code sentinel")
    git(seed, "push", "origin", "main")
    return git(seed, "rev-parse", "HEAD").strip()


@pytest.mark.parametrize(
    "point",
    [
        "after_api_rename",
        "after_api_promote",
        "after_dist_rename",
        "after_dist_promote",
        "after_code_checkout",
        "after_smoke",
    ],
)
def test_injected_promotion_failures_restore_fixture_and_seal_rollback(
    tmp_path: Path, point: str
) -> None:
    repo, seed, env = fixture_repo(tmp_path)
    old_head = git(repo, "rev-parse", "HEAD").strip()
    assert advance_target(seed) != old_head
    env["SAFE_DEPLOY_FAIL_AT"] = point
    result = run_deploy(repo, env)

    assert result.returncode != 0
    assert git(repo, "rev-parse", "HEAD").strip() == old_head
    assert not (repo / "scripts/target-marker.txt").exists()
    assert (repo / "data/api/live.txt").read_text() == "old-api"
    assert (repo / "site/dist/live.txt").read_text() == "old-dist"
    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1, result.stdout + result.stderr
    assert json.loads(manifests[0].read_text())["state"] == "rolled_back"
    assert stat.S_IMODE(manifests[0].stat().st_mode) == 0o600
    assert "token" not in (result.stdout + result.stderr).lower()


def test_prebackup_failure_never_mutates_live_fixture(tmp_path: Path) -> None:
    repo, _, env = fixture_repo(tmp_path)
    (repo / "site/dist").chmod(0o000)
    result = run_deploy(repo, env)
    (repo / "site/dist").chmod(0o700)
    assert result.returncode != 0
    assert (repo / "data/api/live.txt").read_text() == "old-api"


def test_promoted_public_trees_are_readable_while_deploy_state_stays_private(
    tmp_path: Path,
) -> None:
    repo, seed, env = fixture_repo(tmp_path)
    target_head = advance_target(seed)
    result = run_deploy(repo, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo, "rev-parse", "HEAD").strip() == target_head
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


def test_pre_promotion_failure_keeps_tracked_live_artifacts_unchanged(
    tmp_path: Path,
) -> None:
    repo, seed, env = fixture_repo(tmp_path)
    old_head = git(repo, "rev-parse", "HEAD").strip()
    advance_target(seed)
    write(seed / "data/api/live.txt", "target-api")
    write(seed / "site/dist/live.txt", "target-dist")
    git(seed, "add", "data/api/live.txt", "site/dist/live.txt")
    git(seed, "commit", "-m", "target artifact sentinel")
    git(seed, "push", "origin", "main")
    env["SAFE_DEPLOY_FAIL_AT"] = "before_promotion"

    result = run_deploy(repo, env)

    assert result.returncode != 0
    assert git(repo, "rev-parse", "HEAD").strip() == old_head
    assert (repo / "data/api/live.txt").read_text() == "old-api"
    assert (repo / "site/dist/live.txt").read_text() == "old-dist"
    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["state"] == "rolled_back"
    assert not (manifests[0].parent / "staging").exists()
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
