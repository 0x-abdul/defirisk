#!/usr/bin/env node
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { gzipSync } from 'node:zlib';

const repoRoot = process.cwd();
const distRoot = path.join(repoRoot, 'site', 'dist');
const assetRoot = path.join(distRoot, '_astro');
const maxSingleGzip = Number(process.env.MAX_SINGLE_JS_GZIP_BYTES ?? 350 * 1024);
const maxTotalGzip = Number(process.env.MAX_TOTAL_JS_GZIP_BYTES ?? 800 * 1024);

function walk(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(fullPath) : [fullPath];
  });
}

if (!existsSync(distRoot)) {
  console.error(`FAIL: ${distRoot} does not exist. Run the site build first.`);
  process.exit(1);
}

const jsFiles = walk(assetRoot).filter((file) => file.endsWith('.js'));
if (jsFiles.length === 0) {
  console.log('OK: no emitted JavaScript assets found.');
  process.exit(0);
}

const results = jsFiles
  .map((file) => {
    const rawBytes = statSync(file).size;
    const gzipBytes = gzipSync(readFileSync(file)).length;
    return { file, rawBytes, gzipBytes };
  })
  .sort((a, b) => b.gzipBytes - a.gzipBytes);

const totalGzip = results.reduce((sum, item) => sum + item.gzipBytes, 0);
const failures = results.filter((item) => item.gzipBytes > maxSingleGzip);

for (const item of results.slice(0, 10)) {
  const rel = path.relative(repoRoot, item.file).replaceAll(path.sep, '/');
  console.log(`${rel}: raw=${item.rawBytes} gzip=${item.gzipBytes}`);
}
console.log(`Total JS gzip bytes: ${totalGzip}`);

if (failures.length > 0 || totalGzip > maxTotalGzip) {
  for (const item of failures) {
    const rel = path.relative(repoRoot, item.file).replaceAll(path.sep, '/');
    console.error(
      `FAIL: ${rel} gzip=${item.gzipBytes} exceeds MAX_SINGLE_JS_GZIP_BYTES=${maxSingleGzip}`,
    );
  }
  if (totalGzip > maxTotalGzip) {
    console.error(
      `FAIL: total JS gzip=${totalGzip} exceeds MAX_TOTAL_JS_GZIP_BYTES=${maxTotalGzip}`,
    );
  }
  process.exit(1);
}

console.log('OK: JavaScript bundle budget holds.');
