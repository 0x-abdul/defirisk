import { describe, expect, it } from 'vitest';
import { buildJsonFeed, type GradeChange } from './feed-generator';
import {
  buildWatchDigest,
  changesFromFeed,
  emptyWatchlist,
  markDigestSeen,
  readWatchlist,
  toggleWatched,
} from './local-watchlist';
const event = (id: string, slug = 'example-one'): GradeChange => ({
  id,
  protocol_slug: slug,
  protocol_name: 'Synthetic reviewed test fixture',
  detected_at: '2026-01-01T00:00:00Z',
  from_grade: 'C',
  to_grade: 'B',
  rubric_version: 'test-only',
  snapshot_date_before: '2025-12-31',
  snapshot_date_after: '2026-01-01',
  is_upgrade: true,
});
const changes = changesFromFeed(
  buildJsonFeed([event('synthetic-a'), event('synthetic-b', 'example-two')])
);
describe('local public watchlist', () => {
  it('starts empty, roundtrips safely and rejects invalid/corrupt/future state', () => {
    expect(readWatchlist(null)).toEqual({ state: emptyWatchlist(), reset: false });
    const saved = toggleWatched(emptyWatchlist(), 'example-one');
    expect(readWatchlist(JSON.stringify(saved))).toEqual({ state: saved, reset: false });
    for (const raw of [
      'bad JSON',
      '{"version":2,"entries":[]}',
      '{"version":1,"entries":[{"slug":"../private","seenIds":[],"lastSeen":null}]}',
      '{"version":1,"entries":[{"slug":"example-one","seenIds":[],"lastSeen":"bad"}]}',
    ])
      expect(readWatchlist(raw).reset).toBe(true);
  });
  it('adds/removes protocols without accounts and caps storage', () => {
    let state = emptyWatchlist();
    for (let i = 0; i < 105; i++) state = toggleWatched(state, `example-${i}`);
    expect(state.entries).toHaveLength(100);
    expect(toggleWatched(state, 'invalid/path')).toBe(state);
    expect(toggleWatched(state, 'example-0').entries).toHaveLength(99);
  });
  it('uses only valid public feed entries and refuses missing/offsite URLs', () => {
    expect(changes).toHaveLength(2);
    expect(changes[0]?.url).toBe('/changes/synthetic-a/');
    expect(changesFromFeed(null)).toEqual([]);
    expect(
      changesFromFeed({
        items: [
          {
            url: 'https://evil.example/changes/a/',
            id: 'a',
            title: 'A',
            date_published: '2026-01-01',
            _risk_dashboard: { protocol_slug: 'example-one' },
          },
        ],
      })
    ).toEqual([]);
  });
  it('filters to watched protocols and uses explicit mark-read history', () => {
    const state = toggleWatched(emptyWatchlist(), 'example-one');
    expect(buildWatchDigest(state, changes, '2026-01-02').unread.map((c) => c.id)).toEqual([
      changes[0]!.id,
    ]);
    const read = markDigestSeen(state, changes, '2026-01-02');
    expect(buildWatchDigest(read, changes, '2026-01-02').unread).toEqual([]);
    // A late-arriving event at the same timestamp must still be unread.
    const later = changesFromFeed(buildJsonFeed([event('synthetic-late')]));
    expect(buildWatchDigest(read, later, '2026-01-03').unread).toEqual(later);
  });
  it('handles older releases, missing feeds and unavailable saved protocols without losing history', () => {
    const state = markDigestSeen(
      toggleWatched(emptyWatchlist(), 'no-longer-published'),
      [],
      '2026-02-01'
    );
    expect(buildWatchDigest(state, [], '2026-01-01').rollback).toBe(true);
    expect(markDigestSeen(state, [], '2026-01-01').entries[0]?.lastSeen).toBe('2026-02-01');
    expect(markDigestSeen(state, [], 'invalid')).toBe(state);
    expect(buildWatchDigest(state, [], '2026-03-01').unread).toEqual([]);
    expect(state.entries[0]?.slug).toBe('no-longer-published');
  });
});
