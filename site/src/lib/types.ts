// Placeholder types mirroring Drizzle schema enums.
// Regenerated via `npm run db:types` once E-03 Drizzle schema is applied.

export type FactorScoreValue =
  | 'green'
  | 'yellow'
  | 'red'
  | 'gray'
  | 'not_assessed'
  | 'not_applicable';

export type CollectionMode = 'programmatic' | 'manual' | 'hybrid';

export type ProtocolStatus =
  | 'live'
  | 'under_assessment_review'
  | 'under_regulatory_review'
  | 'deprecated';

export type IncidentSeverity = 'advisory' | 'critical';

export type IncidentStatus = 'open' | 'closed';

export type SourceType =
  | 'url'
  | 'github'
  | 'etherscan'
  | 'transaction'
  | 'audit_report'
  | 'governance_post'
  | 'docs'
  | 'partner_feed'
  | 'curator_note'
  | 'commit_sha';

export type { Letter, GradeInputs } from './rubric';
