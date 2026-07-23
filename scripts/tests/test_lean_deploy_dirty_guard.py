from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "ci" / "deploy-vps-safe.sh").read_text(encoding="utf-8")


def test_deploy_refuses_live_dirty_state_before_backup_or_live_checkout() -> None:
    preflight = SCRIPT.index("preflight_live_checkout\nold_head")
    first_backup = SCRIPT.index('cp -a data/api "$backup/original-api"')
    live_checkout = SCRIPT.index('git -C "$repo" checkout "$target_head"')
    assert preflight < first_backup < live_checkout
    assert "git -C \"$repo\" diff --quiet -- . \"${runtime_excludes[@]}\"" in SCRIPT
    assert "git -C \"$repo\" diff --cached --quiet -- . \"${runtime_excludes[@]}\"" in SCRIPT
    assert "git -C \"$repo\" ls-files -u" in SCRIPT
    assert "CHERRY_PICK_HEAD" in SCRIPT and "REVERT_HEAD" in SCRIPT


def test_deploy_allows_only_generated_artifacts_and_deployment_state_to_be_untracked() -> None:
    assert "data/api|data/api/*|site/dist|site/dist/*" in SCRIPT
    assert ".deploy-backups|.deploy-backups/*|backups|backups/*" in SCRIPT
    assert ".local/state|.local/state/*" in SCRIPT
    assert ".node|.node/*|.npm-cache|.npm-cache/*" in SCRIPT
    assert "scripts/control_service.py|scripts/nightly.sh" in SCRIPT
    assert "site/src/lib/freshness.ts|issue12_new" in SCRIPT
    assert 'git -C "$repo" ls-files --others --exclude-standard -z' in SCRIPT
    assert "is_runtime_only_untracked_path \"$path\" || fail_dirty_deploy_tree" in SCRIPT
