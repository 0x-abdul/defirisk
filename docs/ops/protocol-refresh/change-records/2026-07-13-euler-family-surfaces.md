# Euler Family Surface Migration Change Record

- Refresh ID: `2026-07-13-euler-family-surfaces`
- Protocol family: `euler`
- Surfaces: `v2` (primary), `v1`
- Effective date: `2026-07-13`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/173`
- Public artifact file SHA-256:
  `3f90f5a67e436a2d3e328b3ed282a160353417999d52ed91980559406b2576da`
- Public payload SHA-256:
  `ab67f0a2ecbaf338c349d42ab362a74c4108e73196dc6c9ee920c6c9dbf19f27`

## Scope

This record covers the structural migration from the standalone `euler-v2`
row to canonical family `euler`:

| Surface | Status | Primary | Legacy alias | Deployments |
| --- | --- | --- | --- | ---: |
| `v2` | active | yes | `euler-v2` | 17 |
| `v1` | deprecated | no | none | 1 |

The reviewed payload contains 366 current factor rows, 477 factor-source joins,
and 18 deployments. Cleanup is limited to the replaced standalone row and its
reviewed dependent data. Every other protocol, family, surface, factor,
deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `euler` as the canonical family.
- Establish `v2` as the sole primary active surface and retain `v1` as the
  deprecated secondary surface.
- Preserve `euler-v2` as the selected-surface alias when the family is later
  published.
- Attach the 18 reviewed deployments and 366 current factor rows to their
  reviewed family or surface scopes.
- Remove the stale standalone row after replacement and alias compatibility
  checks.
- Remap the reviewed Euler hack reference to the canonical family.

The composed results are `v2=A/11.37` and `v1=C/33.28`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `v2`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 196 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `3a1079a8eb76a93e5f0a34c5c4948b0f34f52aa05b22618889613e7eab5df869`
- Production operation plan SHA-256:
  `64dba70ea55c7378dd8cb6fe1bd45c5e75a1acda369ac297de2257871e1c6ab3`
- Production cleanup audit SHA-256:
  `6ed7b0efcbf92a61afa889ed01a1edf384ad87c34fe123049483eef3470a7dba`
- Deployment workflow: [run 29235157490](https://github.com/0x-abdul/defirisk/actions/runs/29235157490),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Euler family remains unpublished
pending assessment review, with `last_refreshed=2026-07-13`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
