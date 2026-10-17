import { toggleWatched } from '../lib/local-watchlist';
import { useWatchlist } from '../lib/use-watchlist';
import styles from './PublicTools.module.css';

export default function WatchProtocolButton({ slug, name }: { slug: string; name: string }) {
  const { state, ready, notice, update } = useWatchlist();
  const watched = state.entries.some((entry) => entry.slug === slug);
  return (
    <div>
      <button
        class={styles.watchButton}
        type="button"
        disabled={!ready || (!watched && state.entries.length >= 100)}
        aria-pressed={watched}
        onClick={() => update(toggleWatched(state, slug))}
      >
        {watched ? `Unwatch ${name}` : `Watch ${name} in this browser`}
      </button>{' '}
      <a href="/watchlist/">View watchlist</a>
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}
