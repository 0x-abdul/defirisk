import {
  buildWatchDigest,
  changesFromFeed,
  markDigestSeen,
  toggleWatched,
} from '../lib/local-watchlist';
import { useWatchlist } from '../lib/use-watchlist';
import { comparisonDate, comparisonHref } from '../lib/protocol-comparison';
import styles from './PublicTools.module.css';

interface Props {
  protocols: { slug: string; name: string }[];
  feed: unknown;
  snapshot: string;
}
export default function LocalWatchlist({ protocols, feed, snapshot }: Props) {
  const { state, ready, notice, update } = useWatchlist();
  const changes = changesFromFeed(feed);
  const digest = buildWatchDigest(state, changes, snapshot);
  const available = state.entries.filter((entry) => protocols.some((p) => p.slug === entry.slug));
  return (
    <div class={styles.tools}>
      <p>
        Your watchlist and read history stay in this browser. No account, email or background
        notifications. Clearing browser storage removes them.
      </p>
      <p>
        Digest snapshot: <b>{comparisonDate(snapshot)} UTC</b>. It uses the existing public
        grade-change JSON Feed (up to 200 events). Older events, factor-only evidence updates and
        changes outside this feed may be absent. This page does not check live assessments.
      </p>
      <div role="status">{!ready ? 'Loading browser watchlist…' : notice}</div>
      {protocols.length === 0 ? (
        <p class={styles.notice}>
          No reviewed protocol assessments are published in this snapshot. You can remove saved
          entries below; new entries will be available after publication.
        </p>
      ) : (
        <div class={styles.controls}>
          <label for="watchlist-add">Watch a protocol</label>
          <select
            id="watchlist-add"
            disabled={!ready || state.entries.length >= 100}
            value=""
            onChange={(event) => {
              if (event.currentTarget.value)
                update(toggleWatched(state, event.currentTarget.value));
            }}
          >
            <option value="">Select a published protocol</option>
            {protocols
              .filter((p) => !state.entries.some((e) => e.slug === p.slug))
              .map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.name}
                </option>
              ))}
          </select>
        </div>
      )}
      {state.entries.length >= 100 && (
        <p>Watchlist limit reached (100). Remove an entry to add another.</p>
      )}
      <h2 id="saved">Watched protocols</h2>
      {ready && state.entries.length === 0 && <p>No protocols saved yet.</p>}
      <div class={styles.cards}>
        {state.entries.map((entry) => {
          const protocol = protocols.find((p) => p.slug === entry.slug);
          return (
            <div key={entry.slug} class={styles.card}>
              {protocol ? (
                <a href={`/protocols/${entry.slug}/`}>{protocol.name}</a>
              ) : (
                <b>{entry.slug} — unavailable in this public snapshot</b>
              )}
              <small>Last marked read: {comparisonDate(entry.lastSeen)} UTC</small>
              <button
                type="button"
                disabled={!ready}
                onClick={() => update(toggleWatched(state, entry.slug))}
              >
                Remove {protocol?.name ?? entry.slug}
              </button>
            </div>
          );
        })}
      </div>
      {available.length >= 2 && (
        <p>
          <a
            href={comparisonHref(
              available.slice(0, 4).map((entry) => ({ protocol: entry.slug, surface: '' }))
            )}
          >
            Compare {Math.min(available.length, 4)} watched protocols
          </a>
        </p>
      )}
      <h2 id="digest">Change digest</h2>
      {digest.rollback && (
        <p class={styles.notice}>
          This public snapshot is older than your saved read history. The digest may be incomplete;
          your last-seen date will be retained.
        </p>
      )}
      {digest.initial && (
        <p>Newly watched protocols show all available feed entries until you mark them read.</p>
      )}
      {ready && state.entries.length > 0 && digest.unread.length === 0 && (
        <p>
          No unread grade changes in the available feed for your saved protocols. This does not
          establish that assessments are current or unchanged.
        </p>
      )}
      {digest.unread.map((change) => (
        <article key={change.id} class={styles.change}>
          <a href={change.url}>{change.title}</a>
          <p>{change.summary}</p>
          <small>{comparisonDate(change.date)} UTC</small>
        </article>
      ))}
      <button
        type="button"
        disabled={!ready || state.entries.length === 0}
        onClick={() => update(markDigestSeen(state, changes, snapshot))}
      >
        Mark available feed entries as read
      </button>
      <p>
        <a href="/changes/">All published grade changes</a> ·{' '}
        <a href="/feeds/grade-changes.json">JSON Feed</a> ·{' '}
        <a href="/feeds/grade-changes.xml">RSS</a>
      </p>
    </div>
  );
}
