from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "ci" / "deploy-vps-safe.sh").read_text(encoding="utf-8")


def test_manifest_is_atomic_private_state_machine_with_digest_receipts() -> None:
    assert "os.replace(tmp,path)" in SCRIPT
    assert "os.fchmod(fd,0o600)" in SCRIPT
    for state in ("staging", "promoting", "succeeded", "rolled_back", "rollback_failed"):
        assert f"write_manifest {state}" in SCRIPT
    for field in ("api_before_sha256", "site_dist_before_sha256", "api_after_sha256", "site_dist_after_sha256"):
        assert field in SCRIPT


def test_success_cleanup_cannot_trigger_rollback_or_prune_failure_receipts() -> None:
    succeeded = SCRIPT.index("write_manifest succeeded")
    disable_rollback = SCRIPT.index("trap - ERR HUP INT TERM", succeeded)
    cleanup = SCRIPT.index('rm -rf "$backup/original-api"', succeeded)
    assert disable_rollback < cleanup
    assert "prune_verified_successes()" in SCRIPT
    assert 'json.load(manifest).get("state") != "succeeded"' in SCRIPT
    assert "shutil.rmtree(candidate)" in SCRIPT


def test_failures_before_or_during_promotion_rollback_to_verified_backup() -> None:
    assert "backups_ready=0" in SCRIPT
    assert 'if [ "$backups_ready" != 1 ]; then write_manifest rollback_failed || true; exit "$code"; fi' in SCRIPT
    assert "backups_ready=1" in SCRIPT
    assert "trap 'rollback $?' ERR" in SCRIPT
    assert "trap 'rollback 128' HUP INT TERM" in SCRIPT
    assert "test \"$(git rev-parse HEAD)\" = \"$old_head\"" in SCRIPT
    assert "curl -fsS https://defirisk.co/ >/dev/null" in SCRIPT
    for point in ("after_api_rename", "after_api_promote", "after_dist_rename", "after_dist_promote", "after_smoke"):
        assert f'SAFE_DEPLOY_FAIL_AT:-}}" != {point}' in SCRIPT


def test_staged_smoke_and_live_isolation_precede_any_live_rename() -> None:
    smoke = 'scripts/ci/smoke-staged-deploy.py --dist-root "$stage/site-dist" --api-root "$stage/data/api/v1.7.0"'
    assert smoke in SCRIPT
    assert 'test "$(tree_digest data/api)" = "$api_before"' in SCRIPT
    assert 'test "$(tree_digest site/dist)" = "$dist_before"' in SCRIPT
    assert SCRIPT.index(smoke) < SCRIPT.index('mv data/api "$backup/pre-promotion-api"')
