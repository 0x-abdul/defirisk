from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "ci" / "verify-openapi-artifacts.py"
SPEC = importlib.util.spec_from_file_location("verify_openapi_artifacts", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalized_bytes_ignores_checkout_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "openapi.yaml"
    path.write_bytes(b"openapi: 3.1.0\r\npaths:\r\n")

    assert MODULE.normalized_bytes(path) == b"openapi: 3.1.0\npaths:\n"


def test_normalized_bytes_preserves_content_changes(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_bytes(b"openapi: 3.1.0\r\npaths:\r\n")
    second.write_bytes(b"openapi: 3.1.0\npaths:\nchanged: true\n")

    assert MODULE.normalized_bytes(first) != MODULE.normalized_bytes(second)
