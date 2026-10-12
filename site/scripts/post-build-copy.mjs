/**
 * Copy a validated immutable public API snapshot into a fresh local build.
 * DEFIRISK_PYTHON_EXECUTABLE selects the installed Python interpreter;
 * otherwise `python` must be on PATH. Validation is mandatory in either case.
 */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  lstat, mkdir, mkdtemp, readFile, readdir, rename, rm, unlink, writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const API_LANDING_ARTIFACT = 'index.html';

export function buildConfiguration(env = process.env, siteRoot = SITE_ROOT) {
  const repoRoot = path.resolve(siteRoot, '..');
  const curatorOverride = env.DEFIRISK_CURATOR_ROOT;
  if (curatorOverride !== undefined && (!curatorOverride.trim() || curatorOverride.includes('\0'))) {
    throw new Error('curator input override must identify a valid base directory');
  }
  const treeRoot = env.DEFIRISK_API_TREE_ROOT ? path.resolve(env.DEFIRISK_API_TREE_ROOT) : null;
  const versionRoot = env.DEFIRISK_API_ROOT ? path.resolve(env.DEFIRISK_API_ROOT) : null;
  if (versionRoot && path.basename(versionRoot) !== 'v1.7.0') {
    throw new Error('API version override must identify v1.7.0 inside a qualified complete API tree');
  }
  if (treeRoot && versionRoot && versionRoot !== path.join(treeRoot, 'v1.7.0')) {
    throw new Error('complete API tree and version overrides disagree');
  }
  return {
    siteRoot,
    repoRoot,
    sourceRoot: treeRoot ?? (versionRoot ? path.dirname(versionRoot) : path.join(repoRoot, 'data', 'api')),
    curatorRoot: path.resolve(curatorOverride ?? path.join(repoRoot, 'data', 'curator')),
    curatorRootExplicit: curatorOverride !== undefined,
    distRoot: path.resolve(env.DEFIRISK_DIST_ROOT ?? path.join(siteRoot, 'dist')),
    python: env.DEFIRISK_PYTHON_EXECUTABLE ?? 'python',
    validatorScript: path.join(repoRoot, 'scripts', 'ci', 'candidate_boundary.py'),
    validatorArguments: ['--root', repoRoot],
    privateInput: false,
    receiptPath: path.resolve(env.DEFIRISK_BUILD_RECEIPT ?? path.join(siteRoot, '.astro', 'public-build-receipt.json')),
    receiptModule: 'candidate_boundary',
    receiptImportRoot: path.join(repoRoot, 'scripts', 'ci'),
    receiptFactoryNeedsRoot: true,
  };
}

async function directoryExists(root) {
  const resolved = path.resolve(root);
  let exists = false;
  // Missing optional roots still require safe existing ancestors.
  for (let ancestor = resolved; ; ancestor = path.dirname(ancestor)) {
    try {
      const stat = await lstat(ancestor);
      if (stat.isSymbolicLink() || !stat.isDirectory()) {
        throw new Error(ancestor === resolved
          ? 'build tree must be a real directory'
          : 'symlink ancestors are forbidden in build trees');
      }
      if (ancestor === resolved) exists = true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    if (path.dirname(ancestor) === ancestor) break;
  }
  return exists;
}

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

/** Hash every regular file, rejecting links and special files before traversal. */
export async function hashTree(root, { excludeUnpublished = false } = {}) {
  if (!(await directoryExists(root))) throw new Error('required build tree is missing');
  const hashes = new Map();
  async function visit(directory, prefix = '') {
    for (const name of (await readdir(directory)).sort()) {
      const file = path.join(directory, name);
      const relative = prefix ? `${prefix}/${name}` : name;
      const stat = await lstat(file);
      if (stat.isSymbolicLink()) throw new Error('symlinks are forbidden in build trees');
      if (excludeUnpublished && name === 'unpublished' && stat.isDirectory()) continue;
      if (stat.isDirectory()) await visit(file, relative);
      else if (stat.isFile()) hashes.set(relative, digest(await readFile(file)));
      else throw new Error('special files are forbidden in build trees');
    }
  }
  await visit(root);
  return hashes;
}

export function treesMatch(left, right) {
  return left.size === right.size
    && [...left].every(([name, hash]) => right.get(name) === hash);
}

/** Curator absence is supported; later additions or removals change this map. */
export async function curatorInputHashes(config) {
  if (!(await directoryExists(config.curatorRoot))) {
    if (config.curatorRootExplicit) throw new Error('explicit curator input base is missing');
    return new Map();
  }
  return hashTree(config.curatorRoot);
}

async function snapshotCurator(config, stageRoot) {
  const original = await curatorInputHashes(config);
  await mkdir(stageRoot);
  for (const [relative, hash] of original) {
    const source = path.join(config.curatorRoot, ...relative.split('/'));
    const stat = await lstat(source);
    if (stat.isSymbolicLink() || !stat.isFile()) {
      throw new Error('curator inputs changed during snapshot');
    }
    const bytes = await readFile(source);
    if (digest(bytes) !== hash) throw new Error('curator inputs changed during snapshot');
    const destination = path.join(stageRoot, ...relative.split('/'));
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, bytes);
  }
  if (!treesMatch(original, await curatorInputHashes(config))
    || !treesMatch(original, await hashTree(stageRoot))) {
    throw new Error('curator inputs changed during snapshot');
  }
  return original;
}

/** Stage only the private checkout's unpublished subtree exclusion; never repair values. */
async function snapshotSource(config, stageRoot) {
  const options = { excludeUnpublished: config.privateInput };
  const original = await hashTree(config.sourceRoot, options);
  if (!original.size) throw new Error('public API source has no files');
  await mkdir(stageRoot);
  for (const [relative, hash] of original) {
    const source = path.join(config.sourceRoot, ...relative.split('/'));
    const stat = await lstat(source);
    if (stat.isSymbolicLink() || !stat.isFile()) {
      throw new Error('API source changed during snapshot');
    }
    const bytes = await readFile(source);
    if (digest(bytes) !== hash) throw new Error('API source changed during snapshot');
    const destination = path.join(stageRoot, ...relative.split('/'));
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, bytes);
  }
  if (!treesMatch(original, await hashTree(config.sourceRoot, options))) {
    throw new Error('API source changed during snapshot');
  }
  if (!treesMatch(original, await hashTree(stageRoot))) {
    throw new Error('staged API bytes differ from source');
  }
  return original;
}

export async function runBoundary(config, apiRoot, distRoot = null) {
  // Missing Python/the pinned validator is a failure, never a skipped check.
  const args = [
    config.validatorScript, ...(config.validatorArguments ?? []), '--api-root', apiRoot,
    '--curator-root', config.curatorRoot,
    ...(distRoot ? ['--dist', distRoot, '--expected-output-manifest', config.receiptPath] : []),
  ];
  await new Promise((resolve, reject) => {
    const child = spawn(config.python, args, {
      cwd: config.siteRoot, stdio: 'inherit', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    child.once('error', () => reject(new Error('public output validator could not start')));
    child.once('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error('public output boundary validation failed'));
    });
  });
}

/** Freeze and qualify the entire public API before Astro can read any assessment. */
export async function prepareBuildSnapshot(config = buildConfiguration()) {
  if (within(config.curatorRoot, config.sourceRoot)
    || within(config.sourceRoot, config.curatorRoot)
    || within(config.curatorRoot, path.dirname(config.distRoot))) {
    throw new Error('curator, API, and local build staging roots must be separate');
  }
  if (!(await directoryExists(path.dirname(config.distRoot)))) {
    throw new Error('local build output parent is missing');
  }
  const scratch = await mkdtemp(path.join(path.dirname(config.distRoot), '.public-build-stage-'));
  try {
    const apiRoot = path.join(scratch, 'api');
    const hashes = await snapshotSource(config, apiRoot);
    const curatorRoot = path.join(scratch, 'curator');
    const curatorHashes = await snapshotCurator(config, curatorRoot);
    await runBoundary({ ...config, curatorRoot }, apiRoot);
    return { scratch, apiRoot, hashes, curatorRoot, curatorHashes };
  } catch (error) {
    await rm(scratch, { recursive: true, force: true });
    throw error;
  }
}

export async function buildInputHashes(config, apiHashes = null, curatorHashes = null) {
  const entries = new Map();
  const api = apiHashes ?? await hashTree(config.sourceRoot, { excludeUnpublished: config.privateInput });
  for (const [relative, hash] of api) entries.set(`data/api/${relative}`, hash);
  const curator = curatorHashes ?? await curatorInputHashes(config);
  for (const [relative, hash] of curator) entries.set(`data/curator/${relative}`, hash);
  for (const [relative, hash] of await hashTree(path.join(config.repoRoot, 'scripts', 'ci'))) {
    entries.set(`scripts/ci/${relative}`, hash);
  }
  for (const name of ['src', 'public', 'scripts']) {
    const root = path.join(config.siteRoot, name);
    if (await directoryExists(root)) {
      for (const [relative, hash] of await hashTree(root)) entries.set(`site/${name}/${relative}`, hash);
    }
  }
  for (const name of (await readdir(config.siteRoot)).sort()) {
    if (!/^(?:package(?:-lock)?\.json|astro\.config\.[cm]?[jt]s|tsconfig\.json|\.node-version|\.npmrc)$/.test(name)) continue;
    const file = path.join(config.siteRoot, name);
    const stat = await lstat(file);
    if (stat.isSymbolicLink() || !stat.isFile()) throw new Error('unsafe build source input');
    entries.set(`site/${name}`, digest(await readFile(file)));
  }
  return new Map([...entries].sort(([left], [right]) => left.localeCompare(right)));
}

function within(parent, child) {
  const relative = path.relative(parent, child);
  return !relative || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

/** Called only after known runner stages in a fresh build; no content/roster bypass. */
export async function captureBuildReceipt(config, buildInputs) {
  const receiptPath = path.resolve(config.receiptPath);
  if (within(config.sourceRoot, receiptPath) || within(config.curatorRoot, receiptPath)
    || within(config.distRoot, receiptPath)) {
    throw new Error('build receipt must remain outside API and emitted output');
  }
  const code = [
    'import importlib,json,sys',
    'from pathlib import Path',
    'sys.path.insert(0,sys.argv[1])',
    'module=importlib.import_module(sys.argv[2])',
    'inputs=json.load(sys.stdin)',
    'kwargs={"build_inputs":inputs,"curator_root":Path(sys.argv[6])}',
    'if sys.argv[5]: kwargs["source_root"]=Path(sys.argv[5])',
    'receipt=module.create_output_manifest(Path(sys.argv[3]),Path(sys.argv[4]),**kwargs)',
    'sys.stdout.write(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False)+"\\n")',
  ].join('\n');
  const bytes = await new Promise((resolve, reject) => {
    const child = spawn(config.python, [
      '-c', code, config.receiptImportRoot, config.receiptModule,
      config.sourceRoot, config.distRoot,
      config.receiptFactoryNeedsRoot ? config.repoRoot : '', config.curatorRoot,
    ], {
      cwd: config.siteRoot, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    const chunks = [];
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify(Object.fromEntries(buildInputs)));
    // Unexpected interpreter diagnostics may contain private absolute paths.
    child.stderr.on('data', () => {});
    child.stdout.on('data', (chunk) => chunks.push(chunk));
    child.once('error', () => reject(new Error('build receipt validator could not start')));
    child.once('close', (status) => {
      if (status !== 0) reject(new Error('independent complete output scan rejected build receipt'));
      else resolve(Buffer.concat(chunks));
    });
  });
  const receipt = JSON.parse(bytes.toString('utf8'));
  if (!treesMatch(buildInputs, new Map(Object.entries(receipt.build_inputs ?? {})))) {
    throw new Error('captured build inputs differ from frozen source');
  }
  await mkdir(path.dirname(receiptPath), { recursive: true });
  try {
    const previous = await readFile(receiptPath);
    if (!previous.equals(bytes)) throw new Error('existing build receipt differs; choose a fresh local receipt path');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    await writeFile(receiptPath, bytes, { flag: 'wx' });
  }
  return receipt;
}

/** Move only exclusively allocated fresh output; differing prior builds remain intact. */
export async function installBuildOutput(stageRoot, destination, expectedFiles) {
  if (!(expectedFiles instanceof Map) || !expectedFiles.size) {
    throw new Error('a validated output receipt is required before installation');
  }
  const staged = await hashTree(stageRoot);
  if (!treesMatch(expectedFiles, staged)) {
    throw new Error('verified build output changed before installation');
  }
  if (await directoryExists(destination)) {
    if (!treesMatch(staged, await hashTree(destination))) {
      throw new Error('existing build differs; choose a fresh local output directory');
    }
    return;
  }
  await rename(stageRoot, destination);
  try {
    if (!treesMatch(expectedFiles, await hashTree(destination))) {
      throw new Error('verified build output changed during installation');
    }
  } catch (error) {
    // This destination did not exist before our atomic rename. Restore only
    // this invocation's tree so no rejected output remains installed.
    await rename(destination, stageRoot);
    throw error;
  }
}

async function withSnapshot(config, action) {
  if (!(await directoryExists(config.distRoot))) {
    throw new Error('build output is missing; run Astro build first');
  }
  // A sibling temporary directory keeps rename atomic on the same filesystem.
  const scratch = await mkdtemp(path.join(path.dirname(config.distRoot), '.public-api-stage-'));
  try {
    const stageRoot = path.join(scratch, 'api');
    const hashes = await snapshotSource(config, stageRoot);
    await runBoundary(config, stageRoot);
    return await action(stageRoot, hashes, scratch);
  } finally {
    // Exclusively allocated scratch; never an existing dist path.
    await rm(scratch, { recursive: true, force: true });
  }
}

/** Existing output must be identical or contain only the known Astro landing artifact. */
async function inspectDestination(destination, expected) {
  if (!(await directoryExists(destination))) return { exists: false, landing: null, identical: false };
  const actual = await hashTree(destination);
  const landing = actual.has(API_LANDING_ARTIFACT)
    ? await readFile(path.join(destination, API_LANDING_ARTIFACT)) : null;
  actual.delete(API_LANDING_ARTIFACT);
  if (!actual.size) return { exists: true, landing, identical: false };
  if (!treesMatch(actual, expected)) {
    throw new Error('existing API output is stale or differs; use a fresh local Astro build');
  }
  return { exists: true, landing, identical: true };
}

export async function copyPublicApi(config = buildConfiguration()) {
  return withSnapshot(config, async (stageRoot, hashes, scratch) => {
    const destination = path.join(config.distRoot, 'api');
    const state = await inspectDestination(destination, hashes);
    if (!state.identical) {
      if (state.landing) await writeFile(path.join(stageRoot, API_LANDING_ARTIFACT), state.landing);
      const previous = path.join(scratch, 'previous-landing');
      if (state.exists) await rename(destination, previous);
      try {
        await rename(stageRoot, destination);
      } catch (error) {
        if (state.exists) await rename(previous, destination);
        throw error;
      }
    }
    for (const name of await readdir(config.distRoot)) {
      if (name.startsWith('_canonical_') && name.endsWith('.html')) {
        const file = path.join(config.distRoot, name);
        const stat = await lstat(file);
        if (stat.isSymbolicLink() || !stat.isFile()) throw new Error('unsafe canonical build fixture');
        await unlink(file);
      }
    }
    console.log(`[post-build-copy] validated ${hashes.size} API files and matched the complete output roster`);
    return hashes.size;
  });
}

/** OG readers use the copied API root, never the raw repository fallback. */
export async function verifiedCopiedApi(config = buildConfiguration()) {
  return withSnapshot(config, async (_stageRoot, hashes) => {
    const destination = path.join(config.distRoot, 'api');
    const state = await inspectDestination(destination, hashes);
    if (!state.identical) throw new Error('validated API copy is required before OG generation');
    return destination;
  });
}

export async function verifyOutput(config = buildConfiguration()) {
  return withSnapshot(config, async (stageRoot) => {
    await runBoundary(config, stageRoot, config.distRoot);
    console.log('[post-build-copy] complete JSON, HTML, and browser output boundary passed');
  });
}

export async function main(args = process.argv.slice(2)) {
  if (args.length && !(args.length === 1 && args[0] === '--verify-output')) {
    throw new Error('supported argument: --verify-output');
  }
  if (args[0] === '--verify-output') await verifyOutput();
  else await copyPublicApi();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => {
    console.error('[post-build-copy] failed: validated public build required; no source content was repaired');
    process.exitCode = 1;
  });
}
