/**
 * build-og-images.mjs — generate all OG PNG cards using satori + @resvg/resvg-js.
 *
 * Run after `astro build` (or standalone: `node scripts/build-og-images.mjs`).
 * Outputs PNG files to site/dist/og/. Existing files are overwritten.
 *
 * Requires the validated copied API tree; unsafe or missing inputs fail closed.
 *
 * Card types generated:
 *   default.png              — site-wide fallback
 *   protocols/<slug>.png     — one per graded protocol
 *   factors/<id>.png         — one per factor
 *   hacks/<id>.png           — one per indexed hack
 *   analytics.png            — analytics page
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { lstat, mkdtemp, readFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { buildConfiguration, hashTree, treesMatch, verifiedCopiedApi } from './post-build-copy.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SITE_ROOT = path.resolve(__dirname, '..');
// ── Rubric version (mirrors site/src/lib/rubric.ts) ─────────────────────────
const RUBRIC_VERSION = 'v1.7.0';

function readJson(dataRoot, relpath) {
  return JSON.parse(readFileSync(path.join(dataRoot, relpath), 'utf-8'));
}

function requireRows(dataRoot, filename, key) {
  const rows = readJson(dataRoot, filename)?.data?.[key];
  if (!Array.isArray(rows)) throw new Error('validated OG input roster is missing');
  return rows;
}

function cardId(value) {
  if (typeof value !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value)) {
    throw new Error('unsafe or missing OG card identity');
  }
  return value;
}

export function assertPublicProtocol(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) {
    throw new Error('invalid public OG protocol row');
  }
  if (row.do_not_publish === true
    || (Object.hasOwn(row, 'is_published') && row.is_published !== true)
    || (Object.hasOwn(row, 'protocol_is_published') && row.protocol_is_published !== true)
    || (Object.hasOwn(row, 'family_is_published') && row.family_is_published !== true)
    || (Object.hasOwn(row, 'editorial_status') && row.editorial_status !== 'published')
    || (Object.hasOwn(row, 'publication_exception') && row.publication_exception !== 'none')
    || (Object.hasOwn(row, 'projection_visibility') && row.projection_visibility !== 'public')
    || (Object.hasOwn(row, 'assessment_eligibility') && row.assessment_eligibility !== 'eligible')
    || (Object.hasOwn(row, 'assessment_grade_status') && row.assessment_grade_status !== 'rated')) {
    throw new Error('held or ineligible protocol may not produce a public OG card');
  }
  const slug = cardId(row.slug);
  // A topology-only family preserves its surfaces without inventing a family grade.
  if (row.headline_grade == null) return null;
  if (!['A', 'B', 'C', 'D', 'F'].includes(row.headline_grade)) {
    throw new Error('held or ineligible protocol may not produce a public OG card');
  }
  return slug;
}

export async function loadOgInputs(config = buildConfiguration()) {
  const copiedApi = await verifiedCopiedApi(config);
  const dataRoot = path.join(copiedApi, RUBRIC_VERSION);
  const protocols = requireRows(dataRoot, 'index.json', 'protocols');
  const factors = requireRows(dataRoot, 'factors.json', 'factors');
  const hacks = requireRows(dataRoot, 'hacks.json', 'hacks');
  const paths = new Set(['default.png', 'analytics.png']);
  const sourceDefaultFiles = new Map();
  let sourceDefaultHashes = new Map();
  const sourceDefaults = path.join(config.siteRoot, 'public', 'og');
  try {
    sourceDefaultHashes = await hashTree(sourceDefaults);
    if ([...sourceDefaultHashes.keys()].some((name) => !['default.png', 'default.svg'].includes(name))) {
      throw new Error('unexpected static OG source asset');
    }
    for (const name of sourceDefaultHashes.keys()) sourceDefaultFiles.set(name, await readFile(path.join(sourceDefaults, name)));
  } catch (error) {
    if (error.code !== 'ENOENT' && error.message !== 'required build tree is missing') throw error;
  }
  if (sourceDefaultFiles.has('default.svg')) paths.add('default.svg');
  const gradedProtocols = protocols.filter((row) => assertPublicProtocol(row) !== null);
  for (const row of gradedProtocols) paths.add(`protocols/${assertPublicProtocol(row)}.png`);
  for (const row of factors) paths.add(`factors/${cardId(row?.id)}.png`);
  for (const row of hacks) paths.add(`hacks/${cardId(row?.id)}.png`);
  if (paths.size !== 2 + (sourceDefaultFiles.has('default.svg') ? 1 : 0) + gradedProtocols.length + factors.length + hacks.length) {
    throw new Error('duplicate OG card identity');
  }
  return { protocols, gradedProtocols, factors, hacks, paths, sourceDefaultFiles, sourceDefaultHashes };
}

function ensureDir(dir) {
  mkdirSync(dir, { recursive: true });
}

function writePng(outPath, buffer) {
  ensureDir(path.dirname(outPath));
  writeFileSync(outPath, buffer);
}

export function exactFontArrayBuffer(bytes) {
  // Node may return a view into a pooled allocation containing unrelated bytes.
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

// ── Lazy import render + templates (ESM, after node_modules exist) ───────────

async function loadModules() {
  // Templates are inlined in this script (no .ts imports) so we can run
  // post-Astro-build under plain Node ESM without needing tsx at deploy time.
  const { renderOgCard, h } = await importRender();
  return { renderOgCard, h };
}

// Inline font loading so we don't need to import render.ts at runtime
async function importRender() {
  const { default: satori } = await import('satori');
  const { Resvg } = await import('@resvg/resvg-js');

  const fontRegPath = path.join(
    SITE_ROOT, 'node_modules', '@fontsource', 'inter', 'files', 'inter-latin-400-normal.woff',
  );
  const fontBoldPath = path.join(
    SITE_ROOT, 'node_modules', '@fontsource', 'inter', 'files', 'inter-latin-700-normal.woff',
  );
  const fontReg  = existsSync(fontRegPath)  ? exactFontArrayBuffer(readFileSync(fontRegPath))  : null;
  const fontBold = existsSync(fontBoldPath) ? exactFontArrayBuffer(readFileSync(fontBoldPath)) : null;

  const fonts = [
    fontReg  ? { name: 'Inter', data: fontReg,  weight: 400 } : null,
    fontBold ? { name: 'Inter', data: fontBold, weight: 700 } : null,
  ].filter(Boolean);

  async function renderOgCard(element) {
    const svg = await satori(element, { width: 1200, height: 630, fonts });
    const resvg = new Resvg(svg, { fitTo: { mode: 'width', value: 1200 } });
    return Buffer.from(resvg.render().asPng());
  }

  function h(type, props, ...children) {
    const flat = children.flat().filter((c) => c != null);
    return {
      type,
      props: {
        ...props,
        children: flat.length === 1 ? flat[0] : flat.length === 0 ? undefined : flat,
      },
    };
  }

  return { renderOgCard, h };
}

// ── Colour palette ───────────────────────────────────────────────────────────

const C = {
  bg: '#f8fafc', ink: '#0f172a', muted: '#64748b', border: '#e2e8f0', white: '#ffffff',
  gradeA: '#16a34a', gradeAbg: '#f0fdf4',
  gradeB: '#2563eb', gradeBbg: '#eff6ff',
  gradeC: '#ca8a04', gradeCbg: '#fefce8',
  gradeD: '#ea580c', gradeDbg: '#fff7ed',
  gradeF: '#dc2626', gradeFbg: '#fef2f2',
  gradeN: '#94a3b8', gradeNbg: '#f1f5f9',
  critical: '#dc2626', criticalBg: '#fde8e4',
};

function gradeColor(letter) {
  const map = {
    A: [C.gradeA, C.gradeAbg], B: [C.gradeB, C.gradeBbg], C: [C.gradeC, C.gradeCbg],
    D: [C.gradeD, C.gradeDbg], F: [C.gradeF, C.gradeFbg],
  };
  return map[letter] ?? [C.gradeN, C.gradeNbg];
}

function fmtLoss(v) {
  if (v == null || v === 0) return '—';
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v}`;
}

const OUTER = { display: 'flex', width: 1200, height: 630, padding: '60px 72px', fontFamily: 'Inter, sans-serif' };

// ── Card builders ─────────────────────────────────────────────────────────────

function mkLogo(h) {
  // Aperture mark approximated for satori (no stroke-dasharray support):
  // solid circle outline with center dot, matches the brand mark concept.
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 } },
    h('div', {
      style: {
        width: 28, height: 28, borderRadius: '50%',
        border: `3px solid ${C.ink}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      },
    },
      h('div', { style: { width: 6, height: 6, borderRadius: '50%', background: C.ink } }),
    ),
    h('div', { style: { display: 'flex', alignItems: 'baseline' } },
      h('span', { style: { fontSize: 18, fontWeight: 600, color: C.ink, letterSpacing: '-0.02em' } }, 'defirisk'),
      h('span', { style: { fontSize: 18, fontWeight: 400, color: C.muted, letterSpacing: '-0.01em' } }, '.co'),
    ),
  );
}

function mkFooter(h, urlPath, right) {
  return h('div', {
    style: { display: 'flex', alignItems: 'center', paddingTop: 20, borderTop: `2px solid ${C.border}` },
  },
    h('div', { style: { fontSize: 16, color: C.muted } }, `defirisk.co${urlPath}`),
    h('div', { style: { flex: 1 } }),
    right ? h('div', { style: { fontSize: 16, color: C.muted } }, right) : null,
  );
}

function buildDefault(h) {
  const GRADE_COLORS = {
    A: '#118a4d', B: '#3da55f', C: '#c4881b', D: '#cc6420', F: '#b62a1f',
  };
  return h('div', {
    style: { ...OUTER, background: C.bg, flexDirection: 'column', justifyContent: 'space-between' },
  },
    // Main row: left text + right grade-pill column
    h('div', { style: { display: 'flex', flex: 1, alignItems: 'flex-start' } },
      // Left column
      h('div', { style: { display: 'flex', flexDirection: 'column', flex: 1 } },
        mkLogo(h),
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 20, marginTop: 96 } },
          h('div', { style: { fontSize: 58, fontWeight: 700, color: C.ink, lineHeight: 1.05, letterSpacing: '-0.02em' } },
            'A field guide to'),
          h('div', { style: { fontSize: 58, fontWeight: 700, color: C.ink, lineHeight: 1.05, letterSpacing: '-0.02em', marginTop: -14 } },
            'DeFi risk.'),
          h('div', { style: { fontSize: 24, color: C.muted, letterSpacing: '-0.01em', marginTop: 6 } },
            '184 risk factors \xb7 13 categories \xb7 open source'),
        ),
      ),
      // Right column: A–F grade pills at 75% opacity
      h('div', {
        style: { display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center', opacity: 0.75 },
      },
        ...['A', 'B', 'C', 'D', 'F'].map(g =>
          h('div', {
            style: {
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 80, height: 80, borderRadius: 10,
              background: GRADE_COLORS[g],
              fontSize: 36, fontWeight: 700, color: '#ffffff',
            },
          }, g),
        ),
      ),
    ),
    mkFooter(h, '', 'CC BY 4.0 \xb7 MIT'),
  );
}

function buildProtocol(h, { name, slug, grade, badge, chain, tvlDisplay }) {
  const [gradeText, gradeBg] = gradeColor(grade);
  return h('div', {
    style: { ...OUTER, background: C.bg, flexDirection: 'column', justifyContent: 'space-between' },
  },
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
      mkLogo(h),
      h('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 28 } },
        h('div', {
          style: { display: 'flex', alignItems: 'center', justifyContent: 'center', width: 96, height: 96,
            borderRadius: 20, background: gradeBg, fontSize: 44, fontWeight: 700, color: gradeText, flexShrink: 0 },
        }, grade === 'ineligible' ? '—' : grade),
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
          h('div', { style: { fontSize: 42, fontWeight: 700, color: C.ink, lineHeight: 1.1 } }, name),
          h('div', { style: { display: 'flex', gap: 12, alignItems: 'center' } },
            badge ? h('div', {
              style: { padding: '5px 16px', borderRadius: 999, background: gradeBg, color: gradeText, fontSize: 18, fontWeight: 700, letterSpacing: '0.04em' },
            }, badge) : null,
            chain ? h('div', { style: { fontSize: 18, color: C.muted } }, chain) : null,
            tvlDisplay ? h('div', { style: { fontSize: 18, color: C.muted, fontFamily: 'monospace' } }, `TVL: ${tvlDisplay}`) : null,
          ),
        ),
      ),
    ),
    mkFooter(h, `/protocols/${slug}/`, `Grade ${grade}`),
  );
}

function buildFactor(h, { id, name, description, isCritical, hacksCount }) {
  return h('div', {
    style: { ...OUTER, background: isCritical ? C.criticalBg : C.bg, flexDirection: 'column', justifyContent: 'space-between' },
  },
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      mkLogo(h),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
        h('div', {
          style: { fontFamily: 'monospace', fontSize: 20, color: isCritical ? C.critical : C.muted,
            background: isCritical ? '#fde8e4' : C.white, padding: '4px 12px', borderRadius: 6,
            border: `1px solid ${isCritical ? C.critical : C.border}` },
        }, id),
        isCritical ? h('div', {
          style: { fontSize: 20, fontWeight: 700, color: C.critical, background: C.criticalBg, padding: '4px 14px', borderRadius: 999 },
        }, '★ critical') : null,
      ),
      h('div', { style: { fontSize: 44, fontWeight: 700, color: C.ink, lineHeight: 1.15, maxWidth: 920 } }, name),
      description ? h('div', {
        style: { fontSize: 22, color: C.muted, maxWidth: 860, lineHeight: 1.4 },
      }, description.slice(0, 160) + (description.length > 160 ? '…' : '')) : null,
    ),
    mkFooter(h, `/factors/${id}/`, hacksCount != null ? `${hacksCount} hacks linked` : null),
  );
}

function buildHack(h, { id, protocolName, occurredAt, lossUsd, category, factorIds, hasCritical }) {
  const topFactors = (factorIds ?? []).slice(0, 5);
  return h('div', {
    style: { ...OUTER, background: hasCritical ? '#fff8f8' : C.bg, flexDirection: 'column', justifyContent: 'space-between' },
  },
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      mkLogo(h),
      hasCritical ? h('div', { style: { fontSize: 16, color: C.critical, fontWeight: 700 } }, '★ critical factor implicated') : null,
      h('div', { style: { fontSize: 52, fontWeight: 700, color: C.ink, lineHeight: 1.1 } }, protocolName),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 24 } },
        occurredAt ? h('div', { style: { fontSize: 24, color: C.muted, fontFamily: 'monospace' } }, occurredAt.slice(0, 10)) : null,
        lossUsd ? h('div', { style: { fontSize: 28, fontWeight: 700, color: C.gradeF } }, fmtLoss(lossUsd)) : null,
        category ? h('div', { style: { fontSize: 18, color: C.muted, background: C.white, padding: '4px 12px', borderRadius: 6, border: `1px solid ${C.border}` } }, category) : null,
      ),
      topFactors.length > 0 ? h('div', { style: { display: 'flex', gap: 10 } },
        ...topFactors.map((fid) => h('div', {
          style: { fontFamily: 'monospace', fontSize: 16, padding: '4px 12px', borderRadius: 6, background: C.white, color: C.muted, border: `1px solid ${C.border}` },
        }, fid)),
      ) : null,
    ),
    mkFooter(h, `/hacks/${id}/`, 'Hacks Ledger'),
  );
}

function buildAnalytics(h, { protocolCount, factorCount, hackCount }) {
  const stats = [
    { label: 'Protocols graded', value: String(protocolCount) },
    { label: 'Evidence factors', value: String(factorCount) },
    { label: 'Hacks indexed', value: String(hackCount) },
  ];
  return h('div', {
    style: { ...OUTER, background: C.bg, flexDirection: 'column', justifyContent: 'space-between' },
  },
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
      mkLogo(h),
      h('div', { style: { fontSize: 52, fontWeight: 700, color: C.ink, lineHeight: 1.1 } }, 'Grade distribution & trends'),
      h('div', { style: { fontSize: 24, color: C.muted, lineHeight: 1.4 } }, 'How DeFi risk grades evolve across the protocol universe over time.'),
      h('div', { style: { display: 'flex', gap: 32, marginTop: 8 } },
        ...stats.map((s) => h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
          h('div', { style: { fontSize: 32, fontWeight: 700, color: C.ink } }, s.value),
          h('div', { style: { fontSize: 15, color: C.muted } }, s.label),
        )),
      ),
    ),
    mkFooter(h, '/analytics/', 'DeFi Risk'),
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export async function main(config = buildConfiguration(), renderer = loadModules) {
  // Validate the complete source and copied API roster before importing renderers.
  const { gradedProtocols, factors, hacks, paths, sourceDefaultFiles, sourceDefaultHashes } = await loadOgInputs(config);
  const { renderOgCard, h } = await renderer();
  const scratch = await mkdtemp(path.join(path.dirname(config.distRoot), '.public-og-stage-'));
  const stagedOg = path.join(scratch, 'og');
  const destination = path.join(config.distRoot, 'og');
  try {
    writePng(path.join(stagedOg, 'default.png'), await renderOgCard(buildDefault(h)));
    if (sourceDefaultFiles.has('default.svg')) writePng(path.join(stagedOg, 'default.svg'), sourceDefaultFiles.get('default.svg'));
    writePng(path.join(stagedOg, 'analytics.png'), await renderOgCard(buildAnalytics(h, {
      protocolCount: gradedProtocols.length, factorCount: factors.length, hackCount: hacks.length,
    })));
    for (const p of gradedProtocols) {
      const slug = assertPublicProtocol(p);
      writePng(path.join(stagedOg, 'protocols', `${slug}.png`), await renderOgCard(buildProtocol(h, {
        name: p.display_name ?? slug, slug, grade: p.headline_grade,
        badge: p.headline_badge ?? '', chain: p.primary_chain ?? null,
        tvlDisplay: p.total_value_secured_usd
          ? fmtLoss(typeof p.total_value_secured_usd === 'string'
            ? parseFloat(p.total_value_secured_usd) : p.total_value_secured_usd) : null,
      })));
    }
    for (const f of factors) {
      const id = cardId(f.id);
      writePng(path.join(stagedOg, 'factors', `${id}.png`), await renderOgCard(buildFactor(h, {
        id, name: f.name ?? id, description: f.description ?? null,
        isCritical: Boolean(f.is_critical), hacksCount: null,
      })));
    }
    for (const hack of hacks) {
      const id = cardId(hack.id);
      const lossRaw = hack.loss_usd;
      const lossNum = lossRaw != null
        ? (typeof lossRaw === 'string' ? parseFloat(lossRaw) : lossRaw) : null;
      writePng(path.join(stagedOg, 'hacks', `${id}.png`), await renderOgCard(buildHack(h, {
        id, protocolName: hack.protocol_name, occurredAt: hack.occurred_at ?? null,
        lossUsd: lossNum, category: hack.category ?? null,
        factorIds: (hack.linked_factors ?? []).map((lf) => lf.factor_id), hasCritical: false,
      })));
    }
    const stagedHashes = await hashTree(stagedOg);
    if (stagedHashes.size !== paths.size || [...stagedHashes.keys()].some((name) => !paths.has(name))) {
      throw new Error('OG output roster differs from validated API');
    }
    try {
      const stat = await lstat(destination);
      if (stat.isSymbolicLink() || !stat.isDirectory()) {
        throw new Error('existing OG output is stale or differs; use a fresh local Astro build');
      }
      const actual = await hashTree(destination);
      if (!treesMatch(stagedHashes, actual)) {
        if (!sourceDefaultHashes.size || !treesMatch(sourceDefaultHashes, actual)) {
          throw new Error('existing OG output is stale or differs; use a fresh local Astro build');
        }
        // Only unchanged source fallback assets copied by Astro can be replaced.
        const previous = path.join(scratch, 'source-defaults');
        await rename(destination, previous);
        try { await rename(stagedOg, destination); }
        catch (error) { await rename(previous, destination); throw error; }
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      await rename(stagedOg, destination);
    }
    console.log(`[build-og] generated and verified ${paths.size} OG cards from copied API`);
    return paths;
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    const staticFailures = new Set([
      'validated OG input roster is missing', 'unsafe or missing OG card identity',
      'held or ineligible protocol may not produce a public OG card', 'duplicate OG card identity',
      'unexpected static OG source asset', 'OG output roster differs from validated API',
      'existing OG output is stale or differs; use a fresh local Astro build',
      'public output boundary validation failed', 'validated API copy is required before OG generation',
    ]);
    const reason = staticFailures.has(error?.message) ? error.message : 'renderer or filesystem operation failed';
    const codes = new Set(['ENOENT', 'EPERM', 'EBUSY', 'EACCES', 'EINVAL', 'ENOMEM', 'ERR_MODULE_NOT_FOUND', 'ERR_INVALID_ARG_TYPE']);
    const category = codes.has(error?.code) ? ` (${error.code})` : '';
    console.error(`[build-og] failed: ${reason}${category}`);
    process.exitCode = 1;
  });
}
