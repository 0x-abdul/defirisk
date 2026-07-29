import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "ci" / "compare-build-trees.py"
SPEC = importlib.util.spec_from_file_location("compare_build_trees", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
compare = MODULE.compare
hash_tree = MODULE.hash_tree


def write(root: Path, relative: str, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_identical_trees_pass(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write(first, "index.html", b"stable")
    write(second, "index.html", b"stable")

    result = compare(first, second)

    assert result["ok"] is True
    assert result["file_count"] == 1


def test_byte_difference_fails(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write(first, "index.html", b"first")
    write(second, "index.html", b"second")

    result = compare(first, second)

    assert result["ok"] is False
    assert result["changed"] == ["index.html"]


def test_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("content", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(ValueError, match="symlink"):
        hash_tree(root)
