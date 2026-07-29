import { describe, expect, it } from 'vitest';
import { PUBLIC_SNAPSHOT_RFC_822 } from './build-metadata';
import { buildRssFeed } from './feed-generator';

describe('grade-change feed', () => {
  it('uses committed snapshot time when the feed is empty', () => {
    expect(buildRssFeed([])).toContain(
      `<lastBuildDate>${PUBLIC_SNAPSHOT_RFC_822}</lastBuildDate>`,
    );
  });
});
