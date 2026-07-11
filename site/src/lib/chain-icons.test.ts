import { existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { CHAIN_ICON_IDS, chainIconPath } from './chain-icons';

const iconRoot = fileURLToPath(new URL('../../public/chains/mono/', import.meta.url));

describe('chainIconPath()', () => {
  it('returns shipped icon paths with case and whitespace normalized', () => {
    expect(chainIconPath('ethereum')).toBe('/chains/mono/ethereum.svg');
    expect(chainIconPath(' Solana ')).toBe('/chains/mono/solana.svg');
  });

  it('maps supported aliases to a shipped icon', () => {
    expect(chainIconPath('bnb')).toBe('/chains/mono/bsc.svg');
    expect(chainIconPath('binance')).toBe('/chains/mono/bsc.svg');
    expect(chainIconPath('zkSync Era')).toBe('/chains/mono/zksync.svg');
  });

  it.each([undefined, '', 'berachain', 'hyperliquid l1', '../ethereum'])(
    'uses the text fallback instead of requesting an unknown asset for %s',
    (chainId) => {
      expect(chainIconPath(chainId)).toBeNull();
    }
  );

  it('keeps the registry synchronized with the shipped monochrome SVGs', () => {
    const shipped = readdirSync(iconRoot)
      .filter((name) => name.endsWith('.svg'))
      .map((name) => name.slice(0, -4))
      .sort();

    expect([...CHAIN_ICON_IDS].sort()).toEqual(shipped);
    for (const iconId of CHAIN_ICON_IDS) {
      const path = chainIconPath(iconId);
      expect(path).not.toBeNull();
      expect(existsSync(fileURLToPath(new URL(`../../public${path}`, import.meta.url)))).toBe(true);
    }
  });
});
