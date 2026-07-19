from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol_refresh_public.contracts import (
    ContractError,
    build_public_handoff,
    canonical_sha256,
    canonical_surface_fingerprint,
    load_json_strict,
    verify_public_handoff,
)
from protocol_refresh_public.compensation import (
    build_compensation_proof,
    verify_compensation_proof,
)
from protocol_refresh_public.publication import validate_publication_metadata
from protocol_refresh_public.sanitizer import find_private_material


def _load_exporter():
    script = Path(__file__).resolve().parents[1] / "export-protocol-refresh.py"
    spec = importlib.util.spec_from_file_location("refresh_exporter", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accepted_changes(*, changed: bool = True) -> dict:
    factor_scores = []
    if changed:
        factor_scores = [
            {
                "factor_id": "RD-F-001",
                "scope_level": "surface",
                "surface_slug": "v3",
                "chain": None,
                "deployment_key": None,
                "expected_current_sha256": None,
                "score": "green",
                "evidence_summary": "Current public audit evidence.",
                "collection_mode": "manual",
                "sources": [
                    {
                        "source_type": "audit_report",
                        "reference": "https://example.com/audit.pdf",
                    }
                ],
            }
        ]
    return {
        "schema_version": "1.0",
        "batch_id": "batch-2026-07-11",
        "refresh_id": "refresh-2026-07-11",
        "family_slug": "fixture-family",
        "protocol_slug": "fixture-family",
        "surface_slugs": ["v2", "v3"],
        "refresh_type": "targeted_surface_update",
        "rubric_version": "v1.7.0",
        "effective_refresh_date": "2026-07-11",
        "topology_contract": {
            "mode": "preserve_canonical",
            "canonical_surface_slugs": ["v2", "v3"],
            "canonical_surface_fingerprint": canonical_surface_fingerprint(
                "fixture-family", ["v2", "v3"]
            ),
            "operator_approval_artifact_sha256": None,
        },
        "scope": {
            "allowed_surfaces": ["v2", "v3"],
            "allowed_factor_ids": ["RD-F-001"],
            "allowed_protocol_fields": [],
            "allowed_family_fields": [],
            "allowed_surface_fields": [],
            "allowed_deployment_fields": [],
        },
        "baseline": {
            "target_sha256": "1" * 64,
            "other_protocols_sha256": "2" * 64,
        },
        "expected_result": {
            "headline_grade": "B", "risk_score": "17.41", "cap_state": "none",
            "active_factor_count": 1,
            "surface_results": {
                "v2": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none"},
                "v3": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none"},
            },
        },
        "changes": {
            "protocol_fields": {},
            "family_fields": {},
            "surfaces": [],
            "deployments": [],
            "factor_scores": factor_scores,
        },
    }


def approved_status(document: dict) -> dict:
    return {
        "schema_version": "1.0",
        "batch_id": document["batch_id"],
        "refresh_id": document["refresh_id"],
        "family_slug": document["family_slug"],
        "protocol_slug": document["protocol_slug"],
        "surface_slugs": document["surface_slugs"],
        "local_state": "local_ready_for_review",
        "local_outcome": "changed" if document["changes"]["factor_scores"] else "no_change",
        "approval_state": "approved",
        "production_state": "not_authorized",
        "production_authorized": False,
        "reviewed_by": "maintainer",
        "reviewed_at": "2026-07-11T12:00:00Z",
        "checksums": {"accepted_changes_sha256": canonical_sha256(document)},
    }


def test_canonical_hash_ignores_formatting_and_key_order(tmp_path) -> None:
    document = accepted_changes()
    reordered = dict(reversed(list(document.items())))

    assert canonical_sha256(document) == canonical_sha256(reordered)

    path = tmp_path / "duplicate.json"
    path.write_text('{"one": 1, "one": 2}', encoding="utf-8")
    with pytest.raises(ContractError, match="duplicate JSON key"):
        load_json_strict(path)


def test_export_requires_exact_approved_checksum_and_scope() -> None:
    document = accepted_changes()
    status = approved_status(document)
    handoff = build_public_handoff(document, status)

    assert handoff["authorization"]["production_authorized"] is False
    assert verify_public_handoff(handoff) == []

    tampered_status = deepcopy(status)
    tampered_status["checksums"]["accepted_changes_sha256"] = "A" * 64
    with pytest.raises(ContractError, match="strict lowercase SHA-256"):
        build_public_handoff(document, tampered_status)

    out_of_scope = deepcopy(document)
    out_of_scope["changes"]["factor_scores"][0]["surface_slug"] = "v4"
    with pytest.raises(ContractError, match="out-of-scope"):
        build_public_handoff(out_of_scope, approved_status(out_of_scope))


def test_legacy_record_export_derives_checked_expectation_without_rebinding_source(
    tmp_path: Path,
) -> None:
    source = accepted_changes()
    source.pop("expected_result")
    accepted_path = tmp_path / "accepted-changes.json"
    status_path = tmp_path / "status.json"
    output_path = tmp_path / "handoff.json"
    accepted_path.write_text(json.dumps(source), encoding="utf-8")
    status_path.write_text(json.dumps(approved_status(source)), encoding="utf-8")
    (tmp_path / "local-db-after.json").write_text(
        json.dumps(
            {
                "family_slug": "fixture-family",
                "families": [
                    {
                        "family_slug": "fixture-family",
                        "headline_grade": "B",
                        "risk_score": 17.41,
                        "cap_applied": "none",
                    }
                ],
                "surfaces": [
                    {
                        "surface_slug": slug,
                        "headline_grade": "B",
                        "risk_score": 17.41,
                        "cap_applied": "none",
                    }
                    for slug in ("v2", "v3")
                ],
                "current_factor_scores": [
                    {
                        "id": "factor-row-1",
                        "rubric_version": "v1.7.0",
                        "is_current": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    handoff = _load_exporter().export_handoff(accepted_path, status_path, output_path)

    assert handoff["source_approval"]["accepted_changes_sha256"] == canonical_sha256(source)
    assert handoff["payload"]["expected_result"] == {
        "headline_grade": "B",
        "risk_score": "17.41",
        "cap_state": "none",
        "active_factor_count": 1,
        "surface_results": {
            "v2": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none"},
            "v3": {"headline_grade": "B", "risk_score": "17.41", "cap_state": "none"},
        },
    }
    assert verify_public_handoff(handoff) == []

    enriched = accepted_changes()
    mismatched_source = deepcopy(source)
    mismatched_source["family_slug"] = "other-family"
    with pytest.raises(ContractError, match="exactly equal"):
        build_public_handoff(
            enriched,
            approved_status(source),
            source_document=mismatched_source,
        )

    (tmp_path / "local-db-after.json").write_text(
        json.dumps({"family_slug": "other-family"}), encoding="utf-8"
    )
    with pytest.raises(ContractError, match="identity does not match"):
        _load_exporter().export_handoff(accepted_path, status_path, output_path)


def test_compensated_attempt_can_issue_one_fresh_handoff_without_source_drift(
    tmp_path: Path,
) -> None:
    document = accepted_changes()
    status = approved_status(document)
    accepted_path = tmp_path / "accepted-changes.json"
    status_path = tmp_path / "status.json"
    prior_path = tmp_path / "prior.json"
    proof_path = tmp_path / "compensation-proof.json"
    output_path = tmp_path / "reissue.json"
    accepted_path.write_text(json.dumps(document), encoding="utf-8")
    status_path.write_text(json.dumps(status), encoding="utf-8")
    prior = build_public_handoff(document, status)
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    proof = build_compensation_proof(
        prior_refresh_id=document["refresh_id"],
        family_slug=document["family_slug"],
        prior_artifact_sha256=prior["integrity"]["artifact_sha256"],
        restored_target_sha256="3" * 64,
    )
    proof_path.write_text(json.dumps(proof), encoding="utf-8")

    handoff = _load_exporter().export_handoff(
        accepted_path,
        status_path,
        output_path,
        reissue_refresh_id="refresh-2026-07-11.reissue-01",
        prior_handoff_path=prior_path,
        compensation_proof_path=proof_path,
    )

    assert handoff["schema_version"] == "1.2"
    assert verify_public_handoff(handoff) == []
    assert handoff["payload"] == {**document, "refresh_id": "refresh-2026-07-11.reissue-01"}
    assert handoff["source_approval"]["reissue"] == {
        "reason": "compensated_production_attempt",
        "prior_refresh_id": document["refresh_id"],
        "prior_artifact_sha256": prior["integrity"]["artifact_sha256"],
        "compensation_proof_sha256": proof["integrity"]["proof_sha256"],
    }


def test_reissue_rejects_mismatched_or_unproved_compensation_evidence(tmp_path: Path) -> None:
    document = accepted_changes()
    status = approved_status(document)
    accepted_path = tmp_path / "accepted-changes.json"
    status_path = tmp_path / "status.json"
    prior_path = tmp_path / "prior.json"
    proof_path = tmp_path / "compensation-proof.json"
    accepted_path.write_text(json.dumps(document), encoding="utf-8")
    status_path.write_text(json.dumps(status), encoding="utf-8")
    prior = build_public_handoff(document, status)
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    proof = build_compensation_proof(
        prior_refresh_id=document["refresh_id"],
        family_slug="other-family",
        prior_artifact_sha256=prior["integrity"]["artifact_sha256"],
        restored_target_sha256="3" * 64,
    )
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    with pytest.raises(ContractError, match="family_slug"):
        _load_exporter().export_handoff(
            accepted_path,
            status_path,
            tmp_path / "reissue.json",
            reissue_refresh_id="refresh-2026-07-11.reissue-01",
            prior_handoff_path=prior_path,
            compensation_proof_path=proof_path,
        )

    proof["outcome"] = "failed"
    with pytest.raises(ContractError, match="outcome"):
        verify_compensation_proof(proof)


def test_compensated_reissue_can_chain_without_payload_drift(tmp_path: Path) -> None:
    document = accepted_changes()
    status = approved_status(document)
    accepted_path = tmp_path / "accepted-changes.json"
    status_path = tmp_path / "status.json"
    original_path = tmp_path / "original.json"
    first_proof_path = tmp_path / "first-proof.json"
    first_path = tmp_path / "first.json"
    second_proof_path = tmp_path / "second-proof.json"
    second_path = tmp_path / "second.json"
    accepted_path.write_text(json.dumps(document), encoding="utf-8")
    status_path.write_text(json.dumps(status), encoding="utf-8")
    original = build_public_handoff(document, status)
    original_path.write_text(json.dumps(original), encoding="utf-8")
    first_proof = build_compensation_proof(
        prior_refresh_id=original["refresh_id"],
        family_slug=original["family_slug"],
        prior_artifact_sha256=original["integrity"]["artifact_sha256"],
        restored_target_sha256="3" * 64,
    )
    first_proof_path.write_text(json.dumps(first_proof), encoding="utf-8")
    first = _load_exporter().export_handoff(
        accepted_path,
        status_path,
        first_path,
        reissue_refresh_id="refresh-2026-07-11.reissue-01",
        prior_handoff_path=original_path,
        compensation_proof_path=first_proof_path,
    )
    second_proof = build_compensation_proof(
        prior_refresh_id=first["refresh_id"],
        family_slug=first["family_slug"],
        prior_artifact_sha256=first["integrity"]["artifact_sha256"],
        restored_target_sha256="3" * 64,
    )
    second_proof_path.write_text(json.dumps(second_proof), encoding="utf-8")
    second = _load_exporter().export_handoff(
        accepted_path,
        status_path,
        second_path,
        reissue_refresh_id="refresh-2026-07-11.reissue-02",
        prior_handoff_path=first_path,
        compensation_proof_path=second_proof_path,
    )

    assert verify_public_handoff(second) == []
    assert second["source_approval"]["reissue"]["prior_refresh_id"] == first["refresh_id"]
    assert second["payload"] == {**document, "refresh_id": "refresh-2026-07-11.reissue-02"}


def test_export_strips_known_internal_actor_and_note_fields() -> None:
    document = accepted_changes()
    factor = document["changes"]["factor_scores"][0]
    factor["collected_by"] = "internal-researcher"
    factor["sources"][0]["retrieved_by"] = "internal-researcher"
    factor["sources"][0]["notes"] = r"Working copy at C:\Users\person\notes.md"

    handoff = build_public_handoff(document, approved_status(document))
    public_factor = handoff["payload"]["changes"]["factor_scores"][0]
    public_source = public_factor["sources"][0]

    assert "collected_by" not in public_factor
    assert "retrieved_by" not in public_source
    assert "notes" not in public_source
    assert handoff["payload"]["baseline"] == document["baseline"]
    assert handoff["source_approval"]["accepted_changes_sha256"] == canonical_sha256(document)
    assert handoff["integrity"]["payload_sha256"] == canonical_sha256(handoff["payload"])
    assert handoff["source_approval"]["accepted_changes_sha256"] != handoff["integrity"]["payload_sha256"]


def test_standalone_verify_rejects_reintroduced_internal_field_when_rechecksummed() -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    handoff["payload"]["changes"]["factor_scores"][0]["collected_by"] = "someone"
    handoff["integrity"]["payload_sha256"] = canonical_sha256(handoff["payload"])
    unsigned = deepcopy(handoff)
    unsigned["integrity"].pop("artifact_sha256")
    handoff["integrity"]["artifact_sha256"] = canonical_sha256(unsigned)

    errors = verify_public_handoff(handoff)
    assert any("sanitized public shape" in error for error in errors)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("factor", "sql", "UPDATE protocols SET status = 'live'"),
        ("factor", "command", "python scripts/dump.py"),
        ("source", "payload", {"operation": "apply"}),
    ],
)
def test_allowlist_rejects_command_and_unknown_payload_fields(target, field, value) -> None:
    document = accepted_changes()
    factor = document["changes"]["factor_scores"][0]
    destination = factor if target == "factor" else factor["sources"][0]
    destination[field] = value

    with pytest.raises(ContractError, match="unsupported fields"):
        build_public_handoff(document, approved_status(document))


def test_allowlist_accepts_public_safe_curator_source_and_rejects_secret_material() -> None:
    curator = accepted_changes()
    curator["changes"]["factor_scores"][0]["score"] = "gray"
    curator["changes"]["factor_scores"][0]["sources"][0]["source_type"] = "curator_note"
    handoff = build_public_handoff(curator, approved_status(curator))
    assert handoff["payload"]["changes"]["factor_scores"][0]["sources"][0][
        "source_type"
    ] == "curator_note"

    public_channel_check = accepted_changes()
    public_factor = public_channel_check["changes"]["factor_scores"][0]
    public_factor["score"] = "gray"
    public_factor["sources"] = [
        {
            "source_type": "curator_note",
            "url": "https://example.com/community",
            "reference": "Searched public Discord admin and channel records.",
        }
    ]
    build_public_handoff(public_channel_check, approved_status(public_channel_check))

    secret = accepted_changes()
    secret["changes"]["factor_scores"][0]["evidence_summary"] = (
        "-----BEGIN PRIVATE KEY-----"
    )
    with pytest.raises(ContractError, match="secret-like material"):
        build_public_handoff(secret, approved_status(secret))

    private_note = accepted_changes()
    private_factor = private_note["changes"]["factor_scores"][0]
    private_factor["score"] = "gray"
    private_factor["sources"] = [
        {
            "source_type": "curator_note",
            "reference": "Internal maintainer memo from Slack",
        }
    ]
    with pytest.raises(ContractError, match="curator-only material"):
        build_public_handoff(private_note, approved_status(private_note))


@pytest.mark.parametrize("field", ["is_primary", "legacy_slug"])
def test_public_refresh_rejects_structural_surface_ownership_changes(field: str) -> None:
    document = accepted_changes()
    document["scope"]["allowed_surface_fields"] = [field]
    document["changes"]["surfaces"] = [{"surface_slug": "v3", "fields": {field: True}}]

    with pytest.raises(ContractError, match="unsupported fields"):
        build_public_handoff(document, approved_status(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score", "blue"),
        ("collection_mode", "crawler"),
        ("evidence_summary", ""),
        ("evidence_summary", "   "),
        ("evidence_summary", None),
    ],
)
def test_factor_db_values_fail_closed(field, value) -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0][field] = value

    with pytest.raises(ContractError, match=field):
        build_public_handoff(document, approved_status(document))


@pytest.mark.parametrize("source_type", ["pdf", "internal"])
def test_source_type_must_match_public_db_enum(source_type: str) -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["sources"][0]["source_type"] = source_type

    with pytest.raises(ContractError, match="source_type"):
        build_public_handoff(document, approved_status(document))


def test_standalone_verify_rejects_rechecksummed_invalid_source_type() -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    source = handoff["payload"]["changes"]["factor_scores"][0]["sources"][0]
    source["source_type"] = "invalid-db-enum"
    handoff["integrity"]["payload_sha256"] = canonical_sha256(handoff["payload"])
    unsigned = deepcopy(handoff)
    unsigned["integrity"].pop("artifact_sha256")
    handoff["integrity"]["artifact_sha256"] = canonical_sha256(unsigned)

    errors = verify_public_handoff(handoff)
    assert any("source_type" in error for error in errors)


@pytest.mark.parametrize("reference", ["", "   ", None])
def test_source_reference_must_be_non_empty(reference) -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["sources"][0]["reference"] = reference

    with pytest.raises(ContractError, match="reference"):
        build_public_handoff(document, approved_status(document))


def test_independent_source_type_requires_public_http_locator() -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["sources"] = [
        {"source_type": "docs", "reference": "internal memo"}
    ]

    with pytest.raises(ContractError, match=r"public HTTP\(S\) locator"):
        build_public_handoff(document, approved_status(document))


def test_factor_replacement_requires_at_least_one_source() -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["sources"] = []

    with pytest.raises(ContractError, match="at least one citation"):
        build_public_handoff(document, approved_status(document))


def test_gray_factor_replacement_requires_source_or_public_safe_curator_note() -> None:
    document = accepted_changes()
    factor = document["changes"]["factor_scores"][0]
    factor["score"] = "gray"
    factor["sources"] = []

    with pytest.raises(ContractError, match="at least one citation"):
        build_public_handoff(document, approved_status(document))


@pytest.mark.parametrize("score", ["green", "yellow", "red"])
@pytest.mark.parametrize("source_type", ["curator_note", "partner_feed"])
def test_decisive_scores_reject_conditional_only_sources(score: str, source_type: str) -> None:
    document = accepted_changes()
    factor = document["changes"]["factor_scores"][0]
    factor["score"] = score
    factor["sources"] = [
        {"source_type": source_type, "reference": "Public-safe contextual note"}
    ]

    with pytest.raises(ContractError, match="independently verifiable public source"):
        build_public_handoff(document, approved_status(document))


def test_factor_replacement_accepts_valid_source_citation() -> None:
    document = accepted_changes()
    source = document["changes"]["factor_scores"][0]["sources"][0]
    source.update({"source_type": "docs", "reference": "https://example.com/docs"})

    handoff = build_public_handoff(document, approved_status(document))
    assert handoff["payload"]["changes"]["factor_scores"][0]["sources"] == [source]


@pytest.mark.parametrize("score", ["not_assessed", "not_applicable"])
def test_source_optional_scores_accept_empty_sources(score: str) -> None:
    document = accepted_changes()
    factor = document["changes"]["factor_scores"][0]
    factor["score"] = score
    factor["sources"] = []

    handoff = build_public_handoff(document, approved_status(document))
    assert handoff["payload"]["changes"]["factor_scores"][0]["sources"] == []


def test_topology_attestation_rejects_surface_and_fingerprint_drift() -> None:
    document = accepted_changes()
    document["topology_contract"]["canonical_surface_slugs"] = ["v3"]
    with pytest.raises(ContractError, match="canonical topology"):
        build_public_handoff(document, approved_status(document))

    document = accepted_changes()
    document["topology_contract"]["canonical_surface_fingerprint"] = "0" * 64
    with pytest.raises(ContractError, match="fingerprint"):
        build_public_handoff(document, approved_status(document))


@pytest.mark.parametrize("relation", ["supporting", "secondary", "", None])
def test_source_relation_matches_migration_declared_primary_value(relation) -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["sources"][0]["relation"] = relation

    with pytest.raises(ContractError, match="relation"):
        build_public_handoff(document, approved_status(document))


@pytest.mark.parametrize(
    "score",
    ["green", "yellow", "red", "gray", "not_assessed", "not_applicable"],
)
def test_factor_score_accepts_exact_db_enum(score: str) -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["score"] = score

    assert build_public_handoff(document, approved_status(document))["payload"]


@pytest.mark.parametrize("collection_mode", ["programmatic", "manual", "hybrid"])
def test_collection_mode_accepts_exact_db_enum(collection_mode: str) -> None:
    document = accepted_changes()
    document["changes"]["factor_scores"][0]["collection_mode"] = collection_mode

    assert build_public_handoff(document, approved_status(document))["payload"]


@pytest.mark.parametrize(
    "source_type",
    [
        "url",
        "github",
        "etherscan",
        "transaction",
        "audit_report",
        "governance_post",
        "docs",
        "partner_feed",
        "curator_note",
        "commit_sha",
    ],
)
def test_source_type_accepts_exact_public_db_enum(source_type: str) -> None:
    document = accepted_changes()
    if source_type in {"partner_feed", "curator_note"}:
        document["changes"]["factor_scores"][0]["score"] = "gray"
    source = document["changes"]["factor_scores"][0]["sources"][0]
    source["source_type"] = source_type
    source["relation"] = "primary"

    assert build_public_handoff(document, approved_status(document))["payload"]


@pytest.mark.parametrize(
    "unsafe_value",
    [
        {"review_token": "abcd1234"},
        {"source_type": "curator_note", "reference": "private review evidence"},
        {"reference": r"C:\\Users\\person\\notes.json"},
        {"url": "https://example.com/unpublished/family.json?review_token=abc"},
        {"password": "not-for-public"},
    ],
)
def test_sanitizer_rejects_private_material(unsafe_value) -> None:
    assert find_private_material({"evidence": unsafe_value})


def publication_proposal(handoff: dict) -> dict:
    return {
        "schema_version": "1.0",
        "refresh_id": handoff["refresh_id"],
        "family_slug": handoff["family_slug"],
        "approval_state": "approved",
        "approved_public_payload_sha256": handoff["integrity"]["payload_sha256"],
        "issue": {
            "url": "https://github.com/example/defirisk/issues/42",
            "reference": "example/defirisk#42",
            "title": "Refresh fixture protocol data",
            "body": "Updates current public evidence.",
        },
        "branch_name": "protocol-refresh-fixture",
        "worktree_name": "protocol-refresh-fixture",
        "commit_message": "Refresh fixture protocol data",
        "pull_request": {
            "title": "Refresh fixture protocol data",
            "body": "Links the approved public change record.",
        },
        "comments": ["Output isolation verified."],
    }


def test_changed_publication_requires_issue_approved_checksum_and_neutral_text() -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    proposal = publication_proposal(handoff)

    assert validate_publication_metadata(handoff, proposal) == []

    proposal["approved_public_payload_sha256"] = "0" * 64
    proposal["commit_message"] = "Refresh fixture data, generated by an AI assistant"
    errors = validate_publication_metadata(handoff, proposal)
    assert any("does not match" in error for error in errors)
    assert any("forbidden attribution" in error for error in errors)


@pytest.mark.parametrize(
    "text",
    [
        "AI-generated refresh record",
        "Generated by an assistant",
        "Prepared with Codex",
        "Co-authored-by: Example <example@example.com>",
    ],
)
def test_publication_rejects_explicit_attribution(text: str) -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    proposal = publication_proposal(handoff)
    proposal["commit_message"] = text

    assert any(
        "forbidden attribution" in error
        for error in validate_publication_metadata(handoff, proposal)
    )


@pytest.mark.parametrize(
    "text",
    [
        "Update the protocol data model",
        "Improve migration tooling",
        "Document the risk model and operator tool",
    ],
)
def test_publication_allows_ordinary_model_and_tool_language(text: str) -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    proposal = publication_proposal(handoff)
    proposal["commit_message"] = text

    assert validate_publication_metadata(handoff, proposal) == []


def test_no_change_rejects_issue_and_pr_metadata() -> None:
    document = accepted_changes(changed=False)
    handoff = build_public_handoff(document, approved_status(document))
    proposal = publication_proposal(handoff)

    errors = validate_publication_metadata(handoff, proposal)
    assert any("no-change refresh rejects" in error for error in errors)


def test_handoff_checksum_detects_tampering() -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    handoff["payload"]["rubric_version"] = "v9.9.9"

    errors = verify_public_handoff(handoff)
    assert "handoff payload_sha256 mismatch" in errors
    assert "handoff artifact_sha256 mismatch" in errors


def test_handoff_artifact_hash_covers_source_approval() -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    handoff["source_approval"]["status_sha256"] = "0" * 64

    assert "handoff artifact_sha256 mismatch" in verify_public_handoff(handoff)


def test_recomputed_payload_hash_does_not_hide_stale_artifact_hash() -> None:
    document = accepted_changes()
    handoff = build_public_handoff(document, approved_status(document))
    handoff["payload"]["rubric_version"] = "v9.9.9"
    handoff["integrity"]["payload_sha256"] = canonical_sha256(handoff["payload"])

    errors = verify_public_handoff(handoff)
    assert "handoff payload_sha256 mismatch" not in errors
    assert "handoff artifact_sha256 mismatch" in errors


def test_published_schema_fully_constrains_payload_shape() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "ops"
        / "protocol-refresh"
        / "schemas"
        / "public-handoff.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = schema["$defs"]["payload"]

    assert schema["properties"]["schema_version"] == {"enum": ["1.1", "1.2"]}
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == set(accepted_changes())
    assert set(payload["properties"]) == set(accepted_changes())
    assert schema["$defs"]["changes"]["additionalProperties"] is False
    assert schema["$defs"]["factorScoreChange"]["additionalProperties"] is False
    assert schema["$defs"]["source"]["additionalProperties"] is False


def test_fixture_is_json_serializable() -> None:
    json.dumps(accepted_changes(), allow_nan=False)
