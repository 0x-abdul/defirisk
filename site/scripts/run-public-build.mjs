#!/usr/bin/env node

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function runStep(label, command, args) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: SITE_ROOT,
      env: process.env,
      stdio: 'inherit',
    });
    child.on('error', () => resolve(false));
    child.on('close', (code) => {
      if (code === 0) {
        console.log(`[public-build] ${label} completed`);
        resolve(true);
        return;
      }
      console.error(`[public-build] ${label} failed`);
      resolve(false);
    });
  });
}

export function defaultBuildSteps(astroArgs = []) {
  return [
    [
      'Astro build',
      path.join(SITE_ROOT, 'node_modules', 'astro', 'bin', 'astro.mjs'),
      ['build', ...astroArgs],
    ],
    [
      'Astro island canonicalization',
      path.join(SITE_ROOT, 'scripts', 'canonicalize-astro-islands.mjs'),
      [],
    ],
    ['committed API copy', path.join(SITE_ROOT, 'scripts', 'post-build-copy.mjs'), []],
    ['Open Graph image build', path.join(SITE_ROOT, 'scripts', 'build-og-images.mjs'), []],
  ];
}

export async function main(steps = defaultBuildSteps()) {
  for (const [label, command, args] of steps) {
    if (!(await runStep(label, process.execPath, [command, ...args]))) {
      process.exitCode = 1;
      return false;
    }
  }
  return true;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main(defaultBuildSteps(process.argv.slice(2)));
}
