# Curve Family Surface Migration Change Record

- Refresh ID: `2026-07-13-curve-family-surfaces`
- Protocol family: `curve`
- Surfaces: `dex` (primary), `crvusd`
- Effective date: `2026-07-13`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/169`
- Public artifact file SHA-256:
  `3d23388cef3d32fe14c7d0c12d5b133493cf8db96bf2422653d8b575811a2926`
- Public payload SHA-256:
  `df7d7449d5593d3a785c4f5e61e8008a63b39767f5736d956be51f65bb92a077`

## Scope

This record covers the structural migration from standalone `curve-v2/default`
and `crvusd/default` rows to canonical family `curve`:

| Surface | Status | Primary | Legacy alias | Deployments | Current surface factors |
| --- | --- | --- | --- | ---: | ---: |
| `dex` | active | yes | `curve-v2` | 5 | 172 |
| `crvusd` | active | no | `crvusd` | 1 | 172 |

Twelve current factor rows are family-scoped. The reviewed payload contains 356
current factor rows, 484 factor-source joins, and six deployments. Cleanup is
limited to the two replaced standalone rows and their reviewed dependent data.
Every other protocol, family, surface, factor, deployment, and field is out of
scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `curve` as the canonical family.
- Establish `dex` as the sole primary surface and retain `crvusd` as an active
  secondary surface.
- Preserve `curve-v2` and `crvusd` as selected-surface aliases when the family
  is later published.
- Attach the six reviewed deployments and 356 current factor rows to their
  reviewed family or surface scopes.
- Remove the stale standalone rows after replacement and alias compatibility
  checks.
- Remap the three reviewed historical hack references to canonical family
  `curve`.

The composed results are `dex=B/12.57` and `crvusd=B/18.74`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `dex`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 196 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `9558164b9e71ee3e57cdae23626b8c424426466b959ffe4969144b38ae5ac6cc`
- Production operation plan SHA-256:
  `f09acab053700a45bd4a860d88f53f64f78bab06fb9576026c71fae7f7c3d5e8`
- Production cleanup audit SHA-256:
  `21b785fb22b8503087b69204e4acbadc6fef7b20769874f4cdf056763b22cc26`
- Deployment workflow: [run 29213829634](https://github.com/0x-abdul/defirisk/actions/runs/29213829634),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Curve family remains unpublished
pending assessment review, with `last_refreshed=2026-07-13`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
