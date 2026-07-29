import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const API_ROOT = path.join(ROOT, 'data', 'api', 'v1.7.0');
const BASELINE = JSON.parse(
  readFileSync(path.join(ROOT, 'data', 'api', 'publication-baseline.json'), 'utf8'),
);
const EXPECTED_PROTOCOL_COUNT = Number.parseInt(
  process.env.EXPECTED_PUBLIC_PROTOCOL_COUNT ??
    String(BASELINE?.published_protocols?.count),
  10,
);

const failures = [];

function fail(message) {
  failures.push(message);
}

function readJson(relpath) {
  const filepath = path.join(API_ROOT, relpath);
  try {
    return JSON.parse(readFileSync(filepath, 'utf8'));
  } catch (error) {
    fail(`${relpath}: ${error.message}`);
    return null;
  }
}

function listJsonFiles(dir) {
  if (!existsSync(dir)) return [];
  const result = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      result.push(...listJsonFiles(full));
    } else if (entry.isFile() && entry.name.endsWith('.json')) {
      result.push(full);
    }
  }
  return result;
}

function directProtocolFiles() {
  const dir = path.join(API_ROOT, 'protocols');
  if (!existsSync(dir)) {
    return [];
  }
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.json'))
    .map((entry) => entry.name.slice(0, -5));
}

const indexEnvelope = readJson('index.json');
const indexProtocols = indexEnvelope?.data?.protocols;
if (!Array.isArray(indexProtocols)) {
  fail('index.json does not contain data.protocols[]');
}

const indexSlugs = new Set();
for (const protocol of Array.isArray(indexProtocols) ? indexProtocols : []) {
  if (!protocol?.slug) {
    fail('index.json contains a protocol row without a slug');
    continue;
  }
  if (indexSlugs.has(protocol.slug)) {
    fail(`index.json contains duplicate protocol slug ${protocol.slug}`);
  }
  indexSlugs.add(protocol.slug);
}

if (Number.isFinite(EXPECTED_PROTOCOL_COUNT) && indexSlugs.size !== EXPECTED_PROTOCOL_COUNT) {
  fail(
    `index.json has ${indexSlugs.size} protocols; expected ${EXPECTED_PROTOCOL_COUNT} for this public export`,
  );
}

const protocolFileSlugs = new Set(directProtocolFiles());
if (protocolFileSlugs.size !== indexSlugs.size) {
  fail(
    `protocol file count (${protocolFileSlugs.size}) does not match index count (${indexSlugs.size})`,
  );
}

for (const slug of indexSlugs) {
  if (!protocolFileSlugs.has(slug)) {
    fail(`protocols/${slug}.json is missing for indexed protocol`);
  }
}

for (const slug of protocolFileSlugs) {
  if (!indexSlugs.has(slug)) {
    fail(`protocols/${slug}.json is not present in index.json`);
  }
  const envelope = readJson(path.join('protocols', `${slug}.json`));
  const protocol = envelope?.data?.protocol_data?.protocol;
  if (!protocol) {
    fail(`protocols/${slug}.json does not contain data.protocol_data.protocol`);
    continue;
  }
  if (protocol.slug !== slug) {
    fail(`protocols/${slug}.json has protocol.slug=${protocol.slug}`);
  }
  if (protocol.is_published !== true) {
    fail(`protocols/${slug}.json is not marked is_published=true`);
  }
}

const factorFiles = listJsonFiles(path.join(API_ROOT, 'factors'));
for (const file of factorFiles) {
  const rel = path.relative(API_ROOT, file);
  const envelope = readJson(rel);
  const scored = envelope?.data?.factor_data?.scored_protocols ?? [];
  if (!Array.isArray(scored)) {
    fail(`${rel} has non-array scored_protocols`);
    continue;
  }
  for (const row of scored) {
    if (row?.protocol_slug && !indexSlugs.has(row.protocol_slug)) {
      fail(`${rel} exposes non-indexed protocol_slug ${row.protocol_slug}`);
    }
  }
}

const historyEnvelope = readJson('history.json');
const historyRows = historyEnvelope?.data?.history ?? [];
if (Array.isArray(historyRows)) {
  for (const row of historyRows) {
    if (row?.protocol_slug && !indexSlugs.has(row.protocol_slug)) {
      fail(`history.json exposes non-indexed protocol_slug ${row.protocol_slug}`);
    }
  }
} else {
  fail('history.json data.history is not an array');
}

const changesEnvelope = readJson('changes.json');
const changeRows = changesEnvelope?.data?.changes ?? [];
if (Array.isArray(changeRows)) {
  for (const row of changeRows) {
    if (row?.protocol_slug && !indexSlugs.has(row.protocol_slug)) {
      fail(`changes.json exposes non-indexed protocol_slug ${row.protocol_slug}`);
    }
  }
} else {
  fail('changes.json data.changes is not an array');
}

const statusEnvelope = readJson('status.json');
const freshnessRows = statusEnvelope?.data?.fleet_freshness ?? [];
if (Array.isArray(freshnessRows)) {
  for (const row of freshnessRows) {
    if (row?.slug && !indexSlugs.has(row.slug)) {
      fail(`status.json exposes non-indexed slug ${row.slug}`);
    }
  }
}

for (const file of listJsonFiles(API_ROOT)) {
  const rel = path.relative(API_ROOT, file).replaceAll(path.sep, '/');
  const content = readFileSync(file, 'utf8');
  if (content.includes('"review_token"')) {
    fail(`${rel} exposes review_token`);
  }
  if (content.includes('"is_published": false')) {
    fail(`${rel} contains is_published=false`);
  }
}

if (failures.length > 0) {
  console.error('Public export boundary check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(
  `OK: published API surface boundary holds for ${indexSlugs.size} indexed protocols under data/api/v1.7.0`,
);
