/**
 * data-loaders.ts: build-time JSON readers for the static site.
 *
 * Every page in site/src/pages/ that needs data should import from here.
 * Loaders read from data/api/<RUBRIC_VERSION>/ at build time only; no
 * runtime DB calls (eng-review §1C invariant).
 *
 * Missing-file fallback is intentional: dump.py is the upstream writer; if
 * a file is absent, the loader returns [] (lists) or null (single records)
 * rather than throwing. This lets the build succeed pre-M3 (when most
 * tables are empty) and lets E-14 ship even before per-protocol factor
 * scores exist.
 *
 * All loaders synchronous (Node fs); Astro evaluates Astro.glob and
 * imports during build, not during render.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'astro/zod';

import {
  RUBRIC_VERSION,
  computeGradeFromFactors,
  type RawFactorScore,
  type FactorMeta,
} from './rubric';
import type { ExplorerHack, FacetOptions } from './hack-facets';
import {
  protocolListSchema,
  protocolDetailSchema,
  factorListSchema,
  factorMethodologySchema,
  factorScoredProtocolSchema,
  factorLinkedHackSchema,
  factorDetailSchema,
  hackSchema,
  hackDetailSchema,
  incidentSchema,
} from './content-schemas';

// ── Path resolution ──────────────────────────────────────────────────────────

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function resolveDataRoot(): string {
  if (process.env.DEFIRISK_API_ROOT) {
    return path.resolve(process.env.DEFIRISK_API_ROOT);
  }

  const candidates = [
    path.resolve(process.cwd(), '..', 'data', 'api', RUBRIC_VERSION),
    path.resolve(__dirname, '../../../data/api', RUBRIC_VERSION),
    path.resolve(__dirname, '../../../../data/api', RUBRIC_VERSION),
  ];

  return candidates.find((candidate) => existsSync(candidate)) ?? candidates[0];
}

const DATA_ROOT = resolveDataRoot();

function readJson(relpath: string): unknown {
  const filepath = path.join(DATA_ROOT, relpath);
  if (!existsSync(filepath)) return null;
  // Strip UTF-8 BOM (U+FEFF) if present; some JSON writers emit it
  const raw = readFileSync(filepath, 'utf-8');
  const content = raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;
  return JSON.parse(content);
}

function unwrapEnvelope<T>(envelope: unknown, key: string): T | null {
  if (!envelope || typeof envelope !== 'object') return null;
  const data = (envelope as { data?: Record<string, unknown> }).data;
  if (!data || typeof data !== 'object') return null;
  return (data[key] as T) ?? null;
}

// ── Type aliases re-exported for page consumers ──────────────────────────────

export type Protocol = z.infer<typeof protocolListSchema>;
export type ProtocolDetail = z.infer<typeof protocolDetailSchema>;
export type Factor = z.infer<typeof factorListSchema>;
export type FactorMethodology = z.infer<typeof factorMethodologySchema>;
export type FactorScoredProtocol = z.infer<typeof factorScoredProtocolSchema>;
export type FactorLinkedHack = z.infer<typeof factorLinkedHackSchema>;
export type FactorDetail = z.infer<typeof factorDetailSchema>;
export type Hack = z.infer<typeof hackSchema>;
export type HackDetail = z.infer<typeof hackDetailSchema>;
export type Incident = z.infer<typeof incidentSchema>;

// ── Factor meta cache (used by grade computation) ────────────────────────────

let _cachedFactorMeta: FactorMeta[] | null = null;

function _getFactorMeta(): FactorMeta[] {
  if (_cachedFactorMeta) return _cachedFactorMeta;
  _cachedFactorMeta = listFactors().map((f) => ({
    id: f.id,
    category_id: f.category_id,
    is_critical: f.is_critical,
  }));
  return _cachedFactorMeta;
}

function applyComputedGradeFields(
  detail: ProtocolDetail,
  gradeContext: Record<string, unknown> = detail.protocol as Record<string, unknown>
): ProtocolDetail | null {
  const primarySurface = (
    (detail.surfaces as Array<Record<string, unknown>> | undefined) ?? []
  ).find((surface) => surface.is_primary) as Record<string, unknown> | undefined;
  const surfaceScores = (primarySurface?.factor_scores as RawFactorScore[] | undefined) ?? [];
  const legacyScores = detail.factor_scores as unknown as RawFactorScore[];
  const factorScores = legacyScores.length > 0 ? legacyScores : surfaceScores;
  if (factorScores.length === 0) return null;

  const proto = detail.protocol as Record<string, unknown>;
  const computed = computeGradeFromFactors(factorScores, _getFactorMeta(), {
    has_active_incident: gradeContext.has_active_incident as boolean | null | undefined,
    total_value_secured_usd: gradeContext.total_value_secured_usd as
      number | string | null | undefined,
    launched_at: gradeContext.launched_at as string | null | undefined,
  });
  proto.headline_grade = computed.letter;
  proto.category_lights = computed.category_lights;
  proto.risk_score = computed.risk_score;
  proto.cap_applied = computed.cap_applied;
  proto.cap_reason = computed.cap_reason;
  proto.category_severities = computed.category_severities;

  return detail;
}

// ── List loaders ─────────────────────────────────────────────────────────────

/** All scored protocols. Grade fields are computed fresh from factor_scores;
 *  protocols without a detail file or with empty factor_scores are excluded. */
export function listProtocols(): Protocol[] {
  const env = readJson('index.json');
  const arr = unwrapEnvelope<unknown[]>(env, 'protocols') ?? [];
  const result: Protocol[] = [];

  for (const p of arr) {
    const obj = { ...(p as Record<string, unknown>) };
    const slug = obj.slug as string;

    const detailEnv = readJson(path.join('protocols', `${slug}.json`));
    const detail = unwrapEnvelope<ProtocolDetail>(detailEnv, 'protocol_data');
    if (!detail) continue;

    const computedDetail = applyComputedGradeFields(detail, obj);
    if (!computedDetail) continue;
    obj.headline_grade = (computedDetail.protocol as Record<string, unknown>).headline_grade;
    result.push({ ...obj, id: slug } as Protocol);
  }

  return result;
}

/** All published protocol slugs: i.e. every slug that has a per-protocol
 *  detail file under data/api/<rubric>/protocols/. Since 2026-05-27,
 *  dump.py only writes published protocols to that directory; unpublished
 *  protocols live under data/api/<rubric>/unpublished/<slug>-<token>/ and
 *  are loaded via listUnpublishedReviewEntries() / getProtocolByReviewPath(). */
export function listPublishedProtocolSlugs(): string[] {
  const protocolsDir = path.join(DATA_ROOT, 'protocols');
  if (!existsSync(protocolsDir)) return [];
  return readdirSync(protocolsDir, { withFileTypes: true })
    .filter((d) => d.isFile() && d.name.endsWith('.json'))
    .map((d) => d.name.slice(0, -5));
}

/** Directory entries under data/api/<rubric>/unpublished/. Each entry is a
 *  pre-publication review path of the form "<slug>-<token>", exactly the
 *  string that appears in /unpublished/<review>/ URLs. The token is the
 *  unguessable 8-hex-char value generated by migration 0007; the path
 *  itself is never linked from anywhere on the public site (robots noindex,
 *  sitemap-excluded, no cross-references). */
export function listUnpublishedReviewEntries(): string[] {
  const unpublishedDir = path.join(DATA_ROOT, 'unpublished');
  if (!existsSync(unpublishedDir)) return [];
  return readdirSync(unpublishedDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);
}

/** Load the protocol detail blob for an unpublished review path. Mirrors
 *  getProtocol(slug) for the published case but reads from
 *  data/api/<rubric>/unpublished/<review>/index.json instead of
 *  protocols/<slug>.json. Returns null if the file is absent. Computes the
 *  same M1 v4 derived fields (risk_score, category_lights, cap_*) so the
 *  /unpublished/ route can reuse the published detail layout verbatim. */
export function getProtocolByReviewPath(review: string): ProtocolDetail | null {
  const env = readJson(path.join('unpublished', review, 'index.json'));
  const detail = unwrapEnvelope<ProtocolDetail>(env, 'protocol_data');
  if (!detail) return null;

  return applyComputedGradeFields(detail);
}

/** All hacks in the historical ledger (lightweight rows; per-hack details via getHack). */
export function listHacks(): Hack[] {
  const env = readJson('hacks.json');
  return (unwrapEnvelope<Hack[]>(env, 'hacks') ?? []).map((h) => ({
    ...h,
    linked_factors: h.linked_factors ?? [],
  }));
}

/** All 184 factors in canonical RD-F-NNN order. Methodology blob NOT included
 *  use getFactor(id) for the full record. */
export function listFactors(): Factor[] {
  const env = readJson('factors.json');
  return unwrapEnvelope<Factor[]>(env, 'factors') ?? [];
}

/** All currently-open active incidents (drives the IncidentBanner). Empty
 *  when no protocol is under an active incident. */
export function listIncidents(): Incident[] {
  const env = readJson('incidents.json');
  return unwrapEnvelope<Incident[]>(env, 'incidents') ?? [];
}

// ── Single-record loaders ────────────────────────────────────────────────────

/** Full per-protocol blob: protocol record + deployments + factor_scores +
 *  grade history. Returns null if the detail file is absent or factor_scores
 *  is empty. Grade fields are always computed fresh from factor_scores. */
export function getProtocol(slug: string): ProtocolDetail | null {
  const env = readJson(path.join('protocols', `${slug}.json`));
  const detail = unwrapEnvelope<ProtocolDetail>(env, 'protocol_data');
  if (!detail) return null;

  return applyComputedGradeFields(detail);
}

/** Full per-factor blob: methodology + 7-field template + scored protocols
 *  + linked historical hacks. Returns null if the factor doesn't exist. */
export function getFactor(id: string): FactorDetail | null {
  const env = readJson(path.join('factors', `${id}.json`));
  return unwrapEnvelope<FactorDetail>(env, 'factor_data');
}

/** Full per-hack blob: hack record + linked_factors. Returns null if the
 *  hack doesn't exist. */
export function getHack(id: string): HackDetail | null {
  const env = readJson(path.join('hacks', `${id}.json`));
  return unwrapEnvelope<HackDetail>(env, 'hack_data');
}

// ── Cross-cuts (E-14 Feature A queries) ──────────────────────────────────────

/** Every (protocol, score) pair currently graded for a given factor.
 *  Powers the global factor page's sortable all-protocols table. */
export function listScoresForFactor(
  factorId: string
): NonNullable<FactorDetail['scored_protocols']> {
  return getFactor(factorId)?.scored_protocols ?? [];
}

/** Every hack-factor link curated for a given factor (the Feature A
 *  "related historical hacks" panel). Sorted by occurred_at desc by
 *  dump.py; consumers may re-sort. */
export function listLinkedHacksForFactor(
  factorId: string
): NonNullable<FactorDetail['linked_hacks']> {
  return getFactor(factorId)?.linked_hacks ?? [];
}

// ── Meta / introspection ─────────────────────────────────────────────────────

/** True if a per-factor blob is present (i.e. dump.py has emitted it). */
export function hasFactor(id: string): boolean {
  return existsSync(path.join(DATA_ROOT, 'factors', `${id}.json`));
}

/** Currently active rubric metadata (frozen_at / changelog_url / notes). */
export function getRubric(): {
  version: string;
  frozen_at: string | null;
  changelog_url: string | null;
  notes: string | null;
} | null {
  const env = readJson('rubric.json');
  if (!env || typeof env !== 'object') return null;
  return ((env as { data?: unknown }).data ?? null) as {
    version: string;
    frozen_at: string | null;
    changelog_url: string | null;
    notes: string | null;
  } | null;
}

// ── Hacks explorer (E-33) ────────────────────────────────────────────────────

/** Enrich hacks with chain (from protocol) + factor is_critical flag.
 *  Returns the full ExplorerHack array ready for the faceted explorer. */
export function getHacksWithFacets(): ExplorerHack[] {
  const hacks = listHacks();
  const protocols = listProtocols();
  const factors = listFactors();

  const chainBySlug = new Map(
    protocols.map((p) => {
      const obj = p as unknown as Record<string, unknown>;
      return [obj.slug as string, (obj.primary_chain as string) ?? null];
    })
  );

  const criticalById = new Map(factors.map((f) => [f.id, f.is_critical]));

  return hacks.map((h) => {
    const obj = h as unknown as Record<string, unknown>;
    const slug = (obj.protocol_slug as string | null) ?? null;
    const chain = slug ? (chainBySlug.get(slug) ?? null) : null;
    const year = h.occurred_at ? h.occurred_at.slice(0, 4) : null;

    const linkedFactors = (h.linked_factors ?? []).map((lf) => ({
      factor_id: lf.factor_id,
      relevance: lf.relevance ?? 'related',
      is_critical: criticalById.get(lf.factor_id) ?? false,
    }));

    const lossRaw = obj.loss_usd;
    const loss_usd =
      lossRaw != null
        ? typeof lossRaw === 'string'
          ? parseFloat(lossRaw) || null
          : (lossRaw as number)
        : null;

    return {
      id: h.id,
      protocol_slug: slug,
      protocol_name: h.protocol_name,
      occurred_at: h.occurred_at ?? null,
      loss_usd,
      category: (obj.category as string | null) ?? null,
      root_cause: h.root_cause,
      is_active: Boolean(obj.is_active),
      status: (obj.status as string) ?? 'closed',
      chain,
      year,
      linked_factors: linkedFactors,
      has_critical_factor: linkedFactors.some((lf) => lf.is_critical),
    } satisfies ExplorerHack;
  });
}

/** Derive facet options from the enriched hack list. */
export function getHackFacetOptions(hacks: ExplorerHack[]): FacetOptions {
  const chains = [...new Set(hacks.map((h) => h.chain).filter(Boolean) as string[])].sort();
  const years = [...new Set(hacks.map((h) => h.year).filter(Boolean) as string[])].sort().reverse();
  const categories = [...new Set(hacks.map((h) => h.category).filter(Boolean) as string[])].sort();

  // Derive factor facets: only factors that appear in at least 1 hack
  const factorMap = new Map<string, { name: string; is_critical: boolean; hack_count: number }>();
  for (const h of hacks) {
    for (const lf of h.linked_factors) {
      const existing = factorMap.get(lf.factor_id);
      if (existing) {
        existing.hack_count += 1;
      } else {
        factorMap.set(lf.factor_id, {
          name: lf.factor_id, // name resolved at render time from factor list
          is_critical: lf.is_critical ?? false,
          hack_count: 1,
        });
      }
    }
  }

  const factors = [...factorMap.entries()]
    .map(([id, v]) => ({ id, ...v }))
    .sort((a, b) => b.hack_count - a.hack_count);

  return { chains, years, categories, factors };
}

// ── Grade-change feed (E-34) ──────────────────────────────────────────────────

export type { GradeChange } from './feed-generator';

/** Most recent grade change events (up to 200). Returns [] when changes.json is absent. */
export function listGradeChanges(): import('./feed-generator').GradeChange[] {
  const env = readJson('changes.json');
  return unwrapEnvelope<import('./feed-generator').GradeChange[]>(env, 'changes') ?? [];
}

// ── Status page (E-30) ───────────────────────────────────────────────────────

export interface PipelineRun {
  run_at: string;
  script_name: string;
  cadence_bucket: string | null;
  protocols_touched: number;
  fetchers_invoked: string[];
  success_count: number;
  error_count: number;
  duration_seconds: number | null;
  triggered_by: string;
  error_summary?: { protocol?: string; error?: string }[] | null;
  notes?: string | null;
}

export interface BucketFreshness {
  cadence_bucket: 'C' | 'E' | 'S';
  last_run_at: string | null;
  run_count_30: number;
  total_errors: number;
  total_successes: number;
  success_rate_pct: number | null;
}

export interface ProtocolFreshness {
  slug: string;
  display_name: string;
  letter: string | null;
  graded_at: string | null;
  data_as_of: string | null;
  days_stale: number | null;
}

export interface StatusSummary {
  // System version block
  rubric_version: string;
  rubric_frozen_at: string | null;
  build_sha: string | null;
  schema_version: string;
  generated_at: string;
  // Coverage block
  protocols_target: number;
  protocols_graded: number;
  protocols_pending: number;
  critical_factors_target: number;
  critical_factors_covered: number;
  // Per-protocol freshness (sortable on /status/)
  per_protocol: ProtocolFreshness[];
  // Pipeline runs (Phase 3: populated when status.json is emitted by dump.py)
  pipeline_runs: PipelineRun[];
  pipeline_runs_source: 'live' | 'unwired';
  bucket_freshness: Record<'C' | 'E' | 'S', BucketFreshness>;
}

const COVERAGE_TARGET = 57;
const CRITICAL_FACTOR_TARGET = 20;
const SCHEMA_VERSION = 'v0';

/**
 * Build-time status payload for /status/.
 *
 * Reads existing dump artifacts (rubric.json, index.json, future status.json)
 * and computes a freshness summary across the fleet. Returns null-safe
 * defaults when dumps are absent; page renders honest empty states pre-M3a.
 *
 * When E-30 Phase 3 lands and dump.py emits data/api/<rubric>/status.json,
 * the pipeline_runs section is populated from that file. Until then,
 * pipeline_runs_source is 'unwired' and the page renders a deferred-section
 * placeholder matching ticket acceptance criterion 1.5.
 */
export function getStatusSummary(): StatusSummary {
  const rubric = getRubric();
  const protocols = listProtocols();
  const factors = listFactors();

  const now = Date.now();
  const perProtocol: ProtocolFreshness[] = protocols.map((p) => {
    const obj = p as unknown as Record<string, unknown>;
    const gradedAt = (obj.graded_at as string | null | undefined) ?? null;
    const dataAsOf = (obj.data_as_of as string | null | undefined) ?? null;
    const referenceTs = dataAsOf ?? gradedAt;
    const daysStale = referenceTs
      ? Math.floor((now - new Date(referenceTs).getTime()) / 86400000)
      : null;
    return {
      slug: (obj.slug as string) ?? p.id,
      display_name: (obj.display_name as string) ?? (obj.slug as string) ?? p.id,
      letter: (obj.headline_grade as string | null | undefined) ?? null,
      graded_at: gradedAt,
      data_as_of: dataAsOf,
      days_stale: daysStale,
    };
  });

  const protocolsGraded = perProtocol.filter((p) => p.letter !== null).length;
  const criticalFactorsCovered = factors.filter((f) => f.is_critical).length;

  const emptyBucket = (cadence_bucket: 'C' | 'E' | 'S'): BucketFreshness => ({
    cadence_bucket,
    last_run_at: null,
    run_count_30: 0,
    total_errors: 0,
    total_successes: 0,
    success_rate_pct: null,
  });
  const statusEnv = readJson('status.json') as {
    generated_at?: string;
    data_as_of?: string;
    data?: {
      runs?: PipelineRun[];
      bucket_freshness?: Partial<Record<'C' | 'E' | 'S', BucketFreshness>>;
      meta?: { generated_at?: string; data_as_of?: string };
    };
  } | null;
  const liveRuns = statusEnv?.data?.runs ?? null;
  const bucketFreshness = {
    C: statusEnv?.data?.bucket_freshness?.C ?? emptyBucket('C'),
    E: statusEnv?.data?.bucket_freshness?.E ?? emptyBucket('E'),
    S: statusEnv?.data?.bucket_freshness?.S ?? emptyBucket('S'),
  };
  const generatedAt =
    statusEnv?.data?.meta?.generated_at ?? statusEnv?.generated_at ?? new Date().toISOString();

  return {
    rubric_version: RUBRIC_VERSION,
    rubric_frozen_at: rubric?.frozen_at ?? null,
    build_sha: (import.meta.env.PUBLIC_GIT_SHA as string | undefined) ?? null,
    schema_version: SCHEMA_VERSION,
    generated_at: generatedAt,
    protocols_target: COVERAGE_TARGET,
    protocols_graded: protocolsGraded,
    protocols_pending: COVERAGE_TARGET - protocolsGraded,
    critical_factors_target: CRITICAL_FACTOR_TARGET,
    critical_factors_covered: criticalFactorsCovered,
    per_protocol: perProtocol.sort((a, b) => {
      // sort: most stale first, ungraded last
      if (a.days_stale === null && b.days_stale === null) return 0;
      if (a.days_stale === null) return 1;
      if (b.days_stale === null) return -1;
      return b.days_stale - a.days_stale;
    }),
    pipeline_runs: liveRuns ?? [],
    pipeline_runs_source: liveRuns ? 'live' : 'unwired',
    bucket_freshness: bucketFreshness,
  };
}
