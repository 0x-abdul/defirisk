import { describe, it, expect } from 'vitest';
import { grade, computeGradeFromFactors, type GradeInputs } from './rubric';
import type { RawFactorScore, FactorMeta } from './rubric';
import sparkFixture from '../../tests/fixtures/rubric/spark.json' with { type: 'json' };
import aaveV3Fixture from '../../tests/fixtures/rubric/aave-v3.json' with { type: 'json' };
import uniswapV4Fixture from '../../tests/fixtures/rubric/uniswap-v4.json' with { type: 'json' };
import bridgeFixture from '../../tests/fixtures/rubric/bridge.json' with { type: 'json' };
import perpsDexFixture from '../../tests/fixtures/rubric/perps-dex.json' with { type: 'json' };

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Build a GradeInputs where every category has `green` green factors and no reds/yellows. */
function allGreen(greenPerCat = 5): GradeInputs {
  const category_counts: GradeInputs['category_counts'] = {};
  for (let i = 1; i <= 13; i++) {
    category_counts[i] = { red: 0, yellow: 0, green: greenPerCat, gray: 0 };
  }
  return { category_counts, critical_red_count: 0 };
}

// ── Case A: pure green ───────────────────────────────────────────────────────
// All 13 categories all green. Expected: A, risk_score=0.

describe('grade(): Case A (pure green)', () => {
  const result = grade(allGreen());

  it('returns letter A', () => {
    expect(result.letter).toBe('A');
  });

  it('risk_score = 0', () => {
    expect(result.risk_score).toBeCloseTo(0);
  });

  it('cap_applied = none', () => {
    expect(result.cap_applied).toBe('none');
  });

  it('cap_reason = null', () => {
    expect(result.cap_reason).toBeNull();
  });

  it('critical_penalty = 0', () => {
    expect(result.critical_penalty).toBe(0);
  });
});

// ── Case B: single critical red ──────────────────────────────────────────────
// Cat 1: 1 critical red, 9 green → severity = (1×3)/(10×3)×100 = 10.
// base_risk = 10 (only cat with denom>0 for this test).
// critical_penalty = 5, risk_score = 15.
// Letter: critical_reds=1 AND risk ≤ 20 → B.

describe('grade(): Case B (single critical red)', () => {
  // Cat 1 only has factors to keep base_risk low; others are empty (all-gray).
  const inputs: GradeInputs = {
    category_counts: {
      1: { red: 1, yellow: 0, green: 9, gray: 0 },
      // cats 2–13: no factors (denom=0, excluded from weighted avg)
      ...Object.fromEntries(
        Array.from({ length: 12 }, (_, i) => [i + 2, { red: 0, yellow: 0, green: 0, gray: 0 }]),
      ),
    },
    critical_red_count: 1,
  };
  const result = grade(inputs);

  it('returns letter B', () => {
    expect(result.letter).toBe('B');
  });

  it('risk_score ≈ 15', () => {
    // base = 10, penalty = 5
    expect(result.risk_score).toBeCloseTo(15);
  });

  it('critical_penalty = 5', () => {
    expect(result.critical_penalty).toBe(5);
  });

  it('cap_applied = none (severity 10 < 60)', () => {
    expect(result.cap_applied).toBe('none');
  });
});

// ── Case D: 2 critical reds ──────────────────────────────────────────────────
// Cats 1 and 2 each get 1 critical red + 9 green → severity=10 each.
// base_risk = 10, critical_penalty=10, risk_score=20.
// Letter: critical_reds=2 → D.

describe('grade(): Case D (2 critical reds)', () => {
  const inputs: GradeInputs = {
    category_counts: {
      1: { red: 1, yellow: 0, green: 9, gray: 0 },
      2: { red: 1, yellow: 0, green: 9, gray: 0 },
      ...Object.fromEntries(
        Array.from({ length: 11 }, (_, i) => [i + 3, { red: 0, yellow: 0, green: 0, gray: 0 }]),
      ),
    },
    critical_red_count: 2,
  };
  const result = grade(inputs);

  it('returns letter D', () => {
    expect(result.letter).toBe('D');
  });

  it('critical_penalty = 10', () => {
    expect(result.critical_penalty).toBe(10);
  });

  it('risk_score ≈ 20', () => {
    expect(result.risk_score).toBeCloseTo(20);
  });

  it('cap_applied = none', () => {
    expect(result.cap_applied).toBe('none');
  });
});

// ── Case F: 3 critical reds ──────────────────────────────────────────────────
// Cats 1, 2, 3 each get 1 critical red + 9 green → severity=10 each.
// critical_penalty=15, risk_score≈25. Letter: critical_reds=3 → F.

describe('grade(): Case F (3 critical reds)', () => {
  const inputs: GradeInputs = {
    category_counts: {
      1: { red: 1, yellow: 0, green: 9, gray: 0 },
      2: { red: 1, yellow: 0, green: 9, gray: 0 },
      3: { red: 1, yellow: 0, green: 9, gray: 0 },
      ...Object.fromEntries(
        Array.from({ length: 10 }, (_, i) => [i + 4, { red: 0, yellow: 0, green: 0, gray: 0 }]),
      ),
    },
    critical_red_count: 3,
  };
  const result = grade(inputs);

  it('returns letter F', () => {
    expect(result.letter).toBe('F');
  });

  it('critical_penalty capped at 15', () => {
    expect(result.critical_penalty).toBe(15);
  });
});

// ── Case F (high risk score): risk > 55, 0 critical reds ─────────────────────
// All 13 cats: red=2, green=1 → severity=66.7 each.
// base_risk ≈ 66.7, risk_score ≈ 66.7 (> 55) → F.

describe('grade(): Case F (high risk score path, 0 critical reds)', () => {
  const category_counts: GradeInputs['category_counts'] = {};
  for (let i = 1; i <= 13; i++) {
    category_counts[i] = { red: 2, yellow: 0, green: 1, gray: 0 };
  }
  const result = grade({ category_counts, critical_red_count: 0 });

  it('returns letter F', () => {
    expect(result.letter).toBe('F');
  });

  it('risk_score > 55', () => {
    expect(result.risk_score).toBeGreaterThan(55);
  });

  it('critical_penalty = 0', () => {
    expect(result.critical_penalty).toBe(0);
  });
});

// ── Case C: moderate risk score, 0 critical reds ─────────────────────────────
// risk_score 20 < x ≤ 35, 0 critical reds → C.
// Cat 1 (core-five): red=1, yellow=2, green=6 → denom=9,
//   severity=(3+2)/(27)×100=18.5 (stays green on display)
// Cat 4 (non-core): red=2, green=2 → denom=4, severity=(6)/(12)×100=50
// Cats 2,3,5,8 green=5 each (core-five); cats 6,7,9–13 empty.
//   weighted sum = 18.5×1.5 + 0×1.5×3 + 50×1.0 + 0×…
//   total_weight = 1.5 (cat1) + 1.5×3 (cats 2,3,5) + 1.5 (cat8) + 1.0 (cat4)
//   = 1.5 + 4.5 + 1.5 + 1.5 + 1.0 = 10.0
// Wait, let me build a simpler scenario:

// Cat 6 (non-core): red=3, green=3 → severity=50; all 5 core-five: green=5 only
// → base_risk = (0×1.5×5 + 50×1.0) / (5×1.5 + 1.0) = 50/8.5 ≈ 5.88 → A natural
// That's too low. Use more reds.
//
// Simpler: 5 non-core cats each with red=2, green=2 → severity=50 each
// base = (50×1.0 × 5 + 0×1.5×5) / (5×1.0 + 5×1.5) = 250/12.5 = 20
// risk = 20 → riskScore 20 is NOT > 20 per spec ("> 20 → C"), so that's B boundary.
// Use 6 non-core cats red=2, green=2: base = 300/13.5 ≈ 22.2 → C (> 20)

describe('grade(): Case C (moderate risk score)', () => {
  const category_counts: GradeInputs['category_counts'] = {};
  // Core five (1,2,3,5,8): all green
  for (const catId of [1, 2, 3, 5, 8]) {
    category_counts[catId] = { red: 0, yellow: 0, green: 5, gray: 0 };
  }
  // 6 non-core cats (4,6,7,9,10,11): each red=2, green=2
  for (const catId of [4, 6, 7, 9, 10, 11]) {
    category_counts[catId] = { red: 2, yellow: 0, green: 2, gray: 0 };
  }
  // Remaining non-core (12,13): empty
  for (const catId of [12, 13]) {
    category_counts[catId] = { red: 0, yellow: 0, green: 0, gray: 0 };
  }
  const result = grade({ category_counts, critical_red_count: 0 });

  it('returns letter C', () => {
    expect(result.letter).toBe('C');
  });

  it('risk_score is between 20 and 35', () => {
    expect(result.risk_score).toBeGreaterThan(20);
    expect(result.risk_score).toBeLessThanOrEqual(35);
  });

  it('cap_applied = none (no core-five severity ≥ 60)', () => {
    expect(result.cap_applied).toBe('none');
  });
});

// ── Case cap-D: single core-five category severity ≥ 60, natural grade A ─────
// Cat 1 (core-five): red=2, green=1, yellow=0 → severity=66.7
// All other cats: green=5 → severity=0
// base_risk = (66.7×1.5 + 0 for all others with denom>0) / total_weight
//   total_weight = 1.5 (cat1) + 4×1.5 (cats2,3,5,8) + 8×1.0 (non-core)
//   = 1.5 + 6.0 + 8.0 = 15.5
//   base_risk = 100 / 15.5 ≈ 6.45
// risk_score ≈ 6.45, critical_reds=0 → natural A
// cap: Cat 1 severity 66.7 ≥ 60 → cap D → letter D

describe('grade(): Case cap-D (core-five severity ≥ 60, natural grade overridden to D)', () => {
  const category_counts: GradeInputs['category_counts'] = {};
  // Cat 1 (core-five): severity = (2×3)/(3×3)×100 = 66.7
  category_counts[1] = { red: 2, yellow: 0, green: 1, gray: 0 };
  // Remaining 12 cats: all green=5
  for (let i = 2; i <= 13; i++) {
    category_counts[i] = { red: 0, yellow: 0, green: 5, gray: 0 };
  }
  const result = grade({ category_counts, critical_red_count: 0 });

  it('returns letter D (cap override)', () => {
    expect(result.letter).toBe('D');
  });

  it("cap_applied = 'D'", () => {
    expect(result.cap_applied).toBe('D');
  });

  it('cap_reason mentions Cat 1 and ≥ 60', () => {
    expect(result.cap_reason).toMatch(/Cat 1/);
    expect(result.cap_reason).toMatch(/60/);
  });

  it('natural risk_score < 12 (confirms override was needed)', () => {
    // base_risk = (66.7×1.5) / 15.5 ≈ 6.45
    expect(result.base_risk_score).toBeLessThan(12);
  });
});

// ── Case cap-F: single core-five category severity ≥ 90 ──────────────────────
// Cat 1 (core-five): red=3, green=0, yellow=0 → severity=100
// All other cats: green=5 → severity=0
// base_risk = (100×1.5) / 15.5 ≈ 9.68 → natural A
// cap: Cat 1 severity 100 ≥ 90 → cap F → letter F

describe('grade(): Case cap-F (core-five severity ≥ 90, natural grade overridden to F)', () => {
  const category_counts: GradeInputs['category_counts'] = {};
  // Cat 1 (core-five): all red → severity=100
  category_counts[1] = { red: 3, yellow: 0, green: 0, gray: 0 };
  // Remaining 12 cats: all green=5
  for (let i = 2; i <= 13; i++) {
    category_counts[i] = { red: 0, yellow: 0, green: 5, gray: 0 };
  }
  const result = grade({ category_counts, critical_red_count: 0 });

  it('returns letter F (cap override)', () => {
    expect(result.letter).toBe('F');
  });

  it("cap_applied = 'F'", () => {
    expect(result.cap_applied).toBe('F');
  });

  it('cap_reason mentions Cat 1 and ≥ 90', () => {
    expect(result.cap_reason).toMatch(/Cat 1/);
    expect(result.cap_reason).toMatch(/90/);
  });

  it('natural risk_score < 12 (confirms override was needed)', () => {
    expect(result.base_risk_score).toBeLessThan(12);
  });
});

// ── Additional grade boundary checks ────────────────────────────────────────

describe('grade(): band boundary: risk_score exactly at boundaries', () => {
  /** Build inputs with a single core-five cat and a given target base risk.
   *  Cat 1 only has denom>0, so base_risk = severity.
   *  severity = (red×3 + yellow×1) / (denom×3) × 100.
   *  To get severity = 12: use red=0, yellow=12, green=24 → (12)/(108) × 100 ≈ 11.11. Close enough.
   *  Instead use only Cat 4 (non-core) so cap rule doesn't fire.
   */
  it('risk 12 AND critical_reds=0 → A (exactly at boundary)', () => {
    // Cat 4 (non-core): yellow=1, green=24 → severity=(1)/(75)×100=1.33, too low.
    // Let's construct a case with risk_score ≈ 12 using a non-core cat.
    // Cat 4: red=0, yellow=12, green=24 → denom=36, severity=(12)/(108)×100 = 11.11
    // Only cat4 has denom>0: base_risk = 11.11×1.0/1.0 = 11.11 < 12 → A
    const category_counts: GradeInputs['category_counts'] = {};
    category_counts[4] = { red: 0, yellow: 12, green: 24, gray: 0 };
    for (const i of [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13]) {
      category_counts[i] = { red: 0, yellow: 0, green: 0, gray: 0 };
    }
    const result = grade({ category_counts, critical_red_count: 0 });
    expect(result.letter).toBe('A');
    expect(result.risk_score).toBeLessThanOrEqual(12);
  });

  it('risk > 12 AND critical_reds=0 → B', () => {
    // Cat 4: yellow=13, green=24 → severity=(13)/(111)×100 = 11.71, still ≤12
    // Cat 4: red=1, yellow=0, green=6 → denom=7, severity=(3)/(21)×100 = 14.3 > 12 → B
    const category_counts: GradeInputs['category_counts'] = {};
    category_counts[4] = { red: 1, yellow: 0, green: 6, gray: 0 };
    for (const i of [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13]) {
      category_counts[i] = { red: 0, yellow: 0, green: 0, gray: 0 };
    }
    const result = grade({ category_counts, critical_red_count: 0 });
    expect(result.letter).toBe('B');
    expect(result.risk_score).toBeGreaterThan(12);
    expect(result.risk_score).toBeLessThanOrEqual(20);
  });
});

// ── computeGradeFromFactors integration ─────────────────────────────────────

describe('computeGradeFromFactors()', () => {
  const factorMeta: FactorMeta[] = [
    { id: 'F-001', category_id: 1, is_critical: true },
    { id: 'F-002', category_id: 1, is_critical: false },
    { id: 'F-003', category_id: 4, is_critical: false },
    { id: 'F-004', category_id: 4, is_critical: false },
  ];

  it('all green → A', () => {
    const scores: RawFactorScore[] = [
      { factor_id: 'F-001', score: 'green' },
      { factor_id: 'F-002', score: 'green' },
      { factor_id: 'F-003', score: 'green' },
      { factor_id: 'F-004', score: 'green' },
    ];
    const result = computeGradeFromFactors(scores, factorMeta);
    expect(result.letter).toBe('A');
    expect(result.critical_red_count).toBe(0);
  });

  it('critical factor red → C (only 2 factors in Cat 1, severity=50, score=35)', () => {
    // factorMeta: F-001 (cat1, critical), F-002 (cat1), F-003 (cat4), F-004 (cat4)
    // Cat1: red=1, green=1 → severity = (1×3)/(2×3)×100 = 50 (core-five, weight=1.5)
    // Cat4: green=2 → severity=0 (non-core, weight=1.0)
    // base_risk = (50×1.5 + 0×1.0)/(1.5+1.0) = 30
    // critical_penalty = 5×1 = 5, risk_score = 35
    // Letter: critical_reds=1 (not ≥2), risk_score=35 (≤35 → not D), risk>20 → C
    const scores: RawFactorScore[] = [
      { factor_id: 'F-001', score: 'red' },    // critical
      { factor_id: 'F-002', score: 'green' },
      { factor_id: 'F-003', score: 'green' },
      { factor_id: 'F-004', score: 'green' },
    ];
    const result = computeGradeFromFactors(scores, factorMeta);
    expect(result.critical_red_count).toBe(1);
    expect(result.letter).toBe('C');
  });

  it('gray factors are excluded from severity denominator', () => {
    const scores: RawFactorScore[] = [
      { factor_id: 'F-001', score: 'gray' },
      { factor_id: 'F-002', score: 'gray' },
      { factor_id: 'F-003', score: 'gray' },
      { factor_id: 'F-004', score: 'gray' },
    ];
    const result = computeGradeFromFactors(scores, factorMeta);
    // All gray → denom=0 for all cats → severity=0 → risk_score=0 → A
    expect(result.letter).toBe('A');
    expect(result.risk_score).toBeCloseTo(0);
  });

  it('unknown factor_id is silently skipped', () => {
    const scores: RawFactorScore[] = [
      { factor_id: 'UNKNOWN-999', score: 'red' },
      { factor_id: 'F-001', score: 'green' },
    ];
    const result = computeGradeFromFactors(scores, factorMeta);
    expect(result.critical_red_count).toBe(0);
  });

  it('returns correct output shape', () => {
    const scores: RawFactorScore[] = [
      { factor_id: 'F-001', score: 'green' },
    ];
    const result = computeGradeFromFactors(scores, factorMeta);
    expect(result).toHaveProperty('letter');
    expect(result).toHaveProperty('risk_score');
    expect(result).toHaveProperty('base_risk_score');
    expect(result).toHaveProperty('critical_red_count');
    expect(result).toHaveProperty('critical_penalty');
    expect(result).toHaveProperty('category_severities');
    expect(result).toHaveProperty('cap_applied');
    expect(result).toHaveProperty('cap_reason');
    expect(result).toHaveProperty('category_lights');
  });
});

// ── CAT4_EVENT_CASCADE tests ─────────────────────────────────────────────────
// Python mechanism: in compose.py compute_grade(), when cat_id==4 AND
// has_active_incident AND factor_id in {"RD-F-063","RD-F-066","RD-F-067"},
// the score is capped to "yellow" before it increments by_category_counts.
// critical_red_count is counted from the original (uncapped) score.
//
// Cascade factors: RD-F-063, RD-F-066, RD-F-067 (all Cat 4, non-critical).
// Non-cascade Cat 4 factor: RD-F-060 (not in the cascade set).

describe('computeGradeFromFactors(): CAT4_EVENT_CASCADE', () => {
  // 3 Cat 4 cascade factors + 3 green Cat 4 non-cascade factors.
  // Cat 4 has 6 factors total (denom=6).
  // Without incident: 3 reds → severity = (3×3)/(6×3)×100 = 50 → yellow light
  // With incident: cascade reds capped to yellow → counts = {red:0, yellow:3, green:3}
  //   severity = (0×3 + 3×1)/(6×3)×100 = 3/18×100 = 16.7 → green light
  // Only Cat 4 has denom>0 in this test, so base_risk changes noticeably.
  const cascadeMeta: FactorMeta[] = [
    { id: 'RD-F-063', category_id: 4, is_critical: false },
    { id: 'RD-F-066', category_id: 4, is_critical: false },
    { id: 'RD-F-067', category_id: 4, is_critical: false },
    { id: 'RD-F-060', category_id: 4, is_critical: false }, // not a cascade factor
    { id: 'RD-F-061', category_id: 4, is_critical: false },
    { id: 'RD-F-062', category_id: 4, is_critical: false },
  ];

  const cascadeScores: RawFactorScore[] = [
    { factor_id: 'RD-F-063', score: 'red' }, // cascade-eligible
    { factor_id: 'RD-F-066', score: 'red' }, // cascade-eligible
    { factor_id: 'RD-F-067', score: 'red' }, // cascade-eligible
    { factor_id: 'RD-F-060', score: 'green' },
    { factor_id: 'RD-F-061', score: 'green' },
    { factor_id: 'RD-F-062', score: 'green' },
  ];

  it('has_active_incident=false: cascade reds count as red (higher severity)', () => {
    const result = computeGradeFromFactors(cascadeScores, cascadeMeta, {
      has_active_incident: false,
    });
    // Cat 4 severity = (3×3)/(6×3)×100 = 50
    expect(result.category_severities[4]).toBeCloseTo(50, 1);
    // Display rollup: severity >= 50 → red (spec §2: "red ≥ 50")
    expect(result.category_lights[4]).toBe('red');
    // No critical reds → no penalty
    expect(result.critical_red_count).toBe(0);
  });

  it('has_active_incident=true: cascade reds capped to yellow (lower severity)', () => {
    const result = computeGradeFromFactors(cascadeScores, cascadeMeta, {
      has_active_incident: true,
    });
    // Cat 4 severity = (0×3 + 3×1)/(6×3)×100 = 300/1800 ≈ 16.7
    expect(result.category_severities[4]).toBeCloseTo(16.7, 1);
    expect(result.category_lights[4]).toBe('green');
    // critical_red_count unaffected by cascade cap (factors are non-critical)
    expect(result.critical_red_count).toBe(0);
  });

  it('has_active_incident=true: non-cascade Cat 4 reds are NOT capped', () => {
    // RD-F-060 is not in the cascade set; a red on it stays red even with incident.
    const scoresWithNonCascadeRed: RawFactorScore[] = [
      { factor_id: 'RD-F-060', score: 'red' }, // NOT cascade-eligible
      { factor_id: 'RD-F-061', score: 'green' },
      { factor_id: 'RD-F-062', score: 'green' },
      { factor_id: 'RD-F-063', score: 'red' }, // cascade-eligible → capped to yellow
      { factor_id: 'RD-F-066', score: 'green' },
      { factor_id: 'RD-F-067', score: 'green' },
    ];
    const result = computeGradeFromFactors(scoresWithNonCascadeRed, cascadeMeta, {
      has_active_incident: true,
    });
    // Cat4 effective: red=1 (F-060 stays red), yellow=1 (F-063 capped), green=4
    // severity = (1×3 + 1×1)/(6×3)×100 = 400/1800 ≈ 22.2
    expect(result.category_severities[4]).toBeCloseTo(22.2, 1);
  });

  it('has_active_incident=true: critical_red_count uses original score (not capped)', () => {
    // Make RD-F-063 critical to verify critical count is NOT affected by cascade cap.
    const criticalCascadeMeta: FactorMeta[] = [
      { id: 'RD-F-063', category_id: 4, is_critical: true }, // critical AND cascade
      { id: 'RD-F-060', category_id: 4, is_critical: false },
    ];
    const scores: RawFactorScore[] = [
      { factor_id: 'RD-F-063', score: 'red' }, // cascade-capped for severity; original red for crit count
      { factor_id: 'RD-F-060', score: 'green' },
    ];
    const result = computeGradeFromFactors(scores, criticalCascadeMeta, {
      has_active_incident: true,
    });
    // critical_red_count must be 1: the original score is red, even though
    // the severity computation sees it as yellow.
    expect(result.critical_red_count).toBe(1);
    // Cat 4 severity: effective red=0, yellow=1, green=1 → (0+1)/(2×3)×100=16.7
    expect(result.category_severities[4]).toBeCloseTo(16.7, 1);
  });
});

// ── Fixture-driven tests ──────────────────────────────────────────────────────
// Each fixture supplies GradeInputs (category_counts + critical_red_count)
// and an expected output. See site/tests/fixtures/rubric/*.json.

describe('fixture-driven', () => {
  it('spark: A', () => {
    const result = grade(sparkFixture.inputs as GradeInputs);
    expect(result.letter).toBe(sparkFixture.expected.letter);
    expect(result.risk_score).toBeCloseTo(sparkFixture.expected.risk_score, 1);
  });

  it('aave-v3: B', () => {
    const result = grade(aaveV3Fixture.inputs as GradeInputs);
    expect(result.letter).toBe(aaveV3Fixture.expected.letter);
  });

  it('uniswap-v4: A', () => {
    const result = grade(uniswapV4Fixture.inputs as GradeInputs);
    expect(result.letter).toBe(uniswapV4Fixture.expected.letter);
  });

  it('bridge: D', () => {
    const result = grade(bridgeFixture.inputs as GradeInputs);
    expect(result.letter).toBe(bridgeFixture.expected.letter);
  });

  it('perps-dex: F', () => {
    const result = grade(perpsDexFixture.inputs as GradeInputs);
    expect(result.letter).toBe(perpsDexFixture.expected.letter);
  });
});
