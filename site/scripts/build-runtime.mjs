/** Private invocation evidence for the supported compiler backend and actual runtime. */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { lstat, mkdir, readFile, readdir, realpath, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const encode = (value) => JSON.stringify(value, null, 2) + '\n';

export function compilerEnvironment(environment = process.env) {
  const selected = environment.DEFIRISK_COMPILER_BACKEND ?? 'native';
  if (!['native', 'wasi'].includes(selected)) throw new Error('unsupported compiler backend');
  const result = { ...environment, DEFIRISK_COMPILER_BACKEND: selected };
  if (selected === 'wasi') result.NAPI_RS_FORCE_WASI = '1';
  else if (result.NAPI_RS_FORCE_WASI) throw new Error('compiler backend and WASI loader setting disagree');
  if (result.NAPI_RS_NATIVE_LIBRARY_PATH) throw new Error('custom native compiler libraries are unsupported');
  return result;
}

async function packageRoot(require, name) {
  let current = path.dirname(require.resolve(name));
  for (;;) {
    try {
      if (JSON.parse(await readFile(path.join(current, 'package.json'), 'utf8')).name === name) return current;
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (path.dirname(current) === current) throw new Error('compiler package root missing');
    current = path.dirname(current);
  }
}

export async function runtimeBinding(siteRoot, environment) {
  siteRoot = path.resolve(siteRoot);
  const require = createRequire(path.join(siteRoot, 'package.json'));
  const backend = environment.DEFIRISK_COMPILER_BACKEND;
  const nativeName = process.platform === 'win32'
    ? `@astrojs/compiler-binding-win32-${process.arch}-msvc`
    : process.platform === 'darwin' ? `@astrojs/compiler-binding-darwin-${process.arch}`
      : process.platform === 'linux'
        ? `@astrojs/compiler-binding-linux-${process.arch}-${process.report.getReport().header.glibcVersionRuntime ? 'gnu' : 'musl'}` : null;
  const selected = backend === 'wasi' ? '@astrojs/compiler-binding-wasm32-wasi' : nativeName;
  if (!selected) throw new Error('explicit runtime binding for this native platform is unsupported; select wasi');
  const lock = JSON.parse(await readFile(path.join(siteRoot, 'package-lock.json'), 'utf8'));
  const files = {};
  const packages = {};
  const visited = new Set();
  async function visitFiles(directory) {
    for (const name of (await readdir(directory)).sort()) {
      const filename = path.join(directory, name);
      const stat = await lstat(filename);
      if (stat.isSymbolicLink()) throw new Error('linked compiler runtime files are unsupported');
      if (stat.isDirectory()) await visitFiles(filename);
      else if (stat.isFile()) files[filename] = sha256(await readFile(filename));
      else throw new Error('special compiler runtime file rejected');
    }
  }
  async function visitPackage(name, resolver = require) {
    const root = await packageRoot(resolver, name);
    if (visited.has(root)) return;
    visited.add(root);
    const metadata = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
    const relative = path.relative(siteRoot, root).split(path.sep).join('/');
    const pinned = lock.packages[relative];
    if (!pinned || pinned.version !== metadata.version || !pinned.integrity) {
      throw new Error('compiler runtime package differs from lockfile');
    }
    packages[relative] = { name, version: metadata.version, integrity: pinned.integrity };
    await visitFiles(root);
    const childResolver = createRequire(path.join(root, 'package.json'));
    for (const dependency of Object.keys(metadata.dependencies ?? {}).sort()) await visitPackage(dependency, childResolver);
    for (const dependency of Object.keys(metadata.peerDependencies ?? {}).sort()) await visitPackage(dependency, childResolver);
  }
  await visitPackage('@astrojs/compiler-binding');
  await visitPackage(selected);
  const executable = await realpath(process.execPath);
  files[executable] = sha256(await readFile(executable));
  return { schema: 'public-build/runtime-binding/v1', backend, compiler_package: selected,
    node: { executable, version: process.version, platform: process.platform, arch: process.arch,
      parent_exec_argv: process.execArgv, node_options: environment.NODE_OPTIONS ?? '' },
    loader_environment: { NAPI_RS_FORCE_WASI: environment.NAPI_RS_FORCE_WASI ?? '', NAPI_RS_ENFORCE_VERSION_CHECK: environment.NAPI_RS_ENFORCE_VERSION_CHECK ?? '' },
    packages, files };
}

export async function qualifyBuildRuntime(siteRoot, environment) {
  siteRoot = path.resolve(siteRoot);
  const before = await runtimeBinding(siteRoot, environment);
  const source = `import { createRequire } from 'node:module';
const selected = createRequire(${JSON.stringify(pathToFileURL(path.join(siteRoot, 'package.json')).href)})(${JSON.stringify(before.compiler_package)});
const direct = selected.compileAstroSync('<h1>Runtime qualification</h1>', {filename:'runtime-qualification.astro'});
if (!direct.code || direct.diagnostics?.some(item => item.severity === 1)) process.exit(1);
const compiler = await import(${JSON.stringify(pathToFileURL(path.join(siteRoot, 'node_modules/@astrojs/compiler-binding/index.js')).href)});
const exports = ['compileAstro', 'compileAstroSync', 'parseAstro', 'parseAstroSync', 'extractStylesSync'];
if (exports.some(name => typeof selected[name] !== 'function' || compiler[name] !== selected[name])) process.exit(1);
const result = compiler.compileAstroSync('<h1>Runtime qualification</h1>', {filename:'runtime-qualification.astro'});
if (!result.code || result.diagnostics?.some(item => item.severity === 1)) process.exit(1);
process.stdout.write(JSON.stringify({ selected_package: ${JSON.stringify(before.compiler_package)}, wrapper_exports_identical_to_selected_package: exports, direct_compile: 'passed', wrapper_compile: 'passed' }));`;
  const qualification = await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['--input-type=module', '-e', source], { cwd: siteRoot, env: environment, stdio: ['ignore', 'pipe', 'inherit'] });
    const chunks = [];
    child.stdout.on('data', chunk => chunks.push(chunk));
    child.once('error', reject);
    child.once('close', status => {
      if (status !== 0) reject(new Error('supported compiler runtime qualification or wrapper identity failed'));
      else {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
        catch { reject(new Error('compiler runtime qualification evidence missing')); }
      }
    });
  });
  await verifyBuildRuntime(siteRoot, environment, before);
  return { ...before, qualification };
}

export async function verifyBuildRuntime(siteRoot, environment, binding) {
  const expected = { ...binding };
  delete expected.qualification;
  if (encode(expected) !== encode(await runtimeBinding(siteRoot, environment))) throw new Error('compiler runtime changed during build');
}

export async function writeInvocationRecord(receiptPath, binding, buildInputs) {
  const record = { schema: 'public-build/invocation/v1', receipt: path.resolve(receiptPath), receipt_sha256: sha256(await readFile(receiptPath)), build_inputs_sha256: sha256(encode(Object.fromEntries(buildInputs))), runtime: binding };
  const destination = `${receiptPath}.invocation.json`;
  await mkdir(path.dirname(destination), { recursive: true });
  try {
    if ((await readFile(destination, 'utf8')) !== encode(record)) throw new Error('existing invocation record differs; choose a fresh private receipt');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    await writeFile(destination, encode(record), { flag: 'wx' });
  }
  return record;
}

/** Keep ordinary frozen-v1 evidence distinct and allow identical local rebuilds. */
export async function writeFrozenV1Receipt(receiptPath, receipt) {
  if (receipt.schema !== 'public-build/frozen-v1-local/v1') throw new Error('ordinary frozen-v1 receipt required');
  const bytes = encode(receipt);
  await mkdir(path.dirname(receiptPath), { recursive: true });
  try {
    await writeFile(receiptPath, bytes, { flag: 'wx' });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    if (await readFile(receiptPath, 'utf8') !== bytes) throw new Error('existing ordinary receipt differs; choose a fresh private receipt', { cause: error });
  }
}
