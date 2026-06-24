/**
 * curator-sidecar.ts: reads curator-authored protocol fields from
 * data/curator/<RUBRIC_VERSION>/protocols/<slug>.json. Sidecar covers fields that
 * are not yet propagated by the upstream pipeline (verdict_body,
 * multisig + timelock control-surface cells).
 *
 * Returns null when no sidecar exists for a slug; the bulk of protocols
 * sit in that state until a curator pass fills them in.
 *
 * Validation is structural / lightweight: the file is checked-in,
 * code-reviewed JSON. Bad shapes surface at render time as obvious
 * misalignments; we don't need a runtime zod schema here.
 */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { RUBRIC_VERSION } from './rubric';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const CURATOR_ROOT = path.resolve(__dirname, '../../../data/curator', RUBRIC_VERSION);

export type SignalLight = 'green' | 'yellow' | 'red' | 'gray';

export interface SignalCell {
  value: string;
  sub?: string;
  light?: SignalLight;
}

export interface CuratorSidecar {
  slug: string;
  verdict_body?: string | null;
  multisig?: SignalCell | null;
  timelock?: SignalCell | null;
}

const LIGHTS: readonly SignalLight[] = ['green', 'yellow', 'red', 'gray'] as const;

function asSignalCell(v: unknown): SignalCell | null {
  if (!v || typeof v !== 'object') return null;
  const obj = v as Record<string, unknown>;
  if (typeof obj.value !== 'string') return null;
  const cell: SignalCell = { value: obj.value };
  if (typeof obj.sub === 'string') cell.sub = obj.sub;
  if (typeof obj.light === 'string' && (LIGHTS as readonly string[]).includes(obj.light)) {
    cell.light = obj.light as SignalLight;
  }
  return cell;
}

export function loadCuratorSidecar(slug: string): CuratorSidecar | null {
  const filepath = path.join(CURATOR_ROOT, 'protocols', `${slug}.json`);
  if (!existsSync(filepath)) return null;
  const blob = JSON.parse(readFileSync(filepath, 'utf-8')) as Record<string, unknown>;
  if (typeof blob.slug !== 'string') {
    throw new Error(`curator sidecar for "${slug}" missing required string field "slug"`);
  }
  const sidecar: CuratorSidecar = { slug: blob.slug };
  if (typeof blob.verdict_body === 'string' || blob.verdict_body === null) {
    sidecar.verdict_body = blob.verdict_body;
  }
  const ms = asSignalCell(blob.multisig);
  if (ms) sidecar.multisig = ms;
  const tl = asSignalCell(blob.timelock);
  if (tl) sidecar.timelock = tl;
  return sidecar;
}
