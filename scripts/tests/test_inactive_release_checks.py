from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_private_controller_checks_are_public_and_database_free() -> None:
    openapi = (ROOT / "scripts/ci/verify-openapi-artifacts.py").read_text(
        encoding="utf-8"
    )
    inactive = (ROOT / "scripts/ci/verify-inactive-site.py").read_text(
        encoding="utf-8"
    )
    combined = openapi + inactive
    assert "DATABASE_URL" not in combined
    assert "dump.py" not in combined
    assert "data/api" in combined
    assert "site/dist" in combined
    assert "generate-openapi-yaml.mjs" in combined
