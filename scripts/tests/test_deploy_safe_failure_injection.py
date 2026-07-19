from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "ci" / "deploy-vps-safe.sh"


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def fixture_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"; repo.mkdir()
    for path, value in (("data/api/live.txt", "old-api"), ("site/dist/live.txt", "old-dist"), (".fake_head", "old-head")):
        write(repo / path, value)
    (repo / "scripts/ci").mkdir(parents=True)
    shutil.copy2(DEPLOY, repo / "scripts/ci/deploy-vps-safe.sh")
    write(repo / "scripts/ci/sync-vps-checkout.sh", "#!/usr/bin/env bash\nexit 0\n", True)
    write(repo / "scripts/ci/use-node-22.sh", "true\n")
    write(repo / "scripts/dump.py", "from pathlib import Path; import sys; p=Path(sys.argv[sys.argv.index('--out-root')+1])/'api/v1.7.0'; p.mkdir(parents=True); (p/'index.json').write_text('{\"rubric_version\":\"v1.7.0\",\"data_as_of\":\"x\",\"generated_at\":\"x\",\"data\":{\"protocols\":[]}}'); print('protocols     : 0 published in protocols/, 98 in unpublished/ (98 total)')\n")
    write(repo / "scripts/ci/validate-staged-published-api.py", "")
    write(repo / "scripts/ci/verify-deployment-publication-state.py", "")
    write(repo / ".env", "DATABASE_URL=fake\n")
    fake = tmp_path / "bin"; fake.mkdir()
    write(fake / "git", "#!/usr/bin/env bash\nif [ \"$1\" = rev-parse ]; then cat .fake_head; elif [ \"$1\" = reset ]; then echo \"$3\" > .fake_head; fi\n", True)
    write(fake / "curl", "#!/usr/bin/env bash\ntest \"${SAFE_DEPLOY_CURL_FAIL:-}\" != 1\n", True)
    write(fake / "npm", "#!/usr/bin/env bash\nmkdir -p \"$DEFIRISK_DIST_ROOT/api/v1.7.0\"; echo ok > \"$DEFIRISK_DIST_ROOT/index.html\"; cp \"$DEFIRISK_API_ROOT/index.json\" \"$DEFIRISK_DIST_ROOT/api/v1.7.0/index.json\"\n", True)
    state = tmp_path / "state"
    state_posix = "/" + state.drive[0].lower() + state.as_posix()[2:]
    fake_posix = "/" + fake.drive[0].lower() + fake.as_posix()[2:]
    env=os.environ | {"PATH":fake_posix+":/usr/bin:/bin","XDG_STATE_HOME":state_posix,"DATABASE_URL":"fake"}
    return repo,env


def bash_path(path: Path) -> str:
    cygpath = shutil.which("cygpath")
    if cygpath:
        return subprocess.check_output([cygpath, "-u", str(path)], text=True).strip()
    return str(path)


def git_bash() -> str | None:
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
    return str(candidate) if candidate.exists() else shutil.which("bash")


@pytest.mark.parametrize("point", ["after_api_rename","after_api_promote","after_dist_rename","after_dist_promote","after_smoke"])
def test_injected_promotion_failures_restore_fixture_and_seal_rollback(tmp_path: Path, point: str) -> None:
    bash=git_bash()
    if not bash: pytest.skip("bash unavailable")
    repo,env=fixture_repo(tmp_path); env["SAFE_DEPLOY_FAIL_AT"]=point
    result=subprocess.run([bash,"scripts/ci/deploy-vps-safe.sh",bash_path(repo),"origin","main"],cwd=repo,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert (repo/".fake_head").read_text() == "old-head"
    assert (repo/"data/api/live.txt").read_text() == "old-api"
    assert (repo/"site/dist/live.txt").read_text() == "old-dist"
    manifests=list(tmp_path.rglob("manifest.json")); assert len(manifests)==1, result.stdout + result.stderr
    assert json.loads(manifests[0].read_text())["state"] == "rolled_back"
    assert stat.S_IMODE(manifests[0].stat().st_mode) == 0o600
    assert "token" not in (result.stdout+result.stderr).lower()


def test_prebackup_failure_never_mutates_live_fixture(tmp_path: Path) -> None:
    bash=git_bash()
    if not bash: pytest.skip("bash unavailable")
    repo,env=fixture_repo(tmp_path); (repo/"site/dist").chmod(0o000)
    result=subprocess.run([bash,"scripts/ci/deploy-vps-safe.sh",bash_path(repo),"origin","main"],cwd=repo,env=env,capture_output=True,text=True)
    (repo/"site/dist").chmod(0o700)
    assert result.returncode != 0
    assert (repo/"data/api/live.txt").read_text() == "old-api"
