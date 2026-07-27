import { describe, expect, it } from 'vitest';
import {
  findDeployment,
  readFamilyViewState,
  selectDefaultSurface,
  writeFamilyViewState,
} from './family-view-url';

const deployments = [
  { chain: 'ethereum', deployment_key: 'core' },
  { chain: 'ethereum', deployment_key: 'lending' },
  { chain: 'arbitrum', deployment_key: 'core' },
];

describe('family view URL codec', () => {
  it('reads a queryless URL as the default surface mode', () => {
    expect(readFamilyViewState('?utm_source=test')).toEqual({
      mode: 'default',
      surface: null,
      deploymentKey: null,
      chain: null,
    });
  });

  it('reads an explicit surface mode', () => {
    expect(readFamilyViewState('?surface=v3&deployment=core&chain=ethereum')).toEqual({
      mode: 'surface',
      surface: 'v3',
      deploymentKey: 'core',
      chain: 'ethereum',
    });
  });

  it('gives Overview precedence over incompatible selectors', () => {
    expect(
      readFamilyViewState(
        '?view=overview&surface=v3&deployment=core&chain=ethereum&utm_source=test'
      )
    ).toEqual({
      mode: 'overview',
      surface: null,
      deploymentKey: null,
      chain: null,
    });
  });

  it('uses a deployment key rather than a database id', () => {
    expect(writeFamilyViewState('/protocols/family/', '', 'v3', deployments[1])).toBe(
      '/protocols/family/?surface=v3&deployment=lending&chain=ethereum'
    );
  });

  it('accepts only an unambiguous legacy chain selector', () => {
    expect(findDeployment(deployments, readFamilyViewState('?chain=arbitrum'))).toEqual(
      deployments[2]
    );
    expect(findDeployment(deployments, readFamilyViewState('?chain=ethereum'))).toBeNull();
  });

  it('prefers the stable deployment key', () => {
    expect(
      findDeployment(deployments, readFamilyViewState('?deployment=core&chain=ethereum'))
    ).toEqual(deployments[0]);
  });

  it('rejects a repeated deployment key without its chain', () => {
    expect(findDeployment(deployments, readFamilyViewState('?deployment=core'))).toBeNull();
  });

  it('writes the clean default URL while preserving unrelated parameters', () => {
    expect(
      writeFamilyViewState(
        '/protocols/family/',
        '?surface=stale&deployment=core&chain=ethereum&utm_source=test',
        null,
        null,
        'default'
      )
    ).toBe('/protocols/family/?utm_source=test');
  });

  it('writes Overview and removes incompatible selectors', () => {
    expect(
      writeFamilyViewState(
        '/protocols/family/',
        '?surface=v3&deployment=core&chain=ethereum&utm_source=test',
        null,
        null,
        'overview'
      )
    ).toBe('/protocols/family/?utm_source=test&view=overview');
  });

  it('leaves unrelated parameters intact when switching surfaces', () => {
    expect(
      writeFamilyViewState(
        '/protocols/family/',
        '?view=overview&utm_source=test&preview=1',
        'v2',
        null,
        'surface'
      )
    ).toBe('/protocols/family/?utm_source=test&preview=1&surface=v2');
  });

  it('preserves an unrelated view parameter and the current hash', () => {
    expect(
      writeFamilyViewState(
        '/protocols/family/',
        '?view=compact&utm_source=test',
        'v2',
        null,
        'surface',
        '#categories'
      )
    ).toBe('/protocols/family/?view=compact&utm_source=test&surface=v2#categories');
  });

  it('preserves a hash when canonicalizing to the clean default', () => {
    expect(
      writeFamilyViewState(
        '/protocols/family/',
        '?surface=stale&deployment=core',
        null,
        null,
        'default',
        'cat-3'
      )
    ).toBe('/protocols/family/#cat-3');
  });
});

describe('default family surface selection', () => {
  it('selects the greatest eligible TVL regardless of input order or primary status', () => {
    const surfaces = [
      { surface_slug: 'core', is_primary: true, tvs_usd: 10 },
      { surface_slug: 'v2', is_primary: false, tvs_usd: ' 20.5 ' },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it('accepts zero as an eligible TVL', () => {
    const surfaces = [
      { surface_slug: 'unknown', is_primary: true, tvs_usd: null },
      { surface_slug: 'zero', is_primary: false, tvs_usd: 0 },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it.each([
    null,
    undefined,
    '',
    '   ',
    'nope',
    'NaN',
    'Infinity',
    '-1',
    Number.POSITIVE_INFINITY,
    -1,
  ])('rejects an ineligible TVL value: %s', (tvs_usd) => {
    const surfaces = [
      { surface_slug: 'invalid', is_primary: false, tvs_usd },
      { surface_slug: 'valid', is_primary: false, tvs_usd: 0 },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it('prefers the primary surface when eligible TVLs tie', () => {
    const surfaces = [
      { surface_slug: 'alpha', is_primary: false, tvs_usd: 10 },
      { surface_slug: 'zeta', is_primary: true, tvs_usd: '10' },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it('uses lexical slug order when eligible TVLs and primary status tie', () => {
    const surfaces = [
      { surface_slug: 'zeta', is_primary: false, tvs_usd: 10 },
      { surface_slug: 'alpha', is_primary: false, tvs_usd: 10 },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it('falls back to primary and then lexical order when no TVL is eligible', () => {
    const surfaces = [
      { surface_slug: 'zeta', is_primary: true, tvs_usd: null },
      { surface_slug: 'alpha', is_primary: true, tvs_usd: 'invalid' },
      { surface_slug: 'aardvark', is_primary: false, tvs_usd: -1 },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it('uses lexical order when no TVL or primary surface is available', () => {
    const surfaces = [
      { surface_slug: 'zeta', is_primary: false, tvs_usd: null },
      { surface_slug: 'alpha', is_primary: false, tvs_usd: undefined },
    ];
    expect(selectDefaultSurface(surfaces)).toBe(surfaces[1]);
  });

  it('returns null for an empty family', () => {
    expect(selectDefaultSurface([])).toBeNull();
  });
});
