#!/usr/bin/env node
import { execFile, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const SITE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const config = process.argv[2];
const extraArgs = process.argv.slice(3);
const port = process.env.PLAYWRIGHT_PORT || '4321';
const localBaseURL = `http://localhost:${port}`;
const baseURL = process.env.BASE_URL || localBaseURL;

if (!config) {
  console.error('Usage: node scripts/run-playwright-with-preview.mjs <playwright-config> [args...]');
  process.exit(2);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isLocalURL(url) {
  return /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?\//.test(`${url}/`);
}

async function isReady(url) {
  try {
    const res = await fetch(url, { redirect: 'manual' });
    return res.status < 500;
  } catch {
    return false;
  }
}

function rememberOutput(child) {
  const lines = [];
  const push = (chunk) => {
    const text = chunk.toString();
    for (const line of text.split(/\r?\n/)) {
      if (!line) continue;
      lines.push(line);
      if (lines.length > 25) lines.shift();
    }
  };
  child.stdout?.on('data', push);
  child.stderr?.on('data', push);
  return () => lines.join('\n');
}

async function waitForPreview(url, child, getOutput) {
  for (let i = 0; i < 60; i++) {
    if (child.exitCode !== null) {
      throw new Error(`Preview exited before becoming ready.\n${getOutput()}`);
    }
    if (await isReady(url)) return;
    await delay(1000);
  }
  throw new Error(`Preview did not become ready at ${url}.\n${getOutput()}`);
}

function run(command, args, options) {
  return new Promise((resolve) => {
    const child = spawn(command, args, options);
    child.on('exit', (code, signal) => {
      resolve(code ?? (signal ? 1 : 0));
    });
  });
}

function resolvePackageBin(packageName, binName = packageName) {
  const packageJsonPath = path.join(SITE_ROOT, 'node_modules', packageName, 'package.json');
  const pkg = JSON.parse(readFileSync(packageJsonPath, 'utf8'));
  const bin = typeof pkg.bin === 'string' ? pkg.bin : pkg.bin?.[binName];
  if (!bin) {
    throw new Error(`Package ${packageName} does not declare a ${binName} bin.`);
  }
  return path.join(path.dirname(packageJsonPath), bin);
}

function killWindowsTree(pid) {
  return new Promise((resolve) => {
    execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => resolve());
  });
}

async function stopPreview(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === 'win32') {
    await killWindowsTree(child.pid);
    return;
  }
  child.kill('SIGTERM');
  for (let i = 0; i < 20; i++) {
    if (child.exitCode !== null) return;
    await delay(100);
  }
  child.kill('SIGKILL');
}

let preview = null;

try {
  if (isLocalURL(baseURL) && !(await isReady(baseURL))) {
    preview = spawn(
      process.execPath,
      [resolvePackageBin('astro'), 'preview', '--port', port],
      {
        cwd: SITE_ROOT,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: process.env,
      },
    );
    const getOutput = rememberOutput(preview);
    await waitForPreview(baseURL, preview, getOutput);
  }

  const code = await run(
    process.execPath,
    [
      resolvePackageBin('playwright'),
      'test',
      `--config=${config}`,
      ...extraArgs,
    ],
    {
      cwd: SITE_ROOT,
      stdio: 'inherit',
      env: {
        ...process.env,
        BASE_URL: baseURL,
        PLAYWRIGHT_SKIP_WEBSERVER: '1',
      },
    },
  );
  process.exitCode = code;
} catch (err) {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
} finally {
  await stopPreview(preview);
}

process.exit(process.exitCode ?? 0);
