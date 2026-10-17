import { useEffect, useState } from 'preact/hooks';
import { emptyWatchlist, readWatchlist, WATCHLIST_KEY, type Watchlist } from './local-watchlist';

export function useWatchlist() {
  const [state, setState] = useState(emptyWatchlist);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const load = () => {
      try {
        const parsed = readWatchlist(window.localStorage.getItem(WATCHLIST_KEY));
        setState(parsed.state);
        setNotice(
          parsed.reset
            ? 'Saved watchlist data could not be read. Choose protocols to start again.'
            : ''
        );
      } catch {
        setNotice('Browser storage is unavailable. Changes last only for this page visit.');
      }
      setReady(true);
    };
    load();
    const sync = (event: StorageEvent) => {
      if (event.key === WATCHLIST_KEY || event.key === null) load();
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  const update = (next: Watchlist) => {
    setState(next);
    try {
      window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next));
      setNotice('');
    } catch {
      setNotice('Browser storage is unavailable. Changes last only for this page visit.');
    }
  };
  return { state, ready, notice, update };
}
