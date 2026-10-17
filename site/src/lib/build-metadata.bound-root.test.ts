import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import contentMetadata from '../content-metadata.json';

const originalRoot = process.env.DEFIRISK_API_ROOT;
let fixtureRoot: string | undefined;

function fixtureStatus(timestamp: string): Record<string, unknown> {
  return {
    rubric_version: 'v1.7.0',
    data_as_of: timestamp,
    generated_at: timestamp,
    data: {
      assessment_snapshot: {
        rubric_version: 'v1.7.0',
        published_protocol_count: 0,
        data_as_of: timestamp,
        projection_timestamp: timestamp,
      },
    },
  };
}

function boundRoot(): string {
  fixtureRoot = mkdtempSync(path.join(os.tmpdir(), 'defirisk-metadata-private-root-'));
  process.env.DEFIRISK_API_ROOT = fixtureRoot;
  vi.resetModules();
  return fixtureRoot;
}

afterEach(() => {
  if (originalRoot === undefined) delete process.env.DEFIRISK_API_ROOT;
  else process.env.DEFIRISK_API_ROOT = originalRoot;
  vi.resetModules();
  if (fixtureRoot) rmSync(fixtureRoot, { recursive: true, force: true });
  fixtureRoot = undefined;
});

describe('bound public snapshot metadata', () => {
  it('uses the overridden snapshot and agrees with the status loader', async () => {
    const root = boundRoot();
    const timestamp = '2026-09-23T08:15:00Z';
    writeFileSync(path.join(root, 'status.json'), JSON.stringify(fixtureStatus(timestamp)));
    const metadata = await import('./build-metadata');
    const loaders = await import('./data-loaders');

    expect(metadata.PUBLIC_SNAPSHOT_TIMESTAMP).toBe(timestamp);
    expect(metadata.PUBLIC_SNAPSHOT_RFC_822).toBe(new Date(timestamp).toUTCString());
    expect(loaders.getStatusSummary().generated_at).toBe(timestamp);
    expect(metadata.CONTENT_LAST_UPDATED).toEqual(contentMetadata.last_updated);
    expect(Object.isFrozen(metadata.CONTENT_LAST_UPDATED)).toBe(true);
    expect(JSON.stringify(metadata)).not.toContain(root);
  });

  it('refuses a missing overridden status instead of reading the default tree', async () => {
    const root = boundRoot();
    const error = await import('./build-metadata').catch((caught: Error) => caught);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe('Bound assessment snapshot is unreadable');
    expect((error as Error).message).not.toContain(root);
    expect((error as Error).message).not.toContain('status.json');
  });

  it('keeps invalid JSON and timestamps out of diagnostics', async () => {
    const root = boundRoot();
    const secret = 'password=private-metadata-sentinel';
    writeFileSync(path.join(root, 'status.json'), secret);
    const unreadable = await import('./build-metadata').catch((caught: Error) => caught);
    expect((unreadable as Error).message).toBe('Bound assessment snapshot is unreadable');
    expect((unreadable as Error).message).not.toContain(secret);

    writeFileSync(path.join(root, 'status.json'), JSON.stringify(fixtureStatus(secret)));
    vi.resetModules();
    const invalid = await import('./build-metadata').catch((caught: Error) => caught);
    expect((invalid as Error).message).toBe('Bound assessment projection timestamp is invalid');
    expect((invalid as Error).message).not.toContain(secret);
    expect((invalid as Error).message).not.toContain(root);
  });

  it('refuses a blank override instead of selecting default data', async () => {
    process.env.DEFIRISK_API_ROOT = '';
    vi.resetModules();
    const error = await import('./build-metadata').catch((caught: Error) => caught);
    expect((error as Error).message).toBe('Bound assessment snapshot root is invalid');
  });
});
