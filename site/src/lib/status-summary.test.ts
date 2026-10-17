import { describe, expect, it } from 'vitest';

import { getCadenceCounts, getStatusSummary, listPublishedProtocolSlugs } from './data-loaders';

describe('public status summary', () => {
  it('uses the fixed coverage target and current published numerator', () => {
    const status = getStatusSummary();

    expect(status.protocols_target).toBe(57);
    expect(status.protocols_graded).toBe(listPublishedProtocolSlugs().length);
    expect(status.protocols_pending).toBe(
      Math.max(status.protocols_target - status.protocols_graded, 0)
    );
    expect(status.rubric_version).toBe('v1.7.0');
    expect(status.api_envelope_version).toBe('v1.7.0');
    expect('pipeline_runs' in status).toBe(false);
    expect('per_protocol' in status).toBe(false);
    expect('bucket_freshness' in status).toBe(false);
    expect('schema_version' in status).toBe(false);
  });

  it('derives and asserts cadence totals from factor detail metadata', () => {
    expect(getCadenceCounts()).toEqual({ C: 9, E: 36, S: 115, RT: 24 });
  });
});
