import type {
  AssessmentScore,
  AssessmentFactorMeta,
  AssessmentCategoryMeta,
} from '../components/FactorAssessment.types';
import { buildFactorAssessmentModel } from './factor-assessment-model';

export interface ComparisonScore extends AssessmentScore {
  data_as_of?: string | null;
  collected_at?: string | null;
  sources?: Record<string, unknown>[];
}
export interface ComparisonSurface {
  slug: string;
  name: string;
  scope: string;
  status: string;
  reviewedAt: string | null;
  scores: ComparisonScore[];
  categoryLights?: Record<string, unknown>;
  categorySeverities?: Record<string, unknown>;
  deployments: string[];
}
export interface ComparisonProtocol {
  slug: string;
  name: string;
  rubricVersion: string;
  surfaces: ComparisonSurface[];
}
export interface ComparisonSelection {
  protocol: string;
  surface: string;
}

/** Public projections only. Drop aliases and copy only fields needed by the UI. */
export function toComparisonProtocol(
  slug: string,
  detail: {
    protocol: Record<string, unknown>;
    surfaces?: Record<string, unknown>[];
    factor_scores?: Record<string, unknown>[];
    deployments?: Record<string, unknown>[];
  }
): ComparisonProtocol | null {
  const protocol = detail.protocol;
  if (protocol.canonical_family_slug && protocol.canonical_family_slug !== slug) return null;
  const text = (value: unknown, fallback = '') => (typeof value === 'string' ? value : fallback);
  const nullableText = (value: unknown) => (typeof value === 'string' ? value : null);
  const records = (value: unknown): Record<string, unknown>[] =>
    Array.isArray(value) ? value.filter((row) => row && typeof row === 'object') : [];
  const surfaces = detail.surfaces?.length
    ? detail.surfaces
    : [
        {
          ...protocol,
          surface_slug: 'default',
          factor_scores: detail.factor_scores ?? [],
          deployments: detail.deployments ?? [],
        },
      ];
  return {
    slug,
    name: text(protocol.display_name, slug),
    rubricVersion: text(protocol.rubric_version, 'Unknown'),
    surfaces: surfaces.map((surface) => ({
      slug: text(surface.surface_slug, 'default'),
      name: text(surface.display_name, 'Protocol assessment'),
      scope: text(surface.scope_note),
      status: text(surface.status, 'Unknown'),
      reviewedAt: nullableText(surface.graded_at),
      scores: records(surface.factor_scores).map((score) => ({
        factor_id: score.factor_id,
        score: score.score,
        evidence_summary: text(score.evidence_summary),
        gap_reason: nullableText(score.gap_reason),
        data_as_of: nullableText(score.data_as_of),
        collected_at: nullableText(score.collected_at),
        sources: records(score.sources).map((source) => ({
          source_type: source.source_type,
          url: source.url,
          ...(source.retrieved_at === undefined ? {} : { retrieved_at: source.retrieved_at }),
        })),
      })),
      categoryLights: surface.category_lights as Record<string, unknown> | undefined,
      categorySeverities: surface.category_severities as Record<string, unknown> | undefined,
      deployments: records(surface.deployments).map((deployment) =>
        text(deployment.display_name, text(deployment.chain, 'Unknown deployment'))
      ),
    })),
  };
}

/** Canonical, bounded selections: at most four distinct reviewed protocols. */
export function resolveComparisonSelections(
  selections: ComparisonSelection[],
  protocols: ComparisonProtocol[]
) {
  const seen = new Set<string>();
  return selections.flatMap((selection) => {
    const protocol = protocols.find((p) => p.slug === selection.protocol);
    if (!protocol || seen.has(protocol.slug) || seen.size === 4) return [];
    const surface =
      protocol.surfaces.find((s) => s.slug === selection.surface) ?? protocol.surfaces[0];
    if (!surface) return [];
    seen.add(protocol.slug);
    return [{ protocol: protocol.slug, surface: surface.slug }];
  });
}

export function readComparisonSearch(search: string, protocols: ComparisonProtocol[]) {
  const params = new URLSearchParams(search);
  return resolveComparisonSelections(
    params.getAll('protocol').map((protocol, i) => ({
      protocol,
      surface: params.getAll('surface')[i] ?? '',
    })),
    protocols
  );
}
export function comparisonHref(selections: ComparisonSelection[]) {
  const params = new URLSearchParams();
  for (const selection of selections.slice(0, 4)) {
    params.append('protocol', selection.protocol);
    params.append('surface', selection.surface);
  }
  return `/compare/${params.size ? `?${params}` : ''}`;
}

export function buildComparisonColumn(
  protocol: ComparisonProtocol,
  surface: ComparisonSurface,
  categories: AssessmentCategoryMeta[],
  factors: AssessmentFactorMeta[]
) {
  const assessment = buildFactorAssessmentModel({
    context: { protocolSlug: protocol.slug, surfaceSlug: surface.slug },
    categories,
    factors,
    scores: surface.scores,
    categoryLights: surface.categoryLights,
    categorySeverities: surface.categorySeverities,
  });
  return { protocol, surface, assessment, missing: factors.length - surface.scores.length };
}

export function comparisonDate(value: string | null | undefined) {
  return value && Number.isFinite(Date.parse(value))
    ? new Date(value).toISOString().slice(0, 10)
    : 'Unavailable';
}
