import { describe, expect, it } from 'vitest';
import { buildFactorAssessmentModel, mergeAssessmentScores } from './factor-assessment-model';

const categories = [
  { id: 1, name: 'Code & audits' },
  { id: 2, name: 'Governance & admin' },
  { id: 3, name: 'Oracle risk' },
];

const factors = [
  { id: 'RD-F-001', name: 'Source verified', category_id: 1, is_critical: true },
  { id: 'RD-F-002', name: 'Recent audit', category_id: 1 },
  { id: 'RD-F-003', name: 'Admin controls', category_id: 2 },
  { id: 'RD-F-004', name: 'Oracle fallback', category_id: 2 },
];

describe('buildFactorAssessmentModel', () => {
  it('merges partial deployment overrides over surface evidence', () => {
    expect(
      mergeAssessmentScores(
        [
          { factor_id: 'RD-F-001', score: 'yellow', evidence_summary: 'Surface evidence.' },
          { factor_id: 'RD-F-002', score: 'green' },
        ],
        [
          {
            factor_id: 'RD-F-001',
            score: 'red',
            evidence_summary: 'Deployment override.',
          },
        ]
      )
    ).toEqual([
      { factor_id: 'RD-F-001', score: 'red', evidence_summary: 'Deployment override.' },
      { factor_id: 'RD-F-002', score: 'green' },
    ]);
  });

  it('preserves malformed rows so contextual validation cannot be bypassed', () => {
    const scores = mergeAssessmentScores(
      [{ factor_id: 'RD-F-001', score: 'green' }],
      [{ factor_id: '', score: 'red' }]
    );

    expect(() =>
      buildFactorAssessmentModel({
        context: { protocolSlug: 'family', surfaceSlug: 'v2', deploymentId: 'base' },
        categories,
        factors,
        scores,
      })
    ).toThrow(
      'Invalid factor ID "<missing>" (protocol=family, surface=v2, deployment=base, entry_index=1)'
    );
  });

  it('builds every taxonomy category and preserves non-family ordering and counts', () => {
    const model = buildFactorAssessmentModel({
      context: { protocolSlug: 'fixture' },
      categories,
      factors,
      categoryLights: { 1: 'yellow', 2: 'red' },
      categorySeverities: { 1: 25, 2: 67 },
      scores: [
        { factor_id: 'RD-F-002', score: 'green', evidence_summary: 'Covered.' },
        { factor_id: 'RD-F-001', score: 'red', evidence_summary: 'Missing.' },
        {
          factor_id: 'RD-F-004',
          score: 'not_assessed',
          gap_reason: 'pipeline_unimplemented',
        },
        { factor_id: 'RD-F-003', score: 'yellow' },
      ],
    });

    expect(model.categories).toHaveLength(3);
    expect(model.categories[0]).toMatchObject({
      light: 'yellow',
      severity: 25,
      count: '2 of 2',
      bars: ['r', 'g'],
    });
    expect(model.categories[0].rows.map((row) => row.factor_id)).toEqual(['RD-F-001', 'RD-F-002']);
    expect(model.categories[2]).toMatchObject({
      light: 'gray',
      count: '0 of 0',
      rows: [],
    });
    expect(model.totals).toEqual({ red: 1, yellow: 1, green: 1 });
    expect(model.statusTotals).toEqual({
      red: 1,
      yellow: 1,
      green: 1,
      gray: 0,
      not_assessed: 1,
      not_applicable: 0,
    });
    expect(model.assessedTotal).toBe(3);
    expect(model.unassessedTotal).toBe(1);
    expect(model.categoryTotals).toEqual({ red: 1, yellow: 1, green: 0 });
    expect(model.criticalRed).toBe(1);
    expect(model.criticalTotal).toBe(1);
  });

  it('uses the family severity fallback only when supplied rollups are absent', () => {
    const model = buildFactorAssessmentModel({
      context: { protocolSlug: 'family', surfaceSlug: 'v2' },
      categories,
      factors,
      scores: [
        { factor_id: 'RD-F-001', score: 'yellow' },
        { factor_id: 'RD-F-002', score: 'green' },
      ],
    });

    expect(model.categories[0].severity).toBeCloseTo(16.6667, 3);
    expect(model.categories[0].light).toBe('green');
  });

  it('fails with complete assessment context for unknown factor IDs', () => {
    expect(() =>
      buildFactorAssessmentModel({
        context: {
          protocolSlug: 'family',
          surfaceSlug: 'v2',
          deploymentId: 'ethereum-core',
        },
        categories,
        factors,
        scores: [{ factor_id: 'RD-F-999', score: 'red' }],
      })
    ).toThrow(
      'Unknown factor ID "RD-F-999" (protocol=family, surface=v2, deployment=ethereum-core, entry_index=0)'
    );
  });

  it('uses supplied effective severity for a category light when no light is supplied', () => {
    const model = buildFactorAssessmentModel({
      context: { protocolSlug: 'family', surfaceSlug: 'v2' },
      categories,
      factors,
      // Raw rows look green, but the effective rollup says this category is red.
      categorySeverities: { 1: 81 },
      scores: [
        { factor_id: 'RD-F-001', score: 'green' },
        { factor_id: 'RD-F-002', score: 'green' },
      ],
    });

    expect(model.categories[0]).toMatchObject({ severity: 81, light: 'red' });
  });

  it('keeps exporter order for equal-status factors', () => {
    const model = buildFactorAssessmentModel({
      context: { protocolSlug: 'fixture' },
      categories,
      factors,
      scores: [
        { factor_id: 'RD-F-002', score: 'yellow' },
        { factor_id: 'RD-F-001', score: 'yellow' },
      ],
    });

    expect(model.categories[0]?.rows.map((row) => row.factor_id)).toEqual(['RD-F-002', 'RD-F-001']);
  });

  it('rejects non-string factor IDs with full entry context', () => {
    expect(() =>
      buildFactorAssessmentModel({
        context: {
          protocolSlug: 'family',
          surfaceSlug: 'v2',
          deploymentId: 'ethereum-core',
        },
        categories,
        factors,
        scores: [{ factor_id: 42, score: 'red' }],
      })
    ).toThrow(
      'Invalid factor ID "<number:42>" (protocol=family, surface=v2, deployment=ethereum-core, entry_index=0)'
    );
  });

  it('keeps all 13 caller taxonomy categories and effective status counts', () => {
    const taxonomy = Array.from({ length: 13 }, (_, index) => ({
      id: index + 1,
      name: `Category ${index + 1}`,
    }));
    const taxonomyFactors = taxonomy.map((category) => ({
      id: `RD-F-${String(category.id).padStart(3, '0')}`,
      name: `Factor ${category.id}`,
      category_id: category.id,
      is_critical: category.id === 1,
    }));
    const model = buildFactorAssessmentModel({
      context: { protocolSlug: 'fixture', surfaceSlug: 'largest-tvl' },
      categories: taxonomy,
      factors: taxonomyFactors,
      categoryLights: { 2: 'yellow' },
      categorySeverities: { 1: 78, 2: 2 },
      scores: [
        { factor_id: 'RD-F-001', score: 'green' },
        { factor_id: 'RD-F-002', score: 'not_assessed' },
        { factor_id: 'RD-F-003', score: 'red' },
        { factor_id: 'RD-F-004', score: 'not_applicable' },
      ],
    });

    expect(model.categories).toHaveLength(13);
    expect(model.categories[0]).toMatchObject({ light: 'red', count: '1 of 1' });
    expect(model.categories[1]).toMatchObject({ light: 'yellow', count: '1 of 1' });
    expect(model.categories.slice(4).every((category) => category.light === 'gray')).toBe(true);
    expect(model.statusTotals).toEqual({
      red: 1,
      yellow: 0,
      green: 1,
      gray: 0,
      not_assessed: 1,
      not_applicable: 1,
    });
    expect(model.assessedTotal).toBe(2);
    expect(model.unassessedTotal).toBe(2);
  });

  it.each(['red', 'yellow', 'green', 'gray', 'not_assessed', 'not_applicable'])(
    'accepts the supported factor status %s',
    (score) => {
      const model = buildFactorAssessmentModel({
        context: { protocolSlug: 'family', surfaceSlug: 'v2' },
        categories,
        factors,
        scores: [{ factor_id: 'RD-F-001', score }],
      });

      expect(model.categories[0]?.rows[0]?.light).toBe(score);
    }
  );

  it.each(['amber', '', ' red ', 42, {}])(
    'rejects an invalid factor status with full context',
    (score) => {
      expect(() =>
        buildFactorAssessmentModel({
          context: {
            protocolSlug: 'family',
            surfaceSlug: 'v2',
            deploymentId: 'base',
          },
          categories,
          factors,
          scores: [{ factor_id: 'RD-F-001', score }],
        })
      ).toThrow(
        /Invalid factor status .+ \(protocol=family, surface=v2, deployment=base, factor=RD-F-001, entry_index=0\)/
      );
    }
  );

  it('maps missing and null factor statuses to gray', () => {
    for (const score of [undefined, null]) {
      const model = buildFactorAssessmentModel({
        context: { protocolSlug: 'family' },
        categories,
        factors,
        scores: [{ factor_id: 'RD-F-001', score }],
      });
      expect(model.categories[0]?.rows[0]?.light).toBe('gray');
    }
  });

  it.each([0, -0, 50, 100])('accepts category severity boundary %s', (severity) => {
    const model = buildFactorAssessmentModel({
      context: { protocolSlug: 'family', surfaceSlug: 'v2' },
      categories,
      factors,
      categorySeverities: { 1: severity },
      scores: [{ factor_id: 'RD-F-001', score: 'green' }],
    });
    expect(model.categories[0]?.severity).toBe(severity);
  });

  it.each([-0.1, 100.1, Number.NaN, Infinity, -Infinity, '50', ''])(
    'rejects invalid category severity %s',
    (severity) => {
      expect(() =>
        buildFactorAssessmentModel({
          context: { protocolSlug: 'family', surfaceSlug: 'v2' },
          categories,
          factors,
          categorySeverities: { 1: severity },
          scores: [{ factor_id: 'RD-F-001', score: 'green' }],
        })
      ).toThrow(/Invalid category severity .+ \(protocol=family, surface=v2, category_id=1\)/);
    }
  );

  it.each(['red', 'yellow', 'green', 'gray'])(
    'accepts the supported category light %s',
    (light) => {
      const model = buildFactorAssessmentModel({
        context: { protocolSlug: 'family', surfaceSlug: 'v2' },
        categories,
        factors,
        categoryLights: { 1: light },
        scores: [{ factor_id: 'RD-F-001', score: 'green' }],
      });
      expect(model.categories[0]?.light).toBe(light);
    }
  );

  it.each(['amber', 'RED', '', 1])('rejects invalid category light %s', (light) => {
    expect(() =>
      buildFactorAssessmentModel({
        context: { protocolSlug: 'family', surfaceSlug: 'v2' },
        categories,
        factors,
        categoryLights: { 1: light },
        scores: [{ factor_id: 'RD-F-001', score: 'green' }],
      })
    ).toThrow(/Invalid category light .+ \(protocol=family, surface=v2, category_id=1\)/);
  });

  it('derives category values when supplied rollups are missing or null', () => {
    for (const supplied of [undefined, { 1: null }]) {
      const model = buildFactorAssessmentModel({
        context: { protocolSlug: 'family', surfaceSlug: 'v2' },
        categories,
        factors,
        categoryLights: supplied,
        categorySeverities: supplied,
        scores: [{ factor_id: 'RD-F-001', score: 'red' }],
      });
      expect(model.categories[0]).toMatchObject({ light: 'red', severity: 100 });
    }
  });
});
