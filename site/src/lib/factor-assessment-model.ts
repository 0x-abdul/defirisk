import type { FactorLight, FactorRow, GapReason } from '../components/FactorTable.types';
import type {
  BuildFactorAssessmentInput,
  CategoryLight,
  FactorAssessmentCategory,
  FactorAssessmentModel,
  SeverityBar,
} from '../components/FactorAssessment.types';

const SCORE_ORDER: Record<FactorLight, number> = {
  red: 0,
  yellow: 1,
  gray: 2,
  not_assessed: 2,
  not_applicable: 2,
  green: 3,
};

const FACTOR_LIGHTS = new Set<FactorLight>([
  'red',
  'yellow',
  'green',
  'gray',
  'not_assessed',
  'not_applicable',
]);

const CATEGORY_LIGHTS = new Set<CategoryLight>(['red', 'yellow', 'green', 'gray']);

const GAP_REASONS = new Set<GapReason>([
  'protocol_opacity',
  'pipeline_unimplemented',
  'external_api_blocked',
  'requires_curator_input',
  'not_applicable',
]);

function normalizeGapReason(value: string | null | undefined): GapReason | null {
  return value && GAP_REASONS.has(value as GapReason) ? (value as GapReason) : null;
}

function suppliedValue(
  values: Record<string | number, unknown> | null | undefined,
  id: number
): { present: boolean; value: unknown } {
  if (!values || !Object.prototype.hasOwnProperty.call(values, String(id))) {
    return { present: false, value: undefined };
  }
  return { present: true, value: values[String(id)] };
}

function valueLabel(value: unknown): string {
  if (typeof value === 'string') return `"${value}"`;
  if (typeof value === 'number' && Number.isNaN(value)) return 'NaN';
  if (value === Infinity) return 'Infinity';
  if (value === -Infinity) return '-Infinity';
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function severityFor(red: number, yellow: number, green: number): number | undefined {
  const total = red + yellow + green;
  return total > 0 ? ((red * 3 + yellow) / (total * 3)) * 100 : undefined;
}

function lightForSeverity(value: number | undefined): CategoryLight {
  if (value === undefined) return 'gray';
  if (value >= 50) return 'red';
  if (value >= 20) return 'yellow';
  return 'green';
}

function barsFor(red: number, yellow: number, green: number): SeverityBar[] {
  return [
    ...Array<SeverityBar>(red).fill('r'),
    ...Array<SeverityBar>(yellow).fill('y'),
    ...Array<SeverityBar>(green).fill('g'),
  ].slice(0, 18);
}

function contextLabel(input: BuildFactorAssessmentInput): string {
  const parts = [`protocol=${input.context.protocolSlug}`];
  if (input.context.surfaceSlug) parts.push(`surface=${input.context.surfaceSlug}`);
  if (input.context.deploymentId) parts.push(`deployment=${input.context.deploymentId}`);
  return parts.join(', ');
}

function validatedFactorLight(
  value: unknown,
  input: BuildFactorAssessmentInput,
  factorId: string,
  entryIndex: number
): FactorLight {
  if (value === undefined || value === null) return 'gray';
  if (typeof value === 'string' && FACTOR_LIGHTS.has(value as FactorLight)) {
    return value as FactorLight;
  }
  throw new Error(
    `Invalid factor status ${valueLabel(value)} (${contextLabel(input)}, factor=${factorId}, entry_index=${entryIndex})`
  );
}

function suppliedSeverity(
  input: BuildFactorAssessmentInput,
  categoryId: number
): number | undefined {
  const supplied = suppliedValue(input.categorySeverities, categoryId);
  if (!supplied.present || supplied.value === null) return undefined;
  if (
    typeof supplied.value !== 'number' ||
    !Number.isFinite(supplied.value) ||
    supplied.value < 0 ||
    supplied.value > 100
  ) {
    throw new Error(
      `Invalid category severity ${valueLabel(supplied.value)} (${contextLabel(input)}, category_id=${categoryId})`
    );
  }
  return supplied.value;
}

function suppliedCategoryLight(
  input: BuildFactorAssessmentInput,
  categoryId: number
): CategoryLight | undefined {
  const supplied = suppliedValue(input.categoryLights, categoryId);
  if (!supplied.present || supplied.value === null) return undefined;
  if (typeof supplied.value === 'string' && CATEGORY_LIGHTS.has(supplied.value as CategoryLight)) {
    return supplied.value as CategoryLight;
  }
  throw new Error(
    `Invalid category light ${valueLabel(supplied.value)} (${contextLabel(input)}, category_id=${categoryId})`
  );
}

function factorIdLabel(value: unknown): string {
  if (typeof value === 'string') return value.trim() || '<missing>';
  if (value === undefined || value === null) return '<missing>';
  return `<${typeof value}:${String(value)}>`;
}

function isUsableFactorId(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function emptyStatusTotals(): Record<FactorLight, number> {
  return {
    red: 0,
    yellow: 0,
    green: 0,
    gray: 0,
    not_assessed: 0,
    not_applicable: 0,
  };
}

export function mergeAssessmentScores(
  surfaceScores: BuildFactorAssessmentInput['scores'] | undefined,
  deploymentScores: BuildFactorAssessmentInput['scores'] | undefined
): BuildFactorAssessmentInput['scores'] {
  if (!deploymentScores) return surfaceScores ?? [];
  const merged = new Map<string, BuildFactorAssessmentInput['scores'][number]>();
  const malformed: BuildFactorAssessmentInput['scores'] = [];
  for (const score of surfaceScores ?? []) {
    if (isUsableFactorId(score.factor_id)) merged.set(score.factor_id.trim(), score);
    else malformed.push(score);
  }
  for (const score of deploymentScores) {
    if (isUsableFactorId(score.factor_id)) merged.set(score.factor_id.trim(), score);
    else malformed.push(score);
  }
  return [...merged.values(), ...malformed];
}

export function buildFactorAssessmentModel(
  input: BuildFactorAssessmentInput
): FactorAssessmentModel {
  const factorById = new Map(input.factors.map((factor) => [factor.id, factor]));
  const taxonomyTotals = new Map<number, number>();
  for (const factor of input.factors) {
    taxonomyTotals.set(factor.category_id, (taxonomyTotals.get(factor.category_id) ?? 0) + 1);
  }

  const rowsByCategory = new Map<number, FactorRow[]>();
  let red = 0;
  let yellow = 0;
  let green = 0;
  let criticalRed = 0;
  const statusTotals = emptyStatusTotals();

  input.scores.forEach((entry, index) => {
    const factorId = isUsableFactorId(entry.factor_id) ? entry.factor_id.trim() : '';
    const factor = factorById.get(factorId);
    if (!factor) {
      const printable = factorIdLabel(entry.factor_id);
      const kind = factorId ? 'Unknown' : 'Invalid';
      throw new Error(
        `${kind} factor ID "${printable}" (${contextLabel(input)}, entry_index=${index})`
      );
    }

    const light = validatedFactorLight(entry.score, input, factor.id, index);
    statusTotals[light]++;
    if (light === 'red') {
      red++;
      if (factor.is_critical) criticalRed++;
    } else if (light === 'yellow') {
      yellow++;
    } else if (light === 'green') {
      green++;
    }

    const href =
      input.factorHref?.(factor.id, light) ??
      (light !== 'green' && !input.reviewMode
        ? `/protocols/${input.context.protocolSlug}/factors/${factor.id}/`
        : undefined);
    const row: FactorRow = {
      factor_id: factor.id,
      light,
      headline: factor.name,
      evidence: entry.evidence_summary ?? '',
      gap_reason: normalizeGapReason(entry.gap_reason),
      href,
    };
    const categoryRows = rowsByCategory.get(factor.category_id) ?? [];
    categoryRows.push(row);
    rowsByCategory.set(factor.category_id, categoryRows);
  });

  const categories: FactorAssessmentCategory[] = input.categories.map((category) => {
    // Sort only by status. Array sort is stable, so equal-status factors retain the
    // exporter/input order used by the established non-family presentation.
    const rows = [...(rowsByCategory.get(category.id) ?? [])].sort(
      (a, b) => SCORE_ORDER[a.light] - SCORE_ORDER[b.light]
    );
    const categoryRed = rows.filter((row) => row.light === 'red').length;
    const categoryYellow = rows.filter((row) => row.light === 'yellow').length;
    const categoryGreen = rows.filter((row) => row.light === 'green').length;
    const derivedSeverity = severityFor(categoryRed, categoryYellow, categoryGreen);
    const severity = suppliedSeverity(input, category.id) ?? derivedSeverity;
    const light = suppliedCategoryLight(input, category.id) ?? lightForSeverity(severity);
    const taxonomyTotal = taxonomyTotals.get(category.id) ?? 0;
    const categoryStatusTotals = emptyStatusTotals();
    for (const row of rows) categoryStatusTotals[row.light]++;

    return {
      id: category.id,
      name: category.name,
      short: category.short,
      light,
      severity,
      taxonomyTotal,
      scoredTotal: rows.length,
      assessedTotal: categoryRed + categoryYellow + categoryGreen,
      statusTotals: categoryStatusTotals,
      count: `${rows.length} of ${taxonomyTotal}`,
      bars: barsFor(categoryRed, categoryYellow, categoryGreen),
      rows,
    };
  });

  return {
    categories,
    totals: { red, yellow, green },
    statusTotals,
    assessedTotal: red + yellow + green,
    unassessedTotal: statusTotals.gray + statusTotals.not_assessed + statusTotals.not_applicable,
    categoryTotals: {
      red: categories.filter((category) => category.light === 'red').length,
      yellow: categories.filter((category) => category.light === 'yellow').length,
      green: categories.filter((category) => category.light === 'green').length,
    },
    factorTotal: input.factors.length,
    criticalTotal: input.factors.filter((factor) => factor.is_critical).length,
    criticalRed,
  };
}
