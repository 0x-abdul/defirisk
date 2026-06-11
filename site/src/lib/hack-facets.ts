/**
 * hack-facets.ts — Facet derivation + URL-state serializer for the hacks explorer (E-33).
 */

export interface ExplorerHack {
  id: string;
  protocol_slug: string | null;
  protocol_name: string;
  occurred_at: string | null;
  loss_usd: number | null;
  category: string | null;
  root_cause: string;
  is_active: boolean;
  status: string;
  chain: string | null;
  year: string | null;
  linked_factors: Array<{ factor_id: string; relevance: string; is_critical?: boolean }>;
  has_critical_factor: boolean;
}

export interface FacetOptions {
  chains: string[];
  years: string[];
  categories: string[];
  factors: Array<{ id: string; name: string; is_critical: boolean; hack_count: number }>;
}

export interface ExplorerFilters {
  chains: string[];
  years: string[];
  categories: string[];
  factorIds: string[];
  criticalOnly: boolean;
  lossMin: number | null;
  lossMax: number | null;
  sort: 'date_desc' | 'date_asc' | 'loss_desc' | 'factors_desc' | 'alpha';
  page: number;
}

export const DEFAULT_FILTERS: ExplorerFilters = {
  chains: [],
  years: [],
  categories: [],
  factorIds: [],
  criticalOnly: false,
  lossMin: null,
  lossMax: null,
  sort: 'date_desc',
  page: 1,
};

export const PAGE_SIZE = 50;

// ── Filtering ─────────────────────────────────────────────────────────────────

export function applyFilters(hacks: ExplorerHack[], f: ExplorerFilters): ExplorerHack[] {
  let result = hacks;

  if (f.chains.length > 0) {
    result = result.filter((h) => h.chain && f.chains.includes(h.chain));
  }
  if (f.years.length > 0) {
    result = result.filter((h) => h.year && f.years.includes(h.year));
  }
  if (f.categories.length > 0) {
    result = result.filter((h) => h.category && f.categories.includes(h.category));
  }
  if (f.factorIds.length > 0) {
    result = result.filter((h) =>
      h.linked_factors.some((lf) => f.factorIds.includes(lf.factor_id)),
    );
  }
  if (f.criticalOnly) {
    result = result.filter((h) => h.has_critical_factor);
  }
  if (f.lossMin != null) {
    result = result.filter((h) => h.loss_usd != null && h.loss_usd >= f.lossMin!);
  }
  if (f.lossMax != null) {
    result = result.filter((h) => h.loss_usd == null || h.loss_usd <= f.lossMax!);
  }

  // Sort
  result = [...result].sort((a, b) => {
    switch (f.sort) {
      case 'date_asc':
        return (a.occurred_at ?? '').localeCompare(b.occurred_at ?? '');
      case 'loss_desc':
        return (b.loss_usd ?? 0) - (a.loss_usd ?? 0);
      case 'factors_desc':
        return b.linked_factors.length - a.linked_factors.length;
      case 'alpha':
        return a.protocol_name.localeCompare(b.protocol_name);
      default: // date_desc
        return (b.occurred_at ?? '').localeCompare(a.occurred_at ?? '');
    }
  });

  return result;
}

export function paginateResults<T>(items: T[], page: number, size = PAGE_SIZE): T[] {
  return items.slice((page - 1) * size, page * size);
}

export function totalPages(count: number, size = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(count / size));
}

// ── URL-state serializer ──────────────────────────────────────────────────────

export function filtersToParams(f: ExplorerFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.chains.length) p.set('chain', f.chains.join(','));
  if (f.years.length) p.set('year', f.years.join(','));
  if (f.categories.length) p.set('class', f.categories.join(','));
  if (f.factorIds.length) p.set('factor', f.factorIds.join(','));
  if (f.criticalOnly) p.set('critical', '1');
  if (f.lossMin != null) p.set('loss_min', String(f.lossMin));
  if (f.lossMax != null) p.set('loss_max', String(f.lossMax));
  if (f.sort !== 'date_desc') p.set('sort', f.sort);
  if (f.page > 1) p.set('page', String(f.page));
  return p;
}

export function paramsToFilters(search: string): ExplorerFilters {
  const p = new URLSearchParams(search);
  return {
    chains: p.get('chain') ? p.get('chain')!.split(',').filter(Boolean) : [],
    years: p.get('year') ? p.get('year')!.split(',').filter(Boolean) : [],
    categories: p.get('class') ? p.get('class')!.split(',').filter(Boolean) : [],
    factorIds: p.get('factor') ? p.get('factor')!.split(',').filter(Boolean) : [],
    criticalOnly: p.get('critical') === '1',
    lossMin: p.get('loss_min') ? Number(p.get('loss_min')) : null,
    lossMax: p.get('loss_max') ? Number(p.get('loss_max')) : null,
    sort: (p.get('sort') as ExplorerFilters['sort']) ?? 'date_desc',
    page: p.get('page') ? Math.max(1, parseInt(p.get('page')!, 10)) : 1,
  };
}

// ── Formatting helpers ────────────────────────────────────────────────────────

export function fmtLoss(v: number | null | undefined): string {
  if (v == null || v === 0) return '—';
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v}`;
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return '—';
  return s.slice(0, 10);
}
