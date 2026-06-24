// Active rubric version. Single source of truth: config/rubric-version.json
// at the repo root. This file mirrors that value as a TypeScript const so
// in-site consumers don't need to import a JSON file from outside site/'s
// rootDir (which trips Astro's strict tsconfig).
//
// Drift is prevented by CI gate scripts/ci/check-rubric-version-pin.ts, which
// asserts:
//   config/rubric-version.json::active === RUBRIC_VERSION (this constant)
//                                       === active rubric_versions row in DB
// Bumping the rubric requires updating all three in one PR.
export const RUBRIC_VERSION = "v1.7.0" as const;

export type Letter = "A" | "B" | "C" | "D" | "F";

// ── M1 v4 Constants ──────────────────────────────────────────────────────────

const CORE_FIVE = new Set([1, 2, 3, 5, 8]); // Code, Governance, Oracle, Ops History, Fork Lineage

const YELLOW_WEIGHT = 1;
const RED_WEIGHT = 3;
const CORE_FIVE_CATEGORY_WEIGHT = 1.5;
const NON_CORE_CATEGORY_WEIGHT = 1.0;
const CRITICAL_RED_PENALTY_PER = 5;
const CRITICAL_RED_PENALTY_CAP = 15;
const D_CAP_THRESHOLD = 60; // core-five severity ≥ this caps protocol at D
const F_CAP_THRESHOLD = 90; // core-five severity ≥ this caps protocol at F

// Cat 4 (Economic) factor IDs that are event-cascade eligible.
// Decision (M1 v4): KEEP as a severity input transformation.
// When a protocol has an active incident, these factors are capped at yellow
// for the severity computation (not structural design failures).
// Mirrors compose.py CAT4_EVENT_CASCADE (Python single source of truth).
const CAT4_EVENT_CASCADE = new Set(["RD-F-063", "RD-F-066", "RD-F-067"]);

// ── Public types ─────────────────────────────────────────────────────────────

export interface RawFactorScore {
  factor_id: string;
  score: string;
  [key: string]: unknown;
}

export interface FactorMeta {
  id: string;
  category_id: number;
  is_critical: boolean;
}

/**
 * Inputs to grade(): factor-level aggregates for a single protocol.
 * The old integer fields (critical_flag_count etc.) are retained on this type
 * for display purposes but no longer drive the letter grade under M1 v4.
 */
export interface GradeInputs {
  /** Per-category factor score counts: { red, yellow, green, gray } per cat_id */
  category_counts: Record<
    number,
    { red: number; yellow: number; green: number; gray: number }
  >;
  /** Count of factors where is_critical=true AND score=red */
  critical_red_count: number;
}

export interface ComputedGrade {
  letter: Letter;
  risk_score: number;
  base_risk_score: number;
  critical_red_count: number;
  critical_penalty: number;
  /** Per-category severity 0–100, keyed by cat_id */
  category_severities: Record<number, number>;
  cap_applied: "none" | "D" | "F";
  cap_reason: string | null;
  /** Category lights for display (derived from severity) */
  category_lights: Record<number, "red" | "yellow" | "green" | "gray">;
}

// ── Per-category severity ────────────────────────────────────────────────────

/**
 * Compute 0–100 severity for one category.
 * Gray factors are excluded from the denominator (PD-039).
 */
function categorySeverity(counts: {
  red: number;
  yellow: number;
  green: number;
  gray: number;
}): number {
  const denom = counts.green + counts.yellow + counts.red;
  if (denom === 0) return 0;
  return ((counts.red * RED_WEIGHT + counts.yellow * YELLOW_WEIGHT) / (denom * RED_WEIGHT)) * 100;
}

/**
 * Display rollup for the per-category light shown in the UI.
 * denom=0 → gray; severity ≥ 50 → red; ≥ 20 → yellow; < 20 → green.
 */
function severityToLight(
  severity: number,
  denom: number,
): "red" | "yellow" | "green" | "gray" {
  if (denom === 0) return "gray";
  if (severity >= 50) return "red";
  if (severity >= 20) return "yellow";
  return "green";
}

// ── Core grade function ──────────────────────────────────────────────────────

/**
 * Compute the M1 v4 letter grade from per-category factor counts and critical
 * red count. Implements the exact algorithm from the handoff spec §2–§5.
 *
 * Constants: D_CAP_THRESHOLD=60, F_CAP_THRESHOLD=90 (v4 values).
 */
export function grade(inputs: GradeInputs): ComputedGrade {
  const { category_counts, critical_red_count } = inputs;

  // §2 Per-category severity + weighted score accumulation
  const categorySeverities: Record<number, number> = {};
  const categoryLights: Record<number, "red" | "yellow" | "green" | "gray"> = {};
  let weightedSum = 0;
  let totalWeight = 0;
  let capApplied: "none" | "D" | "F" = "none";
  let capReason: string | null = null;

  for (let catId = 1; catId <= 13; catId++) {
    const counts = category_counts[catId] ?? { red: 0, yellow: 0, green: 0, gray: 0 };
    const denom = counts.green + counts.yellow + counts.red;
    const severity = categorySeverity(counts);

    categorySeverities[catId] = severity;
    categoryLights[catId] = severityToLight(severity, denom);

    if (denom > 0) {
      const weight = CORE_FIVE.has(catId)
        ? CORE_FIVE_CATEGORY_WEIGHT
        : NON_CORE_CATEGORY_WEIGHT;
      weightedSum += severity * weight;
      totalWeight += weight;
    }
  }

  // §3 Protocol risk score
  const baseRiskScore = totalWeight === 0 ? 0 : weightedSum / totalWeight;
  const criticalPenalty = Math.min(
    CRITICAL_RED_PENALTY_CAP,
    CRITICAL_RED_PENALTY_PER * critical_red_count,
  );
  const riskScore = Math.min(100, baseRiskScore + criticalPenalty);

  // §4 Letter grade (first match wins)
  let letter: Letter;
  if (critical_red_count >= 3 || riskScore > 55) {
    letter = "F";
  } else if (critical_red_count >= 2 || riskScore > 35) {
    letter = "D";
  } else if (riskScore > 20) {
    letter = "C";
  } else if (critical_red_count >= 1 || riskScore > 12) {
    letter = "B";
  } else {
    letter = "A";
  }

  // §5 Single-category cap override (core-five only)
  for (let catId = 1; catId <= 13; catId++) {
    if (!CORE_FIVE.has(catId)) continue;
    const counts = category_counts[catId] ?? { red: 0, yellow: 0, green: 0, gray: 0 };
    const denom = counts.green + counts.yellow + counts.red;
    if (denom === 0) continue;

    const severity = categorySeverities[catId];

    if (severity >= F_CAP_THRESHOLD) {
      if (capApplied !== "F") {
        capApplied = "F";
        capReason = `Cat ${catId} severity ${Math.round(severity)} ≥ ${F_CAP_THRESHOLD} (core-five cap)`;
      }
      letter = "F";
    } else if (
      severity >= D_CAP_THRESHOLD &&
      capApplied === "none" &&
      (letter === "A" || letter === "B" || letter === "C")
    ) {
      capApplied = "D";
      capReason = `Cat ${catId} severity ${Math.round(severity)} ≥ ${D_CAP_THRESHOLD} (core-five cap)`;
      letter = "D";
    }
  }

  return {
    letter,
    risk_score: riskScore,
    base_risk_score: baseRiskScore,
    critical_red_count,
    critical_penalty: criticalPenalty,
    category_severities: categorySeverities,
    cap_applied: capApplied,
    cap_reason: capReason,
    category_lights: categoryLights,
  };
}

// ── computeGradeFromFactors ───────────────────────────────────────────────────

/**
 * Compute a fresh M1 v4 grade directly from raw factor scores + factor metadata.
 *
 * Equivalent to the Python `compose.py` + `rubric.py` pipeline for a single
 * protocol. The result overrides any pre-computed headline_grade stored in the
 * dump.
 *
 * Note: The CAT4_EVENT_CASCADE rule is retained under M1 v4 (handoff §6 default
 * "keep"). When has_active_incident=true, event-driven Cat 4 factors
 * (RD-F-063/066/067) are capped at yellow for the severity computation;
 * they are not structural design failures. critical_red_count is computed
 * from the original (uncapped) scores, matching Python compose.py exactly.
 */
export function computeGradeFromFactors(
  factorScores: RawFactorScore[],
  factorMeta: FactorMeta[],
  protocol?: {
    has_active_incident?: boolean | null;
    total_value_secured_usd?: number | string | null;
    launched_at?: string | null;
  },
): ComputedGrade {
  const metaById = new Map(factorMeta.map((f) => [f.id, f]));
  const hasActiveIncident = Boolean(protocol?.has_active_incident);

  const byCategory = new Map<
    number,
    { red: number; yellow: number; green: number; gray: number }
  >();
  let criticalRedCount = 0;

  for (const fs of factorScores) {
    const meta = metaById.get(fs.factor_id);
    if (!meta) continue;
    const catId = meta.category_id;

    if (!byCategory.has(catId)) {
      byCategory.set(catId, { red: 0, yellow: 0, green: 0, gray: 0 });
    }
    const counts = byCategory.get(catId)!;

    // Cat 4 event-cascade integrity rule (retained under M1; mirrors compose.py).
    // critical_red_count uses the original score; the cascade only affects
    // the category severity counts used in the weighted-average computation.
    let score = fs.score;
    if (catId === 4 && hasActiveIncident && CAT4_EVENT_CASCADE.has(fs.factor_id)) {
      if (score === "red") score = "yellow";
    }

    if (fs.score === "red" && meta.is_critical) criticalRedCount++;

    if (score === "red") {
      counts.red++;
    } else if (score === "yellow") {
      counts.yellow++;
    } else if (score === "green") {
      counts.green++;
    } else {
      // gray (unscored / n/a)
      counts.gray++;
    }
  }

  // Build category_counts Record for all 13 categories
  const category_counts: GradeInputs["category_counts"] = {};
  for (let catId = 1; catId <= 13; catId++) {
    category_counts[catId] = byCategory.get(catId) ?? {
      red: 0,
      yellow: 0,
      green: 0,
      gray: 0,
    };
  }

  return grade({ category_counts, critical_red_count: criticalRedCount });
}
