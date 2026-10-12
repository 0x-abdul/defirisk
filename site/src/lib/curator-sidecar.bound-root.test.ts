import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let fixtureRoot: string | undefined;

function fixture(): { repository: string; override: string } {
  fixtureRoot = mkdtempSync(path.join(os.tmpdir(), 'defirisk-curator-roots-'));
  return {
    repository: path.join(fixtureRoot, 'repository'),
    override: path.join(fixtureRoot, 'frozen-curator'),
  };
}

function writeSidecar(base: string, slug: string, data: Record<string, unknown>): void {
  const protocols = path.join(base, 'v1.7.0', 'protocols');
  mkdirSync(protocols, { recursive: true });
  writeFileSync(path.join(protocols, `${slug}.json`), JSON.stringify(data));
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
  if (fixtureRoot) rmSync(fixtureRoot, { recursive: true, force: true });
  fixtureRoot = undefined;
});

describe('bound public curator sidecars', () => {
  it('reads the frozen base plus version instead of a different repository default', async () => {
    const { repository, override } = fixture();
    writeSidecar(path.join(repository, 'data', 'curator'), 'example', {
      slug: 'example', verdict_body: 'Repository verdict.',
    });
    const frozen = {
      slug: 'example',
      verdict_body: 'Reviewed frozen verdict.',
      multisig: { value: '3-of-5', sub: 'Reviewed signers', light: 'yellow' },
      timelock: { value: '48 hours', light: 'green' },
    };
    writeSidecar(override, 'example', frozen);
    vi.stubEnv('DEFIRISK_REPOSITORY_ROOT', repository);
    vi.stubEnv('DEFIRISK_CURATOR_ROOT', override);
    vi.resetModules();
    const reader = await import('./curator-sidecar');
    const loaded = reader.loadCuratorSidecar('example');

    expect(loaded).toEqual(frozen);
    expect(JSON.stringify(loaded)).not.toContain(repository);
    expect(JSON.stringify(loaded)).not.toContain(override);
    expect(Object.keys(reader)).toEqual(['loadCuratorSidecar']);
  });

  it('uses the pinned repository default when the base override is absent', async () => {
    const { repository } = fixture();
    const expected = { slug: 'example', verdict_body: 'Pinned repository verdict.' };
    writeSidecar(path.join(repository, 'data', 'curator'), 'example', expected);
    vi.stubEnv('DEFIRISK_REPOSITORY_ROOT', repository);
    vi.stubEnv('DEFIRISK_CURATOR_ROOT', undefined);
    vi.resetModules();
    const { loadCuratorSidecar } = await import('./curator-sidecar');

    expect(loadCuratorSidecar('example')).toEqual(expected);
  });

  it('keeps missing-file null semantics without falling back from the frozen base', async () => {
    const { repository, override } = fixture();
    writeSidecar(path.join(repository, 'data', 'curator'), 'example', {
      slug: 'example', verdict_body: 'Repository verdict that must stay outside this snapshot.',
    });
    mkdirSync(override, { recursive: true });
    vi.stubEnv('DEFIRISK_REPOSITORY_ROOT', repository);
    vi.stubEnv('DEFIRISK_CURATOR_ROOT', override);
    vi.resetModules();
    const { loadCuratorSidecar } = await import('./curator-sidecar');

    expect(loadCuratorSidecar('example')).toBeNull();
  });

  it('preserves the existing field and signal-cell projection semantics', async () => {
    const { override } = fixture();
    writeSidecar(override, 'example', {
      slug: 'example', verdict_body: null, unused: 'ignored',
      multisig: { value: '2-of-3', sub: 'Known signers', light: 'unsupported', unused: 'ignored' },
      timelock: { value: 48, light: 'green' },
    });
    vi.stubEnv('DEFIRISK_CURATOR_ROOT', override);
    vi.resetModules();
    const { loadCuratorSidecar } = await import('./curator-sidecar');

    expect(loadCuratorSidecar('example')).toEqual({
      slug: 'example', verdict_body: null,
      multisig: { value: '2-of-3', sub: 'Known signers' },
    });
  });

  it.each(['', '   ', '\0private-sentinel'])('rejects an invalid explicit base instead of default data: %j', async (invalid) => {
    const { repository } = fixture();
    writeSidecar(path.join(repository, 'data', 'curator'), 'example', {
      slug: 'example', verdict_body: 'Default data must not be used.',
    });
    vi.stubEnv('DEFIRISK_REPOSITORY_ROOT', repository);
    vi.stubEnv('DEFIRISK_CURATOR_ROOT', invalid);
    vi.resetModules();
    const error = await import('./curator-sidecar').catch((caught: Error) => caught);

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe('Bound curator snapshot root is invalid');
    expect((error as Error).message).not.toContain(repository);
    expect((error as Error).message).not.toContain('private-sentinel');
  });
});
