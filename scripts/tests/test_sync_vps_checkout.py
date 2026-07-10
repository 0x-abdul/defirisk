from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def find_bash() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe",
    ]
    which_bash = shutil.which("bash")
    if which_bash:
        candidates.append(Path(which_bash))
    for candidate in candidates:
        if not candidate.exists():
            continue
        probe = subprocess.run(
            [str(candidate), "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and "GNU bash" in probe.stdout:
            return str(candidate)
    return None


BASH = find_bash()
SCRIPT = Path(__file__).resolve().parents[1] / "ci" / "sync-vps-checkout.sh"
ROOT = Path(__file__).resolve().parents[2]


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def commit_file(repo: Path, content: str, message: str) -> None:
    (repo / "tracked.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-m", message)


def repositories(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    vps = tmp_path / "vps"
    git(tmp_path, "init", "--bare", str(remote))
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    seed.mkdir()
    git(seed, "init", "-b", "main")
    git(seed, "config", "user.email", "test@example.com")
    git(seed, "config", "user.name", "Test Operator")
    commit_file(seed, "base\n", "base")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    git(tmp_path, "clone", str(remote), str(vps))
    git(vps, "config", "user.email", "test@example.com")
    git(vps, "config", "user.name", "Test Operator")
    return seed, vps


def run_helper(vps: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    if BASH is None:
        pytest.skip("bash is not installed")
    return subprocess.run(
        [BASH, SCRIPT.as_posix(), vps.as_posix(), *extra],
        check=False,
        capture_output=True,
        text=True,
    )


def test_sync_discards_local_commits_and_preserves_untracked_runtime_files(
    tmp_path: Path,
) -> None:
    seed, vps = repositories(tmp_path)
    runtime = vps / ".env"
    runtime.write_text("PRIVATE_SETTING=test\n", encoding="utf-8")
    commit_file(vps, "local generated data\n", "local runtime snapshot")
    commit_file(seed, "remote code\n", "remote update")
    git(seed, "push", "origin", "main")

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert git(vps, "rev-parse", "HEAD").stdout == git(seed, "rev-parse", "HEAD").stdout
    assert git(vps, "rev-list", "--left-right", "--count", "HEAD...origin/main").stdout.strip() == "0\t0"
    assert runtime.read_text(encoding="utf-8") == "PRIVATE_SETTING=test\n"
    assert git(vps, "status", "--short", "--untracked-files=no").stdout == ""


def test_sync_clears_conflicted_merge_state(tmp_path: Path) -> None:
    seed, vps = repositories(tmp_path)
    commit_file(vps, "local conflict\n", "local conflict")
    commit_file(seed, "remote conflict\n", "remote conflict")
    git(seed, "push", "origin", "main")
    git(vps, "fetch", "origin", "main")
    merge = git(vps, "merge", "origin/main", check=False)
    assert merge.returncode != 0

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert not (vps / ".git" / "MERGE_HEAD").exists()
    assert git(vps, "ls-files", "-u").stdout == ""


def test_sync_clears_conflicted_rebase_state(tmp_path: Path) -> None:
    seed, vps = repositories(tmp_path)
    commit_file(vps, "local conflict\n", "local conflict")
    commit_file(seed, "remote conflict\n", "remote conflict")
    git(seed, "push", "origin", "main")
    git(vps, "fetch", "origin", "main")
    rebase = git(vps, "rebase", "origin/main", check=False)
    assert rebase.returncode != 0
    assert (vps / ".git" / "rebase-merge").exists() or (
        vps / ".git" / "rebase-apply"
    ).exists()

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert git(vps, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert not (vps / ".git" / "rebase-merge").exists()
    assert not (vps / ".git" / "rebase-apply").exists()
    assert git(vps, "ls-files", "-u").stdout == ""


def test_sync_clears_conflicted_cherry_pick_state(tmp_path: Path) -> None:
    _seed, vps = repositories(tmp_path)
    git(vps, "switch", "-c", "picked-change")
    commit_file(vps, "picked conflict\n", "picked change")
    picked = git(vps, "rev-parse", "HEAD").stdout.strip()
    git(vps, "switch", "main")
    commit_file(vps, "main conflict\n", "main conflict")
    cherry_pick = git(vps, "cherry-pick", picked, check=False)
    assert cherry_pick.returncode != 0
    assert (vps / ".git" / "CHERRY_PICK_HEAD").exists()

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert not (vps / ".git" / "CHERRY_PICK_HEAD").exists()
    assert git(vps, "ls-files", "-u").stdout == ""


def test_sync_clears_conflicted_revert_state(tmp_path: Path) -> None:
    _seed, vps = repositories(tmp_path)
    commit_file(vps, "first local change\n", "first local change")
    first = git(vps, "rev-parse", "HEAD").stdout.strip()
    commit_file(vps, "second local change\n", "second local change")
    revert = git(vps, "revert", first, check=False)
    assert revert.returncode != 0
    assert (vps / ".git" / "REVERT_HEAD").exists()

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert not (vps / ".git" / "REVERT_HEAD").exists()
    assert git(vps, "ls-files", "-u").stdout == ""


def test_sync_accepts_force_rewritten_remote_history(tmp_path: Path) -> None:
    seed, vps = repositories(tmp_path)
    original_head = git(vps, "rev-parse", "HEAD").stdout
    git(seed, "switch", "--orphan", "rewritten")
    commit_file(seed, "rewritten root\n", "rewritten root")
    git(seed, "branch", "-M", "main")
    git(seed, "push", "--force", "origin", "main")

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert git(vps, "rev-parse", "HEAD").stdout != original_head
    assert git(vps, "rev-parse", "HEAD").stdout == git(seed, "rev-parse", "HEAD").stdout


def test_fetch_failure_leaves_head_and_tracked_state_unchanged(tmp_path: Path) -> None:
    _seed, vps = repositories(tmp_path)
    before_head = git(vps, "rev-parse", "HEAD").stdout
    (vps / "tracked.txt").write_text("unsaved operator change\n", encoding="utf-8")
    git(vps, "remote", "set-url", "origin", str(tmp_path / "unreachable.git"))

    result = run_helper(vps)

    assert result.returncode != 0
    assert git(vps, "rev-parse", "HEAD").stdout == before_head
    assert (vps / "tracked.txt").read_text(encoding="utf-8") == "unsaved operator change\n"


def test_sync_discards_dirty_tracked_files(tmp_path: Path) -> None:
    _seed, vps = repositories(tmp_path)
    expected = (vps / "tracked.txt").read_text(encoding="utf-8")
    (vps / "tracked.txt").write_text("dirty tracked state\n", encoding="utf-8")

    result = run_helper(vps)

    assert result.returncode == 0, result.stderr
    assert (vps / "tracked.txt").read_text(encoding="utf-8") == expected
    assert git(vps, "status", "--short", "--untracked-files=no").stdout == ""


def test_index_lock_fails_without_changing_tracked_state(tmp_path: Path) -> None:
    _seed, vps = repositories(tmp_path)
    before_head = git(vps, "rev-parse", "HEAD").stdout
    tracked = vps / "tracked.txt"
    tracked.write_text("unsaved operator change\n", encoding="utf-8")
    index_lock = vps / ".git" / "index.lock"
    index_lock.write_text("", encoding="utf-8")

    try:
        result = run_helper(vps)
    finally:
        index_lock.unlink(missing_ok=True)

    assert result.returncode != 0
    assert "index lock" in result.stderr
    assert git(vps, "rev-parse", "HEAD").stdout == before_head
    assert tracked.read_text(encoding="utf-8") == "unsaved operator change\n"


def test_wrong_branch_fails_before_reset(tmp_path: Path) -> None:
    _seed, vps = repositories(tmp_path)
    git(vps, "switch", "-c", "operator-work")
    commit_file(vps, "operator work\n", "operator work")
    before_head = git(vps, "rev-parse", "HEAD").stdout

    result = run_helper(vps)

    assert result.returncode != 0
    assert git(vps, "rev-parse", "HEAD").stdout == before_head


def test_vps_workflows_use_shared_stateless_sync() -> None:
    for workflow_name in ("deploy.yml", "ingest.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        assert "sync-vps-checkout.sh" in workflow
        assert "git pull" not in workflow
        assert "git commit" not in workflow
        assert "git add data/api" not in workflow
        assert "git config user." not in workflow

    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "- 'scripts/ci/sync-vps-checkout.sh'" in deploy
