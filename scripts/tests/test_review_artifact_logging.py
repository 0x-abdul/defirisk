from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "site" / "scripts" / "check-review-artifacts.mjs"
SAFE_BUILD_SCRIPT = REPO_ROOT / "site" / "scripts" / "run-private-safe-build.mjs"
SITE_PACKAGE = REPO_ROOT / "site" / "package.json"


def run_review_check(api_root: Path, dist_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "DEFIRISK_API_ROOT": str(api_root),
            "DEFIRISK_DIST_ROOT": str(dist_root),
        }
    )
    return subprocess.run(
        ["node", str(CHECK_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("case", "expected_code", "expected_message"),
    [
        ("empty", 0, "no unpublished review data"),
        ("missing_json", 1, "missing JSON index files: 1"),
        ("missing_html", 1, "missing HTML review pages: 1"),
        ("invalid_html", 1, "missing private-review markers: 1"),
        ("missing_pending", 1, "missing private-review markers: 1"),
        ("missing_noindex", 1, "missing private-review markers: 1"),
        ("valid", 0, "verified 1 unpublished review page(s)"),
    ],
)
def test_review_artifact_logs_only_aggregate_results(
    tmp_path,
    case: str,
    expected_code: int,
    expected_message: str,
) -> None:
    fake_token = "deadbeef"
    api_root = tmp_path / f"api-root-{fake_token}"
    dist_root = tmp_path / f"dist-root-{fake_token}"
    review = f"fixture-family-{fake_token}"

    if case != "empty":
        review_dir = api_root / "unpublished" / review
        review_dir.mkdir(parents=True)
        if case != "missing_json":
            (review_dir / "index.json").write_text("{}", encoding="utf-8")
        if case in {"invalid_html", "missing_pending", "missing_noindex", "valid"}:
            html_dir = dist_root / "unpublished" / review
            html_dir.mkdir(parents=True)
            html_by_case = {
                "invalid_html": "invalid",
                "missing_pending": "review-banner noindex,nofollow",
                "missing_noindex": "review-banner Pending review",
                "valid": "review-banner Pending review noindex,nofollow",
            }
            html = html_by_case[case]
            (html_dir / "index.html").write_text(html, encoding="utf-8")

    result = run_review_check(api_root, dist_root)
    output = result.stdout + result.stderr

    assert result.returncode == expected_code
    assert expected_message in output
    assert fake_token not in output
    assert str(api_root) not in output
    assert str(dist_root) not in output


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_review_artifact_exception_does_not_log_tokenized_path(tmp_path) -> None:
    fake_token = "deadbeef"
    api_root = tmp_path / f"api-root-{fake_token}"
    dist_root = tmp_path / f"dist-root-{fake_token}"
    review = f"fixture-family-{fake_token}"
    review_dir = api_root / "unpublished" / review
    review_dir.mkdir(parents=True)
    (review_dir / "index.json").write_text("{}", encoding="utf-8")
    (dist_root / "unpublished" / review / "index.html").mkdir(parents=True)

    result = run_review_check(api_root, dist_root)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "check failed before completion" in output
    assert fake_token not in output
    assert str(api_root) not in output
    assert str(dist_root) not in output


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(("exit_code", "expected_result"), [(0, "true"), (1, "false")])
def test_private_build_child_output_is_always_withheld(
    exit_code: int,
    expected_result: str,
) -> None:
    fake_token = "deadbeef"
    script_uri = SAFE_BUILD_SCRIPT.as_uri()
    child = (
        "process.stdout.write('review_token=dead\\u001b[31m');"
        "process.stderr.write('beef /unpublished/fixture-deadbeef/index.html');"
        f"process.exit({exit_code});"
    )
    expression = (
        f"import {{ runStep }} from {json.dumps(script_uri)};"
        f"const ok = await runStep('fixture', process.execPath, "
        f"['--eval', {json.dumps(child)}]);"
        "console.log(`result=${ok}`);"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout + result.stderr

    assert f"result={expected_result}" in output
    assert fake_token not in output
    assert "review_token=" not in output
    assert "/unpublished/" not in output


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_private_build_spawn_error_is_path_safe() -> None:
    fake_token = "deadbeef"
    script_uri = SAFE_BUILD_SCRIPT.as_uri()
    expression = (
        f"import {{ runStep }} from {json.dumps(script_uri)};"
        f"const ok = await runStep('fixture', 'missing-command-{fake_token}', []);"
        "console.log(`result=${ok}`);"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout + result.stderr

    assert "result=false" in output
    assert "child output withheld" in output
    assert fake_token not in output


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(("first_exit", "expected_code"), [(0, 0), (1, 1)])
def test_private_build_main_propagates_status_and_stops(
    tmp_path,
    first_exit: int,
    expected_code: int,
) -> None:
    fake_token = "deadbeef"
    first = tmp_path / "first.mjs"
    sentinel = tmp_path / "sentinel.mjs"
    marker = tmp_path / "sentinel-ran"
    first.write_text(
        f"console.log('review_token={fake_token}'); process.exit({first_exit});",
        encoding="utf-8",
    )
    sentinel.write_text(
        "import { writeFileSync } from 'node:fs';"
        f"writeFileSync({json.dumps(str(marker))}, 'ran');",
        encoding="utf-8",
    )
    script_uri = SAFE_BUILD_SCRIPT.as_uri()
    steps = [["first", str(first), []], ["sentinel", str(sentinel), []]]
    expression = (
        f"import {{ main }} from {json.dumps(script_uri)};"
        f"const ok = await main({json.dumps(steps)});"
        "console.log(`result=${ok}`);"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == expected_code
    assert f"result={'true' if first_exit == 0 else 'false'}" in output
    assert fake_token not in output
    assert marker.exists() is (first_exit == 0)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_private_build_cli_exception_is_generic_and_fails() -> None:
    fake_token = "deadbeef"
    script_uri = SAFE_BUILD_SCRIPT.as_uri()
    expression = (
        f"import {{ runCli }} from {json.dumps(script_uri)};"
        f"const ok = await runCli(async () => {{ throw new Error("
        f"'/unpublished/fixture-{fake_token}/index.html'); }});"
        "console.log(`result=${ok}`);"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "result=false" in output
    assert "failed before completion" in output
    assert fake_token not in output
    assert "/unpublished/" not in output


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_private_build_default_step_contract() -> None:
    script_uri = SAFE_BUILD_SCRIPT.as_uri()
    expression = (
        f"import {{ defaultBuildSteps }} from {json.dumps(script_uri)};"
        "import path from 'node:path';"
        "const contract = defaultBuildSteps().map(([label, script, args]) => "
        "[label, path.basename(script), args]);"
        "process.stdout.write(JSON.stringify(contract));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", expression],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == [
        ["Astro build", "astro.mjs", ["build"]],
        ["API copy", "post-build-copy.mjs", []],
        ["review artifact check", "check-review-artifacts.mjs", []],
        ["Open Graph image build", "build-og-images.mjs", []],
    ]


def test_site_build_uses_private_safe_runner() -> None:
    package = json.loads(SITE_PACKAGE.read_text(encoding="utf-8"))
    command = package["scripts"]["build"]

    assert command == "node ./scripts/run-private-safe-build.mjs"
    assert "astro build" not in command
