# Aave Family Surface Migration Change Record

- Refresh ID: `2026-07-11-aave-family-surfaces`
- Protocol family: `aave`
- Surfaces: `v2`, `v3` (primary), `v4`
- Effective date: pending production authorization
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/146
- Public payload SHA-256:
  `214bb33d6a64652439ec8d07436370fbc7feb8c74621fe996d6b3c44d0b40484`

## Scope

This record covers the structural migration from standalone `aave-v3/default`
to canonical family `aave` with these exact public surfaces and aliases:

| Surface | Status | Primary | Legacy alias | Deployments | Current surface factors |
| --- | --- | --- | --- | ---: | ---: |
| `v2` | legacy | no | `aave-v2` | 3 | 100 |
| `v3` | active | yes | `aave-v3` | 9 | 176 |
| `v4` | active | no | `aave-v4` | 7 | 104 |

Five current factor rows are family-scoped. The approved payload checksum is
the exact allowlist for all 385 current factor rows, their public source joins,
and the 19 named deployments. Cleanup is limited to stale standalone
`aave-v3/default` rows after replacement and alias verification. Every other
protocol, family, surface, factor, deployment, and field is out of scope.

This pull request records the review only. It does not directly change
generated files under `data/api/` or write protocol scores or grades.

## Accepted Changes

- Establish `aave` as the canonical family.
- Establish `v3` as the sole primary surface, with `v2` and `v4` retained as
  explicit versioned surfaces.
- Preserve `aave-v2`, `aave-v3`, and `aave-v4` as selected-surface aliases.
- Attach the 19 approved deployments and 385 current factor rows to their
  reviewed family or surface scopes.
- Remove stale standalone `aave-v3/default` rows only after canonical
  replacement and alias checks pass.
- Remap the historical Aave V3 hack reference to canonical family `aave`.

The staging compose result is `v2=C/21.30`, `v3=B/16.29`, and `v4=C/21.39`.

## Verification

- Approved payload checksum matched: `yes`
- Family/surface/factor scope validated: `yes`
- Exactly one primary surface: `yes`, `v3`
- Canonical and alias API output validated: `yes`
- Canonical overview and `?surface=` views validated: `yes`
- Cleanup dry-run reviewed before staging apply: `yes`
- Unrelated generated API semantic changes: `none`
- Production backup and rollback rehearsal reference: fresh backup restored to
  isolated staging; schema assertion, cleanup audit, and post-cleanup checks
  passed
- Production state verified: `pending`
- Live family and surface output verified: `pending`

Repository script tests, site tests, type checking, a production-style site
build, and targeted browser checks passed against the post-cleanup temporary
output.

## Result

The family migration is complete in isolated staging and ready for review.
Production and live verification remain pending. This record and its linked
issue do not authorize a production database write or deployment; that
requires separate approval for a named operation and a fresh production
preflight.
