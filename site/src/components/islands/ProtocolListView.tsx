import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import styles from './ProtocolListView.module.css';

export type Letter = 'A' | 'B' | 'C' | 'D' | 'F';
export type CategoryLight = 'red' | 'yellow' | 'green' | 'gray';

export interface ProtocolListItem {
  slug: string;
  display_name: string;
  protocol_type: string;
  primary_chain: string;
  deployment_chains?: string[];
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

type SortKey = 'name' | 'grade' | 'tvl';
type SortDir = -1 | 1;
type ListStatus = 'ready' | 'loading' | 'error';

interface Filters {
  chainSel: Set<string>;
  grade: 'all' | Letter;
  q: string;
  sortKey: SortKey;
  sortDir: SortDir;
}

interface Props {
  protocols?: ProtocolListItem[];
  categories: CategoryMeta[];
  chains?: ChainMeta[];
  /** Optional UI state for future async list consumers. Existing static pages remain ready. */
  status?: ListStatus;
  error?: string;
}

const GRADE_LETTERS: Letter[] = ['A', 'B', 'C', 'D', 'F'];
const DEFAULT_FILTERS: Omit<Filters, 'chainSel'> = {
  grade: 'all',
  q: '',
  sortKey: 'tvl',
  sortDir: -1,
};

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
  if (!Number.isFinite(usd) || usd <= 0) return 'N/A';
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(1)}M`;
  if (usd >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

function parseFilters(search: string, chainIds: Set<string>): Filters {
  const params = new URLSearchParams(search);
  const gradeValue = params.get('grade');
  const grade = GRADE_LETTERS.includes(gradeValue as Letter) ? (gradeValue as Letter) : 'all';
  const rawSort = params.get('sort') ?? '';
  const [rawKey, rawDirection] = rawSort.split('-');
  const sortKey: SortKey =
    rawKey === 'name' || rawKey === 'grade' || rawKey === 'tvl' ? rawKey : 'tvl';
  const sortDir: SortDir = rawDirection === 'asc' ? 1 : -1;
  const chainSel = new Set(
    (params.get('chain') ?? '').split(',').filter((chain) => chainIds.has(chain))
  );
  return {
    chainSel,
    grade,
    q: (params.get('q') ?? '').trim(),
    sortKey,
    sortDir,
  };
}

function writeFilters(filters: Filters, replace = false): void {
  const params = new URLSearchParams(window.location.search);
  for (const key of ['q', 'grade', 'chain', 'sort']) params.delete(key);
  if (filters.q) params.set('q', filters.q);
  if (filters.grade !== 'all') params.set('grade', filters.grade);
  if (filters.chainSel.size) params.set('chain', [...filters.chainSel].sort().join(','));
  if (filters.sortKey !== DEFAULT_FILTERS.sortKey || filters.sortDir !== DEFAULT_FILTERS.sortDir) {
    params.set('sort', `${filters.sortKey}-${filters.sortDir === 1 ? 'asc' : 'desc'}`);
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
}

const LIGHT_HEIGHTS = [8, 10.5, 13, 15.5, 18];

export default function ProtocolListView({ protocols, categories, chains, status, error }: Props) {
  const list = protocols ?? [];
  const chainIds = useMemo(
    () =>
      new Set(
        list.flatMap((protocol) =>
          protocol.deployment_chains?.length ? protocol.deployment_chains : [protocol.primary_chain]
        )
      ),
    [list]
  );
  const [filters, setFilters] = useState<Filters>(() =>
    typeof window === 'undefined'
      ? { ...DEFAULT_FILTERS, chainSel: new Set() }
      : parseFilters(window.location.search, chainIds)
  );
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filterTrigger = useRef<HTMLButtonElement>(null);
  const filterSheet = useRef<HTMLElement>(null);
  const listStatus: ListStatus = status ?? (protocols ? 'ready' : 'loading');

  useEffect(() => {
    const onPopState = () => setFilters(parseFilters(window.location.search, chainIds));
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFiltersOpen(false);
    };
    window.addEventListener('popstate', onPopState);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('popstate', onPopState);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [chainIds]);

  useEffect(() => {
    if (!filtersOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !filterSheet.current) return;
      const focusable = [
        ...filterSheet.current.querySelectorAll<HTMLElement>(
          'button,input,[href],[tabindex]:not([tabindex="-1"])'
        ),
      ];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', trapFocus);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', trapFocus);
      filterTrigger.current?.focus();
    };
  }, [filtersOpen]);

  const updateFilters = (update: Partial<Filters>, replace = false) => {
    const next: Filters = {
      ...filters,
      ...update,
      chainSel: update.chainSel ?? filters.chainSel,
    };
    setFilters(next);
    writeFilters(next, replace);
  };

  const toggleChain = (chain: string) => {
    const next = new Set(filters.chainSel);
    if (next.has(chain)) next.delete(chain);
    else next.add(chain);
    updateFilters({ chainSel: next });
  };

  const clearFilters = () => updateFilters({ ...DEFAULT_FILTERS, chainSel: new Set() });

  const maxTvl = useMemo(
    () =>
      list.reduce(
        (maximum, protocol) => Math.max(maximum, protocol.total_value_secured_usd || 0),
        0
      ),
    [list]
  );

  const chainCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const protocol of list) {
      for (const chain of protocol.deployment_chains?.length
        ? protocol.deployment_chains
        : [protocol.primary_chain]) {
        counts.set(chain, (counts.get(chain) ?? 0) + 1);
      }
    }
    return counts;
  }, [list]);

  const chainEntries = useMemo(() => {
    const order = chains?.map((chain) => chain.id) ?? [];
    const all = Array.from(chainCounts.keys());
    const ordered = [
      ...order.filter((id) => chainCounts.has(id)),
      ...all.filter((id) => !order.includes(id)).sort(),
    ];
    return ordered.map((id) => ({
      id,
      name: chains?.find((chain) => chain.id === id)?.name ?? id,
      count: chainCounts.get(id) ?? 0,
    }));
  }, [chainCounts, chains]);

  const gradeCounts = useMemo(() => {
    const counts: Record<Letter, number> = { A: 0, B: 0, C: 0, D: 0, F: 0 };
    for (const protocol of list) if (protocol.headline_grade) counts[protocol.headline_grade]++;
    return counts;
  }, [list]);

  const filtered = useMemo(() => {
    let result = list.slice();
    if (filters.grade !== 'all')
      result = result.filter((protocol) => protocol.headline_grade === filters.grade);
    if (filters.chainSel.size > 0) {
      result = result.filter((protocol) =>
        (protocol.deployment_chains?.length
          ? protocol.deployment_chains
          : [protocol.primary_chain]
        ).some((chain) => filters.chainSel.has(chain))
      );
    }
    if (filters.q) {
      const query = filters.q.toLowerCase();
      result = result.filter(
        (protocol) =>
          protocol.display_name.toLowerCase().includes(query) ||
          protocol.protocol_type.toLowerCase().includes(query)
      );
    }
    result.sort((a, b) => {
      let value: number;
      if (filters.sortKey === 'tvl')
        value = (a.total_value_secured_usd || 0) - (b.total_value_secured_usd || 0);
      else if (filters.sortKey === 'name') value = a.display_name.localeCompare(b.display_name);
      else value = (a.headline_grade ?? 'Z').localeCompare(b.headline_grade ?? 'Z');
      return value * filters.sortDir;
    });
    return result;
  }, [list, filters]);

  const setSort = (key: SortKey) => {
    if (filters.sortKey === key) updateFilters({ sortDir: filters.sortDir === -1 ? 1 : -1 });
    else updateFilters({ sortKey: key, sortDir: -1 });
  };
  const sortLabel = (key: SortKey) =>
    filters.sortKey === key
      ? filters.sortDir === -1
        ? ' descending'
        : ' ascending'
      : ' not sorted';
  const hasFilters = filters.grade !== 'all' || filters.chainSel.size > 0 || Boolean(filters.q);

  const gradeButtons = GRADE_LETTERS.map((grade) => (
    <button
      type="button"
      key={grade}
      class={cn(styles.f, filters.grade === grade && styles.on)}
      onClick={() => updateFilters({ grade })}
      aria-pressed={filters.grade === grade}
    >
      <span class={cn(styles.gpill, styles[grade])}>{grade}</span> Grade {grade}{' '}
      <span class={styles.ct}>{gradeCounts[grade]}</span>
    </button>
  ));

  const chainButtons = chainEntries.map((chain) => {
    const selected = filters.chainSel.has(chain.id);
    return (
      <button
        type="button"
        key={chain.id}
        class={cn(styles.chip, selected && styles.on)}
        onClick={() => toggleChain(chain.id)}
        aria-pressed={selected}
      >
        {chain.name}
        {chain.count > 0 && <span class={styles.ct}>{chain.count}</span>}
      </button>
    );
  });

  if (listStatus === 'loading') {
    return (
      <div class={styles.state} aria-live="polite">
        Loading protocol coverage&hellip;
      </div>
    );
  }

  if (listStatus === 'error') {
    return (
      <div class={styles.state} role="alert">
        <p>Protocol coverage could not be loaded{error ? `: ${error}` : '.'}</p>
        <button type="button" class={styles.clrLink} onClick={() => window.location.reload()}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <div>
      <div class={styles.sechead}>
        <div class={styles.left}>
          <span class={styles.num}>01</span>
          <h3>Protocols</h3>
        </div>
        <div class={styles.right} aria-live="polite">
          {filtered.length} of {list.length} visible
        </div>
      </div>

      <div class={styles.filterbar}>
        <button
          ref={filterTrigger}
          type="button"
          class={cn(styles.f, filters.grade === 'all' && styles.on)}
          onClick={() => updateFilters({ grade: 'all' })}
          aria-pressed={filters.grade === 'all'}
        >
          All <span class={styles.ct}>{list.length}</span>
        </button>
        {gradeButtons}
        <label class={styles.search}>
          <span aria-hidden="true">Search</span>
          <input
            type="search"
            placeholder="Search protocols"
            value={filters.q}
            onInput={(event) =>
              updateFilters({ q: (event.target as HTMLInputElement).value }, true)
            }
            aria-label="Search protocols"
          />
        </label>
        <button
          type="button"
          class={styles.filtersTrigger}
          aria-expanded={filtersOpen}
          aria-controls="protocol-list-filters"
          onClick={() => setFiltersOpen(true)}
        >
          Filters
          {hasFilters
            ? ` (${Number(filters.grade !== 'all') + filters.chainSel.size + Number(Boolean(filters.q))})`
            : ''}
        </button>
      </div>

      {hasFilters && (
        <div class={styles.activeFilters} aria-label="Active filters">
          {filters.q && (
            <button type="button" onClick={() => updateFilters({ q: '' })}>
              Search: {filters.q} <span aria-hidden="true">x</span>
            </button>
          )}
          {filters.grade !== 'all' && (
            <button type="button" onClick={() => updateFilters({ grade: 'all' })}>
              Grade {filters.grade} <span aria-hidden="true">x</span>
            </button>
          )}
          {[...filters.chainSel].map((id) => (
            <button type="button" key={id} onClick={() => toggleChain(id)}>
              {chainEntries.find((chain) => chain.id === id)?.name ?? id}{' '}
              <span aria-hidden="true">x</span>
            </button>
          ))}
          <button type="button" class={styles.clearAll} onClick={clearFilters}>
            Clear all
          </button>
        </div>
      )}

      <div class={styles.frail}>
        <div class={styles.frow}>
          <span class={styles.flbl}>Chain</span>
          {chainButtons}
          {hasFilters && (
            <button type="button" class={styles.clr} onClick={clearFilters}>
              Clear
            </button>
          )}
        </div>
      </div>

      {filtersOpen && (
        <div class={styles.sheetBackdrop} onClick={() => setFiltersOpen(false)}>
          <section
            ref={filterSheet}
            id="protocol-list-filters"
            class={styles.filterSheet}
            role="dialog"
            aria-modal="true"
            aria-label="Filter protocols"
            onClick={(event) => event.stopPropagation()}
          >
            <div class={styles.sheetHeader}>
              <h4>Filters</h4>
              <button
                type="button"
                onClick={() => setFiltersOpen(false)}
                aria-label="Close filters"
                autoFocus
              >
                Close
              </button>
            </div>
            <label class={styles.sheetSearch}>
              Search protocols
              <input
                type="search"
                value={filters.q}
                onInput={(event) =>
                  updateFilters({ q: (event.target as HTMLInputElement).value }, true)
                }
              />
            </label>
            <fieldset class={styles.sheetGroup}>
              <legend>Grade</legend>
              <button
                type="button"
                class={cn(styles.chip, filters.grade === 'all' && styles.on)}
                onClick={() => updateFilters({ grade: 'all' })}
              >
                All grades
              </button>
              {GRADE_LETTERS.map((grade) => (
                <button
                  type="button"
                  key={grade}
                  class={cn(styles.chip, filters.grade === grade && styles.on)}
                  onClick={() => updateFilters({ grade })}
                >
                  Grade {grade}
                </button>
              ))}
            </fieldset>
            <fieldset class={styles.sheetGroup}>
              <legend>Chain</legend>
              {chainButtons}
            </fieldset>
            <div class={styles.sheetActions}>
              <button type="button" class={styles.clearAll} onClick={clearFilters}>
                Clear all
              </button>
              <button type="button" class={styles.apply} onClick={() => setFiltersOpen(false)}>
                Show {filtered.length} protocols
              </button>
            </div>
          </section>
        </div>
      )}

      <div class={styles.hb} role="table" aria-label="Protocols">
        <div class={cn(styles.row, styles.head)} role="row">
          <span role="columnheader">
            <button
              type="button"
              class={styles.sortBtn}
              onClick={() => setSort('name')}
              aria-label={`Sort by protocol${sortLabel('name')}`}
            >
              Protocol
            </button>
          </span>
          <span role="columnheader">
            <button
              type="button"
              class={styles.sortBtn}
              onClick={() => setSort('grade')}
              aria-label={`Sort by grade${sortLabel('grade')}`}
            >
              Grade
            </button>
          </span>
          <span role="columnheader" class={styles.alignRight}>
            <button
              type="button"
              class={styles.sortBtn}
              onClick={() => setSort('tvl')}
              aria-label={`Sort by TVL${sortLabel('tvl')}`}
            >
              TVL
            </button>
          </span>
          <span role="columnheader">13-cat severity</span>
          <span role="columnheader">Profile</span>
        </div>

        {filtered.map((protocol) => (
          <a
            key={protocol.slug}
            class={styles.row}
            role="row"
            href={`/protocols/${protocol.slug}/`}
          >
            <span class={styles.pcell} role="cell">
              <span class={styles.pdot} style={{ background: colorFor(protocol.slug) }} />
              <span>
                <span class={styles.pname}>{protocol.display_name}</span>
                <br />
                <span class={styles.ptag}>
                  {protocol.protocol_type} &middot; {protocol.primary_chain}
                </span>
              </span>
            </span>
            <span role="cell">
              {protocol.headline_grade ? (
                <span class={cn(styles['gpill-lg'], styles[protocol.headline_grade])}>
                  {protocol.headline_grade}
                </span>
              ) : (
                <span class={styles.ungraded}>N/A</span>
              )}
            </span>
            <span class={styles.alignRight} role="cell">
              <span class={styles.tvl}>{fmtTvl(protocol.total_value_secured_usd)}</span>
              <span class={styles['tvl-bar']} aria-hidden="true">
                <i
                  style={{
                    width:
                      maxTvl > 0
                        ? `${((protocol.total_value_secured_usd || 0) / maxTvl) * 100}%`
                        : '0%',
                  }}
                />
              </span>
            </span>
            <span class={styles.lights} role="cell" aria-label="13-category severity profile">
              {categories.map((category, index) => {
                const light = protocol.category_lights?.[category.id] ?? 'gray';
                const className =
                  light === 'red'
                    ? styles.r
                    : light === 'yellow'
                      ? styles.y
                      : light === 'green'
                        ? styles.g
                        : undefined;
                return (
                  <i
                    key={category.id}
                    class={className}
                    style={{
                      height: `${LIGHT_HEIGHTS[index % LIGHT_HEIGHTS.length]}px`,
                    }}
                  />
                );
              })}
            </span>
            <span class={styles.arrow} role="cell" aria-hidden="true">
              &rarr;
            </span>
          </a>
        ))}

        {filtered.length === 0 && (
          <div class={styles.empty}>
            <p>No protocols match the current filters.</p>
            <button type="button" class={styles.clrLink} onClick={clearFilters}>
              Clear filters
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
