import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import {
  getTask10AliasRoute,
  getTask10AliasTarget,
  listTask10AliasSlugs,
  TASK10_ALIASES,
  TASK10_ALIAS_ROUTES,
} from './task10-aliases';

const routeSource = readFileSync(
  new URL('../pages/protocols/[slug]/index.astro', import.meta.url),
  'utf8'
);
const homepageSource = readFileSync(new URL('../pages/index.astro', import.meta.url), 'utf8');
const factorRouteSource = readFileSync(
  new URL('../pages/protocols/[slug]/factors/[factor].astro', import.meta.url),
  'utf8'
);

describe('Task 10 public alias routing', () => {
  it('maps each alias directly to its canonical selected surface', () => {
    expect(TASK10_ALIASES).toEqual({
      eigencloud: '/protocols/eigenlayer/?surface=default',
      'hyperliquid-bridge': '/protocols/hyperliquid/?surface=arbitrum-bridge',
    });
    expect(TASK10_ALIAS_ROUTES.eigencloud).toEqual({
      canonicalFamilySlug: 'eigenlayer',
      selectedSurfaceSlug: 'default',
      target: '/protocols/eigenlayer/?surface=default',
    });
    expect(TASK10_ALIAS_ROUTES['hyperliquid-bridge']).toEqual({
      canonicalFamilySlug: 'hyperliquid',
      selectedSurfaceSlug: 'arbitrum-bridge',
      target: '/protocols/hyperliquid/?surface=arbitrum-bridge',
    });
    expect(getTask10AliasTarget('eigencloud')).toBe('/protocols/eigenlayer/?surface=default');
    expect(getTask10AliasTarget('hyperliquid-bridge')).toBe(
      '/protocols/hyperliquid/?surface=arbitrum-bridge'
    );
    expect(listTask10AliasSlugs()).toEqual(['eigencloud', 'hyperliquid-bridge']);
  });

  it('leaves canonical and unknown slugs outside the alias table', () => {
    expect(getTask10AliasTarget('eigenlayer')).toBeUndefined();
    expect(getTask10AliasTarget('hyperliquid')).toBeUndefined();
    expect(getTask10AliasRoute('unknown-protocol')).toBeUndefined();
    expect(routeSource).toContain("return Astro.redirect('/404');");
  });

  it('resolves static aliases before any protocol data load', () => {
    const aliasLookup = routeSource.indexOf('getTask10AliasTarget(slug)');
    const detailLookup = routeSource.indexOf('const detail = getProtocol(slug)');
    expect(aliasLookup).toBeGreaterThan(-1);
    expect(detailLookup).toBeGreaterThan(aliasLookup);
    expect(routeSource).toContain('aliasSlugs.map');
    expect(routeSource).toContain('return Astro.redirect(aliasTarget);');
    expect(JSON.stringify(TASK10_ALIAS_ROUTES)).not.toMatch(/review|token|[0-9a-f]{8}-/i);
  });

  it('does not expand aliases into index, card, or factor generation', () => {
    expect(routeSource).toContain('listPublishedProtocolSlugs()');
    expect(routeSource).toContain('.filter((slug) => !aliasSet.has(slug))');
    expect(routeSource).toContain('aliasSlugs.map');
    expect(homepageSource).not.toContain('listTask10AliasSlugs');
    expect(homepageSource).not.toContain('TASK10_ALIASES');
    expect(factorRouteSource).not.toContain('listTask10AliasSlugs');
    expect(factorRouteSource).not.toContain('TASK10_ALIASES');
  });
});
