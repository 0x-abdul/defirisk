import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import {
  canonicalizeAstroIslandUids,
  canonicalizeBuildTree,
} from '../../scripts/canonicalize-astro-islands.mjs';

const temporaryRoots: string[] = [];

function island(uid: string, componentUrl: string, props = '{}'): string {
  return `<astro-island uid="${uid}" component-url="${componentUrl}" component-export="default" renderer-url="/_astro/client.js" props="${props}" ssr client="visible"><div>Rendered</div><!--astro:end--></astro-island>`;
}

afterEach(async () => {
  await Promise.all(
    temporaryRoots.splice(0).map((root) => rm(root, { recursive: true, force: true }))
  );
});

describe('canonicalizeAstroIslandUids', () => {
  it('removes checkout-path-derived UID differences without changing island content', () => {
    const first = island('Z1tOdvM', '/_astro/DeploymentTabs.hash.js', '{&quot;x&quot;:1}');
    const second = island('1VzjBz', '/_astro/DeploymentTabs.hash.js', '{&quot;x&quot;:1}');

    const firstResult = canonicalizeAstroIslandUids(first);
    const secondResult = canonicalizeAstroIslandUids(second);

    expect(firstResult).toEqual(secondResult);
    expect(firstResult.html).toContain('uid="dr-');
    expect(firstResult.html).toContain('component-url="/_astro/DeploymentTabs.hash.js"');
    expect(firstResult.html).toContain('<div>Rendered</div><!--astro:end-->');
  });

  it('is idempotent and assigns content-specific UIDs to multiple islands', () => {
    const source = `${island('first', '/_astro/a.js')}${island('second', '/_astro/b.js')}`;
    const once = canonicalizeAstroIslandUids(source);
    const twice = canonicalizeAstroIslandUids(once.html);
    const uids = [...once.html.matchAll(/\suid="([^"]+)"/g)].map((match) => match[1]);

    expect(twice).toEqual(once);
    expect(uids).toHaveLength(2);
    expect(new Set(uids).size).toBe(2);
  });

  it.each([
    '<astro-island component-url="/_astro/a.js"></astro-island>',
    '<astro-island uid=\'single-quoted\' component-url="/_astro/a.js"></astro-island>',
    '<astro-island uid="one" uid="two" component-url="/_astro/a.js"></astro-island>',
    '<astro-island uid="one"></astro-island>',
  ])('fails closed for an invalid island opening tag', (source) => {
    expect(() => canonicalizeAstroIslandUids(source)).toThrow();
  });

  it('rejects malformed island markup', () => {
    expect(() => canonicalizeAstroIslandUids('<astro-island uid="one"')).toThrow(
      'unbalanced astro-island markup'
    );
  });
});

describe('canonicalizeBuildTree', () => {
  it('rewrites every generated HTML file and leaves other files unchanged', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'defirisk-islands-'));
    temporaryRoots.push(root);
    await mkdir(path.join(root, 'nested'));
    await writeFile(path.join(root, 'index.html'), island('one', '/_astro/a.js'));
    await writeFile(path.join(root, 'nested', 'index.html'), island('two', '/_astro/b.js'));
    await writeFile(path.join(root, 'asset.txt'), 'unchanged');

    const result = await canonicalizeBuildTree(root);

    expect(result).toEqual({ fileCount: 2, islandCount: 2 });
    expect(await readFile(path.join(root, 'index.html'), 'utf8')).toContain('uid="dr-');
    expect(await readFile(path.join(root, 'nested', 'index.html'), 'utf8')).toContain('uid="dr-');
    expect(await readFile(path.join(root, 'asset.txt'), 'utf8')).toBe('unchanged');
  });

  it('rejects symlinks anywhere in the generated tree', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'defirisk-islands-'));
    temporaryRoots.push(root);
    await mkdir(path.join(root, 'outside'));
    await writeFile(path.join(root, 'outside', 'outside.html'), '<p>outside</p>');
    await symlink(
      path.join(root, 'outside'),
      path.join(root, 'linked'),
      process.platform === 'win32' ? 'junction' : 'dir'
    );

    await expect(canonicalizeBuildTree(root)).rejects.toThrow(
      'symlink is not permitted in build output'
    );
  });
});
