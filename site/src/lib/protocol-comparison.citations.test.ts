import { describe, expect, it } from 'vitest';
import { toComparisonProtocol } from './protocol-comparison';

describe('comparison citation preservation', () => {
  it('retains exact public citations with the original scoped evidence and score', () => {
    const sources = [
      {
        source_type: 'docs',
        url: 'https://example.org/caf%C3%A9%20report#page=12',
        retrieved_at: '2026-10-02',
      },
    ];
    const detail = {
      protocol: { display_name: 'Fixture', rubric_version: 'v1.7.0' },
      surfaces: [
        {
          surface_slug: 'core',
          display_name: 'Core',
          factor_scores: [
            {
              factor_id: 'RD-F-001',
              score: 'yellow',
              evidence_summary: 'The cited public report records this scoped finding.',
              data_as_of: '2026-10-02',
              collected_by: 'private collector',
              sources,
            },
          ],
        },
      ],
    };
    const result = toComparisonProtocol('fixture-alpha', detail);
    expect(result?.surfaces[0].scores[0]).toMatchObject({
      factor_id: 'RD-F-001',
      score: 'yellow',
      evidence_summary: detail.surfaces[0].factor_scores[0].evidence_summary,
      data_as_of: '2026-10-02',
      sources,
    });
    expect(result?.surfaces[0].scores[0]).not.toHaveProperty('collected_by');
    expect(detail.surfaces[0].factor_scores[0].sources).toEqual(sources);
  });
});
