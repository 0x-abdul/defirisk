"""rubric.py — Python mirror of site/src/lib/rubric.ts grade().

Rubric version: v1.7.0  (M1 "Curve & Calibrate" v4)
Deterministic: no I/O, no randomness, same inputs → same outputs.

Algorithm change from v1.6.0:
- Per-category severity (0–100) replaces category red/yellow/green lights as
  the primary rubric input.
- Protocol risk score is a core-five-weighted average of category severities
  plus a critical-red penalty (5 pts/red, cap 15).
- Letter grade is bucketed from risk_score (12/20/35/55 bands), with critical
  red counts as tie-breakers at the D/F boundary.
- Single-category cap override: any core-five category ≥ 90 severity forces F;
  ≥ 60 forces at most D (if natural grade is A/B/C).
- Removed: gray_on_core_five rule, TVL/age floors for A grade,
  CAT_RED_THRESHOLD per-category override map.
"""

from __future__ import annotations

RUBRIC_VERSION = "v1.7.0"

LETTERS = ("A", "B", "C", "D", "F")

# ── M1 v4 constants ──────────────────────────────────────────────────────────

CORE_FIVE: frozenset[int] = frozenset({1, 2, 3, 5, 8})
YELLOW_WEIGHT: int = 1
RED_WEIGHT: int = 3
CORE_FIVE_CATEGORY_WEIGHT: float = 1.5
NON_CORE_CATEGORY_WEIGHT: float = 1.0
CRITICAL_RED_PENALTY_PER: int = 5
CRITICAL_RED_PENALTY_CAP: int = 15
D_CAP_THRESHOLD: int = 60   # core-five severity ≥ this caps protocol at D
F_CAP_THRESHOLD: int = 90   # core-five severity ≥ this caps protocol at F


# ── Category severity (0–100) ─────────────────────────────────────────────────

def category_severity(
    green_count: int,
    yellow_count: int,
    red_count: int,
) -> float:
    """Compute per-category severity (0–100).

    Gray factors are excluded from the denominator (PD-039).
    Returns 0.0 when denominator is 0 (all-gray category).
    """
    denom = green_count + yellow_count + red_count
    if denom == 0:
        return 0.0
    return (red_count * RED_WEIGHT + yellow_count * YELLOW_WEIGHT) / (denom * RED_WEIGHT) * 100.0


# ── Main grade function ───────────────────────────────────────────────────────

def grade(
    *,
    # Dict mapping category_id (int) → {green, yellow, red, gray counts}.
    # gray factors are excluded from severity denominator per PD-039.
    category_counts: dict[int, dict[str, int]],
    # Count of factors where is_critical=True AND score='red'.
    critical_red_count: int,
) -> dict:
    """Compute M1 v4 grade from per-category score counts and critical-red count.

    Returns:
        {
            "letter": str,                          # A/B/C/D/F
            "risk_score": float,                    # 0–100
            "base_risk_score": float,               # weighted severity avg before penalty
            "critical_red_count": int,              # input echoed back
            "critical_penalty": float,              # min(15, 5 × critical_red_count)
            "category_severities": dict[int,float], # cat_id → severity 0–100
            "cap_applied": str,                     # "none" | "D" | "F"
            "cap_reason": str | None,               # human-readable cap explanation
        }
    """

    # 1. Per-category severity
    category_severities: dict[int, float] = {}
    for cat_id, counts in category_counts.items():
        sev = category_severity(
            green_count=counts.get("green", 0),
            yellow_count=counts.get("yellow", 0),
            red_count=counts.get("red", 0),
        )
        category_severities[cat_id] = sev

    # 2. Protocol risk score (weighted average over categories with denom > 0)
    weighted_sum = 0.0
    total_weight = 0.0
    for cat_id, counts in category_counts.items():
        denom = counts.get("green", 0) + counts.get("yellow", 0) + counts.get("red", 0)
        if denom == 0:
            continue  # all-gray: excluded from denominator
        weight = CORE_FIVE_CATEGORY_WEIGHT if cat_id in CORE_FIVE else NON_CORE_CATEGORY_WEIGHT
        weighted_sum += category_severities[cat_id] * weight
        total_weight += weight

    base_risk_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0
    critical_penalty = float(min(CRITICAL_RED_PENALTY_CAP, CRITICAL_RED_PENALTY_PER * critical_red_count))
    risk_score = min(100.0, base_risk_score + critical_penalty)

    # 3. Letter grade (first match wins)
    if critical_red_count >= 3 or risk_score > 55:
        letter = "F"
    elif critical_red_count >= 2 or risk_score > 35:
        letter = "D"
    elif risk_score > 20:
        letter = "C"
    elif critical_red_count >= 1 or risk_score > 12:
        letter = "B"
    else:
        letter = "A"

    # 4. Single-category cap override (core-five categories only)
    cap_applied = "none"
    cap_reason: str | None = None

    for cat_id in CORE_FIVE:
        if cat_id not in category_counts:
            continue
        counts = category_counts[cat_id]
        denom = counts.get("green", 0) + counts.get("yellow", 0) + counts.get("red", 0)
        if denom == 0:
            continue  # all-gray; excluded
        sev = category_severities[cat_id]
        if sev >= F_CAP_THRESHOLD:
            letter = "F"
            cap_applied = "F"
            cap_reason = f"Cat {cat_id} severity {sev:.0f} ≥ {F_CAP_THRESHOLD} (core-five cap)"
            break  # F is the ceiling; no need to check further
        elif sev >= D_CAP_THRESHOLD and letter in ("A", "B", "C"):
            letter = "D"
            cap_applied = "D"
            cap_reason = f"Cat {cat_id} severity {sev:.0f} ≥ {D_CAP_THRESHOLD} (core-five cap)"
            # Don't break: a later core-five cat may trigger F

    return {
        "letter": letter,
        "risk_score": round(risk_score, 2),
        "base_risk_score": round(base_risk_score, 2),
        "critical_red_count": critical_red_count,
        "critical_penalty": critical_penalty,
        "category_severities": category_severities,
        "cap_applied": cap_applied,
        "cap_reason": cap_reason,
    }
