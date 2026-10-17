import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { compilerEnvironment, runtimeBinding, verifyBuildRuntime, writeInvocationRecord, writeFrozenV1Receipt } from './build-runtime.mjs';

test('backend choice rejects ambiguous or custom loader selection', () => {
  assert.equal(compilerEnvironment({ DEFIRISK_COMPILER_BACKEND: 'wasi' }).NAPI_RS_FORCE_WASI, '1');
  assert.throws(() => compilerEnvironment({ DEFIRISK_COMPILER_BACKEND: 'unknown' }), /unsupported/);
  assert.throws(() => compilerEnvironment({ NAPI_RS_FORCE_WASI: '1' }), /disagree/);
  assert.throws(() => compilerEnvironment({ NAPI_RS_NATIVE_LIBRARY_PATH: 'custom.node' }), /unsupported/);
});

test('runtime verification detects changed compiler bytes and version drift', async (t) => {
  const site = await mkdtemp(path.join(os.tmpdir(), 'compiler-runtime-'));
  t.after(() => rm(site, { recursive: true, force: true }));
  const packages = {};
  await writeFile(path.join(site, 'package.json'), '{}');
  for (const name of ['@astrojs/compiler-binding', '@astrojs/compiler-binding-wasm32-wasi']) {
    const relative = `node_modules/${name}`;
    const root = path.join(site, relative);
    await mkdir(root, { recursive: true });
    await writeFile(path.join(root, 'package.json'), JSON.stringify({ name, version: '1.0.0', main: 'index.js' }));
    await writeFile(path.join(root, 'index.js'), 'module.exports = {};');
    packages[relative] = { version: '1.0.0', integrity: 'synthetic-runtime-fixture' };
  }
  await writeFile(path.join(site, 'package-lock.json'), JSON.stringify({ packages }));
  const environment = compilerEnvironment({ DEFIRISK_COMPILER_BACKEND: 'wasi' });
  const before = await runtimeBinding(site, environment);
  await verifyBuildRuntime(site, environment, before);
  const file = path.join(site, 'node_modules/@astrojs/compiler-binding-wasm32-wasi/index.js');
  await writeFile(file, 'module.exports = { changed: true };');
  await assert.rejects(verifyBuildRuntime(site, environment, before), /changed during build/);
  packages['node_modules/@astrojs/compiler-binding-wasm32-wasi'].version = '2.0.0';
  await writeFile(path.join(site, 'package-lock.json'), JSON.stringify({ packages }));
  await assert.rejects(runtimeBinding(site, environment), /differs from lockfile/);
});

test('private invocation evidence binds exact receipt bytes and rejects replacement', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'compiler-invocation-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const receipt = path.join(root, 'receipt.json');
  await writeFile(receipt, '{"output_files":{}}');
  const binding = { backend: 'synthetic-test' };
  const inputs = new Map([['site/example', 'synthetic-hash']]);
  const record = await writeInvocationRecord(receipt, binding, inputs);
  assert.equal(record.receipt_sha256, createHash('sha256').update(await readFile(receipt)).digest('hex'));
  await writeInvocationRecord(receipt, binding, inputs);
  await writeFile(receipt, '{"changed":true}');
  await assert.rejects(writeInvocationRecord(receipt, binding, inputs), /existing invocation record differs/);
});

test('ordinary frozen-v1 receipt accepts identical rebuilds and rejects replacement', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'frozen-v1-receipt-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const file = path.join(root, 'receipt.json');
  const receipt = { schema: 'public-build/frozen-v1-local/v1', output_files: { 'index.html': 'fixture' } };
  await writeFrozenV1Receipt(file, receipt);
  await writeFrozenV1Receipt(file, receipt);
  await assert.rejects(writeFrozenV1Receipt(file, { ...receipt, output_files: {} }), /differs/);
  await assert.rejects(writeFrozenV1Receipt(file, { schema: 'candidate' }), /ordinary/);
});
