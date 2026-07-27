import { describe, expect, it } from 'vitest';
import { buildFactorAssessmentModel } from './factor-assessment-model';
import { buildAssessmentHeaderModel, formatAssessmentDateUtc } from './assessment-header-model';

const factorAssessment = buildFactorAssessmentModel({
  context: { protocolSlug: 'family', surfaceSlug: 'largest' },
  categories: Array.from({ length: 13 }, (_, index) => ({
    id: index + 1,
    name: `Category ${index + 1}`,
  })),
  factors: [
    { id: 'RD-F-001', name: 'Critical factor', category_id: 1, is_critical: true },
    { id: 'RD-F-002', name: 'Passing factor', category_id: 2 },
  ],
  scores: [
    { factor_id: 'RD-F-001', score: 'red' },
    { factor_id: 'RD-F-002', score: 'green' },
  ],
});

describe('assessment header model', () => {
  it('uses one effective assessment for grade, counts, cap, and UTC date', () => {
    const model = buildAssessmentHeaderModel({
      mode: 'default',
      headlineGrade: 'D',
      riskScore: '40.5',
      gradedAt: '2026-01-01T00:30:00+05:00',
      status: 'under_assessment_review',
      scopeNote: 'Surface-wide assessment.',
      capApplied: 'D',
      capReason: 'Core category cap.',
      factorAssessment,
    });

    expect(model).toMatchObject({
      overview: false,
      grade: 'D',
      meaning: 'Compromised',
      riskScore: 40.5,
      reviewed: 'Dec 31, 2025',
      status: 'under assessment review',
      criticalText: '1 of 1',
      severityText: '1 · 0 · 1',
      assessedText: '2 assessed',
      capApplied: 'D',
      capReason: 'Core category cap.',
    });
  });

  it('hides assessment-specific state in Overview', () => {
    const model = buildAssessmentHeaderModel({
      mode: 'overview',
      headlineGrade: 'A',
      riskScore: 1,
      gradedAt: '2026-01-01T00:00:00Z',
      capApplied: 'F',
      capReason: 'Ignored',
      factorAssessment,
    });

    expect(model).toMatchObject({
      overview: true,
      grade: null,
      riskScore: null,
      reviewed: 'N/A',
      criticalText: 'N/A',
      severityText: 'N/A',
      assessedText: 'N/A',
      capApplied: 'none',
      capReason: null,
    });
  });

  it('formats invalid or absent dates deterministically', () => {
    expect(formatAssessmentDateUtc(null)).toBe('Unavailable');
    expect(formatAssessmentDateUtc('not-a-date')).toBe('Unavailable');
  });
});
