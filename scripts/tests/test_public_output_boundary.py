from __future__ import annotations

import copy
import html
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_output_boundary", ROOT / "scripts/ci/candidate_boundary.py")
assert SPEC and SPEC.loader
BOUNDARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARY)
STAMP = "2026-10-02T00:00:00Z"
PUBLIC_PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108000000003a7e9b550000000a49444154789c636000000002000148afa4710000000049454e44ae426082")
VERSIONS = ("v1.5.0", "v1.6.0", "v1.7.0")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def factor(score: str = "green", surface: str = "alpha") -> dict:
    return {
        "factor_id": "RD-F-001",
        "scope_level": "surface",
        "surface_slug": surface,
        "surface_id": f"public-{surface}",
        "score": score,
        "evidence_summary": "Public evidence – verified claim ≥ public threshold.",
        "sources": [] if score in {"not_assessed", "not_applicable"} else [{
            "source_type": "official_documentation",
            "url": "https://example.org/docs/home/internal/security",
            "retrieved_at": "2026-10-02",
        }],
    }


def envelope(version: str, data: dict) -> dict:
    return {"rubric_version": version, "data_as_of": STAMP, "generated_at": STAMP, "data": data}


def source_tree(root: Path) -> Path:
    api = root / "data/api"
    registry = json.loads((ROOT / BOUNDARY.FIELD_REGISTRY_RELATIVE).read_text(encoding="utf-8"))
    write_json(api / BOUNDARY.FIELD_REGISTRY_RELATIVE.name, registry)
    write_json(api / BOUNDARY.BASELINE_RELATIVE.name, {
        "schema_version": 1,
        "current_api_version": "v1.7.0",
        "published_protocols": {"count": 1, "slug_sha256": BOUNDARY.slug_digest(["example"])},
    })
    for version in VERSIONS:
        base = api / version
        write_json(base / "index.json", envelope(version, {"protocols": [{"slug": "example", "display_name": "Example", "status": "live"}]}))
        for name in ("history", "changes", "incidents", "hacks"):
            write_json(base / f"{name}.json", envelope(version, {name: []}))
        write_json(base / "factors.json", envelope(version, {"factors": []}))
        write_json(base / "openapi.json", {"openapi": "3.1.0", "paths": {}})
        for folder in ("schema", "schemas"):
            write_json(base / folder / "envelope.json", {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {}})
        write_json(base / "status.json", envelope(version, {"assessment_snapshot": {
            "rubric_version": version,
            "published_protocol_count": 1,
            "data_as_of": STAMP,
            "projection_timestamp": STAMP,
        }}))
        write_json(base / "protocols/example.json", envelope(version, {"protocol_data": {
            "protocol": {"slug": "example", "status": "live"},
            "factor_scores": [],
            "surfaces": [
                {"surface_slug": "alpha", "surface_id": "public-alpha", "headline_grade": "A", "factor_scores": [factor()]},
                {"surface_slug": "beta", "surface_id": "public-beta", "headline_grade": "D", "factor_scores": [factor("red", "beta")], "deployments": [{"id": "public-deployment", "factor_scores": [factor("yellow", "beta")]}]},
            ],
        }}))
        write_json(base / "rubric.json", envelope(version, {"factor_definitions": []}))
    (api / "MANIFEST.sha256").write_text(BOUNDARY.file_manifest(root), encoding="utf-8")
    return api


def output_tree(root: Path, api: Path) -> Path:
    dist = root / "built-output"
    shutil.copytree(api, dist / "api")
    for name in ("index.html", "about/index.html", "methodology/index.html", "data/index.html", "changes/index.html", "404.html", "protocols/example/index.html", "api/index.html"):
        path = dist / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!doctype html><title>Public assessment</title><p>Reviewed public evidence.</p>", encoding="utf-8")
    for name in ("default", "analytics"):
        path = dist / "og" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PUBLIC_PNG)
    return dist


@pytest.mark.parametrize("url", [
    "https://example.org/docs/home/internal/report.pdf",
    "https://github.com/example/project/commit/0123456789abcdef0123456789abcdef01234567",
    "https://etherscan.io/tx/0x0123456789abcdef",
    "https://example.org/research/audit.pdf",
    "https://example.org/a%20report.pdf",
])
def test_legitimate_public_citations_are_preserved(url: str) -> None:
    citation = {"source_type": "docs", "url": url, "retrieved_at": "2026-10-02"}
    before = copy.deepcopy(citation)
    assert BOUNDARY.public_source_url_is_safe(url)
    assert BOUNDARY.scan_api_value({"arbitrary": {"sources": [citation]}}, "fixture.json") == []
    assert citation == before


@pytest.mark.parametrize("value", [
    r"C:\Users\operator\private\evidence.json",
    r"C:\Data\private\evidence.json",
    r"D:\Desktop\private\evidence.json",
    r"\\private-server\share\evidence.json",
    "/home/operator/private/evidence.json",
    "file:///private/evidence.json",
    "_local/review/evidence.json",
    ".research/family/evidence.json",
    "../private/evidence.json",
    "https://private.example.org/report",
    "https://example.org/report?access_token=sensitive-value",
    "https://example.org/report#review_token=sensitive-value",
    "https://example.org/_local/report",
    "https://private.example.invalid/report",
])
def test_private_scalars_fail_at_arbitrary_nesting_without_disclosure(value: str) -> None:
    failures = BOUNDARY.scan_api_value({"extra": [{"more": {"text": value}}]}, "fixture.json")
    assert failures
    assert all(value not in failure and "sensitive-value" not in failure for failure in failures)


@pytest.mark.parametrize("transform", [lambda value: quote(quote(value, safe=""), safe=""), lambda value: "".join(f"\\u{ord(character):04x}" for character in value), html.escape])
def test_encoded_locators_cannot_bypass_the_boundary(transform) -> None:
    value = transform("C:/Users/operator/private/evidence.json")
    assert BOUNDARY.scan_api_value({"nested": value}, "fixture.json")


def test_private_object_keys_and_source_labels_are_redacted() -> None:
    private = "C:/Users/operator/private/secret.json"
    failures = BOUNDARY.scan_api_value({private: "safe"}, private)
    assert failures
    assert all(private not in failure and "operator" not in failure for failure in failures)


def test_css_decoding_cannot_hide_windows_locators_or_leak_diagnostic_keys() -> None:
    for private in (r"C:\Data\private.json", r"D:\Desktop\private.json"):
        failures = BOUNDARY.scan_api_value({private: {"review_token": "sensitive-value"}}, "fixture.json")
        assert failures
        assert all(private not in failure and "sensitive-value" not in failure for failure in failures)
        encoded = "".join(f"\\u{ord(character):04x}" for character in private)
        assert BOUNDARY.scan_api_value({"evidence_summary": encoded}, "fixture.json")


@pytest.mark.parametrize("score", ["not_assessed", "not_applicable"])
def test_reviewed_source_optional_states_remain_source_optional(score: str) -> None:
    assert BOUNDARY.scan_api_value(factor(score), "fixture.json") == []
    row = factor(score)
    row["sources"] = [{"source_type": "local_reference", "url": "file:///private/evidence"}]
    assert BOUNDARY.scan_api_value(row, "fixture.json")


@pytest.mark.parametrize("score", ["green", "yellow", "red", "gray"])
def test_every_graded_state_requires_genuine_public_citation(score: str) -> None:
    row = factor(score)
    row["sources"] = []
    assert any("requires a public citation" in failure for failure in BOUNDARY.scan_api_value(row, "fixture.json"))
    row["sources"] = [{"source_type": "curator_note", "url": "https://example.org/note"}]
    assert BOUNDARY.scan_api_value(row, "fixture.json")


def test_distinct_surface_grades_and_deployment_citations_are_checked_without_mutation(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    before = (api / "v1.7.0/protocols/example.json").read_bytes()
    assert BOUNDARY.validate_tree(tmp_path) == []
    assert (api / "v1.7.0/protocols/example.json").read_bytes() == before
    row = json.loads(before)
    row["data"]["protocol_data"]["surfaces"][1]["deployments"][0]["factor_scores"][0]["sources"][0]["url"] = "https://127.0.0.1/private"
    assert BOUNDARY.scan_api_value(row, "fixture.json")


@pytest.mark.parametrize("version", VERSIONS)
def test_each_retained_api_version_is_checked(tmp_path: Path, version: str) -> None:
    api = source_tree(tmp_path)
    path = api / version / "history.json"
    write_json(path, envelope(version, {"history": [], "extra": {"evidence": "_local/working/evidence.json"}}))
    (api / "MANIFEST.sha256").write_text(BOUNDARY.file_manifest(tmp_path), encoding="utf-8")
    failures = BOUNDARY.validate_tree(tmp_path)
    assert any(version in failure and "locator" in failure for failure in failures)


@pytest.mark.parametrize("value", [{"do_not_publish": True}, {"status": "held"}, {"is_published": False}, {"collected_by": "private-operator"}, {"created_at": STAMP}, {"pipeline_runs": []}])
def test_holds_private_provenance_and_telemetry_fail_at_every_scope(value: dict) -> None:
    assert BOUNDARY.scan_api_value({"outer": {"arbitrary": [value]}}, "fixture.json")


def test_registry_exception_is_exact_and_not_a_secret_bypass(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    path = api / BOUNDARY.FIELD_REGISTRY_RELATIVE.name
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["live_operational_telemetry"]["extra"] = "_local/secret.json"
    assert BOUNDARY.scan_api_value(registry, BOUNDARY.FIELD_REGISTRY_RELATIVE.as_posix())


@pytest.mark.parametrize("relative,body", [
    ("api/index.html", "<p>file:///private/evidence</p>"),
    ("assets/main.js", r'const evidence="\u0043\u003a\u002fUsers/operator/private/evidence";'),
    ("assets/main.css", 'body{background:url("file:///private/evidence")}'),
    ("assets/logo.svg", '<svg><text>_local/private/evidence</text></svg>'),
    ("sitemap.xml", '<url><loc>https://example.org/unpublished/review</loc></url>'),
    ("robots.txt", "Disallow: /unpublished/review"),
    ("_headers", "X-Review: https://localhost/private"),
    ("_redirects", "/old https://example.org/review?review_token=sensitive-value 302"),
    ("assets/main.js.map", json.dumps({"version": 3, "sources": ["public-component.tsx"], "sourceRoot": "C:/Users/operator/private/"})),
])
def test_every_emitted_text_family_and_api_landing_is_checked(tmp_path: Path, relative: str, body: str) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    assert BOUNDARY.validate_output_tree(tmp_path, dist) == []
    path = dist / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    failures = BOUNDARY.validate_output_tree(tmp_path, dist)
    assert failures
    assert all("operator" not in failure and "sensitive-value" not in failure for failure in failures)


def test_html_island_and_json_script_fields_are_checked(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    payload = {"deep": {"created_at": STAMP}}
    props = html.escape(json.dumps(payload), quote=True)
    (dist / "index.html").write_text(f'<astro-island props="{props}"></astro-island>', encoding="utf-8")
    assert BOUNDARY.validate_output_tree(tmp_path, dist)
    (dist / "index.html").write_text('<script type="application/json">' + json.dumps({"deep": {"review_token": "sensitive-value"}}) + "</script>", encoding="utf-8")
    failures = BOUNDARY.validate_output_tree(tmp_path, dist)
    assert failures and all("sensitive-value" not in failure for failure in failures)


def astro_props(value: dict) -> dict:
    def encode(item):
        if isinstance(item, dict):
            return [0, {key: encode(child) for key, child in item.items()}]
        if isinstance(item, list):
            return [1, [encode(child) for child in item]]
        return [0, item]
    return {key: encode(child) for key, child in value.items()}


def write_island(path: Path, value: dict) -> None:
    props = html.escape(json.dumps(value, ensure_ascii=False), quote=True)
    path.write_text(f'<astro-island props="{props}"></astro-island>', encoding="utf-8")


def test_astro_transport_decodes_records_before_claim_checks_without_changing_values(tmp_path: Path) -> None:
    row = factor()
    row["evidence_summary"] = 'Public café evidence says "quoted" and literal &quot; text.'
    row["sources"][0]["url"] = "https://example.org/a%20report.pdf"
    payload = {"scores": [row], "nullable": None, "available": True, "count": 2}
    encoded = astro_props(payload)
    assert BOUNDARY._decode_astro_props(encoded) == payload
    path = tmp_path / "fixture.html"
    write_island(path, encoded)
    assert BOUNDARY._scan_text_file(path, "site/dist/fixture.html") == []


@pytest.mark.parametrize("payload", [
    {"data": [99, "private sentinel"]},
    {"data": [True, "private sentinel"]},
    {"data": [0, "value", "extra"]},
    {"data": [0, ["untagged array"]]},
    {"data": [1, [[0, "valid"], "untagged"]]},
    {"data": [3, "2026-10-02T00:00:00Z"]},
])
def test_astro_transport_rejects_unsupported_or_malformed_tags(tmp_path: Path, payload: dict) -> None:
    path = tmp_path / "fixture.html"
    write_island(path, payload)
    failures = BOUNDARY._scan_text_file(path, "site/dist/fixture.html")
    assert any("invalid embedded browser payload" in failure for failure in failures)
    assert all("private sentinel" not in failure for failure in failures)


def test_astro_transport_keeps_private_checks_and_genuine_citation_floor(tmp_path: Path) -> None:
    path = tmp_path / "fixture.html"
    row = factor()
    row.pop("sources")
    write_island(path, astro_props({"scores": [row]}))
    assert any("sources must be an array" in failure for failure in BOUNDARY._scan_text_file(path, "site/dist/fixture.html"))
    write_island(path, astro_props({"data": {"review_token": "sensitive-value", "path": r"C:\Data\private.json"}}))
    failures = BOUNDARY._scan_text_file(path, "site/dist/fixture.html")
    assert failures and all("sensitive-value" not in failure and r"C:\Data\private.json" not in failure for failure in failures)


def test_malformed_factor_score_is_a_safe_validation_error_not_markup_type_error() -> None:
    row = factor()
    row["score"] = ["untrusted array"]
    assert any("score is invalid" in failure for failure in BOUNDARY.scan_api_value(row, "fixture.json"))


def test_stale_api_files_hash_changes_and_unbound_output_fail(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    expected = BOUNDARY.hash_public_tree(dist)
    write_json(dist / "api/v1.4.0/retained.json", {"public": "stale"})
    assert any("roster or bytes" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist))
    (dist / "stale.txt").write_text("otherwise safe stale output", encoding="utf-8")
    assert any("bound build roster" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist, expected_output_files=expected))


def test_symlink_output_fails_without_echoing_target(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    target = tmp_path / "private-target.txt"
    target.write_text("private sentinel", encoding="utf-8")
    try:
        (dist / "escape.txt").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable for this Windows principal")
    failures = BOUNDARY.validate_output_tree(tmp_path, dist)
    assert any("symlink" in failure for failure in failures)
    assert all(str(target) not in failure for failure in failures)


def test_reparse_output_refusal_is_covered_when_symlink_creation_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    link = dist / "escape.txt"
    link.write_text("public-looking bytes are not a link safety proof", encoding="utf-8")
    original = BOUNDARY._is_link
    monkeypatch.setattr(BOUNDARY, "_is_link", lambda path: path == link or original(path))
    assert any("symlinks or junctions" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist))


@pytest.mark.parametrize("relative", [".git/config", ".env", "assets/_local/private.txt", "assets/node_modules/source.js"])
def test_workspace_artifacts_cannot_ship_even_without_secret_text(tmp_path: Path, relative: str) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    path = dist / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("public-looking bytes", encoding="utf-8")
    assert any("workspace-only artifact" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist))


def test_explicit_inactive_root_dist_cli_and_portable_api_override(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    build_inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    receipt = tmp_path / "private-build-receipt.json"
    write_json(receipt, BOUNDARY.create_output_manifest(api, dist, build_inputs=build_inputs))
    result = subprocess.run([sys.executable, str(ROOT / "scripts/ci/verify-inactive-site.py"), "--root", str(tmp_path), "--dist", str(dist), "--api-root", str(api), "--build-receipt", str(receipt)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_extracted_public_source_cannot_hide_local_artifacts(tmp_path: Path) -> None:
    source_tree(tmp_path)
    write_json(tmp_path / "_local/receipt.json", {"review_token": "sensitive-value"})
    failures = BOUNDARY.validate_tree(tmp_path)
    assert any("private path" in failure for failure in failures)
    assert all("sensitive-value" not in failure for failure in failures)


@pytest.mark.parametrize("key", ["review%5Fnotes", "collectedBy", "api-key", "token", "databaseDsn", "reviewerIdentity"])
def test_normalized_private_fields_cannot_evade_key_checks(key: str) -> None:
    assert BOUNDARY.scan_api_value({"arbitrary": {key: "sensitive-value"}}, "fixture.json")
    assert BOUNDARY.scan_api_value({"authorization_required": True, "state_tokens": 4}, "fixture.json") == []


@pytest.mark.parametrize("body", [
    'const data = {collected_by:"fixture-person"};',
    'const evidence = "file:" + "///home/fixture/notes.json";',
    r'const evidence = "\u{43}:\u{2f}Users/fixture/notes.json";',
    r'const evidence = "file:" + `///home/fixture/notes.json`;',
])
def test_static_browser_encodings_and_unquoted_fields_are_checked(tmp_path: Path, body: str) -> None:
    path = tmp_path / "bundle.js"
    path.write_text(body, encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/bundle.js")


@pytest.mark.parametrize("body", ['{"text":"_local/private.json","text":"public"}', '{"value":NaN}', '{"value":Infinity}'])
def test_duplicate_keys_and_nonfinite_numbers_fail_raw_json_and_browser_payloads(tmp_path: Path, body: str) -> None:
    path = tmp_path / "fixture.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(BOUNDARY.BoundaryError):
        BOUNDARY.load_json(path)
    assert BOUNDARY._scan_text_file(path, "site/dist/fixture.json")
    markup = tmp_path / "fixture.html"
    markup.write_text('<script type="application/json">' + body + "</script>", encoding="utf-8")
    assert BOUNDARY._scan_text_file(markup, "site/dist/fixture.html")


@pytest.mark.parametrize("url", ["https://intranet/report", r"https://example.org\private\report", "https://127.1/report", "https://example.org/raw space.pdf"])
def test_nonpublic_or_malformed_hosts_and_locators_are_rejected(url: str) -> None:
    assert not BOUNDARY.public_source_url_is_safe(url)


def test_schema_documentation_has_no_runtime_evidence_or_secret_bypass() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {key: {"type": "string"} for key in ("collected_by", "factor_id", "score", "evidence_summary", "sources")},
    }
    logical = "data/api/v1.7.0/schema/envelope.json"
    assert BOUNDARY.scan_api_value(schema, logical) == []
    schema["examples"] = [{"collected_by": "fixture-private-person"}]
    assert BOUNDARY.scan_api_value(schema, logical)
    schema.pop("examples")
    schema["properties"]["factor_id"]["default"] = "_local/private.json"
    assert BOUNDARY.scan_api_value(schema, logical)


def test_only_registered_documentation_examples_are_illustrative(tmp_path: Path) -> None:
    example = {"factor_id": "RD-F-001", "score": "green", "evidence_summary": "Illustrative documented score.", "sources": []}
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "examples": [example]}
    assert BOUNDARY.scan_api_value(schema, "data/api/v1.7.0/schema/envelope.json") == []
    assert BOUNDARY.scan_api_value(schema, "fixture.json")
    schema["examples"][0]["internal_path"] = "_local/private.json"
    assert BOUNDARY.scan_api_value(schema, "data/api/v1.7.0/schema/envelope.json")
    document = {"openapi": "3.1.0", "paths": {}, "components": {"schemas": {"Fixture": {"properties": {"collected_by": {"type": "string"}}}}}}
    path = tmp_path / "openapi.json"
    write_json(path, document)
    assert BOUNDARY._scan_text_file(path, "site/dist/openapi.json") == []
    document["components"]["schemas"]["Fixture"]["example"] = {"collected_by": "fixture-private-person"}
    write_json(path, document)
    assert BOUNDARY._scan_text_file(path, "site/dist/openapi.json")


def test_public_source_map_references_remain_safe_but_content_and_encoded_paths_do_not(tmp_path: Path) -> None:
    path = tmp_path / "main.js.map"
    payload = {"version": 3, "sources": ["../src/PublicView.tsx"], "sourcesContent": ["export const visible = true;"], "mappings": ""}
    write_json(path, payload)
    assert BOUNDARY._scan_text_file(path, "site/dist/main.js.map") == []
    payload["sourcesContent"] = ["const proof = '_local/private.json';"]
    write_json(path, payload)
    assert BOUNDARY._scan_text_file(path, "site/dist/main.js.map")
    payload["sourcesContent"] = []
    payload["sources"] = [quote("../_local/private.json")]
    write_json(path, payload)
    assert BOUNDARY._scan_text_file(path, "site/dist/main.js.map")


@pytest.mark.parametrize("body", [
    "metadata:\n  collected_by: fixture-person\n",
    "metadata:\n  field: public\n  field: duplicate\n",
    "metadata:\n  review%5Fnotes: fixture-private\n",
])
def test_yaml_private_keys_and_duplicate_mappings_fail(tmp_path: Path, body: str) -> None:
    path = tmp_path / "openapi.yaml"
    path.write_text(body, encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml")


def test_yaml_schema_property_names_are_documentary_and_examples_are_checked(tmp_path: Path) -> None:
    path = tmp_path / "openapi.yaml"
    public = "openapi: 3.1.0\ncomponents:\n  schemas:\n    Fixture:\n      type: object\n      properties:\n        collected_by:\n          type: string\n"
    path.write_text(public, encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml") == []
    path.write_text(public + "      example:\n        collected_by: fixture-person\n", encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml")


@pytest.mark.parametrize("wording", ["Data cache confirms the claim.", "00-profile.md confirms the claim.", "Process learnings confirm the claim.", "Current local preservation row confirms the claim."])
def test_working_evidence_provenance_is_rejected_without_banning_protocol_facts(wording: str) -> None:
    assert BOUNDARY.scan_api_value({"evidence_summary": wording}, "fixture.json")
    assert BOUNDARY.scan_api_value({"evidence_summary": "Public documentation describes the protocol's internal transaction accounting."}, "fixture.json") == []


@pytest.mark.parametrize("row", [{"editorial_status": "draft"}, {"assessment_eligibility": "blocked"}, {"family_is_published": False}, {"protocol_is_published": False}, {"assessment_available": False, "headline_grade": "A"}])
def test_explicit_held_authority_markers_never_become_public_assessments(row: dict) -> None:
    assert BOUNDARY.scan_api_value({"surfaces": [row]}, "fixture.json")


@pytest.mark.parametrize("version", VERSIONS)
def test_unlisted_endpoints_and_definition_rosters_fail_even_with_matching_manifest(tmp_path: Path, version: str) -> None:
    api = source_tree(tmp_path)
    write_json(api / version / "extra-assessment.json", {"public": "unexpected"})
    write_json(api / version / "factors/RD-F-999.json", envelope(version, {"factor_data": {"scored_protocols": []}}))
    (api / "MANIFEST.sha256").write_text(BOUNDARY.file_manifest(tmp_path), encoding="utf-8")
    failures = BOUNDARY.validate_api_tree(api)
    assert any("unlisted public API endpoint" in failure for failure in failures)
    assert any("definition files" in failure for failure in failures)


def test_private_artifact_names_are_redacted_even_when_encoded() -> None:
    for relative in ("site/dist/review_token=synthetic-fixture.txt", "site/dist/review%5Ftoken%3Dsynthetic-fixture.txt"):
        displayed = BOUNDARY._display_source(relative)
        assert "synthetic-fixture" not in displayed and displayed.startswith("<artifact-")


def test_ancestor_reparse_path_is_rejected_without_following_it(tmp_path: Path, monkeypatch) -> None:
    api = source_tree(tmp_path)
    original = Path.lstat
    ancestor = tmp_path

    class ReparseMetadata:
        st_mode = 0
        st_file_attributes = 0x400

    monkeypatch.setattr(Path, "lstat", lambda path: ReparseMetadata() if path == ancestor else original(path))
    assert BOUNDARY._is_link(api)
    assert BOUNDARY.validate_api_tree(api) == ["data/api: missing or unsafe public API tree"]


def test_og_roster_matches_only_graded_public_inputs(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    assert BOUNDARY.validate_output_tree(tmp_path, dist) == []
    path = dist / "og/protocols/held-family.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PUBLIC_PNG)
    assert any("graded API inputs" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist))


def test_fixed_public_og_svg_remains_scanned_and_source_bound(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    source = tmp_path / "site/public/og/default.svg"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Public fallback</text></svg>', encoding="utf-8")
    shutil.copyfile(source, dist / "og/default.svg")
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    inputs["site/public/og/default.svg"] = BOUNDARY.hashlib.sha256(source.read_bytes()).hexdigest()
    assert BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs)
    (dist / "og/default.svg").write_text('<svg><text>_local/private.json</text></svg>', encoding="utf-8")
    assert BOUNDARY.validate_output_tree(tmp_path, dist)
    with pytest.raises(BOUNDARY.BoundaryError):
        BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs)


def test_staged_api_receipt_uses_explicit_candidate_source_root(tmp_path: Path) -> None:
    source = tmp_path / "candidate-source"
    api = source_tree(source)
    dist = output_tree(source, api)
    svg = source / "site/public/og/default.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Public fallback</text></svg>', encoding="utf-8")
    shutil.copyfile(svg, dist / "og/default.svg")
    staged = tmp_path / "frozen-build-stage/api"
    shutil.copytree(api, staged)
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    inputs["site/public/og/default.svg"] = BOUNDARY.hashlib.sha256(svg.read_bytes()).hexdigest()
    receipt = BOUNDARY.create_output_manifest(staged, dist, build_inputs=inputs, source_root=source)
    assert BOUNDARY.validate_output_tree(source, dist, api_root=staged, build_receipt=receipt, require_build_receipt=True) == []


def test_private_build_receipt_binds_all_output_bytes_and_source_inputs(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    receipt = BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs)
    assert BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=receipt, require_build_receipt=True) == []
    assert any("requires a frozen" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist, require_build_receipt=True))
    (dist / "index.html").write_text("<p>Otherwise safe drift.</p>", encoding="utf-8")
    assert any("frozen private build receipt" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=receipt))


def test_bracketed_build_sources_bind_without_publishing_the_private_receipt(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    source = tmp_path / "site/src/pages/protocols/[slug].astro"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("<p>Public route source.</p>", encoding="utf-8")
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    inputs[source.relative_to(tmp_path).as_posix()] = BOUNDARY.hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs)
    assert set(receipt) == {"schema", "build_inputs", "api_files", "output_files"}
    assert BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=receipt) == []
    source.write_text("<p>Unqualified source drift.</p>", encoding="utf-8")
    assert any("build source bytes differ" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=receipt))


def test_extracted_source_cannot_hide_a_private_receipt_in_build_metadata(tmp_path: Path) -> None:
    source_tree(tmp_path)
    write_json(tmp_path / "site/.astro/private-build-receipt.json", {"review_token": "sensitive-value"})
    failures = BOUNDARY.validate_tree(tmp_path)
    assert any("private path" in failure or "workspace-only artifact" in failure for failure in failures)


def test_yaml_sequences_are_not_duplicate_mappings(tmp_path: Path) -> None:
    path = tmp_path / "openapi.yaml"
    path.write_text("openapi: 3.1.0\ntags:\n  -\n    name: protocols\n    description: Public protocols\n  -\n    name: factors\n    description: Public factors\n", encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml") == []


@pytest.mark.parametrize("route", ["/dev/", "/data/api/", "/api/", "/_canonical_", "/unpublished/", "/control/"])
def test_fixed_public_robots_denies_are_policy_metadata(tmp_path: Path, route: str) -> None:
    path = tmp_path / "robots.txt"
    path.write_text(f"User-agent: *\nDisallow: {route}\n", encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/robots.txt") == []
    assert BOUNDARY.scan_api_value({"text": "/unpublished/"}, "fixture.json")


@pytest.mark.parametrize("body", [
    "User-agent: *\nDisallow: /unpublished/private-token\n",
    "User-agent: *\nDisallow: /control/private-token\n",
    "User-agent: *\nDisallow: https://example.org/unpublished/\n",
    "User-agent: *\nDisallow: /control/?review_token=sensitive-value\n",
    "# See /control/private-token for details\nDisallow: /control/\n",
    "# file:///private/evidence\nDisallow: /unpublished/\n",
])
def test_robots_roles_never_hide_comments_dynamic_paths_or_urls(tmp_path: Path, body: str) -> None:
    path = tmp_path / "robots.txt"
    path.write_text(body, encoding="utf-8")
    failures = BOUNDARY._scan_text_file(path, "site/dist/robots.txt")
    assert failures and all("sensitive-value" not in failure for failure in failures)


@pytest.mark.parametrize("route", ["/api/*/unpublished/*", "/unpublished/*", "/control/*"])
def test_guarded_fixed_header_routes_remain_scanned_public_policy(tmp_path: Path, route: str) -> None:
    path = tmp_path / "_headers"
    path.write_text(f"{route}\n  Cache-Control: private, no-store\n  X-Robots-Tag: noindex, nofollow\n", encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/_headers") == []


@pytest.mark.parametrize("body", [
    "/control/*\n  Cache-Control: public\n  X-Robots-Tag: noindex\n",
    "/control/*\n  Cache-Control: private, no-store\n  X-Robots-Tag: index\n",
    "/control/*\n  Cache-Control: private, no-store\n  Cache-Control: public\n  X-Robots-Tag: noindex\n",
    "/control/*\n  Cache-Control: private, no-store\n  X-Robots-Tag: noindex, index\n",
    "/control/private-token\n  Cache-Control: private, no-store\n  X-Robots-Tag: noindex\n",
    "/control/*\n  Cache-Control: private, no-store\n  X-Robots-Tag: noindex\n  X-Reviewer: private-person\n",
    "/control/*\n  Cache-Control: private, no-store\n  X-Robots-Tag: noindex\n  Report-To: https://localhost/private\n",
    "# See /control/private-token\n/control/*\n  Cache-Control: private, no-store\n  X-Robots-Tag: noindex\n",
])
def test_header_roles_require_guards_and_never_hide_comments_or_values(tmp_path: Path, body: str) -> None:
    path = tmp_path / "_headers"
    path.write_text(body, encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/_headers")


@pytest.mark.parametrize("url", [
    "https://0177.0.0.1/report",
    "https://127.0.0.001/report",
    "https://0x7f.0.0.1/report",
    "https://192.168.000.001/report",
    "https://１２７.０.０.１/report",
    "https://０ｘ７ｆ.０.０.１/report",
    "https://example.org/report?redirect=https://10.0.0.1/private",
    "https://example.org/report?redirect=https%3A%2F%2Freview.internal%2Fprivate",
    "https://example.org/report?redirect=https%253A%252F%252F10.0.0.1%252Fprivate",
    "https://example.org/report?path=/home/private-sentinel/review.json",
    "https://example.org/report?path=%252Fhome%252Fprivate-sentinel%252Freview.json",
    "https://example.org/report#path=%2Fhome%2Fprivate-sentinel%2Freview.json",
])
def test_peer_ipv4_and_nested_locator_counterexamples_are_rejected(url: str) -> None:
    assert not BOUNDARY.public_source_url_is_safe(url)
    failures = BOUNDARY.scan_api_value({"arbitrary": [{"citation": url}]}, "fixture.json")
    assert failures
    assert all(url not in failure and "private-sentinel" not in failure for failure in failures)


@pytest.mark.parametrize("url", [
    "https://example.org/caf%C3%A9%20report#page=12",
    "https://example.org/docs/home/internal/report.pdf",
    "https://github.com/example/public-project/tree/main/.github/workflows",
    "https://8.8.8.8/report",
    "https://[2606:4700:4700::1111]/report",
    "https://пример.рф/документ",
    "https://example.org/report?redirect=https%3A%2F%2Fexample.net%2Fhome%2Fdocs%2Finternal",
    "https://example.org/report?redirect=https%3A%2F%2Fexample.net%2Fcaf%25C3%25A9%2520report.pdf",
    "https://example.org/report?path=docs%2Fhome%2Finternal%2Freport.pdf",
])
def test_peer_url_positive_controls_keep_exact_public_evidence(url: str) -> None:
    row = {"url": url, "source_type": "docs", "retrieved_at": "2026-10-02"}
    before = copy.deepcopy(row)
    assert BOUNDARY.public_source_url_is_safe(url)
    assert BOUNDARY.scan_api_value({"sources": [row]}, "fixture.json") == []
    assert row == before


@pytest.mark.parametrize("body", [
    "openapi: 3.1.0\ninfo: {reviewer: private-person}\npaths: {}\n",
    "openapi: 3.1.0\ncomponents:\n  schemas:\n    Fixture:\n      example: {collected_by: private-person}\n",
    "openapi: 3.1.0\ninfo: {nested: [{reviewerIdentity: private-person}]}\n",
    "openapi: 3.1.0\ninfo: {nested: {\"review%5Fnotes\": private-person}}\n",
    "{openapi: 3.1.0, info: {reviewer: private-person}, paths: {}}\n",
    "openapi: 3.1.0\ninfo: {title: public, title: duplicate}\n",
    "openapi: 3.1.0\ninfo: {nested: !unsafe private-person}\n",
    "openapi: 3.1.0\ninfo: {nested: *private_alias}\n",
    "openapi: 3.1.0\ninfo: {nested: .nan}\n",
    "openapi: 3.1.0\ninfo: &private_context {reviewer: private-person}\n",
    "!unsafe {openapi: 3.1.0, info: {reviewer: private-person}}\n",
])
def test_inline_yaml_flow_mappings_cannot_hide_private_fields(tmp_path: Path, body: str) -> None:
    path = tmp_path / "openapi.yaml"
    path.write_text(body, encoding="utf-8")
    failures = BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml")
    assert failures
    assert all("private-person" not in failure for failure in failures)


@pytest.mark.parametrize("body", [
    "openapi: 3.1.0\ninfo: {title: 'Public café & docs', version: 'v1.7.0'}\npaths: {}\n",
    "openapi: 3.1.0\ncomponents: {schemas: {Fixture: {type: object, properties: {collected_by: {type: string}}}}}\n",
    "openapi: 3.1.0\ncomponents:\n  schemas:\n    Fixture:\n      properties: {collected_by: {type: string}}\n",
    "openapi: 3.1.0\ninfo: {title: 'Public café',\n  description: 'Quoted example: public text',\n  version: 'v1.7.0'}\npaths: {}\n",
])
def test_bounded_yaml_flow_parser_preserves_public_metadata_and_definitions(tmp_path: Path, body: str) -> None:
    path = tmp_path / "openapi.yaml"
    path.write_text(body, encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml") == []


def test_yaml_flow_parser_fails_closed_at_bounds_and_bad_suffixes(tmp_path: Path) -> None:
    for body in ("openapi: 3.1.0\ninfo: {title: 'public'} unexpected\n", "openapi: 3.1.0\ninfo: " + "{item: " * 40 + "public" + "}" * 40):
        path = tmp_path / "openapi.yaml"
        path.write_text(body, encoding="utf-8")
        assert BOUNDARY._scan_text_file(path, "data/api/v1.7.0/openapi.yaml")


@pytest.mark.parametrize("mime", ["application/JSON", "APPLICATION/LD+JSON", "application/json; charset=utf-8", "Application/Json ; charset=UTF-8"])
def test_json_script_mime_essence_cannot_bypass_structured_claim_checks(tmp_path: Path, mime: str) -> None:
    row = factor()
    row["sources"] = []
    path = tmp_path / "fixture.html"
    path.write_text(f'<script type="{mime}">' + json.dumps(row) + "</script>", encoding="utf-8")
    failures = BOUNDARY._scan_text_file(path, "site/dist/fixture.html")
    assert any("requires a public citation" in failure for failure in failures)
    row["sources"] = factor()["sources"]
    path.write_text(f'<script type="{mime}">' + json.dumps(row) + "</script>", encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/fixture.html") == []


@pytest.mark.parametrize("branch", ["example", "examples", "default"])
def test_schema_property_exemption_cannot_be_obtained_inside_actual_data(branch: str) -> None:
    instance = {"properties": {"reviewer": {"type": "string", "default": "private-person"}}}
    value = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", branch: [instance] if branch == "examples" else instance}
    failures = BOUNDARY.scan_api_value(value, "data/api/v1.7.0/schema/envelope.json")
    assert failures and all("private-person" not in failure for failure in failures)


def test_bound_curator_override_matches_full_tree_and_never_falls_back(tmp_path: Path) -> None:
    source = tmp_path / "source"
    api = source_tree(source)
    dist = output_tree(source, api)
    default = source / "data/curator/v1.7.0"
    write_json(default / "fixture.json", {"public": "different default"})
    frozen = tmp_path / "frozen-curator"
    write_json(frozen / "v1.7.0/fixture.json", {"public": "frozen input"})
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    inputs.update({f"data/curator/{path}": digest for path, digest in BOUNDARY.hash_public_tree(frozen).items()})
    receipt = BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs, source_root=source, curator_root=frozen)
    assert set(receipt) == {"schema", "build_inputs", "api_files", "output_files"}
    assert BOUNDARY.validate_output_tree(source, dist, api_root=api, curator_root=frozen, build_receipt=receipt) == []
    assert BOUNDARY.validate_output_tree(source, dist, api_root=api, curator_root=tmp_path / "missing-override", build_receipt=receipt)
    assert BOUNDARY.validate_output_tree(source, dist, api_root=api, build_receipt=receipt)
    write_json(frozen / "v1.5.0/addition.json", {"public": "unbound addition"})
    assert any("curator input state differs" in failure for failure in BOUNDARY.validate_output_tree(source, dist, curator_root=frozen, build_receipt=receipt))


def test_curator_absence_is_bound_to_a_real_empty_override_and_reparse_is_rejected(tmp_path: Path, monkeypatch) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    frozen = tmp_path / "empty-frozen-curator"
    frozen.mkdir()
    receipt = BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs, curator_root=frozen)
    assert BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=receipt, curator_root=frozen) == []
    write_json(frozen / "v1.7.0/addition.json", {"public": "unbound addition"})
    assert BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=receipt, curator_root=frozen)
    original = BOUNDARY._is_link
    monkeypatch.setattr(BOUNDARY, "_is_link", lambda path: path == frozen or original(path))
    assert any("unsafe bound curator" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist, curator_root=frozen))


@pytest.mark.parametrize("text", [
    "See docs/review.md for the claim.",
    "The working locator is scripts/internal.py for this factor.",
    "See data/api/v1.7.0/index.json for the claim.",
    "Evidence resides in db/factor-cache.sql.",
])
def test_narrative_repository_locators_are_detected(text: str) -> None:
    failures = BOUNDARY.scan_api_value({"evidence_summary": text}, "fixture.json")
    assert failures and all(text not in failure for failure in failures)


@pytest.mark.parametrize("text", [
    "Public documentation: https://example.org/docs/home/internal/report.pdf",
    "Public script: https://github.com/example/project/blob/main/scripts/review.py",
    "Public data: https://example.org/data/api/v1.7.0/index.json",
])
def test_public_uri_path_words_do_not_become_narrative_locator_false_positives(text: str) -> None:
    assert BOUNDARY.scan_api_value({"evidence_summary": text}, "fixture.json") == []


@pytest.mark.parametrize("body", [
    'const p={["reviewer"]:"Private Name"};',
    'const p={["review"+"er"]:"Private Name"};',
    r'const p={["review\u0065r"]:"Private Name"};',
    'const p={source_type:"local_reference"};',
    'const p={["source_"+"type"]:"local_"+"reference"};',
    'p["review"+"er"]="Private Name";',
    'const p={approved_by:"Private Name", approval_metadata:state, researcher_id:id};',
    'const p={reviewerIdentity:"Private Name"};',
])
def test_static_javascript_computed_keys_and_source_types_are_private_fields(tmp_path: Path, body: str) -> None:
    path = tmp_path / "bundle.js"
    path.write_text(body, encoding="utf-8")
    failures = BOUNDARY._scan_text_file(path, "site/dist/bundle.js")
    assert failures
    assert all("Private Name" not in failure for failure in failures)


@pytest.mark.parametrize("body", [
    'const text="reviewer: public type definition";',
    '// const p={["reviewer"]:"public example"};\nconst p={status:"live"};',
    'type PublicSnapshot = { reviewer: string; collected_by?: string };',
    'interface PublicSnapshot { reviewer: string; collected_by?: string }',
    'const p={["pub"+"lic"]:"café", source_type:"docs", url:"https://example.org/a%20report.pdf"};',
    'const p={authorization_required:true,state_tokens:4};',
])
def test_javascript_code_strings_types_and_public_keys_are_not_private_records(tmp_path: Path, body: str) -> None:
    path = tmp_path / "bundle.js"
    path.write_text(body, encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/bundle.js") == []


@pytest.mark.parametrize("mime", ["", "module", "text/ecmascript", "application/x-javascript", "text/javascript1.5", "TEXT/ECMASCRIPT; charset=UTF-8", "Application/X-JavaScript ; charset=utf-8"])
def test_browser_javascript_mime_essences_use_the_same_static_field_checks(tmp_path: Path, mime: str) -> None:
    path = tmp_path / "fixture.html"
    attribute = f' type="{mime}"' if mime else ""
    path.write_text(f'<script{attribute}>const p={{["review"+"er"]:"Private Name"}};</script>', encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/fixture.html")


def test_source_map_actual_source_code_keeps_static_field_checks(tmp_path: Path) -> None:
    path = tmp_path / "bundle.js.map"
    write_json(path, {"version": 3, "sources": ["../src/PublicView.tsx"], "sourcesContent": ['const p={["reviewer"]:"Private Name"};'], "mappings": ""})
    assert BOUNDARY._scan_text_file(path, "site/dist/bundle.js.map")


def test_registered_manifest_paths_are_exact_documentary_records_not_prose_exemptions(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    path = api / "MANIFEST.sha256"
    assert BOUNDARY._scan_text_file(path, "site/dist/api/MANIFEST.sha256") == []
    assert BOUNDARY._scan_text_file(path, "site/dist/other/MANIFEST.sha256")
    dist = output_tree(tmp_path, api)
    assert BOUNDARY.validate_output_tree(tmp_path, dist) == []
    old = path.read_text(encoding="utf-8")
    for invalid in (
        "See data/api/v1.7.0/index.json for the claim.\n",
        "0" * 64 + "  data/api/../private.json\n",
        "0" * 64 + "  data/api/v1.7.0/extra-assessment.json\n",
        old + old.splitlines()[0] + "\n",
        old + "# source: file:///private/evidence\n",
    ):
        path.write_text(invalid, encoding="utf-8")
        assert BOUNDARY._scan_text_file(path, "site/dist/api/MANIFEST.sha256")


def test_receipt_must_remain_outside_emitted_output_and_api(tmp_path: Path) -> None:
    api = source_tree(tmp_path)
    dist = output_tree(tmp_path, api)
    inputs = {f"data/api/{path}": digest for path, digest in BOUNDARY.hash_public_tree(api).items()}
    receipt = BOUNDARY.create_output_manifest(api, dist, build_inputs=inputs)
    path = dist / "private-receipt.json"
    write_json(path, receipt)
    assert any("unsafe external private build receipt" in failure for failure in BOUNDARY.validate_output_tree(tmp_path, dist, build_receipt=path))


def test_markup_prose_colon_is_not_a_payload_key(tmp_path: Path) -> None:
    path = tmp_path / "factor.html"
    path.write_text('<meta name="description" content="Flash loan targeting protocol tokens: Detect public events."><p>Protocol tokens: public prose.</p>', encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/factor.html") == []
    path.write_text('<script type="application/json">{"tokens":"secret-value"}</script>', encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/factor.html")
    path.write_text('<script>const state={tokens:"secret-value"};</script>', encoding="utf-8")
    assert BOUNDARY._scan_text_file(path, "site/dist/factor.html")
