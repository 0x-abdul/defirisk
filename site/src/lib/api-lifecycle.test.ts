import { describe, expect, it } from 'vitest';
import { retirementVersions } from './api-lifecycle';
describe('selected API lifecycle', () => {
  it('retains frozen input without inferred retirement', () => {
    expect(retirementVersions({ current_api_version: 'v1.7.0' })).toEqual([]);
  });
  it('uses explicit sorted retirement metadata', () => {
    expect(retirementVersions({ retired_api_versions: ['v1.5.0', 'v1.6.0'] })).toEqual(['v1.5.0', 'v1.6.0']);
  });
  it.each([null, 'v1.5.0', ['v1.7.0'], ['v1.6.0', 'v1.5.0'], ['v1.5.0', 'v1.5.0']])('rejects invalid metadata %j', value => {
    expect(() => retirementVersions({ retired_api_versions: value })).toThrow();
  });
});
