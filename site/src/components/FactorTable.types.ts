/**
 * Type definitions for FactorTable.astro — extracted to a .ts module so
 * type-only imports don't pull the .astro file through esbuild's JS parser
 * (esbuild 0.21.5 + vite 5.4 misroutes union types in .astro frontmatter
 * in some configurations). See FactorTable.astro for the component.
 */

export type FactorLight =
  | 'red'
  | 'yellow'
  | 'green'
  | 'gray'
  | 'not_assessed'
  | 'not_applicable';

export type GapReason =
  | 'protocol_opacity'
  | 'pipeline_unimplemented'
  | 'external_api_blocked'
  | 'requires_curator_input'
  | 'not_applicable';

export interface FactorRow {
  factor_id: string;
  light: FactorLight;
  headline: string;
  evidence?: string;
  /** Why a GRAY / not_assessed cell couldn't be measured (PD-039). */
  gap_reason?: GapReason | null;
  /** Pre-rendered href; rows are non-clickable when omitted. */
  href?: string;
}
