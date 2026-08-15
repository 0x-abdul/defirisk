/**
 * post-build-copy.mjs — copy the canonical API data dumps into site/dist/.
 *
 * The reviewed public projection lives at <repo>/data/api/ (committed JSON).
 * Astro builds to <repo>/site/dist/. The public API surface defined in
 * eng-review-2026-04-23.md §1E is at /api/<rubric>/, which means the files
 * need to be served from <repo>/site/dist/api/<rubric>/.
 *
 * This script runs as a postbuild step (npm run build = `astro build` AND
 * this copy). The same npm command runs in the Cloudflare Pages build, so
 * the deploy artifact contains the API responses alongside the static
 * pages.
 */

import { cp, access, constants, readdir, unlink } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SITE_ROOT = path.resolve(__dirname, '..'); // .../site
const REPO_ROOT = path.resolve(SITE_ROOT, '..'); // repo root
const COMMITTED_API_ROOT = path.join(REPO_ROOT, 'data', 'api');

export function resolveBuildPaths(env = process.env) {
  const distRoot = env.DEFIRISK_DIST_ROOT
    ? path.resolve(env.DEFIRISK_DIST_ROOT)
    : path.join(SITE_ROOT, 'dist');

  return {
    sourceRoot: COMMITTED_API_ROOT,
    distRoot,
    destinationRoot: path.join(distRoot, 'api'),
  };
}

async function exists(p) {
  try {
    await access(p, constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

export async function copyCommittedApiTree({ env = process.env, log = console.log } = {}) {
  const { sourceRoot, distRoot, destinationRoot } = resolveBuildPaths(env);

  if (!(await exists(sourceRoot))) {
    throw new Error(
      `[post-build-copy] ERROR: source not found: ${sourceRoot}\n` +
        '[post-build-copy]   Restore the reviewed committed API projection.'
    );
  }
  if (!(await exists(path.dirname(destinationRoot)))) {
    throw new Error('[post-build-copy] ERROR: site/dist/ not found — run `astro build` first.');
  }

  await cp(sourceRoot, destinationRoot, { recursive: true });
  log(
    `[post-build-copy] copied ${path.relative(REPO_ROOT, sourceRoot)} → ${path.relative(REPO_ROOT, destinationRoot)}`
  );

  // Strip canonical-preview fixtures from dist/. They live in public/ so the
  // dev server can serve them for visual-rebuild verification, but they should
  // not ship to production — they're design-system internals, not user-facing.
  const entries = await readdir(distRoot);
  for (const name of entries) {
    if (name.startsWith('_canonical_') && name.endsWith('.html')) {
      await unlink(path.join(distRoot, name));
      log(`[post-build-copy] removed dist/${name} (design-fixture, not for production)`);
    }
  }
}

export async function main() {
  try {
    await copyCommittedApiTree();
    return true;
  } catch (err) {
    console.error('[post-build-copy] failed:', err);
    process.exitCode = 1;
    return false;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
