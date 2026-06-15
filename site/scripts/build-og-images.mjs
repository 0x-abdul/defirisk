/**
 * build-og-images.mjs — generate all OG PNG cards using satori + @resvg/resvg-js.
 *
 * Run after `astro build` (or standalone: `node scripts/build-og-images.mjs`).
 * Outputs PNG files to site/dist/og/. Existing files are overwritten.
 *
 * Skips gracefully when data/api/<rubric>/ does not exist (pre-dump.py runs).
 *
 * Card types generated:
 *   default.png              — site-wide fallback
 *   protocols/<slug>.png     — one per graded protocol
 *   factors/<id>.png         — one per factor
 *   hacks/<id>.png           — one per indexed hack
 *   analytics.png            — analytics page
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SITE_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(SITE_ROOT, '..');
const DIST_OG   = path.join(SITE_ROOT, 'dist', 'og');

// ── Rubric version (mirrors site/src/lib/rubric.ts) ─────────────────────────
const RUBRIC_VERSION = 'v1.7.0';
const DATA_ROOT = path.join(REPO_ROOT, 'data', 'api', RUBRIC_VERSION);

function readJson(relpath) {
  const p = path.join(DATA_ROOT, relpath);
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, 'utf-8'));
}

function ensureDir(dir) {
  mkdirSync(dir, { recursive: true });
}

function writePng(outPath, buffer) {
  ensureDir(path.dirname(outPath));
  writeFileSync(outPath, buffer);
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
  const fontReg  = existsSync(fontRegPath)  ? readFileSync(fontRegPath).buffer  : null;
  const fontBold = existsSync(fontBoldPath) ? readFileSync(fontBoldPath).buffer : null;

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
    mkFooter(h, '', 'CC-BY 4.0 \xb7 MIT'),
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
    { label: 'Protocols graded', value: String(protocolCount ?? '57') },
    { label: 'Evidence factors', value: String(factorCount ?? '184') },
    { label: 'Hacks indexed', value: String(hackCount ?? '311') },
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

async function main() {
  if (!existsSync(path.join(SITE_ROOT, 'dist'))) {
    console.error('[build-og] ERROR: site/dist/ not found — run `astro build` first');
    process.exit(1);
  }

  if (!existsSync(DATA_ROOT)) {
    console.warn(`[build-og] SKIP: data root not found (${DATA_ROOT}); generating default card only`);
    const { renderOgCard, h } = await loadModules();
    ensureDir(DIST_OG);
    const defaultBuf = await renderOgCard(buildDefault(h));
    writePng(path.join(DIST_OG, 'default.png'), defaultBuf);
    console.log('[build-og] wrote og/default.png (fallback only)');
    return;
  }

  const { renderOgCard, h } = await loadModules();
  ensureDir(DIST_OG);

  let count = 0;

  // Default card
  const defaultBuf = await renderOgCard(buildDefault(h));
  writePng(path.join(DIST_OG, 'default.png'), defaultBuf);
  count++;

  // Analytics card
  const indexEnv = readJson('index.json');
  const protocols = indexEnv?.data?.protocols ?? [];
  const factsEnv = readJson('factors.json');
  const factors = factsEnv?.data?.factors ?? [];
  const hacksEnv = readJson('hacks.json');
  const hacks = hacksEnv?.data?.hacks ?? [];

  const analyticsBuf = await renderOgCard(buildAnalytics(h, {
    protocolCount: protocols.length,
    factorCount: factors.length,
    hackCount: hacks.length,
  }));
  writePng(path.join(DIST_OG, 'analytics.png'), analyticsBuf);
  count++;

  // Protocol cards
  ensureDir(path.join(DIST_OG, 'protocols'));
  for (const p of protocols) {
    const slug = p.slug ?? p.id;
    if (!slug) continue;
    try {
      const buf = await renderOgCard(buildProtocol(h, {
        name: p.display_name ?? slug,
        slug,
        grade: p.headline_grade ?? 'ineligible',
        badge: p.headline_badge ?? '',
        chain: p.primary_chain ?? null,
        tvlDisplay: p.total_value_secured_usd
          ? fmtLoss(typeof p.total_value_secured_usd === 'string'
            ? parseFloat(p.total_value_secured_usd)
            : p.total_value_secured_usd)
          : null,
      }));
      writePng(path.join(DIST_OG, 'protocols', `${slug}.png`), buf);
      count++;
    } catch (e) {
      console.warn(`[build-og] WARN: protocol ${slug}: ${e.message}`);
    }
  }

  // Factor cards
  ensureDir(path.join(DIST_OG, 'factors'));
  for (const f of factors) {
    if (!f.id) continue;
    try {
      const buf = await renderOgCard(buildFactor(h, {
        id: f.id,
        name: f.name ?? f.id,
        description: f.description ?? null,
        isCritical: Boolean(f.is_critical),
        hacksCount: null,
      }));
      writePng(path.join(DIST_OG, 'factors', `${f.id}.png`), buf);
      count++;
    } catch (e) {
      console.warn(`[build-og] WARN: factor ${f.id}: ${e.message}`);
    }
  }

  // Hack cards
  ensureDir(path.join(DIST_OG, 'hacks'));
  for (const hack of hacks) {
    if (!hack.id) continue;
    try {
      const lossRaw = hack.loss_usd;
      const lossNum = lossRaw != null
        ? (typeof lossRaw === 'string' ? parseFloat(lossRaw) : lossRaw)
        : null;
      const factorIds = (hack.linked_factors ?? []).map((lf) => lf.factor_id);
      const buf = await renderOgCard(buildHack(h, {
        id: hack.id,
        protocolName: hack.protocol_name,
        occurredAt: hack.occurred_at ?? null,
        lossUsd: lossNum,
        category: hack.category ?? null,
        factorIds,
        hasCritical: false,
      }));
      writePng(path.join(DIST_OG, 'hacks', `${hack.id}.png`), buf);
      count++;
    } catch (e) {
      console.warn(`[build-og] WARN: hack ${hack.id}: ${e.message}`);
    }
  }

  console.log(`[build-og] ✓ generated ${count} OG cards → dist/og/`);
}

main().catch((err) => {
  console.error('[build-og] fatal:', err);
  process.exit(1);
});
