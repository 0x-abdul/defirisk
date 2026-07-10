"""Smoke tests for scripts/merge-grading-fragments.py — used during Tier-1.5
implementation, kept for future regression checks. Run from repo root:
    python scripts/_test_merge_grading_fragments.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows (cp1252 default chokes on arrows / checkmarks).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
SLUG = "test-merge-protocol"
TMP = REPO / ".research" / "protocols" / SLUG


def cleanup():
    if TMP.exists():
        shutil.rmtree(TMP)


def run_merge(*extra_args):
    return subprocess.call(
        [sys.executable, "scripts/merge-grading-fragments.py", SLUG, *extra_args],
        cwd=REPO,
    )


def make_factor(fid, cat, score="green", source_type="docs"):
    return {
        "factor_id": fid,
        "category": cat,
        "score": score,
        "evidence_summary": "test evidence",
        "collection_mode": "manual",
        "sources": [{"source_type": source_type, "reference": "test ref", "url": "https://test"}],
    }


def setup_fragments():
    TMP.mkdir(parents=True, exist_ok=True)

    (TMP / "00-profile.meta.json").write_text(json.dumps({
        "schema_version": "1.0",
        "agent": "protocol-profiler",
        "produced_at": "2026-04-27T10:00:00Z",
        "protocol": {
            "slug": SLUG,
            "display_name": "Test Merge Protocol",
            "protocol_type": "lending",
            "primary_chain": "ethereum",
            "has_bridge_surface": False,
        },
        "deployments": [{"chain": "ethereum", "anchor_address": "0xdead", "display_name": "TMP"}],
    }))

    # Critical factors (excluding cross-chain since has_bridge_surface=False)
    critical_routing = [
        ("RD-F-027", 2, "02-governance-admin"),
        ("RD-F-028", 2, "02-governance-admin"),
        ("RD-F-041", 2, "02-governance-admin"),
        ("RD-F-042", 2, "02-governance-admin"),
        ("RD-F-043", 2, "02-governance-admin"),
        ("RD-F-046", 2, "02-governance-admin"),
        ("RD-F-036", 2, "02-governance-admin"),
        ("RD-F-039", 2, "02-governance-admin"),
        ("RD-F-022", 1, "01-code-security"),
        ("RD-F-001", 1, "01-code-security"),
        ("RD-F-143", 9, "02-governance-admin"),
        ("RD-F-139", 9, "02-governance-admin"),
        ("RD-F-070", 4, "04-economic"),
        ("RD-F-053", 3, "03-oracle-deps"),
        ("RD-F-180", 3, "03-oracle-deps"),
        ("RD-F-124", 7, "07-dev-identity"),
        ("RD-F-125", 7, "07-dev-identity"),
        ("RD-F-123", 7, "07-dev-identity"),
    ]

    fragments = {
        "01-code-security.factors.json":     ("code-security-analyst",     [1, 8, 12]),
        "02-governance-admin.factors.json":  ("governance-admin-analyst",  [2, 9]),
        "03-oracle-deps.factors.json":       ("oracle-dependency-analyst", [3, 10]),
        "04-economic.factors.json":          ("economic-market-analyst",   [4]),
        "05-ops-history.factors.json":       ("ops-history-analyst",       [5, 13]),
        "06-realtime-intel.factors.json":    ("realtime-intel-analyst",    [6, 11]),
        "07-dev-identity.factors.json":      ("dev-identity-analyst",      [7]),
    }
    factors_by = {fn: [] for fn in fragments}
    for fid, cat, basename in critical_routing:
        factors_by[f"{basename}.factors.json"].append(make_factor(fid, cat))

    bonus = {
        "01-code-security.factors.json": ("RD-F-002", 1),
        "02-governance-admin.factors.json": ("RD-F-029", 2),
        "03-oracle-deps.factors.json": ("RD-F-049", 3),
        "04-economic.factors.json": ("RD-F-064", 4),
        "05-ops-history.factors.json": ("RD-F-076", 5),
        "06-realtime-intel.factors.json": ("RD-F-090", 6),
        "07-dev-identity.factors.json": ("RD-F-111", 7),
    }
    for fn, (fid, cat) in bonus.items():
        factors_by[fn].append(make_factor(fid, cat, score="yellow", source_type="url"))

    for fname, (agent, cats) in fragments.items():
        (TMP / fname).write_text(json.dumps({
            "schema_version": "1.0",
            "agent": agent,
            "protocol_slug": SLUG,
            "categories": cats,
            "produced_at": "2026-04-27T10:34:23Z",
            "factor_scores": factors_by[fname],
        }))


def main() -> int:
    cleanup()
    try:
        setup_fragments()

        print("=== Test 1: dry-run on valid fragments → rc=0 ===")
        rc = run_merge("--dry-run")
        assert rc == 0, f"dry-run failed (rc={rc})"
        print(f"  ✓ rc={rc}")

        print("\n=== Test 2: real merge writes grading.json ===")
        rc = run_merge()
        assert rc == 0, f"merge failed (rc={rc})"
        out = json.loads((TMP / "grading.json").read_text())
        assert out["protocol"]["slug"] == SLUG
        assert len(out["factor_scores"]) == 25, f"expected 25, got {len(out['factor_scores'])}"
        assert all("category" not in fs for fs in out["factor_scores"]), "category should be stripped"
        assert "_meta" in out
        print(f"  ✓ {len(out['factor_scores'])} factors, _meta present, no per-factor category")

        print("\n=== Test 3: missing critical factor → rc=3 ===")
        data = json.loads((TMP / "01-code-security.factors.json").read_text())
        data["factor_scores"] = [fs for fs in data["factor_scores"] if fs["factor_id"] != "RD-F-001"]
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))
        rc = run_merge("--dry-run")
        assert rc == 3, f"expected rc=3, got {rc}"
        print(f"  ✓ rc={rc} for missing RD-F-001")

        # Restore
        data["factor_scores"].append(make_factor("RD-F-001", 1))
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))

        print("\n=== Test 4: duplicate factor_id across fragments → rc=3 ===")
        eco = json.loads((TMP / "04-economic.factors.json").read_text())
        eco["factor_scores"].append(make_factor("RD-F-001", 4))
        (TMP / "04-economic.factors.json").write_text(json.dumps(eco))
        rc = run_merge("--dry-run")
        assert rc == 3, f"expected rc=3, got {rc}"
        print(f"  ✓ rc={rc} for RD-F-001 duplicated")

        # Restore
        eco["factor_scores"] = [fs for fs in eco["factor_scores"] if fs["factor_id"] != "RD-F-001"]
        (TMP / "04-economic.factors.json").write_text(json.dumps(eco))

        print("\n=== Test 5: out-of-scope factor → rc=3 ===")
        data = json.loads((TMP / "01-code-security.factors.json").read_text())
        data["factor_scores"].append(make_factor("RD-F-099", 4))   # cat=4 in code-security fragment
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))
        rc = run_merge("--dry-run")
        assert rc == 3, f"expected rc=3, got {rc}"
        print(f"  ✓ rc={rc} for cat=4 factor in code-security fragment")

        print("\n=== Test 6: missing fragment file → rc=2 ===")
        cleanup()
        setup_fragments()
        (TMP / "04-economic.factors.json").unlink()
        rc = run_merge("--dry-run")
        assert rc == 2, f"expected rc=2, got {rc}"
        print(f"  ✓ rc={rc} for missing 04-economic.factors.json")

        print("\n=== Test 7: invalid score value → rc=3 ===")
        cleanup()
        setup_fragments()
        data = json.loads((TMP / "01-code-security.factors.json").read_text())
        data["factor_scores"][0]["score"] = "purple"
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))
        rc = run_merge("--dry-run")
        assert rc == 3, f"expected rc=3, got {rc}"
        print(f"  ✓ rc={rc} for score=purple")

        print("\n=== Test 8: red factor without source → rc=3 ===")
        cleanup()
        setup_fragments()
        data = json.loads((TMP / "01-code-security.factors.json").read_text())
        data["factor_scores"][0]["score"] = "red"
        data["factor_scores"][0]["sources"] = []
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))
        rc = run_merge("--dry-run")
        assert rc == 3, f"expected rc=3, got {rc}"
        print(f"  ✓ rc={rc} for red factor with no sources")

        print("\n=== Test 9: not_assessed with notes and no source is allowed → rc=0 ===")
        cleanup()
        setup_fragments()
        data = json.loads((TMP / "01-code-security.factors.json").read_text())
        data["factor_scores"][0]["score"] = "not_assessed"
        data["factor_scores"][0]["sources"] = []
        data["factor_scores"][0]["notes"] = "fixture intentionally leaves evidence unavailable"
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))
        rc = run_merge("--dry-run")
        assert rc == 0, f"expected rc=0 (not_assessed exempt from source requirement when notes explain why), got {rc}"
        print(f"  ✓ rc={rc} for not_assessed with notes and no sources")

        print("\n=== Test 10: family + surface scoped same factor is allowed → rc=0 ===")
        cleanup()
        setup_fragments()
        data = json.loads((TMP / "01-code-security.factors.json").read_text())
        family_scoped = make_factor("RD-F-002", 1)
        family_scoped["scope_level"] = "family"
        data["factor_scores"].append(family_scoped)
        (TMP / "01-code-security.factors.json").write_text(json.dumps(data))
        rc = run_merge()
        assert rc == 0, f"expected rc=0 for same factor at family + surface scopes, got {rc}"
        out = json.loads((TMP / "grading.json").read_text())
        scoped = [fs for fs in out["factor_scores"] if fs["factor_id"] == "RD-F-002"]
        assert {fs["scope_level"] for fs in scoped} == {"family", "surface"}
        print("  ✓ RD-F-002 emitted once at family scope and once at surface scope")

        print("\nAll merge-script smoke tests PASSED.")
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
