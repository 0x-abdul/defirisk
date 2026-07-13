# Aave Family Surface Migration Change Record

- Refresh ID: `2026-07-11-aave-family-surfaces`
- Protocol family: `aave`
- Surfaces: `v2`, `v3` (primary), `v4`
- Effective date: `2026-07-11`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/146
- Public artifact file SHA-256:
  `214bb33d6a64652439ec8d07436370fbc7feb8c74621fe996d6b3c44d0b40484`
- Public payload SHA-256:
  `2e1b41b87c76c2c0f25bc8e8f441df00d0c40f5d3e33bd287bfbea558c77f5d8`

## Scope

This record covers the structural migration from standalone `aave-v3/default`
to canonical family `aave` with these exact review surfaces and legacy aliases:

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

This pull request records the reviewed migration and its verification. The
production operation was separately authorized by exact plan checksum and did
not hand-edit generated files under `data/api/`.

## Accepted Changes

- Establish `aave` as the canonical family.
- Establish `v3` as the sole primary surface, with `v2` and `v4` retained as
  explicit versioned surfaces.
- Preserve `aave-v2`, `aave-v3`, and `aave-v4` as selected-surface aliases
  when the family is eventually published.
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
- Canonical and alias API output validated in temporary pre-publication output:
  `yes`
- Canonical overview and `?surface=` views validated in temporary
  pre-publication output: `yes`
- Cleanup dry-run reviewed before staging apply: `yes`
- Unrelated generated API semantic changes: `none`
- Production backup and rollback rehearsal reference: backup SHA-256
  `30f3842a9e2e6191e65faa2e549f561909b1d878a79ece44df730f5cbaf8d31c`,
  restore-tested at `2026-07-11T10:19:07Z`
- Production operation plan SHA-256:
  `b7274ea7ad3abcf529305d0123acb05bc8d84ca4cc6373e7da8fdf34d5281746`
- Production transaction: `succeeded`; cleanup audit SHA-256
  `0b5ddf4b35b9a2d7d7f661201e77cfd3651f1711aad0230cfe63df2a68d9724f`
- Production state verified: `yes`; verification SHA-256
  `6444c663fb76ca9c20e80f71e3855fa794e083bd4d0c9bf8fd2271a2c1a5d426`
- Unrelated protocol verification: `188` protocol detail files with zero
  semantic changes; verification SHA-256
  `257d050c070035c7d08691537e09bf0917a2c095a1d3a9b1ce2e597268a0dc27`
- Initial deployment workflow: run `29149772942`, `success`; the run log is no
  longer retained. Its published state was subsequently corrected to the
  required review-gated state below.

Repository script tests, site tests, type checking, a production-style site
build, and targeted browser checks passed against the post-cleanup temporary
output.

## Publication Review State

- Publication status: `unpublished`, pending review
- `last_refreshed`: `2026-07-11`
- Review-state correction plan SHA-256:
  `fea7b270a27f0c2896279832100eb6d5cdb3b69946cec6bcf0bd9ef304ec1e21`
- Correction backup SHA-256:
  `8f603b80a0f1d2b650af9b1028fe84c3219e9c6c545fc4d13eb689a4a6b71228`
- Production correction verification SHA-256:
  `2465fbf78f1a3e9ca751ede784a94ca59024dbaa971c0a6ecbad01c262153ea6`
- Correction deployment workflow: run `29151485584`, `success`; the run log is
  no longer retained
- Live public index contains Aave: `no`
- Canonical and legacy alias public API/page responses: `404`
- Tokenized review API/page responses: `200`; review page is `noindex`
- Review payload surfaces: `v2`, primary `v3`, `v4`
- Non-Aave protocol detail/history semantic changes: `none` across `94`
  protocols, excluding generated and fleet-wide `data_as_of` timestamps

## Result

The structural Aave family migration is complete in production. The canonical
family, three surfaces, deployments, factor scopes, and historical hack remap
match the reviewed target, but Aave remains unpublished while its assessment
undergoes review. Publication requires a separate later decision. Overall
family-migration rollout readiness remains pending completion of the pilot
review and follow-up operational assessment.
