/**
 * 13-category taxonomy metadata for the UI.
 *
 * Source of truth: research/outputs/03-taxonomy.md (post-PD-032 2026-04-23).
 * `id` matches `category_id` on every factor and on `category_lights` keys.
 * `short` is the chip-friendly label (≤ 22 chars); `name` is the full name.
 */

export interface CategoryMeta {
  id: number;
  name: string;
  short?: string;
}

export const CATEGORIES: CategoryMeta[] = [
  { id: 1, name: 'Code & audits' },
  { id: 2, name: 'Governance & admin', short: 'Governance & admin' },
  { id: 3, name: 'Oracle & external dependencies', short: 'Oracle & ext deps' },
  { id: 4, name: 'Economic risk' },
  { id: 5, name: 'Operational history' },
  { id: 6, name: 'Real-time signals' },
  { id: 7, name: 'Dev identity & insider risk', short: 'Dev identity & insider' },
  { id: 8, name: 'Fork / dependency lineage', short: 'Fork / dependency' },
  { id: 9, name: 'Post-deploy hygiene & change mgmt', short: 'Post-deploy hygiene' },
  { id: 10, name: 'Cross-chain & bridge' },
  { id: 11, name: 'Threat intelligence & recon', short: 'Threat intel & recon' },
  { id: 12, name: 'Tooling / compiler / AI', short: 'Tooling / compiler / AI' },
  { id: 13, name: 'Response & disclosure hygiene', short: 'Response hygiene' },
];

export interface ChainMeta {
  id: string;
  name: string;
  /** Brand color for chain glyphs (DeploymentChip background). */
  color?: string;
  /** Single-character mark shown inside the DeploymentChip circle. */
  mark?: string;
}

/**
 * Chain display registry. Matches `primary_chain` values used in protocol records.
 * Order here is the canonical sort order in the homepage filter rail.
 */
export const CHAINS: ChainMeta[] = [
  { id: 'ethereum', name: 'Ethereum', color: '#627eea', mark: 'Ξ' },
  { id: 'arbitrum', name: 'Arbitrum', color: '#28a0f0', mark: 'A' },
  { id: 'base', name: 'Base', color: '#0052ff', mark: 'B' },
  { id: 'optimism', name: 'Optimism', color: '#ff0420', mark: 'O' },
  { id: 'polygon', name: 'Polygon', color: '#8247e5', mark: 'P' },
  { id: 'bsc', name: 'BNB Chain', color: '#f0b90b', mark: 'B' },
  { id: 'bnb', name: 'BNB Chain', color: '#f0b90b', mark: 'B' },
  { id: 'avalanche', name: 'Avalanche', color: '#e84142', mark: 'A' },
  { id: 'gnosis', name: 'Gnosis', color: '#04795b', mark: 'G' },
  { id: 'mantle', name: 'Mantle', color: '#0a0a0a', mark: 'M' },
  { id: 'scroll', name: 'Scroll', color: '#fff7e7', mark: 'S' },
  { id: 'zksync', name: 'zkSync', color: '#1e69ff', mark: 'Z' },
  { id: 'solana', name: 'Solana', color: '#9945ff', mark: 'S' },
  { id: 'bitcoin', name: 'Bitcoin', color: '#f7931a', mark: '₿' },
];

export function chainMeta(id: string): ChainMeta {
  return (
    CHAINS.find((c) => c.id === id) ?? {
      id,
      name: id.charAt(0).toUpperCase() + id.slice(1),
      color: '#7a7e85',
      mark: id.charAt(0).toUpperCase(),
    }
  );
}
