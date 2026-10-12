import { readFileSync } from 'node:fs';
import path from 'node:path';
import { RUBRIC_VERSION } from './rubric';

export function retirementVersions(baseline: unknown): string[] {
  const field = (baseline as { retired_api_versions?: unknown })?.retired_api_versions;
  const value = field === undefined ? [] : field;
  if (!Array.isArray(value) || value.some(v => !['v1.5.0', 'v1.6.0'].includes(v))
    || JSON.stringify(value) !== JSON.stringify([...new Set(value)].sort())) {
    throw new Error('Invalid API retirement metadata');
  }
  return value;
}

/** Server-only: lifecycle labels follow the selected complete build input. */
export function selectedRetiredVersions(): string[] {
  const api = process.env.DEFIRISK_API_TREE_ROOT
    ?? (process.env.DEFIRISK_API_ROOT ? path.dirname(process.env.DEFIRISK_API_ROOT)
      : path.resolve(process.cwd(), '..', 'data/api'));
  const baseline = JSON.parse(readFileSync(path.join(api, 'publication-baseline.json'), 'utf8'));
  if (baseline.current_api_version !== RUBRIC_VERSION) throw new Error('Invalid current API version');
  return retirementVersions(baseline);
}
