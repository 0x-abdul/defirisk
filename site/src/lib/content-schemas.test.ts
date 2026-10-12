import { describe, expect, it } from 'vitest';

import { factorDetailSchema, factorScoredProtocolSchema } from './content-schemas';

const evidenceRow = {
  protocol_slug: 'alpha',
  protocol_name: 'Alpha',
  score: 'green',
  evidence_summary: 'A public audit identifies the assessed contracts.',
  evidence_detail: 'https://example.com/audits/alpha.pdf#page=3',
  collection_mode: 'manual',
  collected_at: '2026-09-20T00:00:00Z',
  data_as_of: '2026-09-19',
  gap_reason: null,
};

describe('public factor evidence schema', () => {
  it('retains evidence rows without private collector provenance', () => {
    const detail = factorDetailSchema.parse({
      factor: {
        id: 'RD-F-001',
        category_id: 1,
        name: 'Public audit coverage',
        description: 'Coverage of the assessed contracts.',
        scoring_methodology: 'Compare the public audit scope to the assessed contracts.',
        is_critical: true,
        curation_archetype: 'manual',
        introduced_in_rubric: 'v1.7.0',
      },
      scored_protocols: [evidenceRow],
    });
    expect(detail.scored_protocols).toEqual([evidenceRow]);
    expect(detail.scored_protocols[0]).not.toHaveProperty('collected_by');
  });

  it('accepts legacy string provenance while retaining other requirements', () => {
    expect(factorScoredProtocolSchema.parse({ ...evidenceRow, collected_by: 'legacy' }))
      .toEqual({ ...evidenceRow, collected_by: 'legacy' });
    expect(factorScoredProtocolSchema.safeParse({ ...evidenceRow, collected_by: 42 }).success)
      .toBe(false);
    expect(factorScoredProtocolSchema.safeParse({ ...evidenceRow, score: 'unknown' }).success)
      .toBe(false);
    const { evidence_summary: _summary, ...withoutEvidence } = evidenceRow;
    expect(factorScoredProtocolSchema.safeParse(withoutEvidence).success).toBe(false);
  });
});
