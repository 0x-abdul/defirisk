# Compound Family Surface Migration Change Record

- Refresh ID: `2026-07-12-compound-family-surfaces`
- Protocol family: `compound`
- Surfaces: `v2`, `v3` (primary)
- Effective date: `2026-07-12`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/161`
- Public artifact manifest SHA-256:
  `a136e1bb6dc6a2c0b98ee3d21e5125d91ca67fc1f2ec4c4eadedf4acfbc24348`
- Public payload SHA-256:
  `92a7d08cdc3557b6ded40f1fae7026bdb3f0ac482a221f6d19ba3176b7a61e83`

## Scope

This record covers the structural migration from standalone
`compound-v3/default` to canonical family `compound` with these exact public
surfaces and aliases:

| Surface | Status | Primary | Legacy alias | Deployments | Current surface factors |
| --- | --- | --- | --- | ---: | ---: |
| `v2` | legacy | no | `compound-v2` | 1 | 152 |
| `v3` | active | yes | `compound-v3` | 10 | 152 |

Thirty-two current factor rows are family-scoped. The approved payload is the
exact allowlist for all 336 current factor rows, 366 public source joins, and
11 named deployments. Cleanup was limited to the reviewed stale standalone
`compound-v3/default` identities after replacement and alias compatibility
passed. Every other protocol, family, surface, factor, deployment, and field
was out of scope.

This pull request records the reviewed migration and its verification. The
production operation was separately authorized by exact plan checksum and did
not hand-edit generated files under `data/api/`.

## Accepted Changes

- Establish `compound` as the canonical family.
- Establish `v3` as the sole primary surface and retain `v2` as an explicit
  legacy surface.
- Preserve `compound-v3` and `compound-v2` as selected-surface aliases.
- Attach the 11 approved deployments and 336 current factor rows to their
  reviewed family or surface scopes.
- Remove the reviewed stale standalone `compound-v3/default` rows only after
  canonical replacement and alias checks passed.
- Remap the historical Compound hack reference to canonical family `compound`.

The composed result is `v3=B/17.88` and `v2=D/36.11`.

## Verification

- Approved payload checksum matched: `yes`
- Family/surface/factor scope validated: `yes`
- Exactly one primary surface: `yes`, `v3`
- Canonical and alias compatibility validated in staging: `yes`
- Cleanup identities and effects checksum-locked: `yes`
- Unrelated generated API semantic changes: `none`; 188 non-target detail and
  history documents matched apart from permitted generated metadata
- Production backup and rollback rehearsal reference: backup SHA-256
  `d424ee3224d40684bae22b1002dc5853c0e2cfa79707acee0f20f9236019e302`,
  restore and database-swap rollback verified on `2026-07-12`
- Production operation plan SHA-256:
  `eb2aba0d2c2dd67dd3ac6ad723ec6c979927bba4905fe1adc633be74b0d8b8a0`
- Production transaction: `succeeded`; cleanup audit SHA-256
  `b91adaf8ebc69ccebc4cd2a6228dabf128bdab161a0e2abe2ebda1d6c0e70569`
- Production state verified: `yes`; protocol and family remain unpublished and
  `last_refreshed` is `2026-07-12`
- Deployment workflow: [run 29202303023](https://github.com/0x-abdul/defirisk/actions/runs/29202303023),
  `success`
- Live family and surface output verified: `yes`; canonical and alias public
  routes return 404, private review routes return 200 and are noindex, and both
  surfaces render without browser or console errors

## Result

The Compound structural migration is complete in production and verified live.
The family remains unpublished pending assessment review. Public canonical and
alias routes remain unavailable, while the private review boundary is working
and noindex. Publication requires a separate future decision.
