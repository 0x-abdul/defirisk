export interface DeploymentSelector {
  chain?: string | null;
  deployment_key?: string | null;
  selector?: { chain?: string | null; deployment_key?: string | null } | null;
  id?: string | null;
}

function deploymentKey(deployment: DeploymentSelector): string | null | undefined {
  return deployment.selector?.deployment_key ?? deployment.deployment_key;
}

function deploymentChain(deployment: DeploymentSelector): string | null | undefined {
  return deployment.selector?.chain ?? deployment.chain;
}

export type FamilyViewMode = 'default' | 'surface' | 'overview';

export interface FamilyViewState {
  mode: FamilyViewMode;
  surface: string | null;
  deploymentKey: string | null;
  chain: string | null;
}

export interface DefaultSurfaceSelector {
  surface_slug?: string | null;
  is_primary?: boolean | null;
  tvs_usd?: unknown;
}

function eligibleTvl(value: unknown): number | null {
  if (typeof value === 'string') {
    if (!value.trim()) return null;
    value = Number(value);
  }
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function compareSurfaceSlug(a: DefaultSurfaceSelector, b: DefaultSurfaceSelector): number {
  const aSlug = a.surface_slug ?? '';
  const bSlug = b.surface_slug ?? '';
  return aSlug < bSlug ? -1 : aSlug > bSlug ? 1 : 0;
}

/**
 * Select the deterministic queryless family surface.
 *
 * TVL is preferred when at least one surface has a valid value. Primary status
 * and then surface slug resolve equal TVLs. When no TVL is usable, primary
 * status and surface slug provide the fallback order.
 */
export function selectDefaultSurface<T extends DefaultSurfaceSelector>(
  surfaces: readonly T[]
): T | null {
  const eligible = surfaces
    .map((surface) => ({ surface, tvl: eligibleTvl(surface.tvs_usd) }))
    .filter((entry): entry is { surface: T; tvl: number } => entry.tvl !== null);

  if (eligible.length) {
    return [...eligible].sort(
      (a, b) =>
        b.tvl - a.tvl ||
        Number(Boolean(b.surface.is_primary)) - Number(Boolean(a.surface.is_primary)) ||
        compareSurfaceSlug(a.surface, b.surface)
    )[0].surface;
  }

  return (
    [...surfaces].sort(
      (a, b) =>
        Number(Boolean(b.is_primary)) - Number(Boolean(a.is_primary)) || compareSurfaceSlug(a, b)
    )[0] ?? null
  );
}

/**
 * Public, version-tolerant family selector codec.  Old payloads only have an
 * internal deployment id; that id is intentionally never written to a URL.
 */
export function readFamilyViewState(search: string): FamilyViewState {
  const params = new URLSearchParams(search);
  if (params.get('view') === 'overview') {
    return {
      mode: 'overview',
      surface: null,
      deploymentKey: null,
      chain: null,
    };
  }
  const surface = params.get('surface');
  return {
    mode: surface ? 'surface' : 'default',
    surface,
    deploymentKey: params.get('deployment'),
    chain: params.get('chain'),
  };
}

export function findDeployment<T extends DeploymentSelector>(
  deployments: T[],
  state: FamilyViewState
): T | null {
  if (state.deploymentKey) {
    const keyed = deployments.filter(
      (deployment) => deploymentKey(deployment) === state.deploymentKey
    );
    const matchingChain = state.chain
      ? keyed.filter((deployment) => deploymentChain(deployment) === state.chain)
      : keyed;
    return matchingChain.length === 1 ? matchingChain[0] : null;
  }
  // Backwards compatibility: a legacy chain URL is valid only when unique.
  if (state.chain) {
    const chainMatches = deployments.filter(
      (deployment) => deploymentChain(deployment) === state.chain
    );
    return chainMatches.length === 1 ? chainMatches[0] : null;
  }
  return null;
}

export function writeFamilyViewState(
  pathname: string,
  currentSearch: string,
  surface: string | null,
  deployment: DeploymentSelector | null,
  mode: FamilyViewMode = surface ? 'surface' : 'default',
  currentHash = ''
): string {
  const params = new URLSearchParams(currentSearch);
  if (mode === 'overview') {
    params.set('view', 'overview');
    params.delete('surface');
    params.delete('deployment');
    params.delete('chain');
  } else {
    if (params.get('view') === 'overview') params.delete('view');
    if (mode === 'surface' && surface) params.set('surface', surface);
    else params.delete('surface');
    if (deployment && deploymentKey(deployment))
      params.set('deployment', deploymentKey(deployment)!);
    else params.delete('deployment');
    if (deployment && deploymentChain(deployment))
      params.set('chain', deploymentChain(deployment)!);
    else params.delete('chain');
  }
  const query = params.toString();
  const hash = currentHash && !currentHash.startsWith('#') ? `#${currentHash}` : currentHash;
  return `${query ? `${pathname}?${query}` : pathname}${hash}`;
}
