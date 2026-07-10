#!/usr/bin/env python3
"""Deterministically merge protocol assessment fragments into grading.json.

Inputs live under `.research/protocols/<slug>/` by default:
- `00-profile.meta.json` with protocol, family, surface, and deployment metadata.
- Seven `*.factors.json` domain fragments defined by `FRAGMENT_CONTRACTS`.

The merged file is validated for scope, factor uniqueness, critical coverage,
and source requirements before it can be written. Use `--dry-run` to validate
without changing grading.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protocol_validation import (
    CRITICAL_FACTORS,
    CROSS_CHAIN_CRITICAL,
    FRAGMENT_CONTRACTS,
    VALID_COLLECTION_MODES,
    VALID_FACTOR_SCORE_SCOPES,
    VALID_GAP_REASONS,
    VALID_SCORES,
    VALID_SOURCE_TYPES,
    VALID_SURFACE_STATUSES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SURFACE_SLUG = "default"

# Force UTF-8 stdout/stderr on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Validation constants are imported from protocol_validation.py so this script
# and import-protocol-assessment.py accept the same assessment vocabulary.
# ---------------------------------------------------------------------------
# Family/surface normalisation
# ---------------------------------------------------------------------------

def _surface_status_from_protocol(status: str | None) -> str:
    return "deprecated" if status == "deprecated" else "active"


def normalise_family(profile_meta: dict, slug: str) -> dict:
    """Return canonical family metadata, defaulting old packets to one family."""
    protocol = profile_meta.get("protocol", {})
    raw = dict(profile_meta.get("family") or {})
    family_slug = raw.get("family_slug") or raw.get("slug") or protocol.get("slug") or slug
    return {
        "family_slug": family_slug,
        "display_name": raw.get("display_name") or protocol.get("display_name") or family_slug,
        "description": raw.get("description", protocol.get("description")),
        "homepage_url": raw.get("homepage_url", protocol.get("homepage_url")),
        "protocol_type": raw.get("protocol_type") or protocol.get("protocol_type"),
        "primary_chain": raw.get("primary_chain") or protocol.get("primary_chain"),
        "primary_surface_slug": raw.get("primary_surface_slug") or raw.get("primary_surface"),
        "legacy_caveat": raw.get("legacy_caveat"),
    }


def normalise_surfaces(profile_meta: dict, family: dict) -> list[dict]:
    """Return canonical surfaces, defaulting old packets to one default surface."""
    protocol = profile_meta.get("protocol", {})
    raw_surfaces = profile_meta.get("surfaces")
    if not raw_surfaces:
        return [
            {
                "surface_slug": DEFAULT_SURFACE_SLUG,
                "display_name": protocol.get("display_name") or family["display_name"],
                "status": _surface_status_from_protocol(protocol.get("status")),
                "launched_at": protocol.get("launched_at"),
                "primary_chain": protocol.get("primary_chain") or family.get("primary_chain"),
                "tvs_usd": protocol.get("total_value_secured_usd"),
                "scope_note": None,
                "is_primary": True,
                "legacy_slug": protocol.get("slug"),
            }
        ]

    surfaces: list[dict] = []
    primary = family.get("primary_surface_slug")
    for raw in raw_surfaces:
        s = dict(raw)
        surface_slug = s.get("surface_slug") or s.get("slug")
        surfaces.append(
            {
                "surface_slug": surface_slug,
                "display_name": s.get("display_name") or surface_slug,
                "status": s.get("status") or "active",
                "launched_at": s.get("launched_at"),
                "primary_chain": s.get("primary_chain") or family.get("primary_chain"),
                "tvs_usd": (
                    s.get("tvs_usd")
                    if s.get("tvs_usd") is not None
                    else s.get("total_value_secured_usd")
                ),
                "scope_note": s.get("scope_note"),
                "is_primary": bool(s.get("is_primary")) or (primary is not None and surface_slug == primary),
                "legacy_slug": s.get("legacy_slug") or s.get("protocol_slug"),
            }
        )
    if surfaces and not any(s["is_primary"] for s in surfaces):
        surfaces[0]["is_primary"] = True
    return surfaces


def primary_surface_slug(surfaces: list[dict]) -> str:
    for s in surfaces:
        if s.get("is_primary"):
            return s["surface_slug"]
    return surfaces[0]["surface_slug"] if surfaces else DEFAULT_SURFACE_SLUG


def score_scope_key(fs: dict, family: dict, surfaces: list[dict]) -> tuple[str, str]:
    """Return a stable logical scope key for duplicate checks."""
    scope = fs.get("scope_level") or fs.get("scope") or "surface"
    if scope == "family":
        return ("family", fs.get("family_slug") or family["family_slug"])
    if scope == "deployment":
        surface = fs.get("surface_slug") or primary_surface_slug(surfaces)
        chain = fs.get("chain") or "?"
        deployment_key = fs.get("deployment_key") or fs.get("deployment_slug") or "primary"
        return ("deployment", f"{surface}:{chain}:{deployment_key}")
    return ("surface", fs.get("surface_slug") or primary_surface_slug(surfaces))


def canonical_factor_score(fs: dict, family: dict, surfaces: list[dict]) -> dict:
    """Strip fragment-only fields and add canonical scope metadata."""
    out = {k: v for k, v in fs.items() if k not in {"category", "scope"}}
    scope = fs.get("scope_level") or fs.get("scope") or "surface"
    out["scope_level"] = scope
    if scope == "family":
        out["family_slug"] = fs.get("family_slug") or family["family_slug"]
        out.pop("surface_slug", None)
        out.pop("deployment_key", None)
    elif scope == "deployment":
        out["surface_slug"] = fs.get("surface_slug") or primary_surface_slug(surfaces)
        out["deployment_key"] = (
            fs.get("deployment_key")
            or fs.get("deployment_slug")
            or fs.get("chain")
            or "primary"
        )
        out.pop("family_slug", None)
    else:
        out["surface_slug"] = fs.get("surface_slug") or primary_surface_slug(surfaces)
        out.pop("family_slug", None)
        out.pop("deployment_key", None)
    return out


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def find_research_dir(slug: str) -> Path:
    """Resolve the public-safe default packet directory."""
    candidate = REPO_ROOT / ".research" / "protocols" / slug
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        f"No .research/protocols/{slug}/ directory found. Expected: "
        f"{candidate.relative_to(REPO_ROOT)}"
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def load_profile_meta(research_dir: Path) -> dict:
    p = research_dir / "00-profile.meta.json"
    if not p.exists():
        raise FileNotFoundError(
            f"missing 00-profile.meta.json — protocol-profiler must produce this "
            f"alongside 00-profile.md. Expected at: {p.relative_to(REPO_ROOT)}"
        )
    return load_json(p)


def load_fragments(research_dir: Path) -> list[tuple[str, str, set[int], dict]]:
    """Return list of (filename, agent, expected_categories, fragment_data)."""
    out = []
    missing = []
    for filename, expected_agent, expected_cats in FRAGMENT_CONTRACTS:
        p = research_dir / filename
        if not p.exists():
            missing.append(filename)
            continue
        try:
            data = load_json(p)
        except json.JSONDecodeError as e:
            raise ValueError(f"{filename}: invalid JSON — {e}") from e
        out.append((filename, expected_agent, expected_cats, data))
    if missing:
        raise FileNotFoundError(
            "missing fragment file(s):\n"
            + "\n".join(f"  - {m}" for m in missing)
            + "\n\nEach domain specialist must write its factor fragment alongside"
            + "\nits .md report. Include its narrative report in the same packet."
        )
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_profile_meta(meta: dict, slug: str) -> list[str]:
    errors: list[str] = []
    if "protocol" not in meta:
        errors.append("00-profile.meta.json: missing 'protocol' object")
        return errors
    p = meta["protocol"]
    if p.get("slug") != slug:
        errors.append(
            f"00-profile.meta.json: protocol.slug ({p.get('slug')!r}) != argument ({slug!r})"
        )
    for required in ("slug", "display_name", "protocol_type", "primary_chain"):
        if not p.get(required):
            errors.append(f"00-profile.meta.json: protocol.{required} is required")

    family = normalise_family(meta, slug)
    for required in ("family_slug", "display_name", "protocol_type", "primary_chain"):
        if not family.get(required):
            errors.append(f"00-profile.meta.json: family.{required} is required")
    if family.get("family_slug") != p.get("slug"):
        errors.append("00-profile.meta.json: family.family_slug must equal protocol.slug")

    surfaces = normalise_surfaces(meta, family)
    if not surfaces:
        errors.append("00-profile.meta.json: at least one surface is required")
    seen_surfaces: set[str] = set()
    primary_count = 0
    for i, surface in enumerate(surfaces):
        prefix = f"00-profile.meta.json: surfaces[{i}]"
        surface_slug = surface.get("surface_slug")
        if not surface_slug:
            errors.append(f"{prefix}.surface_slug is required")
        elif surface_slug in seen_surfaces:
            errors.append(f"{prefix}.surface_slug {surface_slug!r} duplicated")
        seen_surfaces.add(surface_slug)
        if not surface.get("display_name"):
            errors.append(f"{prefix}.display_name is required")
        if surface.get("status") not in VALID_SURFACE_STATUSES:
            errors.append(
                f"{prefix}.status {surface.get('status')!r} not in {sorted(VALID_SURFACE_STATUSES)}"
            )
        if not surface.get("primary_chain"):
            errors.append(f"{prefix}.primary_chain is required")
        if surface.get("is_primary"):
            primary_count += 1
    if surfaces and primary_count != 1:
        errors.append("00-profile.meta.json: exactly one surface must be primary")
    return errors


def validate_fragment(
    filename: str,
    expected_agent: str,
    expected_cats: set[int],
    data: dict,
    slug: str,
) -> list[str]:
    """Validate one fragment file. Returns list of error strings."""
    errors: list[str] = []

    if data.get("agent") != expected_agent:
        errors.append(
            f"{filename}: agent={data.get('agent')!r} (expected {expected_agent!r})"
        )
    if data.get("protocol_slug") != slug:
        errors.append(
            f"{filename}: protocol_slug={data.get('protocol_slug')!r} (expected {slug!r})"
        )
    # Declared categories must be a SUBSET of the agent's expected scope.
    # Subset (not exact match) lets oracle-dependency-analyst declare just [3] for
    # non-bridge protocols (Cat 10 N/A) without breaking validation. The factor
    # category check below still prevents factors leaking into wrong scopes.
    declared_cats = set(data.get("categories") or [])
    if not declared_cats:
        errors.append(f"{filename}: 'categories' must be a non-empty list")
    elif not declared_cats.issubset(expected_cats):
        extra = sorted(declared_cats - expected_cats)
        errors.append(
            f"{filename}: declared categories {sorted(declared_cats)} include {extra} "
            f"outside this agent's scope {sorted(expected_cats)}"
        )

    fs_list = data.get("factor_scores")
    if not isinstance(fs_list, list):
        errors.append(f"{filename}: factor_scores must be a list")
        return errors

    default_family = {"family_slug": slug}
    default_surfaces = [{"surface_slug": DEFAULT_SURFACE_SLUG, "is_primary": True}]
    seen_in_fragment: set[tuple[str, str, str]] = set()
    for i, fs in enumerate(fs_list):
        prefix = f"{filename}: factor_scores[{i}]"
        fid = fs.get("factor_id")
        if not fid or not isinstance(fid, str) or not fid.startswith("RD-F-"):
            errors.append(f"{prefix}.factor_id invalid: {fid!r}")
            continue
        scope = fs.get("scope_level") or fs.get("scope") or "surface"
        if scope not in VALID_FACTOR_SCORE_SCOPES:
            errors.append(
                f"{prefix}.scope_level {scope!r} not in {sorted(VALID_FACTOR_SCORE_SCOPES)}"
            )
        scope_type, scope_target = score_scope_key(fs, default_family, default_surfaces)
        duplicate_key = (scope_type, scope_target, fid)
        if duplicate_key in seen_in_fragment:
            errors.append(
                f"{prefix}.factor_id {fid!r} duplicated within fragment for "
                f"{scope_type} {scope_target!r}"
            )
        seen_in_fragment.add(duplicate_key)

        cat = fs.get("category")
        if cat is None:
            errors.append(f"{prefix}.category is required (one of {sorted(expected_cats)})")
        elif cat not in expected_cats:
            errors.append(
                f"{prefix} ({fid}).category {cat} not in this agent's scope {sorted(expected_cats)}"
            )

        score = fs.get("score")
        if score not in VALID_SCORES:
            errors.append(f"{prefix} ({fid}).score {score!r} not in {sorted(VALID_SCORES)}")

        if not fs.get("evidence_summary"):
            errors.append(f"{prefix} ({fid}).evidence_summary is required")

        if score == "not_assessed" and not fs.get("notes"):
            errors.append(f"{prefix} ({fid}).notes is required when score='not_assessed'")

        cm = fs.get("collection_mode", "manual")
        if cm not in VALID_COLLECTION_MODES:
            errors.append(
                f"{prefix} ({fid}).collection_mode {cm!r} not in {sorted(VALID_COLLECTION_MODES)}"
            )

        gap_reason = fs.get("gap_reason")
        if gap_reason is not None:
            if gap_reason not in VALID_GAP_REASONS:
                errors.append(
                    f"{prefix} ({fid}).gap_reason {gap_reason!r} not in {sorted(VALID_GAP_REASONS)}"
                )
            if score in ("green", "yellow", "red"):
                errors.append(
                    f"{prefix} ({fid}).gap_reason must be null/omitted for graded score {score!r}"
                )

        sources = fs.get("sources", [])
        if score not in ("not_assessed", "not_applicable") and not sources:
            errors.append(
                f"{prefix} ({fid}, score={score!r}) requires ≥1 source per ER-17"
            )
        for j, s in enumerate(sources):
            sprefix = f"{prefix} ({fid}).sources[{j}]"
            st = s.get("source_type")
            if st not in VALID_SOURCE_TYPES:
                errors.append(f"{sprefix}.source_type {st!r} not in {sorted(VALID_SOURCE_TYPES)}")
            if not s.get("reference"):
                errors.append(f"{sprefix}.reference is required")

    return errors


def cross_fragment_validate(
    fragments: list[tuple[str, str, set[int], dict]],
    profile_meta: dict,
) -> list[str]:
    """Check duplicate scoped factor IDs + critical-factor coverage."""
    errors: list[str] = []
    protocol_slug = profile_meta.get("protocol", {}).get("slug", "")
    family = normalise_family(profile_meta, protocol_slug)
    surfaces = normalise_surfaces(profile_meta, family)

    seen: dict[tuple[str, str, str], str] = {}
    for filename, _agent, _cats, data in fragments:
        for fs in data.get("factor_scores", []):
            fid = fs.get("factor_id")
            if not fid:
                continue
            scope_type, scope_target = score_scope_key(fs, family, surfaces)
            key = (scope_type, scope_target, fid)
            if key in seen:
                errors.append(
                    f"factor_id {fid} appears in BOTH {seen[key]} and {filename} "
                    f"for {scope_type} {scope_target!r} - each factor must be scored "
                    "once per logical scope"
                )
            else:
                seen[key] = filename

    # Critical factors must be available to each surface, either inherited from
    # family scope or scored directly at surface scope. Deployment-only rows do
    # not satisfy the surface headline grade.
    has_bridge = bool(
        profile_meta.get("protocol", {}).get("has_bridge_surface")
        or profile_meta.get("protocol", {}).get("is_a_bridge")
    )
    required_critical = set(CRITICAL_FACTORS)
    if not has_bridge:
        required_critical -= CROSS_CHAIN_CRITICAL

    scored_keys = set(seen.keys())
    missing_critical: set[str] = set()
    for fid in required_critical:
        if ("family", family["family_slug"], fid) in scored_keys:
            continue
        for surface in surfaces:
            if ("surface", surface["surface_slug"], fid) not in scored_keys:
                missing_critical.add(fid)
                break
    if missing_critical:
        errors.append(
            "missing critical factor scores: "
            + ", ".join(sorted(missing_critical))
            + ". Each critical factor must be available at family scope or "
            "on every surface, either with a graded color or explicitly "
            "score='not_assessed' with notes explaining why evidence was not obtained."
        )

    # Warn on cross-chain critical absence when bridge surface unclear.
    if has_bridge:
        for fid in CROSS_CHAIN_CRITICAL:
            if not any(key[2] == fid for key in seen):
                # already caught as error above
                pass

    return errors


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_grading_json(
    profile_meta: dict,
    fragments: list[tuple[str, str, set[int], dict]],
) -> dict:
    """Produce the final grading.json structure."""
    slug = profile_meta.get("protocol", {}).get("slug", "")
    family = normalise_family(profile_meta, slug)
    surfaces = normalise_surfaces(profile_meta, family)
    family["primary_surface_slug"] = family.get("primary_surface_slug") or primary_surface_slug(surfaces)

    factor_scores: list[dict] = []
    for _filename, _agent, _cats, data in fragments:
        for fs in data.get("factor_scores", []):
            # Strip fragment-only fields and add canonical score scope.
            out_fs = canonical_factor_score(fs, family, surfaces)
            factor_scores.append(out_fs)

    # Stable sort by scope + factor_id for diffability.
    factor_scores.sort(
        key=lambda fs: (
            fs.get("scope_level", ""),
            fs.get("family_slug") or fs.get("surface_slug") or fs.get("deployment_key") or "",
            fs.get("factor_id", ""),
        )
    )

    return {
        "_meta": {
            "merged_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "merged_by": "merge-grading-fragments.py",
            "fragment_count": len(fragments),
            "factor_count": len(factor_scores),
        },
        "family": family,
        "surfaces": surfaces,
        "protocol": profile_meta["protocol"],
        "deployments": profile_meta.get("deployments", []),
        "factor_scores": factor_scores,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Merge per-specialist factor fragments into grading.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("slug", help="Protocol slug (e.g. centrifuge)")
    ap.add_argument("--dry-run", action="store_true", help="Validate + show summary, don't write grading.json")
    ap.add_argument("--out", help="Override output path (default: <research_dir>/grading.json)")
    args = ap.parse_args(argv)

    try:
        research_dir = find_research_dir(args.slug)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"Reading fragments from: {research_dir.relative_to(REPO_ROOT)}")

    try:
        profile_meta = load_profile_meta(research_dir)
        fragments = load_fragments(research_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Per-fragment + profile validation
    all_errors: list[str] = []
    all_errors.extend(validate_profile_meta(profile_meta, args.slug))
    for filename, expected_agent, expected_cats, data in fragments:
        all_errors.extend(validate_fragment(filename, expected_agent, expected_cats, data, args.slug))

    # Cross-fragment validation
    all_errors.extend(cross_fragment_validate(fragments, profile_meta))

    if all_errors:
        print(f"\nValidation FAILED ({len(all_errors)} error(s)):", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 3

    print(f"  ✓ profile meta: {profile_meta['protocol']['display_name']}")
    print(f"  ✓ {len(fragments)} fragments")
    for filename, agent, _cats, data in fragments:
        n = len(data.get("factor_scores", []))
        print(f"      {filename}: {n} factors ({agent})")

    grading = compose_grading_json(profile_meta, fragments)
    n_factors = len(grading["factor_scores"])
    print(f"  ✓ merged grading: {n_factors} factor_scores total")

    if args.dry_run:
        print("\n--dry-run: skipping write")
        return 0

    out_path = Path(args.out) if args.out else (research_dir / "grading.json")
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(grading, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\n→ wrote {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
