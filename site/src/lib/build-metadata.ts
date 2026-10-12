import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import contentMetadata from '../content-metadata.json';
import { RUBRIC_VERSION } from './rubric';

/** Server-only reader of status.data.assessment_snapshot.projection_timestamp.
 * Only the validated public date leaves this module. */
function readProjectionTimestamp(): string {
  const override = process.env.DEFIRISK_API_ROOT;
  if (override !== undefined && !override.trim()) {
    throw new Error('Bound assessment snapshot root is invalid');
  }
  const directory = path.dirname(fileURLToPath(import.meta.url));
  // Match the public data loader's version-root resolution. A frozen build
  // binds DEFIRISK_API_ROOT, so missing snapshot data can never fall back.
  const candidates = [
    path.resolve(process.cwd(), '..', 'data', 'api', RUBRIC_VERSION),
    path.resolve(directory, '../../../data/api', RUBRIC_VERSION),
    path.resolve(directory, '../../../../data/api', RUBRIC_VERSION),
  ];
  const root = override !== undefined
    ? path.resolve(override)
    : candidates.find((candidate) => existsSync(candidate)) ?? candidates[0];

  let status: unknown;
  try {
    const raw = readFileSync(path.join(root, 'status.json'), 'utf-8');
    status = JSON.parse(raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw);
  } catch {
    throw new Error('Bound assessment snapshot is unreadable');
  }
  if (!status || typeof status !== 'object') {
    throw new Error('Bound assessment snapshot is invalid');
  }
  const snapshot = (status as {
    data?: { assessment_snapshot?: { projection_timestamp?: unknown } };
  }).data?.assessment_snapshot;
  const timestamp = snapshot?.projection_timestamp;
  if (typeof timestamp !== 'string' || !Number.isFinite(Date.parse(timestamp))) {
    throw new Error('Bound assessment projection timestamp is invalid');
  }
  return timestamp;
}

const projectionTimestamp = readProjectionTimestamp();

/**
 * Build-visible timestamps come from the reviewed assessment snapshot.
 * They must never depend on the wall clock of the machine performing the build.
 */
export const PUBLIC_SNAPSHOT_TIMESTAMP = projectionTimestamp;
export const PUBLIC_SNAPSHOT_RFC_822 = new Date(projectionTimestamp).toUTCString();
export const CONTENT_LAST_UPDATED = Object.freeze(contentMetadata.last_updated);
