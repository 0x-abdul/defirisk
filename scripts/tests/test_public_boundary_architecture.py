from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "ci" / "public_boundary.py"
SPEC = importlib.util.spec_from_file_location("public_boundary", MODULE_PATH)
assert SPEC and SPEC.loader
BOUNDARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARY)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _history(slug: str) -> dict:
    return {
        "rubric_version": "v1.7.0",
        "data": {
            "protocol_slug": slug,
            "series": [
                {
                    "snapshot_date": "2026-08-07",
                    "snapshot_version": f"fixture:{slug}:2026-08-07",
                    "grade_letter": "B",
                    "risk_score": 10.0,
                }
            ],
        },
    }


def _version_fixture(root: Path, *, indexed: tuple[str, ...] = ("alpha",)) -> Path:
    version = root / "data" / "api" / "v1.7.0"
    _write_json(
        version / "index.json",
        {"data": {"protocols": [{"slug": slug} for slug in indexed]}},
    )
    for slug in indexed:
        _write_json(
            version / "protocols" / f"{slug}.json",
            {"data": {"protocol_data": {"factor_scores": []}}},
        )
    for filename, key in (
        ("history.json", "history"),
        ("changes.json", "changes"),
        ("incidents.json", "incidents"),
    ):
        _write_json(version / filename, {"data": {key: []}})
    (version / "factors").mkdir(parents=True, exist_ok=True)
    return version


def test_current_tree_passes_the_fail_closed_boundary() -> None:
    failures = BOUNDARY.validate_tree(ROOT)
    assert failures == []


def test_indexed_protocol_history_is_the_only_allowed_nested_shape(tmp_path: Path) -> None:
    version = _version_fixture(tmp_path)
    _write_json(version / "protocols" / "alpha" / "history.json", _history("alpha"))
    assert BOUNDARY.validate_api_version(tmp_path, version) == []


def test_top_level_protocol_details_still_equal_the_index(tmp_path: Path) -> None:
    version = _version_fixture(tmp_path)
    _write_json(
        version / "protocols" / "extra.json",
        {"data": {"protocol_data": {"factor_scores": []}}},
    )
    failures = BOUNDARY.validate_api_version(tmp_path, version)
    assert any("detail files must match" in failure for failure in failures)


def test_unindexed_or_detail_less_protocol_history_fails(tmp_path: Path) -> None:
    version = _version_fixture(tmp_path)
    _write_json(version / "protocols" / "ghost" / "history.json", _history("ghost"))
    (version / "protocols" / "alpha.json").unlink()
    _write_json(version / "protocols" / "alpha" / "history.json", _history("alpha"))
    failures = BOUNDARY.validate_api_version(tmp_path, version)
    assert any("history slug is not indexed" in failure for failure in failures)
    assert any("lacks a matching top-level detail" in failure for failure in failures)


def test_protocol_history_path_payload_and_depth_are_bound(tmp_path: Path) -> None:
    version = _version_fixture(tmp_path)
    _write_json(version / "protocols" / "alpha" / "history.json", _history("beta"))
    _write_json(version / "protocols" / "alpha" / "extra.json", _history("alpha"))
    _write_json(
        version / "protocols" / "alpha" / "deeper" / "history.json",
        _history("alpha"),
    )
    failures = BOUNDARY.validate_api_version(tmp_path, version)
    assert any("protocol_slug must match" in failure for failure in failures)
    assert len([failure for failure in failures if "unexpected nested protocol path" in failure]) == 2


def test_protocol_history_rejects_unsafe_private_material(tmp_path: Path) -> None:
    version = _version_fixture(tmp_path)
    history = _history("alpha")
    history["data"]["private_url"] = "https://example.org/private-review"
    _write_json(version / "protocols" / "alpha" / "history.json", history)
    failures = BOUNDARY.validate_api_version(tmp_path, version)
    assert any("prohibited private field" in failure for failure in failures)


def test_protocol_history_is_bound_into_the_manifest(tmp_path: Path) -> None:
    version = _version_fixture(tmp_path)
    history_path = version / "protocols" / "alpha" / "history.json"
    _write_json(history_path, _history("alpha"))
    manifest = tmp_path / BOUNDARY.MANIFEST_RELATIVE
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(BOUNDARY.file_manifest(tmp_path), encoding="utf-8")
    assert BOUNDARY.validate_manifest(tmp_path) == []

    manifest.write_text(
        "\n".join(
            line
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if "protocols/alpha/history.json" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    assert BOUNDARY.validate_manifest(tmp_path)

    manifest.write_text(BOUNDARY.file_manifest(tmp_path), encoding="utf-8")
    history_path.write_text(history_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert BOUNDARY.validate_manifest(tmp_path)


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
                        "scope_level": "surface",
                        "surface_slug": "default",
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
                        "scope_level": "surface",
                        "surface_slug": "default",
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


def test_factor_identity_is_unique_within_its_scope() -> None:
    source = {
        "source_type": "official_documentation",
        "url": "https://example.org/security",
    }
    rows = [
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "surface_slug": surface_slug,
            "score": "green",
            "evidence_summary": "Public evidence summary.",
            "sources": [source],
        }
        for surface_slug in ("v2", "v3", "v4")
    ]
    detail = {"data": {"protocol_data": {"factor_scores": rows}}}
    assert BOUNDARY.validate_protocol_citations(detail, "fixture.json") == []

    duplicate = dict(rows[0])
    duplicate["family_slug"] = "irrelevant-to-surface-scope"
    rows.append(duplicate)
    failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
    assert any(
        "scoped factor identity must be non-empty and unique" in failure
        for failure in failures
    )


def test_family_and_deployment_scopes_have_distinct_identities() -> None:
    source = {
        "source_type": "official_documentation",
        "url": "https://example.org/security",
    }
    rows = [
        {
            "factor_id": "RD-F-001",
            "scope_level": "family",
            "family_slug": "fixture",
            "score": "green",
            "evidence_summary": "Public evidence summary.",
            "sources": [source],
        },
        {
            "factor_id": "RD-F-001",
            "scope_level": "deployment",
            "surface_slug": "default",
            "chain": "ethereum",
            "deployment_key": "primary",
            "score": "green",
            "evidence_summary": "Public evidence summary.",
            "sources": [source],
        },
    ]
    detail = {"data": {"protocol_data": {"factor_scores": rows}}}
    assert BOUNDARY.validate_protocol_citations(detail, "fixture.json") == []


def test_malformed_factor_and_scope_identities_fail_closed() -> None:
    base = {
        "factor_id": "RD-F-001",
        "scope_level": "surface",
        "surface_slug": "default",
        "score": "not_applicable",
        "evidence_summary": "Structurally outside this protocol surface.",
        "sources": [],
    }
    malformed = [
        {**base, "factor_id": value}
        for value in (None, "", [], {})
    ] + [
        {**base, "scope_level": None},
        {**base, "scope_level": "bogus"},
        {**base, "surface_slug": None},
        {**base, "surface_slug": []},
        {
            **base,
            "scope_level": "family",
            "family_slug": "",
        },
        {
            **base,
            "scope_level": "deployment",
            "chain": "ethereum",
            "deployment_key": "primary",
            "surface_slug": {},
        },
    ]
    for row in malformed:
        detail = {"data": {"protocol_data": {"factor_scores": [row]}}}
        failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
        assert failures

    duplicate_invalid = [
        {**base, "scope_level": "bogus", "surface_slug": "one"},
        {**base, "scope_level": "bogus", "surface_slug": "two"},
    ]
    detail = {"data": {"protocol_data": {"factor_scores": duplicate_invalid}}}
    failures = BOUNDARY.validate_protocol_citations(detail, "fixture.json")
    assert len([failure for failure in failures if "scope identity" in failure]) == 2


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
                        "scope_level": "surface",
                        "surface_slug": "default",
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


def _preservation_fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    versions: dict[str, Path] = {}
    for version in sorted(BOUNDARY.V1_API_PRESERVATION_VERSIONS):
        version_root = tmp_path / "data" / "api" / version
        _write_json(version_root / "index.json", {"data": {"value": version}})
        (version_root / "notes.yaml").write_text(
            f"version: {version}\n", encoding="utf-8"
        )
        versions[version] = version_root
    _write_json(
        tmp_path / BOUNDARY.V1_API_PRESERVATION_RELATIVE,
        {
            "schema": BOUNDARY.V1_API_PRESERVATION_SCHEMA,
            "hashing": BOUNDARY.V1_API_PRESERVATION_HASHING,
            "versions": {
                version: BOUNDARY.api_version_digest(version_root)
                for version, version_root in versions.items()
            },
        },
    )
    return tmp_path, versions


def test_frozen_v1_contract_matches_the_current_tree() -> None:
    assert BOUNDARY.validate_v1_api_preservation(ROOT) == []


def test_frozen_contract_rejects_one_byte_changes(tmp_path: Path) -> None:
    fixture, versions = _preservation_fixture(tmp_path)
    target = versions["v1.5.0"] / "index.json"
    target.write_bytes(target.read_bytes().replace(b"v1.5.0", b"v1.5.1", 1))

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("v1.5.0: raw_sha256 mismatch" in failure for failure in failures)
    assert any("v1.5.0: semantic_sha256 mismatch" in failure for failure in failures)


def test_frozen_contract_rejects_missing_files(tmp_path: Path) -> None:
    fixture, versions = _preservation_fixture(tmp_path)
    (versions["v1.6.0"] / "notes.yaml").unlink()

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("v1.6.0: file_count mismatch" in failure for failure in failures)
    assert any("v1.6.0: raw_sha256 mismatch" in failure for failure in failures)


def test_frozen_contract_rejects_extra_files(tmp_path: Path) -> None:
    fixture, versions = _preservation_fixture(tmp_path)
    (versions["v1.7.0"] / "unexpected.txt").write_text(
        "not part of the frozen tree\n", encoding="utf-8"
    )

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("v1.7.0: file_count mismatch" in failure for failure in failures)
    assert any("v1.7.0: raw_sha256 mismatch" in failure for failure in failures)


def test_frozen_contract_rejects_semantic_json_changes(tmp_path: Path) -> None:
    fixture, versions = _preservation_fixture(tmp_path)
    _write_json(
        versions["v1.5.0"] / "index.json",
        {"data": {"value": "different-version"}},
    )

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("v1.5.0: raw_sha256 mismatch" in failure for failure in failures)
    assert any("v1.5.0: semantic_sha256 mismatch" in failure for failure in failures)


def test_frozen_contract_proves_formatting_only_json_is_semantically_equal(
    tmp_path: Path,
) -> None:
    fixture, versions = _preservation_fixture(tmp_path)
    target = versions["v1.5.0"] / "index.json"
    target.write_text(
        '{\n  "data": {\n    "value": "v1.5.0"\n  }\n}\n',
        encoding="utf-8",
    )

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("v1.5.0: raw_sha256 mismatch" in failure for failure in failures)
    assert not any("v1.5.0: semantic_sha256 mismatch" in failure for failure in failures)


def test_frozen_contract_rejects_malformed_json(tmp_path: Path) -> None:
    fixture, versions = _preservation_fixture(tmp_path)
    (versions["v1.6.0"] / "index.json").write_text(
        '{"data": ', encoding="utf-8"
    )

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("invalid JSON" in failure for failure in failures)


def test_frozen_contract_requires_every_pinned_version_entry(tmp_path: Path) -> None:
    fixture, _versions = _preservation_fixture(tmp_path)
    contract_path = fixture / BOUNDARY.V1_API_PRESERVATION_RELATIVE
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    del contract["versions"]["v1.7.0"]
    _write_json(contract_path, contract)

    failures = BOUNDARY.validate_v1_api_preservation(fixture)

    assert any("missing version entries" in failure for failure in failures)
