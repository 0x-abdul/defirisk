export const WATCHLIST_KEY = 'defirisk-watchlist-v1';
const MAX_WATCHED = 100;
const MAX_SEEN = 400;
const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export interface WatchEntry {
  slug: string;
  lastSeen: string | null;
  seenIds: string[];
}
export interface Watchlist {
  version: 1;
  entries: WatchEntry[];
}
export interface DigestChange {
  id: string;
  slug: string;
  title: string;
  summary: string;
  date: string;
  url: string;
}
export const emptyWatchlist = (): Watchlist => ({ version: 1, entries: [] });
export function readWatchlist(raw: string | null): { state: Watchlist; reset: boolean } {
  if (raw === null) return { state: emptyWatchlist(), reset: false };
  try {
    const value = JSON.parse(raw);
    if (value.version !== 1 || !Array.isArray(value.entries) || value.entries.length > MAX_WATCHED)
      throw new Error();
    const entries: WatchEntry[] = [];
    for (const entry of value.entries) {
      if (
        !entry ||
        typeof entry.slug !== 'string' ||
        !slugPattern.test(entry.slug) ||
        (entry.lastSeen !== null &&
          (typeof entry.lastSeen !== 'string' || !Number.isFinite(Date.parse(entry.lastSeen)))) ||
        !Array.isArray(entry.seenIds) ||
        entry.seenIds.length > MAX_SEEN ||
        entry.seenIds.some((id: unknown) => typeof id !== 'string' || id.length > 1000)
      )
        throw new Error();
      if (!entries.some((e) => e.slug === entry.slug))
        entries.push({
          slug: entry.slug,
          lastSeen: entry.lastSeen,
          seenIds: [...new Set<string>(entry.seenIds)],
        });
    }
    return { state: { version: 1, entries }, reset: false };
  } catch {
    return { state: emptyWatchlist(), reset: true };
  }
}
export function toggleWatched(state: Watchlist, slug: string): Watchlist {
  if (!slugPattern.test(slug)) return state;
  if (state.entries.some((e) => e.slug === slug))
    return { version: 1, entries: state.entries.filter((e) => e.slug !== slug) };
  if (state.entries.length >= MAX_WATCHED) return state;
  return { version: 1, entries: [...state.entries, { slug, lastSeen: null, seenIds: [] }] };
}

/** Parse only the existing public JSON Feed fields, refusing off-site event URLs. */
export function changesFromFeed(feed: unknown): DigestChange[] {
  if (!feed || typeof feed !== 'object' || !('items' in feed) || !Array.isArray(feed.items))
    return [];
  const result: DigestChange[] = [];
  for (const item of feed.items.slice(0, 200)) {
    const slug = item?._risk_dashboard?.protocol_slug;
    if (
      typeof slug !== 'string' ||
      !slugPattern.test(slug) ||
      typeof item.id !== 'string' ||
      typeof item.title !== 'string' ||
      typeof item.date_published !== 'string' ||
      !Number.isFinite(Date.parse(item.date_published))
    )
      continue;
    try {
      const url = new URL(item.url, 'https://defirisk.co');
      if (
        url.origin !== 'https://defirisk.co' ||
        !/^\/changes\/[a-zA-Z0-9_-]+\/$/.test(url.pathname)
      )
        continue;
      if (!result.some((change) => change.id === item.id))
        result.push({
          id: item.id,
          slug,
          title: item.title,
          summary: typeof item.content_text === 'string' ? item.content_text : '',
          date: item.date_published,
          url: url.pathname,
        });
    } catch {
      /* Missing or invalid feed item is unavailable, never fabricated. */
    }
  }
  return result.sort((a, b) => Date.parse(b.date) - Date.parse(a.date) || a.id.localeCompare(b.id));
}
export function buildWatchDigest(state: Watchlist, changes: DigestChange[], snapshot: string) {
  const watched = new Map(state.entries.map((entry) => [entry.slug, entry]));
  const unread = changes.filter((change) => {
    const entry = watched.get(change.slug);
    return entry && !entry.seenIds.includes(change.id);
  });
  const snapshotTime = Date.parse(snapshot);
  const rollback = state.entries.some(
    (entry) =>
      entry.lastSeen &&
      (!Number.isFinite(snapshotTime) || Date.parse(entry.lastSeen) > snapshotTime)
  );
  return { unread, rollback, initial: state.entries.some((e) => e.lastSeen === null) };
}
export function markDigestSeen(
  state: Watchlist,
  changes: DigestChange[],
  snapshot: string
): Watchlist {
  if (!Number.isFinite(Date.parse(snapshot))) return state;
  return {
    version: 1,
    entries: state.entries.map((entry) => ({
      ...entry,
      // Viewing an older release must not move the stored cursor backwards.
      lastSeen:
        entry.lastSeen && Date.parse(entry.lastSeen) > Date.parse(snapshot)
          ? entry.lastSeen
          : snapshot,
      seenIds: [
        ...new Set([
          ...entry.seenIds,
          ...changes.filter((c) => c.slug === entry.slug).map((c) => c.id),
        ]),
      ].slice(-MAX_SEEN),
    })),
  };
}
