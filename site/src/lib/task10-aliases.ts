/**
 * Public, build-time-only protocol aliases for the Task 10 topology.
 *
 * Keep this table explicit and one-hop: each alias points directly at the
 * canonical protocol URL that should receive the request. Alias slugs are
 * intentionally not part of any protocol or factor data roster.
 */

export const TASK10_ALIAS_ROUTES = Object.freeze({
  eigencloud: Object.freeze({
    canonicalFamilySlug: 'eigenlayer',
    selectedSurfaceSlug: 'default',
    target: '/protocols/eigenlayer/?surface=default',
  }),
  'hyperliquid-bridge': Object.freeze({
    canonicalFamilySlug: 'hyperliquid',
    selectedSurfaceSlug: 'arbitrum-bridge',
    target: '/protocols/hyperliquid/?surface=arbitrum-bridge',
  }),
} as const);

export type Task10AliasSlug = keyof typeof TASK10_ALIAS_ROUTES;
export type Task10AliasRoute = (typeof TASK10_ALIAS_ROUTES)[Task10AliasSlug];

export const TASK10_ALIASES = Object.freeze({
  eigencloud: TASK10_ALIAS_ROUTES.eigencloud.target,
  'hyperliquid-bridge': TASK10_ALIAS_ROUTES['hyperliquid-bridge'].target,
} as const);

/** Return the public-safe canonical family and selected surface for an alias. */
export function getTask10AliasRoute(slug: string): Task10AliasRoute | undefined {
  if (!Object.prototype.hasOwnProperty.call(TASK10_ALIAS_ROUTES, slug)) return undefined;
  return TASK10_ALIAS_ROUTES[slug as Task10AliasSlug];
}

/** Return the direct canonical target for a known alias, if any. */
export function getTask10AliasTarget(slug: string): string | undefined {
  return getTask10AliasRoute(slug)?.target;
}

/** Return the fixed alias roster for static route generation. */
export function listTask10AliasSlugs(): Task10AliasSlug[] {
  return Object.keys(TASK10_ALIASES) as Task10AliasSlug[];
}
