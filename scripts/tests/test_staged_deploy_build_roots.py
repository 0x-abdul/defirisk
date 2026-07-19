from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_deploy_build_exports_staged_api_and_dist_roots() -> None:
    deploy = (ROOT / "scripts" / "ci" / "deploy-vps-safe.sh").read_text(encoding="utf-8")
    assert 'DEFIRISK_API_ROOT="$stage/data/api/v1.7.0"' in deploy
    assert 'DEFIRISK_DIST_ROOT="$stage/site-dist"' in deploy


def test_post_build_copy_honors_staged_api_and_dist_roots(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    api_root = tmp_path / "generated" / "api" / "v1.7.0"
    dist_root = tmp_path / "staging" / "site-dist"
    api_root.mkdir(parents=True)
    dist_root.mkdir(parents=True)
    (api_root / "index.json").write_text('{"data":{"protocols":[]}}', encoding="utf-8")
    env = os.environ | {
        "DEFIRISK_API_ROOT": str(api_root),
        "DEFIRISK_DIST_ROOT": str(dist_root),
    }

    result = subprocess.run(
        [node, ROOT / "site" / "scripts" / "post-build-copy.mjs"],
        cwd=ROOT / "site",
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (dist_root / "api" / "v1.7.0" / "index.json").exists()
    assert not (ROOT / "site" / "dist" / "api" / "v1.7.0" / "index.json").exists()


def test_og_builder_honors_staged_roots() -> None:
    og_builder = (ROOT / "site" / "scripts" / "build-og-images.mjs").read_text(encoding="utf-8")
    assert "const DIST_ROOT = process.env.DEFIRISK_DIST_ROOT" in og_builder
    assert "const DATA_ROOT = process.env.DEFIRISK_API_ROOT" in og_builder
