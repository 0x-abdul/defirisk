/**
 * status-thresholds.ts — single source for all numeric cutoffs rendered on
 * /status/. Imported by status.astro so the page never hard-codes magic
 * numbers in markdown (per E-21/E-30 ticket convention).
 */

export const FRESHNESS_GREEN_DAYS = 7;
export const FRESHNESS_YELLOW_DAYS = 30;

export const COVERAGE_TARGET_PROTOCOLS = 57;
export const COVERAGE_TARGET_CRITICAL_FACTORS = 20;
export const COVERAGE_TARGET_FACTORS = 184;
export const COVERAGE_TARGET_CATEGORIES = 13;

/**
 * Cadence buckets per E-30 ticket §Background. Counts derived from the
 * cadence column of risk-dashboard/.research/methodology/template.md
 * (verified 2026-04-26: 9 C, 37 E, 115 S, 24 RT — 185 pre-PD-032; 184
 * post-PD-032 with F169 deleted).
 */
export const CADENCE_BUCKETS = [
  {
    code: 'C',
    label: 'Continuous',
    count: 9,
    refresh: 'Nightly cron — 4 fetchers',
    sla: `Refreshed every 24h. Stale flag fires above ${FRESHNESS_GREEN_DAYS} days.`,
    examples: 'TVL, oracle pool depth, utilization rate, days since last exploit',
  },
  {
    code: 'E',
    label: 'Episodic',
    count: 37,
    refresh: 'Weekly event-checker — 7 fetchers, write only on diff',
    sla: 'Re-checked weekly; underlying value only changes on a discrete event.',
    examples: 'Pause activations, post-exploit response, signer rotations, new audits',
  },
  {
    code: 'S',
    label: 'Static',
    count: 115,
    refresh: 'On-trigger (upgrade event detected) + quarterly curator sweep',
    sla: 'Re-graded only when the protocol redeploys or upgrades.',
    examples: 'Audit↔bytecode match, EIP-712 chainId, admin = deployer EOA, contract verified',
  },
  {
    code: 'RT',
    label: 'Real-time',
    count: 24,
    refresh: 'Deferred to v1.1 — needs streaming infra, not a cron',
    sla: 'Not graded at v1.0; surfaced once the signal-engine ships.',
    examples: 'Mempool patterns, mixer-withdrawal alerts, flash-loan spikes',
  },
] as const;

export type CadenceCode = (typeof CADENCE_BUCKETS)[number]['code'];

export function classifyFreshness(daysStale: number | null):
  | 'green'
  | 'yellow'
  | 'red'
  | 'gray' {
  if (daysStale === null) return 'gray';
  if (daysStale <= FRESHNESS_GREEN_DAYS) return 'green';
  if (daysStale <= FRESHNESS_YELLOW_DAYS) return 'yellow';
  return 'red';
}
