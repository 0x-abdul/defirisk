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

export interface FamilyViewState {
  surface: string | null;
  deploymentKey: string | null;
  chain: string | null;
}

/**
 * Public, version-tolerant family selector codec.  Old payloads only have an
 * internal deployment id; that id is intentionally never written to a URL.
 */
export function readFamilyViewState(search: string): FamilyViewState {
  const params = new URLSearchParams(search);
  return {
    surface: params.get('surface'),
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
  deployment: DeploymentSelector | null
): string {
  const params = new URLSearchParams(currentSearch);
  if (surface) params.set('surface', surface);
  else params.delete('surface');
  if (deployment && deploymentKey(deployment)) params.set('deployment', deploymentKey(deployment)!);
  else params.delete('deployment');
  if (deployment && deploymentChain(deployment)) params.set('chain', deploymentChain(deployment)!);
  else params.delete('chain');
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}
