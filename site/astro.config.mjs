import { defineConfig } from 'astro/config';
import preact from '@astrojs/preact';
import sitemap from '@astrojs/sitemap';
import { execSync } from 'node:child_process';
import path from 'node:path';

function gitSha() {
  if (process.env.GIT_SHA) return process.env.GIT_SHA.slice(0, 7);
  try {
    return execSync('git rev-parse --short HEAD').toString().trim();
  } catch {
    return 'dev';
  }
}

function sitemapPriority(url) {
  // Homepage: exactly one trailing slash after the origin
  try {
    const pathname = new URL(url).pathname;
    if (pathname === '/') return 1.0;
    // List views (single path segment)
    const segments = pathname.split('/').filter(Boolean);
    if (segments.length === 1) return 0.9;
    // Detail pages under known content collections
    const topLevel = segments[0];
    if (['protocols', 'factors', 'hacks', 'incidents', 'learn'].includes(topLevel)) return 0.8;
  } catch {
    // fallthrough
  }
  return 0.5;
}

export default defineConfig({
  site: 'https://defirisk.co',
  output: 'static',
  trailingSlash: 'always',
  build: {
    outDir: process.env.DEFIRISK_DIST_ROOT
      ? path.resolve(process.env.DEFIRISK_DIST_ROOT)
      : undefined,
    // Force all CSS into external _astro/*.css chunks instead of inlining
    // small ones. The default 'auto' policy inlines chunks < ~4KB, which on
    // a 7,176-page build duplicates ~9KB of scoped component CSS into every
    // thin per-factor page (~63 MB of redundant bytes in dist/). With
    // 'never', the CSS lives in fingerprinted, immutably-cached chunks
    // under /_astro/, shared across all pages.
    inlineStylesheets: 'never',
  },
  redirects: {
    '/api-docs': '/data',
    '/api-docs/': '/data/',
    '/how-to-use': '/methodology',
    '/how-to-use/': '/methodology/',
  },
  integrations: [
    preact(),
    sitemap({
      filter: (page) =>
        !page.includes('/dev/') &&
        !page.includes('/data/api/') &&
        !page.includes('/api/') &&
        !page.includes('/unpublished/') &&
        !page.includes('/control/'),
      serialize: (item) => ({
        ...item,
        priority: sitemapPriority(item.url),
      }),
    }),
  ],
  vite: {
    define: {
      'import.meta.env.PUBLIC_GIT_SHA': JSON.stringify(gitSha()),
    },
  },
});
