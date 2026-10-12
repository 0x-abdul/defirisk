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


def frozen_worktree(root):
    import subprocess
    from test_public_boundary_architecture import BOUNDARY as immutable
    api = source_tree(root)
    write_json(root / immutable.V1_API_PRESERVATION_RELATIVE, {
        'schema': immutable.V1_API_PRESERVATION_SCHEMA,
        'hashing': immutable.V1_API_PRESERVATION_HASHING,
        'versions': {v: immutable.api_version_digest(api / v)
                     for v in immutable.V1_API_PRESERVATION_VERSIONS},
    })
    (root / '.gitignore').write_text('node_modules/\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
    subprocess.run(['git', 'add', '.gitignore'], cwd=root, check=True, capture_output=True)
    return api


def test_frozen_source_prunes_ignored_runtime_before_recursion(tmp_path):
    frozen_worktree(tmp_path)
    runtime = tmp_path / 'site/node_modules/package/node_modules/.bin'
    runtime.mkdir(parents=True)
    (runtime / 'tool').write_text('runtime shim', encoding='utf-8')
    assert not any('node_modules' in p.parts for p in BOUNDARY._iter_tree(tmp_path, worktree=True))
    assert BOUNDARY.validate_tree(tmp_path) == []


@pytest.mark.parametrize('relative', ['site/node_modules/.bin/tool', 'site/node_modules/dep/node_modules/.bin/tool'])
def test_frozen_source_ignores_installed_dependency_links_but_output_rejects_them(tmp_path, relative):
    from test_public_output_boundary import output_tree
    root = tmp_path / 'source'
    api = frozen_worktree(root)
    link = root / relative
    link.parent.mkdir(parents=True)
    target = link.parent.parent / 'tool.mjs'
    target.write_text('export default 1;', encoding='utf-8')
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation is unavailable for this Windows principal')
    assert BOUNDARY.validate_tree(root) == []
    dist = output_tree(root, api)
    output_link = dist / 'node_modules/.bin/tool'
    output_link.parent.mkdir(parents=True)
    output_link.symlink_to(target)
    failures = BOUNDARY.validate_output_tree(root, dist)
    assert any('symlinks or junctions' in failure for failure in failures)
    assert all(str(target) not in failure for failure in failures)


@pytest.mark.parametrize('relative,expected', [
    ('receipts/private.txt', 'private path is prohibited'),
    ('site/node_modules/.bin/tool', 'private or workspace-only artifact path'),
])
def test_frozen_source_keeps_non_runtime_guards_and_tracked_runtime_guard(tmp_path, relative, expected):
    import subprocess
    frozen_worktree(tmp_path)
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text('fixture', encoding='utf-8')
    if 'node_modules' in target.parts:
        subprocess.run(['git', 'add', '-f', relative], cwd=tmp_path, check=True, capture_output=True)
    assert any(expected in failure for failure in BOUNDARY.validate_tree(tmp_path))
