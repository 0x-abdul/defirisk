from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "ci" / "public_boundary.py"
SPEC = importlib.util.spec_from_file_location("public_boundary", MODULE_PATH)
assert SPEC and SPEC.loader
BOUNDARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARY)


def test_current_tree_passes_the_fail_closed_boundary() -> None:
    failures = BOUNDARY.validate_tree(ROOT)
    assert failures == []


def test_private_fields_fail_before_any_github_write() -> None:
    fixture = {
        "data": {
            "protocol": {
                "slug": "fixture",
                "review_token": "sensitive-fixture-value",
            }
        }
    }
    failures = BOUNDARY.scan_api_value(fixture, "fixture.json")
    assert failures
    assert all("sensitive-fixture-value" not in failure for failure in failures)


def test_live_telemetry_cannot_enter_versioned_status() -> None:
    fixture = {"data": {"runs": [{"error_count": 0}], "days_stale": 1}}
    failures = BOUNDARY.scan_api_value(fixture, "status.json")
    assert any("live telemetry" in failure for failure in failures)


def test_raw_database_timestamps_cannot_enter_public_projection() -> None:
    failures = BOUNDARY.scan_api_value(
        {"data": {"protocol": {"created_at": "2026-07-29T00:00:00Z"}}},
        "protocol.json",
    )
    assert any("raw database timestamp" in failure for failure in failures)


def test_assessed_factor_requires_public_safe_citation() -> None:
    detail = {
        "data": {
            "protocol_data": {
                "factor_scores": [
                    {
                        "factor_id": "RD-F-001",
                        "score": "red",
                        "evidence_summary": "Public evidence summary.",
                        "sources": [],
                    }
                ]
            }
        }
    }
    failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
    assert any("requires a public citation" in failure for failure in failures)
    detail["data"]["protocol_data"]["factor_scores"][0]["sources"] = [
        {
            "source_type": "official_documentation",
            "url": "https://example.org/security",
        }
    ]
    assert BOUNDARY.validate_protocol_citations(detail, "fixture.json") == []


def test_not_applicable_factor_may_omit_a_citation() -> None:
    detail = {
        "data": {
            "protocol_data": {
                "factor_scores": [
                    {
                        "factor_id": "RD-F-001",
                        "score": "not_applicable",
                        "evidence_summary": (
                            "The factor is structurally outside this protocol surface."
                        ),
                        "sources": [],
                    }
                ]
            }
        }
    }
    assert BOUNDARY.validate_protocol_citations(detail, "fixture.json") == []


def test_private_or_tokenized_citation_url_is_rejected() -> None:
    for url in (
        "http://example.org/report",
        "https://localhost/report",
        "https://10.0.0.1/report",
        "https://example.org/report?token=secret",
    ):
        assert not BOUNDARY.public_source_url_is_safe(url)


def test_reference_cannot_bypass_public_citation_boundary() -> None:
    detail = {
        "data": {
            "protocol_data": {
                "factor_scores": [
                    {
                        "factor_id": "RD-F-001",
                        "score": "red",
                        "evidence_summary": "Public evidence summary.",
                        "sources": [
                            {
                                "source_type": "official_documentation",
                                "reference": "RiskProduct/private-review/token=secret",
                            }
                        ],
                    }
                ]
            }
        }
    }
    failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
    assert any("citation shape" in failure for failure in failures)
    for reference in (
        "C:/Users/operator/private.txt",
        "/Users/operator/private.txt",
        "../private/evidence.json",
        "api_key: secret",
    ):
        detail["data"]["protocol_data"]["factor_scores"][0]["sources"][0].update(
            {
                "url": "https://example.org/public-report",
                "reference": reference,
            }
        )
        failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
        assert any("citation shape" in failure for failure in failures)
    detail["data"]["protocol_data"]["factor_scores"][0]["sources"][0].update(
        {"notes": "See docs/ops/protocol-addition/README.md"}
    )
    failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
    assert any("citation shape" in failure for failure in failures)


def test_runtime_export_and_overlay_controllers_are_absent() -> None:
    for relative in BOUNDARY.PROHIBITED_EXACT_PATHS:
        assert not (ROOT / relative).exists(), relative
    assert not (ROOT / "data" / "api" / "v1.7.0" / "unpublished").exists()
    assert not (ROOT / "site" / "src" / "pages" / "unpublished").exists()


def test_manifest_checker_is_reproducible() -> None:
    first = BOUNDARY.file_manifest(ROOT)
    second = BOUNDARY.file_manifest(ROOT)
    assert first == second
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ci" / "build-public-api-manifest.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_push_guard_has_no_boundary_bypass() -> None:
    hook = (ROOT / "scripts" / "git-hooks" / "pre-push").read_text(encoding="utf-8")
    assert "ALLOW_INTERNAL_PUSH" not in hook
    assert "verify-public-boundary.py" in hook
    assert "git archive" in hook
