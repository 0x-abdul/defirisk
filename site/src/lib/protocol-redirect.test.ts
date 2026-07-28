import { describe, expect, it } from 'vitest';

import { buildProtocolFamilyRedirect } from './protocol-redirect';

describe('buildProtocolFamilyRedirect', () => {
  it('returns the canonical family path without an empty query', () => {
    expect(buildProtocolFamilyRedirect('aave', '')).toBe('/protocols/aave/');
  });

  it('adds the selected surface', () => {
    expect(buildProtocolFamilyRedirect('aave', '', 'v3')).toBe('/protocols/aave/?surface=v3');
  });

  it('preserves unrelated parameters', () => {
    expect(buildProtocolFamilyRedirect('aave', '?chain=ethereum', 'v3')).toBe(
      '/protocols/aave/?chain=ethereum&surface=v3'
    );
  });

  it('preserves multiple parameters', () => {
    expect(buildProtocolFamilyRedirect('aave', '?chain=ethereum&deployment=core')).toBe(
      '/protocols/aave/?chain=ethereum&deployment=core'
    );
  });

  it('encodes query values', () => {
    expect(buildProtocolFamilyRedirect('aave', '?deployment=Core Pool', 'v3 mainnet')).toBe(
      '/protocols/aave/?deployment=Core+Pool&surface=v3+mainnet'
    );
  });
});
