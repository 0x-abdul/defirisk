import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_site_source_has_no_build_time_random_or_wall_clock_reads() -> None:
    component = (ROOT / "site/src/components/CodeBlock.astro").read_text(
        encoding="utf-8"
    )
    assert "data-target" not in component

    prohibited = ("Math.random(", "Date.now(", "new Date()", "randomUUID(")
    for path in (ROOT / "site/src").rglob("*"):
        if path.is_file() and path.suffix in {".astro", ".js", ".mjs", ".ts", ".tsx"}:
            text = path.read_text(encoding="utf-8")
            for marker in prohibited:
                assert marker not in text, f"{path}: prohibited {marker}"
            if "toLocaleDateString(" in text or "toLocaleString(" in text:
                assert "timeZone: 'UTC'" in text, f"{path}: locale date lacks UTC"


def test_build_metadata_reads_committed_assessment_snapshot() -> None:
    status = json.loads(
        (ROOT / "data/api/v1.7.0/status.json").read_text(encoding="utf-8")
    )
    metadata = (ROOT / "site/src/lib/build-metadata.ts").read_text(encoding="utf-8")
    projection_timestamp = status["data"]["assessment_snapshot"][
        "projection_timestamp"
    ]
    parsed = datetime.fromisoformat(projection_timestamp.replace("Z", "+00:00"))

    assert "status.data.assessment_snapshot.projection_timestamp" in metadata
    assert parsed.tzinfo is not None


def test_documentation_dates_are_explicit_versioned_metadata() -> None:
    metadata = json.loads(
        (ROOT / "site/src/content-metadata.json").read_text(encoding="utf-8")
    )

    assert set(metadata["last_updated"]) == {
        "about",
        "contributions",
        "data",
        "methodology",
    }
    for value in metadata["last_updated"].values():
        assert datetime.fromisoformat(value).date().isoformat() == value


def test_reproducible_ci_builds_under_distinct_timezones() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "TZ: Pacific/Honolulu" in workflow
    assert "TZ: Asia/Tokyo" in workflow
    assert "Compare complete output trees" in workflow


def test_public_build_canonicalizes_path_derived_astro_island_uids() -> None:
    runner = (ROOT / "site/scripts/run-public-build.mjs").read_text(encoding="utf-8")
    canonicalizer = (
        ROOT / "site/scripts/canonicalize-astro-islands.mjs"
    ).read_text(encoding="utf-8")

    assert runner.index("Astro build") < runner.index("Astro island canonicalization")
    assert runner.index("Astro island canonicalization") < runner.index(
        "committed API copy"
    )
    assert "createHash('sha256')" in canonicalizer
    assert "component-url" in canonicalizer
