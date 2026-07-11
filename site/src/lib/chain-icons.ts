const CHAIN_ICON_ALIASES: Readonly<Record<string, string>> = {
  bnb: 'bsc',
  binance: 'bsc',
  'zksync era': 'zksync',
};

export const CHAIN_ICON_IDS = [
  'arbitrum',
  'avalanche',
  'base',
  'bitcoin',
  'bsc',
  'ethereum',
  'gnosis',
  'mantle',
  'optimism',
  'polygon',
  'scroll',
  'solana',
  'zksync',
] as const;

const chainIconIds = new Set<string>(CHAIN_ICON_IDS);

export function chainIconPath(chainId: string | undefined): string | null {
  if (!chainId) return null;
  const normalized = chainId.trim().toLowerCase();
  const iconId = CHAIN_ICON_ALIASES[normalized] ?? normalized;
  return chainIconIds.has(iconId) ? `/chains/mono/${iconId}.svg` : null;
}
