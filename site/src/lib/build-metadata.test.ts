import { describe, expect, it } from 'vitest';
import status from '../../../data/api/v1.7.0/status.json';
import {
  CONTENT_LAST_UPDATED,
  PUBLIC_SNAPSHOT_RFC_822,
  PUBLIC_SNAPSHOT_TIMESTAMP,
} from './build-metadata';

describe('committed build metadata', () => {
  it('derives stable display values from the assessment snapshot', () => {
    const committed = status.data.assessment_snapshot.projection_timestamp;
    expect(PUBLIC_SNAPSHOT_TIMESTAMP).toBe(committed);
    expect(PUBLIC_SNAPSHOT_RFC_822).toBe(new Date(committed).toUTCString());
  });

  it('keeps documentation dates in explicit versioned metadata', () => {
    expect(CONTENT_LAST_UPDATED).toEqual({
      about: '2026-07-29',
      contributions: '2026-07-29',
      data: '2026-07-29',
      methodology: '2026-07-29',
    });
  });
});
