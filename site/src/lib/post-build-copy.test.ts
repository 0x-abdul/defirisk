import { execFile } from 'node:child_process';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it } from 'vitest';

const execFileAsync = promisify(execFile);
const POST_BUILD_COPY = fileURLToPath(
  new URL('../../scripts/post-build-copy.mjs', import.meta.url)
);
const COMMITTED_API_ROOT = path.resolve(path.dirname(POST_BUILD_COPY), '../../data/api');
const HISTORICAL_VERSIONS = ['v1.5.0', 'v1.6.0', 'v1.7.0'];
const temporaryRoots: string[] = [];

async function listFiles(root: string, prefix = ''): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const relativePath = path.join(prefix, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(path.join(root, entry.name), relativePath)));
    } else {
      files.push(relativePath);
    }
  }

  return files;
}

async function expectByteIdenticalTree(expectedRoot: string, actualRoot: string) {
  const expectedFiles = await listFiles(expectedRoot);
  const actualFiles = await listFiles(actualRoot);
  expect(actualFiles).toEqual(expectedFiles);

  const mismatches: string[] = [];
  await Promise.all(
    expectedFiles.map(async (relativePath) => {
      const [expected, actual] = await Promise.all([
        readFile(path.join(expectedRoot, relativePath)),
        readFile(path.join(actualRoot, relativePath)),
      ]);
      if (!actual.equals(expected)) {
        mismatches.push(relativePath);
      }
    })
  );
  expect(mismatches).toEqual([]);
}

afterEach(async () => {
  await Promise.all(
    temporaryRoots.splice(0).map((root) => rm(root, { force: true, recursive: true }))
  );
});

describe('post-build API copy', () => {
  it(
    'copies every historical tree byte-for-byte despite an API root override',
    { timeout: 30_000 },
    async () => {
      const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'defirisk-post-build-copy-'));
      temporaryRoots.push(temporaryRoot);

      const distRoot = path.join(temporaryRoot, 'dist');
      const poisonRoot = path.join(temporaryRoot, 'future-api', 'v2.0.0');
      await mkdir(distRoot);
      await mkdir(poisonRoot, { recursive: true });
      await writeFile(path.join(distRoot, '_canonical_preview.html'), 'fixture');
      await writeFile(path.join(poisonRoot, 'poison.json'), '{"source":"mutable-active-rubric"}');

      const { stdout } = await execFileAsync(process.execPath, [POST_BUILD_COPY], {
        env: {
          ...process.env,
          DEFIRISK_API_ROOT: poisonRoot,
          DEFIRISK_DIST_ROOT: distRoot,
        },
        encoding: 'utf8',
      });

      const copiedApiRoot = path.join(distRoot, 'api');
      expect(stdout).toContain('[post-build-copy] copied data');
      expect(stdout).not.toContain('v2.0.0');
      expect(await readdir(copiedApiRoot)).toEqual(expect.arrayContaining(HISTORICAL_VERSIONS));
      await expect(readFile(path.join(copiedApiRoot, 'v2.0.0', 'poison.json'))).rejects.toThrow();
      expect(await readdir(distRoot)).not.toContain('_canonical_preview.html');

      for (const version of HISTORICAL_VERSIONS) {
        await expectByteIdenticalTree(
          path.join(COMMITTED_API_ROOT, version),
          path.join(copiedApiRoot, version)
        );
      }
    }
  );
});
