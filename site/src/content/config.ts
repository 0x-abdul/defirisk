/**
 * Content collection schemas: single source of truth for the JSON shapes
 * that flow from `data/api/<RUBRIC_VERSION>/` through the build.
 *
 * The actual file reading lives in `site/src/lib/data-loaders.ts` (Node
 * `fs` against the dump.py output). The zod schemas defined here are
 * imported by data-loaders.ts and used to derive TypeScript types via
 * `z.infer<>`; pages import the types via `Protocol`, `Factor`, etc.
 *
 * The `defineCollection` bindings at the bottom keep Astro's content-
 * collection plumbing wired in case a future change wants to switch from
 * the inline loaders to `getCollection()` semantics.
 */

import { defineCollection, z } from 'astro:content';

// ── Protocols ────────────────────────────────────────────────────────────────

/** Lightweight protocol record from the index.json envelope (list view). */
export const protocolListSchema = z.object({
  id: z.string(),
  slug: z.string(),
  display_name: z.string(),
  protocol_type: z.string(),
  primary_chain: z.string(),
  headline_grade: z.enum(['A', 'B', 'C', 'D', 'F']).nullable().optional(),
  total_value_secured_usd: z.union([z.number(), z.string()]).nullable().optional(),
  graded_at: z.string().nullable().optional(),
  rubric_version: z.string().nullable().optional(),
  status: z.enum([
    'live',
    'under_assessment_review',
    'under_regulatory_review',
    'deprecated',
  ]),
  has_active_incident: z.boolean(),
  // ── M1 v4 rubric fields (v1.7.0+) ──────────────────────────────────────────
  /** Numeric risk score 0–100. Core-five-weighted severity average plus critical-red penalty. */
  risk_score: z.number().min(0).max(100).nullable().optional(),
  /** Per-category severity scores (0–100), keyed by category id as string. */
  category_severities: z.record(z.string(), z.number().min(0).max(100)).nullable().optional(),
  /** Whether a single-category cap override was applied to the letter grade. */
  cap_applied: z.enum(['none', 'D', 'F']).nullable().optional(),
  /** Human-readable reason for the cap, or null when cap_applied is 'none'. */
  cap_reason: z.string().nullable().optional(),
});

/** Full protocol detail from protocols/<slug>.json envelope. */
export const protocolDetailSchema = z.object({
  protocol: z.record(z.unknown()), // shape mirrors db/schema.ts protocols
  deployments: z.array(z.record(z.unknown())).default([]),
  factor_scores: z.array(z.record(z.unknown())).default([]),
  grade_history: z.array(z.record(z.unknown())).default([]),
});

// ── Factors ──────────────────────────────────────────────────────────────────

/** Lightweight factor record from factors.json (index view). */
export const factorListSchema = z.object({
  id: z.string(),
  category_id: z.number().int(),
  name: z.string(),
  description: z.string(),
  is_critical: z.boolean(),
  curation_archetype: z.string(),
  introduced_in_rubric: z.string(),
  deprecated_in_rubric: z.string().nullable().optional(),
});

/** Full factor methodology: appears under `data.factor_data.factor` in
 *  factors/<id>.json. */
export const factorMethodologySchema = z.object({
  id: z.string(),
  category_id: z.number().int(),
  name: z.string(),
  description: z.string(),
  scoring_methodology: z.string(),
  is_critical: z.boolean(),
  curation_archetype: z.string(),
  measurement: z.string().nullable().optional(),
  data_source: z.string().nullable().optional(),
  method: z.string().nullable().optional(),
  output_format: z.string().nullable().optional(),
  cadence: z.string().nullable().optional(),
  evidence_artifact: z.string().nullable().optional(),
  confidence_signal: z.string().nullable().optional(),
  introduced_in_rubric: z.string(),
  deprecated_in_rubric: z.string().nullable().optional(),
});

/** A single (protocol, score) pair as shown in the factor's all-protocols
 *  table. */
export const factorScoredProtocolSchema = z.object({
  protocol_slug: z.string(),
  protocol_name: z.string().nullable().optional(),
  primary_chain: z.string().nullable().optional(),
  deployment_id: z.string().nullable().optional(),
  score: z.enum([
    'green',
    'yellow',
    'red',
    'gray',
    'not_assessed',
    'not_applicable',
  ]),
  evidence_summary: z.string(),
  evidence_detail: z.string().nullable().optional(),
  collection_mode: z.enum(['programmatic', 'manual', 'hybrid']),
  collected_at: z.string(),
  data_as_of: z.string(),
  collected_by: z.string(),
  // PD-039 (2026-05-11): why a GRAY / not_assessed cell couldn't be measured.
  // Null on graded scores (green/yellow/red).
  gap_reason: z
    .enum([
      'protocol_opacity',
      'pipeline_unimplemented',
      'external_api_blocked',
      'requires_curator_input',
      'not_applicable',
    ])
    .nullable()
    .optional(),
});

/** A single linked hack on a factor's "related historical hacks" panel. */
export const factorLinkedHackSchema = z.object({
  hack_id: z.string(),
  relevance: z.string(),
  notes: z.string().nullable().optional(),
  hack_protocol_name: z.string().nullable().optional(),
  hack_protocol_slug: z.string().nullable().optional(),
  occurred_at: z.string().nullable().optional(),
  loss_usd: z.union([z.number(), z.string()]).nullable().optional(),
  root_cause: z.string().nullable().optional(),
});

/** Full per-factor blob from factors/<id>.json envelope. */
export const factorDetailSchema = z.object({
  factor: factorMethodologySchema,
  scored_protocols: z.array(factorScoredProtocolSchema).default([]),
  linked_hacks: z.array(factorLinkedHackSchema).default([]),
});

// ── Hacks ────────────────────────────────────────────────────────────────────

/** Lightweight hack record from hacks.json (ledger). */
const hackLinkedFactorSchema = z.object({
  factor_id: z.string(),
  relevance: z.string().optional(),
  notes: z.string().nullable().optional(),
});

export const hackSchema = z.object({
  id: z.string(),
  protocol_slug: z.string().nullable().optional(),
  protocol_name: z.string(),
  occurred_at: z.string(),
  loss_usd: z.union([z.number(), z.string()]).nullable().optional(),
  category: z.string().nullable().optional(),
  root_cause: z.string(),
  description: z.string(),
  postmortem_url: z.string().nullable().optional(),
  funds_recovered_pct: z.union([z.number(), z.string()]).nullable().optional(),
  is_active: z.boolean(),
  status: z.string(),
  linked_factors: z.array(hackLinkedFactorSchema).default([]),
});

/** Full per-hack blob from hacks/<id>.json. */
export const hackDetailSchema = z.object({
  hack: hackSchema.omit({ linked_factors: true }),
  linked_factors: z.array(hackLinkedFactorSchema).default([]),
});

// ── Incidents ────────────────────────────────────────────────────────────────

export const incidentSchema = z.object({
  id: z.string(),
  protocol_slug: z.string(),
  hack_id: z.string().nullable().optional(),
  severity: z.enum(['advisory', 'critical']),
  headline: z.string(),
  detail_url: z.string().nullable().optional(),
  opened_at: z.string(),
  closed_at: z.string().nullable().optional(),
  status: z.enum(['open', 'closed']),
});

// ── Astro content-collection bindings ────────────────────────────────────────

const protocols = defineCollection({ type: 'data', schema: protocolListSchema });
const factors = defineCollection({ type: 'data', schema: factorListSchema });
const hacks = defineCollection({ type: 'data', schema: hackSchema });
const incidents = defineCollection({ type: 'data', schema: incidentSchema });

export const collections = { protocols, factors, hacks, incidents };
