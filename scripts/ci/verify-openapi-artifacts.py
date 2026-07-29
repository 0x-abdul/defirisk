#!/usr/bin/env python3
"""Verify both OpenAPI formats are deterministic and mutually identical."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JSON_PATHS = (
    ROOT / "site/public/openapi.json",
    ROOT / "data/api/v1.7.0/openapi.json",
)
YAML_PATHS = tuple(path.with_suffix(".yaml") for path in JSON_PATHS)


def main() -> int:
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in JSON_PATHS]
    if documents[0] != documents[1] or documents[0].get("openapi") != "3.1.0":
        raise SystemExit("OpenAPI JSON artifacts differ or are not version 3.1.0")
    before = {path: path.read_bytes() for path in YAML_PATHS}
    result = subprocess.run(
        ["node", str(ROOT / "scripts/generate-openapi-yaml.mjs")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise SystemExit("OpenAPI YAML regeneration failed")
    changed = [
        str(path.relative_to(ROOT))
        for path in YAML_PATHS
        if path.read_bytes() != before[path]
    ]
    if changed:
        raise SystemExit(f"OpenAPI YAML artifacts are stale: {changed}")
    print("OK: OpenAPI JSON/YAML artifacts are deterministic and aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
