"""Candidate lifecycle checks remain separate from immutable v1 preservation."""
from pathlib import Path
import shutil

import pytest
from test_public_output_boundary import BOUNDARY, source_tree, write_json


def retired_candidate(root):
    api = source_tree(root)
    baseline = BOUNDARY.load_json(api / 'publication-baseline.json')
    baseline['retired_api_versions'] = ['v1.5.0', 'v1.6.0']
    write_json(api / 'publication-baseline.json', baseline)
    registry = BOUNDARY.load_json(api / 'public-field-classification.json')
    registry['version_lifecycle'] = BOUNDARY.RETIREMENT_FIELD_CLASSIFICATION
    write_json(api / 'public-field-classification.json', registry)
    for version in baseline['retired_api_versions']:
        shutil.rmtree(api / version)
    (api / 'MANIFEST.sha256').write_text(BOUNDARY.file_manifest(root), encoding='utf-8')
    return api


def test_candidate_retirement_omits_trees_and_keeps_strict_manifest(tmp_path):
    api = retired_candidate(tmp_path)
    assert BOUNDARY.validate_api_tree(api) == []
    (api / 'v1.7.0/index.json').write_text('{}', encoding='utf-8')
    assert BOUNDARY.validate_api_tree(api)


def test_retired_artifact_cannot_be_served(tmp_path):
    api = retired_candidate(tmp_path)
    (api / 'v1.6.0').mkdir()
    failures = BOUNDARY.validate_api_tree(api)
    assert any('retired_api_version_artifacts_present' in failure for failure in failures)


@pytest.mark.parametrize('value', [None, 'v1.5.0', ['v1.7.0'], ['v1.6.0', 'v1.5.0'], ['v1.5.0', 'v1.5.0']])
def test_retirement_metadata_is_not_inferred_or_coerced(value):
    with pytest.raises(BOUNDARY.BoundaryError):
        BOUNDARY.validate_retired_api_versions({'current_api_version':'v1.7.0', 'retired_api_versions':value})


def test_frozen_metadata_without_retirement_retains_versions():
    assert BOUNDARY.validate_retired_api_versions({'current_api_version':'v1.7.0'}) == ()


def test_distinct_candidate_never_uses_frozen_selection(tmp_path):
    from test_public_boundary_architecture import BOUNDARY as immutable
    source = tmp_path / 'source'
    source_tree(source)
    write_json(source / immutable.V1_API_PRESERVATION_RELATIVE, {
        'schema': immutable.V1_API_PRESERVATION_SCHEMA,
        'hashing': immutable.V1_API_PRESERVATION_HASHING,
        'versions': {v: immutable.api_version_digest(source / 'data/api' / v)
                     for v in immutable.V1_API_PRESERVATION_VERSIONS},
    })
    api = retired_candidate(tmp_path / 'candidate')
    assert BOUNDARY.validate_selected_api(source, api) == []
    # The selected candidate passes, but cannot hide source freeze corruption.
    target = source / 'data/api/v1.6.0/index.json'
    target.write_text('{}', encoding='utf-8')
    assert immutable.validate_v1_api_preservation(source)
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(Path(BOUNDARY.__file__)),
                             '--root', str(source), '--api-root', str(api)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert 'data/api/v1.6.0: byte_count mismatch' in result.stdout


def test_exact_frozen_selection_retains_main_checks(tmp_path):
    from test_public_boundary_architecture import BOUNDARY as immutable
    source_tree(tmp_path)
    write_json(tmp_path / immutable.V1_API_PRESERVATION_RELATIVE, {
        'schema': immutable.V1_API_PRESERVATION_SCHEMA,
        'hashing': immutable.V1_API_PRESERVATION_HASHING,
        'versions': {v: immutable.api_version_digest(tmp_path / 'data/api' / v)
                     for v in immutable.V1_API_PRESERVATION_VERSIONS},
    })
    assert BOUNDARY.validate_selected_api(tmp_path, tmp_path / 'data/api') == immutable.validate_tree(tmp_path)
    (tmp_path / 'data/api/v1.6.0/index.json').write_text('{}', encoding='utf-8')
    assert BOUNDARY.validate_selected_api(tmp_path, tmp_path / 'data/api')
