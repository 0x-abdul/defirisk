# dYdX Family Surface Migration Change Record

- Refresh ID: `2026-07-13-dydx-family-surfaces`
- Protocol family: `dydx`
- Surfaces: `dydx-v4` (primary), `dydx-v3`
- Effective date: `2026-07-13`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/171`
- Public artifact file SHA-256:
  `ce603e55568a48914b3609248c31f2138a41f97ecb90e2f05f676d1e426dec73`
- Public payload SHA-256:
  `8621078c8f0a3b9ac691189103565a85dce62c9af0fa5cf332f0ab5a6b57691f`

## Scope

This record covers the structural migration from the standalone `dydx-v4`
row to canonical family `dydx`:

| Surface | Status | Primary | Legacy alias | Deployments |
| --- | --- | --- | --- | ---: |
| `dydx-v4` | active | yes | `dydx-v4` | 2 |
| `dydx-v3` | deprecated | no | `dydx-v3` | 2 |

The reviewed payload contains 360 current factor rows, 614 factor-source joins,
and four deployments. Cleanup is limited to the replaced standalone row and
its reviewed dependent data. Every other protocol, family, surface, factor,
deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `dydx` as the canonical family.
- Establish `dydx-v4` as the sole primary active surface and retain `dydx-v3`
  as the deprecated secondary surface.
- Preserve `dydx-v4` and `dydx-v3` as selected-surface aliases when the family
  is later published.
- Attach the four reviewed deployments and 360 current factor rows to their
  reviewed family or surface scopes.
- Remove the stale standalone row after replacement and alias compatibility
  checks.

The composed results are `dydx-v4=B/15.03` and `dydx-v3=C/22.69`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `dydx-v4`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 196 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `6db4287146e8d07c88361346b96277b9e9d7c32735c77f7a713581b0bb0ee81d`
- Production operation plan SHA-256:
  `fd7b21940d10b1873dc34cf72509f24b35261b6648e0e2698650554c6b90cd61`
- Production cleanup audit SHA-256:
  `bd0fd67b268d8ad896000361abfe363005729e632d40f7777690832f958130b4`
- Deployment workflow: [run 29216082739](https://github.com/0x-abdul/defirisk/actions/runs/29216082739),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The dYdX family remains unpublished
pending assessment review, with `last_refreshed=2026-07-13`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
