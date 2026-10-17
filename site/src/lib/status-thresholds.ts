/**
 * status-thresholds.ts: single source for all numeric cutoffs rendered on
 * /status/. Imported by status.astro so the page never hard-codes magic
 * numbers in markdown (per E-21/E-30 ticket convention).
 */

export const COVERAGE_TARGET_PROTOCOLS = 57;
export const COVERAGE_TARGET_CRITICAL_FACTORS = 20;
export const COVERAGE_TARGET_FACTORS = 184;
export const COVERAGE_TARGET_CATEGORIES = 13;

/**
 * Public assessment cadence buckets. Counts are derived from factor details
 * at build time by the status model.
 */
export const CADENCE_BUCKETS = [
  {
    code: 'C',
    label: 'Continuous',
    refresh: 'Every 24 hours',
    sla: 'Reviewed on a daily cadence.',
    examples: 'TVL, oracle pool depth, utilization rate, days since last exploit',
  },
  {
    code: 'E',
    label: 'Episodic',
    refresh: 'Weekly event review',
    sla: 'Reviewed weekly; values change after discrete events.',
    examples: 'Pause activations, post-exploit response, signer rotations, new audits',
  },
  {
    code: 'S',
    label: 'Static',
    refresh: 'On upgrade or quarterly review',
    sla: 'Re-graded after a redeploy, upgrade, or curator review.',
    examples: 'Audit↔bytecode match, EIP-712 chainId, admin = deployer EOA, contract verified',
  },
  {
    code: 'RT',
    label: 'Real-time',
    refresh: 'Deferred to v1.1: requires the signal engine',
    sla: 'Surfaced once the signal engine ships.',
    examples: 'Mempool patterns, mixer-withdrawal alerts, flash-loan spikes',
  },
] as const;

export type CadenceCode = (typeof CADENCE_BUCKETS)[number]['code'];

/** The v1.7.0 factor detail projection is expected to contain this shape. */
export const EXPECTED_CADENCE_COUNTS: Readonly<Record<CadenceCode, number>> = {
  C: 9,
  E: 36,
  S: 115,
  RT: 24,
};

export const EXPECTED_CADENCE_TOTAL = Object.values(EXPECTED_CADENCE_COUNTS).reduce(
  (total, count) => total + count,
  0,
);
