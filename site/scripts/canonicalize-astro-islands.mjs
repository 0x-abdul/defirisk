import { createHash } from 'node:crypto';
import { lstat, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_DIST_ROOT = path.join(SITE_ROOT, 'dist');
const ISLAND_OPEN_TAG = /<astro-island\b[^>]*>/g;
const UID_ATTRIBUTE = /\suid="[^"]*"/g;

function stableIslandUid(openingTag) {
  const uidMatches = openingTag.match(UID_ATTRIBUTE) ?? [];
  if (uidMatches.length !== 1) {
    throw new Error('each astro-island must contain exactly one double-quoted uid attribute');
  }
  if (!/\scomponent-url="[^"]+"/.test(openingTag)) {
    throw new Error('each astro-island must contain a component-url attribute');
  }

  const canonicalTag = openingTag.replace(UID_ATTRIBUTE, '');
  return `dr-${createHash('sha256').update(canonicalTag).digest('hex')}`;
}

export function canonicalizeAstroIslandUids(html) {
  const islandMarkers = html.match(/<astro-island\b/g) ?? [];
  const closingMarkers = html.match(/<\/astro-island>/g) ?? [];
  if (islandMarkers.length !== closingMarkers.length) {
    throw new Error('unbalanced astro-island markup');
  }
  let rewritten = 0;
  const output = html.replace(ISLAND_OPEN_TAG, (openingTag) => {
    rewritten += 1;
    const stableUid = stableIslandUid(openingTag);
    return openingTag.replace(UID_ATTRIBUTE, ` uid="${stableUid}"`);
  });

  if (rewritten !== islandMarkers.length) {
    throw new Error('malformed astro-island opening tag');
  }
  return { html: output, islandCount: rewritten };
}

async function htmlFiles(root) {
  const rootStat = await lstat(root);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error(`build tree is not a safe directory: ${root}`);
  }

  const files = [];
  async function walk(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const absolute = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) {
        throw new Error(`symlink is not permitted in build output: ${absolute}`);
      }
      if (entry.isDirectory()) {
        await walk(absolute);
      } else if (entry.isFile() && entry.name.endsWith('.html')) {
        files.push(absolute);
      }
    }
  }
  await walk(root);
  return files;
}

export async function canonicalizeBuildTree(root = DEFAULT_DIST_ROOT) {
  let fileCount = 0;
  let islandCount = 0;
  for (const file of await htmlFiles(path.resolve(root))) {
    const source = await readFile(file, 'utf8');
    const result = canonicalizeAstroIslandUids(source);
    fileCount += 1;
    islandCount += result.islandCount;
    if (result.html !== source) {
      await writeFile(file, result.html, 'utf8');
    }
  }
  return { fileCount, islandCount };
}

export async function main(argv = process.argv.slice(2)) {
  if (argv.length > 1) {
    throw new Error('usage: canonicalize-astro-islands.mjs [dist-root]');
  }
  const result = await canonicalizeBuildTree(argv[0] ?? DEFAULT_DIST_ROOT);
  console.log(
    `[canonicalize-astro-islands] canonicalized ${result.islandCount} island(s) across ${result.fileCount} HTML file(s)`
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(`[canonicalize-astro-islands] ERROR: ${error.message}`);
    process.exitCode = 1;
  });
}
