import type { FactorAssessmentModel } from '../components/FactorAssessment.types';
import type { Letter } from './rubric';

export const GRADE_MEANING: Record<Letter, string> = {
  A: 'Resilient',
  B: 'Sound',
  C: 'Watch',
  D: 'Compromised',
  F: 'Failing',
};

export const GRADE_VERDICT: Record<Letter, string> = {
  A: 'Strong evidence across categories. No material gaps.',
  B: 'Sound. Minor, well-documented gaps.',
  C: 'Watch. Material gaps; monitor.',
  D: 'Compromised. Meaningful structural risk.',
  F: 'Failing. Disqualifying issues present.',
};

const LETTERS = new Set<Letter>(['A', 'B', 'C', 'D', 'F']);

export interface AssessmentHeaderInput {
  mode: 'default' | 'surface' | 'overview';
  headlineGrade?: unknown;
  riskScore?: unknown;
  gradedAt?: string | null;
  status?: string | null;
  scopeNote?: string | null;
  capApplied?: 'none' | 'D' | 'F' | null;
  capReason?: string | null;
  factorAssessment: FactorAssessmentModel;
}

export interface AssessmentHeaderModel {
  overview: boolean;
  grade: Letter | null;
  meaning: string | null;
  verdict: string | null;
  riskScore: number | null;
  reviewed: string;
  status: string;
  scopeNote: string | null;
  criticalText: string;
  severityText: string;
  assessedText: string;
  capApplied: 'none' | 'D' | 'F';
  capReason: string | null;
}

export function finiteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function formatAssessmentDateUtc(value?: string | null): string {
  if (!value) return 'Unavailable';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return 'Unavailable';
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export function buildAssessmentHeaderModel(input: AssessmentHeaderInput): AssessmentHeaderModel {
  const overview = input.mode === 'overview';
  const grade =
    !overview &&
    typeof input.headlineGrade === 'string' &&
    LETTERS.has(input.headlineGrade as Letter)
      ? (input.headlineGrade as Letter)
      : null;
  const riskScore = overview ? null : finiteNumber(input.riskScore);
  const capApplied =
    !overview && (input.capApplied === 'D' || input.capApplied === 'F') ? input.capApplied : 'none';

  return {
    overview,
    grade,
    meaning: grade ? GRADE_MEANING[grade] : null,
    verdict: grade ? GRADE_VERDICT[grade] : null,
    riskScore,
    reviewed: overview ? 'N/A' : formatAssessmentDateUtc(input.gradedAt),
    status: overview
      ? 'No aggregate assessment'
      : input.status?.replace(/_/g, ' ') || (grade ? 'Active' : 'Pending'),
    scopeNote: overview ? null : (input.scopeNote ?? null),
    criticalText: overview
      ? 'N/A'
      : `${input.factorAssessment.criticalRed} of ${input.factorAssessment.criticalTotal}`,
    severityText: overview
      ? 'N/A'
      : `${input.factorAssessment.totals.red} · ${input.factorAssessment.totals.yellow} · ${input.factorAssessment.totals.green}`,
    assessedText: overview ? 'N/A' : `${input.factorAssessment.assessedTotal} assessed`,
    capApplied,
    capReason: capApplied === 'none' ? null : (input.capReason ?? null),
  };
}
