#!/usr/bin/env node

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const SITE_ROOT = path.resolve(path.dirname(__filename), '..');

export function runStep(label, command, args) {
  return new Promise((resolve) => {
    let spawnFailed = false;
    const child = spawn(command, args, {
      cwd: SITE_ROOT,
      env: process.env,
      stdio: ['inherit', 'pipe', 'pipe'],
    });

    // Child output can contain unpublished route names. Drain it without
    // replaying it into CI, including on failures where chunks may be split
    // across streams or terminal control sequences.
    child.stdout?.resume();
    child.stderr?.resume();
    child.on('error', () => {
      spawnFailed = true;
    });
    child.on('close', (code) => {
      if (code === 0 && !spawnFailed) {
        console.log(`[private-safe-build] ${label} completed`);
        resolve(true);
        return;
      }

      console.error(`[private-safe-build] ${label} failed; child output withheld`);
      resolve(false);
    });
  });
}

export async function runBuildSteps(steps) {
  for (const [label, script, args] of steps) {
    if (!(await runStep(label, process.execPath, [script, ...args]))) return false;
  }
  return true;
}

export function defaultBuildSteps(astroArgs = []) {
  return [
    ['Astro build', path.join(SITE_ROOT, 'node_modules', 'astro', 'bin', 'astro.mjs'), ['build', ...astroArgs]],
    ['API copy', path.join(SITE_ROOT, 'scripts', 'post-build-copy.mjs'), []],
    ['review artifact check', path.join(SITE_ROOT, 'scripts', 'check-review-artifacts.mjs'), []],
    ['Open Graph image build', path.join(SITE_ROOT, 'scripts', 'build-og-images.mjs'), []],
  ];
}

export async function main(steps = defaultBuildSteps()) {
  const succeeded = await runBuildSteps(steps);
  if (!succeeded) process.exitCode = 1;
  return succeeded;
}

export async function runCli(entrypoint = main, astroArgs = process.argv.slice(2)) {
  try {
    return await entrypoint(defaultBuildSteps(astroArgs));
  } catch {
    console.error('[private-safe-build] failed before completion');
    process.exitCode = 1;
    return false;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await runCli();
}
