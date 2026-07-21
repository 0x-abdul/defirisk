from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "ci" / "validate-staged-published-api.py"
STATE_PATH = ROOT / "scripts" / "ci" / "verify-deployment-publication-state.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validator = load_module("staged_api_validator", VALIDATOR_PATH)
state = load_module("publication_state_verifier", STATE_PATH)


EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def policy(count: int = 0, digest: str = EMPTY_DIGEST) -> dict[str, object]:
    return {
        "rubric_version": "v1.7.0",
        "published_protocols": {"count": count, "slug_sha256": digest},
        "database": {
            "protocol_count": 98,
            "published_protocol_count": 0,
            "unpublished_protocol_count": 98,
            "family_count": 98,
            "published_family_count": 0,
            "publication_parity_mismatches": 0,
        },
    }


def canonical_empty_index() -> dict[str, object]:
    return {
        "rubric_version": "v1.7.0",
        "data_as_of": "2026-07-20",
        "generated_at": "2026-07-20T00:00:00Z",
        "data": {"protocols": []},
    }


def test_approved_empty_roster_passes(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1.7.0"
    policy_path = tmp_path / "policy.json"
    write_json(api / "index.json", canonical_empty_index())
    write_json(policy_path, policy())

    validator.validate(api, policy_path)


def test_unexpected_empty_roster_fails_for_nonempty_policy(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1.7.0"
    policy_path = tmp_path / "policy.json"
    write_json(api / "index.json", canonical_empty_index())
    write_json(policy_path, policy(count=1, digest=validator.published_slug_digest(["axelar"])))

    with pytest.raises(validator.ValidationError, match="count"):
        validator.validate(api, policy_path)


def test_malformed_canonical_envelope_fails(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1.7.0"
    policy_path = tmp_path / "policy.json"
    malformed = canonical_empty_index()
    del malformed["data_as_of"]
    write_json(api / "index.json", malformed)
    write_json(policy_path, policy())

    with pytest.raises(validator.ValidationError, match="data_as_of"):
        validator.validate(api, policy_path)


def test_empty_roster_rejects_stray_published_detail_file(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1.7.0"
    policy_path = tmp_path / "policy.json"
    write_json(api / "index.json", canonical_empty_index())
    write_json(api / "protocols" / "axelar.json", canonical_empty_index())
    write_json(policy_path, policy())

    with pytest.raises(validator.ValidationError, match="absent or empty"):
        validator.validate(api, policy_path)


def test_empty_roster_rejects_nested_non_json_artifact(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1.7.0"
    policy_path = tmp_path / "policy.json"
    write_json(api / "index.json", canonical_empty_index())
    (api / "protocols" / "nested").mkdir(parents=True)
    (api / "protocols" / "nested" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    write_json(policy_path, policy())

    with pytest.raises(validator.ValidationError, match="absent or empty"):
        validator.validate(api, policy_path)


def test_nonempty_roster_requires_complete_detail_envelope_and_exact_artifacts(tmp_path: Path) -> None:
    api = tmp_path / "api" / "v1.7.0"
    policy_path = tmp_path / "policy.json"
    index = canonical_empty_index()
    index["data"] = {"protocols": [{"slug": "axelar"}]}
    write_json(api / "index.json", index)
    incomplete_detail = canonical_empty_index()
    del incomplete_detail["generated_at"]
    write_json(api / "protocols" / "axelar.json", incomplete_detail)
    write_json(policy_path, policy(count=1, digest=validator.published_slug_digest(["axelar"])))

    with pytest.raises(validator.ValidationError, match="generated_at"):
        validator.validate(api, policy_path)

    write_json(api / "protocols" / "axelar.json", canonical_empty_index())
    (api / "protocols" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(validator.ValidationError, match="detail files"):
        validator.validate(api, policy_path)


def test_publication_state_verifier_is_select_only(monkeypatch: pytest.MonkeyPatch) -> None:
    queries: list[str] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query: str) -> None:
            queries.append(query)

        def fetchone(self):
            return (98, 0, 98, 98, 0, 0)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _url: Connection()))
    assert state.inspect_database("postgresql://example") == (98, 0, 98, 98, 0, 0)
    assert queries and all(query.lstrip().upper().startswith("SELECT") for query in queries)


def test_dump_and_database_counts_must_match_policy() -> None:
    parsed_policy = state.load_policy(ROOT / "scripts" / "ci" / "deploy-publication-policy.json")
    state.verify(parsed_policy, (0, 98, 98), (98, 0, 98, 98, 0, 0))
    with pytest.raises(state.PublicationStateError, match="dump publication summary"):
        state.verify(parsed_policy, (1, 97, 98), (98, 0, 98, 98, 0, 0))
