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
    assert "api_renamed=0" in SCRIPT
    assert "dist_renamed=0" in SCRIPT
    assert "trap 'rollback $?' ERR" in SCRIPT
    assert "trap 'rollback 128' HUP INT TERM" in SCRIPT
    assert "test \"$(git rev-parse HEAD 2>/dev/null)\" = \"$old_head\"" in SCRIPT
    assert "curl -fsS https://defirisk.co/ >/dev/null" in SCRIPT
    for point in ("after_api_rename", "after_api_promote", "after_dist_rename", "after_dist_promote", "after_code_checkout", "after_smoke"):
        assert f'SAFE_DEPLOY_FAIL_AT:-}}" != {point}' in SCRIPT


def test_staged_smoke_and_live_isolation_precede_any_live_rename() -> None:
    smoke = '"$stage_worktree/scripts/ci/smoke-staged-deploy.py" --dist-root "$stage/site-dist" --api-root "$stage/data/api/v1.7.0"'
    assert smoke in SCRIPT
    assert "verify_live_tree_unchanged" in SCRIPT
    assert SCRIPT.index(smoke) < SCRIPT.index('mv data/api "$backup/pre-promotion-api"')


def test_only_promoted_public_artifact_trees_are_normalized_for_caddy() -> None:
    normalize = "normalize_public_artifact_permissions"
    assert normalize in SCRIPT
    assert 'for public_root in "$stage/site-dist" "$stage/data/api"' in SCRIPT
    assert 'find "$public_root" -type d -exec chmod 0755 {} +' in SCRIPT
    assert 'find "$public_root" -type f -exec chmod 0644 {} +' in SCRIPT
    assert SCRIPT.index(normalize + "\n") < SCRIPT.index('require_staged_file "$stage/site-dist/index.html"')


def test_pre_promotion_checks_emit_safe_aggregate_invariant_categories() -> None:
    for category in ("staged_site_index", "staged_api_index", "staged_smoke", "live_tree_digest"):
        assert category in SCRIPT
    assert "SAFE_DEPLOY_INVARIANT_FAILED" in SCRIPT


def test_target_code_uses_an_isolated_worktree_without_resetting_live_artifacts() -> None:
    assert 'git -C "$repo" fetch --no-tags "$remote"' in SCRIPT
    assert 'git -C "$repo" worktree add --detach "$stage_worktree" "$target_head"' in SCRIPT
    assert 'cp -a data/api "$stage_worktree/data/api"' in SCRIPT
    assert 'git -C "$stage_worktree" diff --quiet' in SCRIPT
    assert 'git reset --hard' not in SCRIPT
    assert "sync-vps-checkout.sh" not in SCRIPT
    assert 'test "${SAFE_DEPLOY_FAIL_AT:-}" != before_promotion' in SCRIPT
    assert 'git -C "$repo" worktree remove --force "$stage_worktree"' in SCRIPT
    code_update = 'git -C "$repo" checkout "$target_head" -- . "${runtime_excludes[@]}"'
    assert code_update in SCRIPT
    assert SCRIPT.index(code_update) > SCRIPT.index('mv "$stage/site-dist" site/dist')
    assert 'git -C "$repo" update-ref "refs/heads/$branch" "$target_head" "$old_head"' in SCRIPT
    assert SCRIPT.rindex("live_code_replaced=1") < SCRIPT.index(code_update)
    assert "remove_added_code_paths()" in SCRIPT
    assert 'git -C "$repo" rm --cached --ignore-unmatch -- "$path"' in SCRIPT
    assert 'remove_added_code_paths "$old_head" "$target_head"' in SCRIPT
    assert 'remove_added_code_paths "$target_head" "$old_head"' in SCRIPT
    assert "status --porcelain --untracked-files=all" in SCRIPT
    assert 'find "$stage_worktree/data/api" -type l -print -quit' in SCRIPT


def test_deploy_logs_are_limited_to_safe_fixed_messages() -> None:
    assert '| tee "$dump_log"' not in SCRIPT
    assert '"$stage_worktree/scripts/dump.py" --out-root "$stage/data" >"$dump_log" 2>&1' in SCRIPT
    assert "SAFE_DEPLOY_MANIFEST=sealed" in SCRIPT
    assert "SAFE_DEPLOY_MANIFEST=$manifest" not in SCRIPT
    assert 'DEPLOY_NODE_CACHE="$stage/node-cache"' in SCRIPT
    assert '. "$stage_worktree/scripts/ci/use-node-22.sh"' in SCRIPT
    for message in (
        "deployment target fetch unavailable",
        "deployment staging checkout unavailable",
        "staged API generation failed",
        "staged publication validation failed",
        "staged site build failed",
        "deployment code update failed",
        "deployment artifact digest unavailable",
        "artifact promotion failed",
    ):
        assert message in SCRIPT
