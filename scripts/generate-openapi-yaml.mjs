#!/usr/bin/env node
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SPECS = [
  path.join(ROOT, 'data', 'api', 'v1.7.0', 'openapi.json'),
  path.join(ROOT, 'site', 'public', 'openapi.json'),
];

function isPlainKey(key) {
  return /^[A-Za-z_][A-Za-z0-9_-]*$/.test(key);
}

function renderKey(key) {
  return isPlainKey(key) ? key : JSON.stringify(key);
}

function renderScalar(value, indent) {
  if (value === null) return 'null';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (typeof value !== 'string') {
    throw new TypeError(`Unsupported scalar type: ${typeof value}`);
  }
  if (value.includes('\n')) {
    const pad = ' '.repeat(indent);
    return `${pad}|-\n${value.split(/\r?\n/).map((line) => `${pad}  ${line}`).join('\n')}`;
  }
  return JSON.stringify(value);
}

function isInline(value) {
  if (value === null) return true;
  if (typeof value === 'number' || typeof value === 'boolean') return true;
  if (typeof value === 'string') return !value.includes('\n');
  if (Array.isArray(value)) return value.length === 0;
  return value && typeof value === 'object' && Object.keys(value).length === 0;
}

function renderYaml(value, indent = 0) {
  const pad = ' '.repeat(indent);

  if (isInline(value)) {
    if (Array.isArray(value)) return '[]';
    if (value && typeof value === 'object') return '{}';
    return renderScalar(value, indent);
  }

  if (typeof value === 'string') {
    return renderScalar(value, indent);
  }

  if (Array.isArray(value)) {
    return value.map((item) => {
      if (isInline(item)) return `${pad}- ${renderYaml(item, indent + 2)}`;
      return `${pad}-\n${renderYaml(item, indent + 2)}`;
    }).join('\n');
  }

  return Object.entries(value).map(([key, child]) => {
    const renderedKey = renderKey(key);
    if (isInline(child)) return `${pad}${renderedKey}: ${renderYaml(child, indent + 2)}`;
    return `${pad}${renderedKey}:\n${renderYaml(child, indent + 2)}`;
  }).join('\n');
}

async function main() {
  for (const specPath of SPECS) {
    const spec = JSON.parse(await readFile(specPath, 'utf8'));
    const yaml = `${renderYaml(spec)}\n`;
    const outPath = specPath.replace(/\.json$/, '.yaml');
    await writeFile(outPath, yaml, 'utf8');
    console.log(`wrote ${path.relative(ROOT, outPath)}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
