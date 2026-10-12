#!/usr/bin/env node

import { spawn } from 'node:child_process';
import { rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { compilerEnvironment, qualifyBuildRuntime, verifyBuildRuntime, writeInvocationRecord, writeFrozenV1Receipt } from './build-runtime.mjs';
import {
  buildConfiguration, buildInputHashes, captureBuildReceipt, hashTree,
  installBuildOutput, prepareBuildSnapshot, treesMatch,
} from './post-build-copy.mjs';

const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function runStep(label, command, args, environment = process.env) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd: SITE_ROOT, env: environment, stdio: 'inherit' });
    child.once('error', () => resolve(false));
    child.once('close', (code) => {
      console[code === 0 ? 'log' : 'error'](`[public-build] ${label} ${code === 0 ? 'completed' : 'failed'}`);
      resolve(code === 0);
    });
  });
}

export function defaultBuildSteps(astroArgs = []) {
  validateAstroArguments(astroArgs);
  return [
    ['Astro build', path.join(SITE_ROOT, 'node_modules', 'astro', 'bin', 'astro.mjs'), ['build', ...astroArgs]],
    ['Astro island canonicalization', path.join(SITE_ROOT, 'scripts', 'canonicalize-astro-islands.mjs'), []],
    ['committed API copy', path.join(SITE_ROOT, 'scripts', 'post-build-copy.mjs'), []],
    ['Open Graph image build', path.join(SITE_ROOT, 'scripts', 'build-og-images.mjs'), []],
    ['complete public output boundary', path.join(SITE_ROOT, 'scripts', 'post-build-copy.mjs'), ['--verify-output']],
  ];
}

/** The qualified runner fixes source, config, mode, URLs, and output location.
 * Only logging switches may be forwarded; aliases/values/positionals cannot
 * select inputs that are absent from the frozen receipt.
 */
export function validateAstroArguments(args) {
  if (!Array.isArray(args)
    || args.some((arg) => !['--verbose', '--silent', '--no-verbose', '--no-silent'].includes(arg))) {
    throw new Error('qualified builds accept only Astro logging flags; source and configuration overrides are unsupported');
  }
}

export function frozenEnvironment(config, snapshot) {
  const environment = compilerEnvironment();
  if (config.privateInput) {
    environment.RISKDASHBOARD_DATA_ROOT = snapshot.apiRoot;
    environment.RISKDASHBOARD_CURATOR_ROOT = snapshot.curatorRoot;
    environment.RISKDASHBOARD_DIST_ROOT = path.join(snapshot.scratch, 'dist');
    environment.RISKDASHBOARD_BUILD_RECEIPT = config.receiptPath;
    environment.RISKDASHBOARD_PYTHON_EXECUTABLE = config.python;
  } else {
    environment.DEFIRISK_API_TREE_ROOT = snapshot.apiRoot;
    environment.DEFIRISK_API_ROOT = path.join(snapshot.apiRoot, 'v1.7.0');
    environment.DEFIRISK_CURATOR_ROOT = snapshot.curatorRoot;
    environment.DEFIRISK_DIST_ROOT = path.join(snapshot.scratch, 'dist');
    environment.DEFIRISK_BUILD_RECEIPT = config.receiptPath;
    environment.DEFIRISK_PYTHON_EXECUTABLE = config.python;
  }
  return environment;
}

export async function verifyFrozenInputs(config, snapshot, inputs) {
  if (!treesMatch(inputs, await buildInputHashes(config))
    || !treesMatch(snapshot.hashes, await hashTree(snapshot.apiRoot))
    || !treesMatch(snapshot.curatorHashes, await hashTree(snapshot.curatorRoot))) {
    throw new Error('public build inputs changed during rendering; candidate rejected');
  }
}

/** Frozen v1 builds retain main's four-stage build contract and validator.
 * Complete candidate output qualification is selected explicitly by API overrides.
 */
export async function ordinaryBuild(steps, configuration, executeStep = runStep) {
  const snapshot = await prepareBuildSnapshot(configuration);
  try {
    const inputs = await buildInputHashes(configuration, snapshot.hashes, snapshot.curatorHashes);
    const environment = frozenEnvironment(configuration, snapshot);
    const binding = await qualifyBuildRuntime(SITE_ROOT, environment);
    const stagedDist = path.join(snapshot.scratch, 'dist');
    for (const [label, command, args] of steps) {
      if (label === 'complete public output boundary') continue;
      await verifyFrozenInputs(configuration, snapshot, inputs);
      await verifyBuildRuntime(SITE_ROOT, environment, binding);
      const stageArgs = label === 'Astro build' ? [...args, '--outDir', stagedDist] : args;
      if (!(await executeStep(label, process.execPath, [command, ...stageArgs], environment))) {
        throw new Error('ordinary frozen API build stage failed');
      }
      await verifyFrozenInputs(configuration, snapshot, inputs);
      await verifyBuildRuntime(SITE_ROOT, environment, binding);
    }
    const files = await hashTree(stagedDist);
    const receipt = { schema: 'public-build/frozen-v1-local/v1',
      build_inputs: Object.fromEntries(inputs), api_files: Object.fromEntries(snapshot.hashes),
      output_files: Object.fromEntries(files) };
    await writeFrozenV1Receipt(configuration.receiptPath, receipt);
    await writeInvocationRecord(configuration.receiptPath, binding, inputs);
    await installBuildOutput(stagedDist, configuration.distRoot, files);
    console.log('[public-build] ordinary frozen-v1 build passed main validation and runtime binding');
    return true;
  } finally {
    await rm(snapshot.scratch, { recursive: true, force: true });
  }
}

export async function main(steps = defaultBuildSteps(), options = {}) {
  const configuration = options.configuration ?? buildConfiguration();
  const executeStep = options.executeStep ?? runStep;
  for (const [label, , args] of steps) {
    if (label === 'Astro build') {
      if (args[0] !== 'build') throw new Error('qualified runner requires the ordinary Astro build command');
      validateAstroArguments(args.slice(1));
    }
  }
  const ordinary = !options.configuration && !process.env.DEFIRISK_API_TREE_ROOT && !process.env.DEFIRISK_API_ROOT;
  if (ordinary) return ordinaryBuild(steps, configuration, executeStep);
  const snapshot = await prepareBuildSnapshot(configuration);
  try {
    const inputs = await buildInputHashes(configuration, snapshot.hashes, snapshot.curatorHashes);
    const environment = frozenEnvironment(configuration, snapshot);
    const runtime = await qualifyBuildRuntime(SITE_ROOT, environment);
    const stagedDist = path.join(snapshot.scratch, 'dist');
    const stagedConfiguration = {
      ...configuration, sourceRoot: snapshot.apiRoot, curatorRoot: snapshot.curatorRoot,
      distRoot: stagedDist, privateInput: false,
    };
    let receipt = null;
    for (const [label, command, args] of steps) {
      await verifyFrozenInputs(configuration, snapshot, inputs);
      await verifyBuildRuntime(SITE_ROOT, environment, runtime);
      if (label === 'complete public output boundary') {
        // Only the known fresh runner stages can create a new external receipt.
        receipt = await captureBuildReceipt(stagedConfiguration, inputs);
      }
      const stageArgs = label === 'Astro build' ? [...args, '--outDir', stagedDist] : args;
      if (!(await executeStep(label, process.execPath, [command, ...stageArgs], environment))) {
        throw new Error('public build stage failed');
      }
      await verifyFrozenInputs(configuration, snapshot, inputs);
      await verifyBuildRuntime(SITE_ROOT, environment, runtime);
    }
    await writeInvocationRecord(configuration.receiptPath, runtime, inputs);
    await installBuildOutput(stagedDist, configuration.distRoot, new Map(Object.entries(receipt?.output_files ?? {})));
    console.log('[public-build] installed complete local output from frozen source and verified receipt');
    return true;
  } finally {
    // No shared or prior output is removed. This directory belongs to this invocation.
    await rm(snapshot.scratch, { recursive: true, force: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(defaultBuildSteps(process.argv.slice(2))).catch(() => {
    console.error('[public-build] rejected: frozen inputs, fresh output, and complete build receipt required');
    process.exitCode = 1;
  });
}
