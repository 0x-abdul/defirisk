import { describe, expect, it } from 'vitest';
import {
  buildComparisonColumn,
  comparisonDate,
  comparisonHref,
  readComparisonSearch,
  resolveComparisonSelections,
  toComparisonProtocol,
  type ComparisonProtocol,
} from './protocol-comparison';

// Reviewed for schema/behavior only: invented test examples, never publication data.
const factors = [
  { id: 'TEST-F-001', name: 'Synthetic code factor', category_id: 1 },
  { id: 'TEST-F-002', name: 'Synthetic pending factor', category_id: 1 },
  { id: 'TEST-F-003', name: 'Synthetic missing factor', category_id: 1 },
];
const categories = [{ id: 1, name: 'Synthetic code category' }];
const fixture = (slug: string): ComparisonProtocol => ({
  slug,
  name: `Synthetic ${slug}`,
  rubricVersion: 'test-only',
  surfaces: [
    {
      slug: 'core',
      name: 'Synthetic core',
      status: 'active',
      scope: 'Synthetic scope',
      reviewedAt: null,
      deployments: ['Synthetic chain'],
      scores: [
        {
          factor_id: 'TEST-F-001',
          score: 'red',
          evidence_summary: 'Synthetic evidence',
          data_as_of: '2026-01-01',
        },
        { factor_id: 'TEST-F-002', score: 'not_applicable' },
      ],
    },
    {
      slug: 'legacy',
      name: 'Synthetic legacy',
      status: 'deprecated',
      scope: '',
      reviewedAt: null,
      deployments: [],
      scores: [],
    },
  ],
});
const protocols = [
  'example-one',
  'example-two',
  'example-three',
  'example-four',
  'example-five',
].map(fixture);
describe('public cross-protocol comparison', () => {
  it('roundtrips per-protocol surfaces in the share URL and preserves order', () => {
    const selections = [
      { protocol: 'example-two', surface: 'legacy' },
      { protocol: 'example-one', surface: 'core' },
    ];
    expect(readComparisonSearch(comparisonHref(selections).split('?')[1]!, protocols)).toEqual(
      selections
    );
  });
  it('rejects unavailable/duplicate selections, bounds to four, and falls back for stale surfaces', () => {
    const requested = [
      { protocol: 'absent', surface: 'core' },
      ...protocols.map((p) => ({ protocol: p.slug, surface: 'absent' })),
      { protocol: 'example-one', surface: 'legacy' },
    ];
    expect(resolveComparisonSelections(requested, protocols)).toEqual(
      protocols.slice(0, 4).map((p) => ({ protocol: p.slug, surface: 'core' }))
    );
    expect(readComparisonSearch('?protocol=example-one', [])).toEqual([]);
  });
  it('keeps category severity separate from coverage, not-applicable and missing factors', () => {
    const protocol = protocols[0]!;
    const column = buildComparisonColumn(protocol, protocol.surfaces[0]!, categories, factors);
    expect(column.assessment.assessedTotal).toBe(1);
    expect(column.assessment.factorTotal).toBe(3);
    expect(column.assessment.statusTotals.not_applicable).toBe(1);
    expect(column.missing).toBe(1);
    expect(column.assessment.categories[0]?.severity).toBe(100);
    expect(column).not.toHaveProperty('grade');
    expect(
      buildComparisonColumn(protocol, protocol.surfaces[1]!, categories, factors).assessment
        .assessedTotal
    ).toBe(0);
  });
  it('retains surface-scoped evidence dates, excludes aliases and unnecessary fields', () => {
    expect(
      toComparisonProtocol('alias', { protocol: { canonical_family_slug: 'family' } })
    ).toBeNull();
    const normalized = toComparisonProtocol('example-one', {
      protocol: { display_name: 'Synthetic One', rubric_version: 'test-only', irrelevant: 'omit' },
      surfaces: [
        {
          surface_slug: 'core',
          factor_scores: [
            {
              factor_id: 'TEST-F-001',
              score: 'gray',
              data_as_of: '2026-01-01',
              collected_at: '2026-01-02',
              irrelevant: 'omit',
            },
          ],
        },
      ],
    });
    expect(normalized?.surfaces[0]?.scores[0]?.data_as_of).toBe('2026-01-01');
    expect(normalized?.surfaces[0]?.scores[0]).not.toHaveProperty('irrelevant');
    expect(normalized).not.toHaveProperty('irrelevant');
  });
  it('supports a legacy public assessment without inventing an evidence date', () => {
    const normalized = toComparisonProtocol('example-one', {
      protocol: { display_name: 'Synthetic' },
      factor_scores: [{ factor_id: 'TEST-F-001', score: 'green' }],
    });
    expect(normalized?.surfaces[0]?.slug).toBe('default');
    expect(comparisonDate(normalized?.surfaces[0]?.scores[0]?.data_as_of)).toBe('Unavailable');
    expect(comparisonDate('invalid')).toBe('Unavailable');
    expect(comparisonDate('2026-01-01T23:30:00-05:00')).toBe('2026-01-02');
  });
});
