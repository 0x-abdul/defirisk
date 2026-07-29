from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "ci" / "verify-inactive-site.py"
SPEC = importlib.util.spec_from_file_location("verify_inactive_site", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write(root: Path, relative: str, value: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def test_exact_api_data_plus_landing_artifact_passes(tmp_path: Path) -> None:
    committed = tmp_path / "data/api"
    deployed = tmp_path / "site/dist/api"
    write(committed, "v1.7.0/index.json", b'{"data":[]}\n')
    write(deployed, "v1.7.0/index.json", b'{"data":[]}\n')
    write(deployed, "index.html", b"<!doctype html><title>API</title>\n")

    assert MODULE.verify_deployed_api(committed, deployed) == 1


def test_missing_landing_artifact_fails(tmp_path: Path) -> None:
    committed = tmp_path / "data/api"
    deployed = tmp_path / "site/dist/api"
    write(committed, "v1.7.0/index.json", b"same")
    write(deployed, "v1.7.0/index.json", b"same")

    with pytest.raises(ValueError, match="landing artifact"):
        MODULE.verify_deployed_api(committed, deployed)


@pytest.mark.parametrize(
    ("path", "committed_value", "deployed_value"),
    [
        ("v1.7.0/index.json", b"reviewed", b"altered"),
        ("unexpected.json", None, b"extra"),
    ],
)
def test_changed_or_extra_api_data_fails(
    tmp_path: Path,
    path: str,
    committed_value: bytes | None,
    deployed_value: bytes,
) -> None:
    committed = tmp_path / "data/api"
    deployed = tmp_path / "site/dist/api"
    write(committed, "v1.7.0/index.json", b"reviewed")
    write(deployed, "v1.7.0/index.json", b"reviewed")
    if committed_value is not None:
        write(committed, path, committed_value)
    write(deployed, path, deployed_value)
    write(deployed, "index.html", b"landing")

    with pytest.raises(ValueError, match="differs from committed"):
        MODULE.verify_deployed_api(committed, deployed)
