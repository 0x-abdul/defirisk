import { useMemo, useState } from 'preact/hooks';
import styles from './ProtocolListView.module.css';

export type Letter = 'A' | 'B' | 'C' | 'D' | 'F';
export type CategoryLight = 'red' | 'yellow' | 'green' | 'gray';

export interface ProtocolListItem {
  slug: string;
  display_name: string;
  protocol_type: string;
  primary_chain: string;
  headline_grade: Letter | null;
  total_value_secured_usd: number;
  has_active_incident: boolean;
  category_lights: Record<number, CategoryLight>;
}

export interface CategoryMeta {
  id: number;
  name: string;
  short?: string;
}

export interface ChainMeta {
  id: string;
  name: string;
}

interface Props {
  protocols: ProtocolListItem[];
  categories: CategoryMeta[];
  chains?: ChainMeta[];
}

const GRADE_LETTERS: Letter[] = ['A', 'B', 'C', 'D', 'F'];

const DOT_PALETTE = [
  '#5a8dee',
  '#e07b3a',
  '#7a55c4',
  '#2c8a6f',
  '#b8417a',
  '#d4a017',
  '#3a8fb7',
  '#a64949',
  '#5e6b4f',
  '#8e6dcc',
];

function colorFor(slug: string): string {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) & 0xfffffff;
  return DOT_PALETTE[h % DOT_PALETTE.length];
}

function fmtTvl(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0) return '—';
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(1)}M`;
  if (usd >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

const LIGHT_HEIGHTS = [8, 10.5, 13, 15.5, 18];

function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

export default function ProtocolListView({ protocols, categories, chains }: Props) {
  const [chainSel, setChainSel] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<'all' | Letter>('all');
  const [q, setQ] = useState('');
  const [sortKey, setSortKey] = useState<'name' | 'grade' | 'tvl'>('tvl');
  const [sortDir, setSortDir] = useState<-1 | 1>(-1);

  const toggleChain = (chain: string) =>
    setChainSel((prev) => {
      const next = new Set(prev);
      if (next.has(chain)) next.delete(chain);
      else next.add(chain);
      return next;
    });

  const clearFilters = () => {
    setChainSel(new Set());
    setFilter('all');
    setQ('');
  };

  const maxTvl = useMemo(
    () => protocols.reduce((m, p) => Math.max(m, p.total_value_secured_usd || 0), 0),
    [protocols],
  );

  const chainCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of protocols) m.set(p.primary_chain, (m.get(p.primary_chain) ?? 0) + 1);
    return m;
  }, [protocols]);

  const chainEntries = useMemo(() => {
    const order = chains?.map((c) => c.id) ?? [];
    const all = Array.from(chainCounts.keys());
    const ordered = [
      ...order.filter((id) => chainCounts.has(id)),
      ...all.filter((id) => !order.includes(id)).sort(),
    ];
    return ordered.map((id) => ({
      id,
      name: chains?.find((c) => c.id === id)?.name ?? id,
      count: chainCounts.get(id) ?? 0,
    }));
  }, [chainCounts, chains]);

  const gradeCounts = useMemo(() => {
    const m: Record<Letter, number> = { A: 0, B: 0, C: 0, D: 0, F: 0 };
    for (const p of protocols) if (p.headline_grade) m[p.headline_grade]++;
    return m;
  }, [protocols]);

  const filtered = useMemo(() => {
    let arr = protocols.slice();
    if (filter !== 'all') arr = arr.filter((p) => p.headline_grade === filter);
    if (chainSel.size > 0) arr = arr.filter((p) => chainSel.has(p.primary_chain));
    if (q) {
      const qs = q.toLowerCase();
      arr = arr.filter(
        (p) =>
          p.display_name.toLowerCase().includes(qs) ||
          p.protocol_type.toLowerCase().includes(qs),
      );
    }
    arr.sort((a, b) => {
      let v = 0;
      if (sortKey === 'tvl')
        v = (a.total_value_secured_usd || 0) - (b.total_value_secured_usd || 0);
      else if (sortKey === 'name') v = a.display_name.localeCompare(b.display_name);
      else if (sortKey === 'grade')
        v = (a.headline_grade ?? 'Z').localeCompare(b.headline_grade ?? 'Z');
      return v * sortDir;
    });
    return arr;
  }, [protocols, filter, chainSel, q, sortKey, sortDir]);

  const setSort = (k: 'name' | 'grade' | 'tvl') => {
    if (sortKey === k) setSortDir(sortDir === -1 ? 1 : -1);
    else {
      setSortKey(k);
      setSortDir(-1);
    }
  };
  const arr = (k: 'name' | 'grade' | 'tvl') =>
    sortKey === k ? (sortDir === -1 ? ' ↓' : ' ↑') : '';

  return (
    <div>
      <div class={styles.sechead}>
        <div class={styles.left}>
          <span class={styles.num}>01</span>
          <h3>Protocols</h3>
        </div>
        <div class={styles.right}>
          {filtered.length} of {protocols.length} visible
        </div>
      </div>

      <div class={styles.filterbar}>
        <button
          type="button"
          class={cn(styles.f, filter === 'all' && styles.on)}
          onClick={() => setFilter('all')}
          aria-pressed={filter === 'all'}
        >
          All <span class={styles.ct}>{protocols.length}</span>
        </button>
        {GRADE_LETTERS.map((g) => (
          <button
            type="button"
            key={g}
            class={cn(styles.f, filter === g && styles.on)}
            onClick={() => setFilter(g)}
            aria-pressed={filter === g}
          >
            <span class={cn(styles.gpill, styles[g])}>{g}</span> Grade {g}{' '}
            <span class={styles.ct}>{gradeCounts[g]}</span>
          </button>
        ))}
        <label class={styles.right}>
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            placeholder="search…"
            value={q}
            onInput={(e) => setQ((e.target as HTMLInputElement).value)}
            aria-label="Search protocols"
          />
        </label>
      </div>

      <div class={styles.frail}>
        <div class={styles.frow}>
          <span class={styles.flbl}>Chain</span>
          {chainEntries.map((ch) => {
            const on = chainSel.has(ch.id);
            return (
              <button
                type="button"
                key={ch.id}
                class={cn(styles.chip, on && styles.on)}
                onClick={() => toggleChain(ch.id)}
                aria-pressed={on}
              >
                {ch.name}
                {ch.count > 0 && <span class={styles.ct}>{ch.count}</span>}
              </button>
            );
          })}
          <button type="button" class={styles.clr} onClick={clearFilters}>
            Clear
          </button>
        </div>
      </div>

      <div class={styles.hb} role="table" aria-label="Protocols">
        <div class={cn(styles.row, styles.head)} role="row">
          <span role="columnheader">
            <button type="button" class={styles.sortBtn} onClick={() => setSort('name')}>
              Protocol{arr('name')}
            </button>
          </span>
          <span role="columnheader">
            <button type="button" class={styles.sortBtn} onClick={() => setSort('grade')}>
              Grade{arr('grade')}
            </button>
          </span>
          <span role="columnheader" class={styles.alignRight}>
            <button type="button" class={styles.sortBtn} onClick={() => setSort('tvl')}>
              TVL{arr('tvl')}
            </button>
          </span>
          <span role="columnheader">13-cat severity</span>
          <span role="columnheader">Profile</span>
        </div>

        {filtered.map((p) => (
          <a key={p.slug} class={styles.row} role="row" href={`/protocols/${p.slug}/`}>
            <span class={styles.pcell} role="cell">
              <span class={styles.pdot} style={{ background: colorFor(p.slug) }} />
              <span>
                <span class={styles.pname}>{p.display_name}</span>
                <br />
                <span class={styles.ptag}>
                  {p.protocol_type} · {p.primary_chain}
                </span>
              </span>
            </span>
            <span role="cell">
              {p.headline_grade ? (
                <span class={cn(styles['gpill-lg'], styles[p.headline_grade])}>
                  {p.headline_grade}
                </span>
              ) : null}
            </span>
            <span class={styles.alignRight} role="cell">
              <span class={styles.tvl}>{fmtTvl(p.total_value_secured_usd)}</span>
              <span class={styles['tvl-bar']} aria-hidden="true">
                <i
                  style={{
                    width: maxTvl > 0 ? `${((p.total_value_secured_usd || 0) / maxTvl) * 100}%` : '0%',
                  }}
                />
              </span>
            </span>
            <span class={styles.lights} role="cell" aria-label="13-category severity profile">
              {categories.map((c, i) => {
                const l = p.category_lights?.[c.id] ?? 'gray';
                const cls =
                  l === 'red'
                    ? styles.r
                    : l === 'yellow'
                      ? styles.y
                      : l === 'green'
                        ? styles.g
                        : undefined;
                return (
                  <i
                    key={c.id}
                    class={cls}
                    style={{ height: `${LIGHT_HEIGHTS[i % LIGHT_HEIGHTS.length]}px` }}
                  />
                );
              })}
            </span>
            <span class={styles.arrow} role="cell" aria-hidden="true">
              →
            </span>
          </a>
        ))}

        {filtered.length === 0 && (
          <div class={styles.empty}>
            No protocols match the current filters.{' '}
            <button type="button" class={styles.clrLink} onClick={clearFilters}>
              Clear filters
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
