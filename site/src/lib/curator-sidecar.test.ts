import { describe, it, expect } from 'vitest';
import { loadCuratorSidecar } from './curator-sidecar';

describe('loadCuratorSidecar()', () => {
  it('returns parsed sidecar for aave-v3 (seeded)', () => {
    const sidecar = loadCuratorSidecar('aave-v3');
    expect(sidecar).not.toBeNull();
    expect(sidecar?.slug).toBe('aave-v3');
    expect(typeof sidecar?.verdict_body).toBe('string');
    expect((sidecar?.verdict_body ?? '').length).toBeGreaterThan(50);
  });

  it('exposes multisig cell with value, sub, light', () => {
    const sidecar = loadCuratorSidecar('aave-v3');
    expect(sidecar?.multisig?.value).toBe('5/9');
    expect(sidecar?.multisig?.light).toBe('yellow');
    expect(sidecar?.multisig?.sub).toBe('Aave Guardian');
  });

  it('exposes timelock cell with value, sub, light', () => {
    const sidecar = loadCuratorSidecar('aave-v3');
    expect(sidecar?.timelock?.value).toBe('24h');
    expect(sidecar?.timelock?.light).toBe('green');
  });

  it('returns null for slugs without a sidecar file', () => {
    expect(loadCuratorSidecar('nonexistent-protocol-xyz')).toBeNull();
  });
});
