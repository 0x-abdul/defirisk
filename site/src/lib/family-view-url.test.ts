import { describe, expect, it } from 'vitest';
import { findDeployment, readFamilyViewState, writeFamilyViewState } from './family-view-url';

const deployments = [
  { chain: 'ethereum', deployment_key: 'core' },
  { chain: 'ethereum', deployment_key: 'lending' },
  { chain: 'arbitrum', deployment_key: 'core' },
];

describe('family view URL codec', () => {
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
});
