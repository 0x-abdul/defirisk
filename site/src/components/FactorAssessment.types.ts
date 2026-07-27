import type { FactorLight, FactorRow, GapReason } from './FactorTable.types';

export type CategoryLight = 'red' | 'yellow' | 'green' | 'gray';
export type SeverityBar = 'r' | 'y' | 'g';

export interface AssessmentCategoryMeta {
  id: number;
  name: string;
  short?: string;
}

export interface AssessmentFactorMeta {
  id: string;
  name: string;
  category_id: number;
  is_critical?: boolean;
}

export interface AssessmentScore {
  /** API input is intentionally untrusted; the model validates IDs and statuses. */
  factor_id?: unknown;
  score?: unknown;
  evidence_summary?: string;
  gap_reason?: GapReason | string | null;
}

export interface AssessmentContext {
  protocolSlug: string;
  surfaceSlug?: string | null;
  deploymentId?: string | null;
}

export interface BuildFactorAssessmentInput {
  context: AssessmentContext;
  categories: AssessmentCategoryMeta[];
  factors: AssessmentFactorMeta[];
  scores: AssessmentScore[];
  categoryLights?: Record<string | number, unknown> | null;
  categorySeverities?: Record<string | number, unknown> | null;
  reviewMode?: boolean;
  factorHref?: (factorId: string, light: FactorLight) => string | undefined;
}

export interface FactorAssessmentCategory {
  id: number;
  name: string;
  short?: string;
  light: CategoryLight;
  severity?: number;
  taxonomyTotal: number;
  scoredTotal: number;
  assessedTotal: number;
  statusTotals: Record<FactorLight, number>;
  count: string;
  bars: SeverityBar[];
  rows: FactorRow[];
}

export interface FactorAssessmentModel {
  categories: FactorAssessmentCategory[];
  totals: {
    red: number;
    yellow: number;
    green: number;
  };
  /** Effective factor statuses after surface/deployment evidence is resolved. */
  statusTotals: Record<FactorLight, number>;
  /** Factors with a red, yellow, or green effective status. */
  assessedTotal: number;
  /** Factors without a red, yellow, or green effective status. */
  unassessedTotal: number;
  categoryTotals: {
    red: number;
    yellow: number;
    green: number;
  };
  factorTotal: number;
  criticalTotal: number;
  criticalRed: number;
}
