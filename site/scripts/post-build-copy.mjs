/**
 * post-build-copy.mjs — copy the canonical API data dumps into site/dist/.
 *
 * The `dump.py` output lives at <repo>/data/api/<rubric>/ (committed JSON).
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
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SITE_ROOT = path.resolve(__dirname, '..'); // .../site
const REPO_ROOT = path.resolve(SITE_ROOT, '..'); // repo root
const OVERRIDE_ROOT = process.env.DEFIRISK_API_ROOT
  ? path.resolve(process.env.DEFIRISK_API_ROOT)
  : null;
const SRC = OVERRIDE_ROOT ?? path.join(REPO_ROOT, 'data', 'api');
const DST = path.join(SITE_ROOT, 'dist', 'api'); // site/dist/api
const COPY_TARGET = OVERRIDE_ROOT ? path.join(DST, path.basename(OVERRIDE_ROOT)) : DST;

async function exists(p) {
  try {
    await access(p, constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  if (!(await exists(SRC))) {
    console.error(`[post-build-copy] ERROR: source not found: ${SRC}`);
    console.error(`[post-build-copy]   Run scripts/dump.py first to generate the API JSON dumps.`);
    process.exit(1);
  }
  if (!(await exists(path.dirname(DST)))) {
    console.error(`[post-build-copy] ERROR: site/dist/ not found — run \`astro build\` first.`);
    process.exit(1);
  }

  await cp(SRC, COPY_TARGET, { recursive: true });
  console.log(
    `[post-build-copy] copied ${path.relative(REPO_ROOT, SRC)} → ${path.relative(REPO_ROOT, COPY_TARGET)}`
  );

  // Strip canonical-preview fixtures from dist/. They live in public/ so the
  // dev server can serve them for visual-rebuild verification, but they should
  // not ship to production — they're design-system internals, not user-facing.
  const distRoot = path.resolve(SITE_ROOT, 'dist');
  const entries = await readdir(distRoot);
  for (const name of entries) {
    if (name.startsWith('_canonical_') && name.endsWith('.html')) {
      await unlink(path.join(distRoot, name));
      console.log(`[post-build-copy] removed dist/${name} (design-fixture, not for production)`);
    }
  }
}

main().catch((err) => {
  console.error('[post-build-copy] failed:', err);
  process.exit(1);
});
