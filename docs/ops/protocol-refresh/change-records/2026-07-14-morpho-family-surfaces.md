# Morpho Family Surface Migration Change Record

- Refresh ID: `2026-07-14-morpho-family-surfaces`
- Protocol family: `morpho`
- Surfaces: `v1` (primary), `optimizer`
- Effective date: `2026-07-14`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/183`
- Public artifact file SHA-256:
  `67f95f2c61a1f81b469cb8cf74aea24b71be2ccfbacaa854602ce2d2ca9d955f`
- Public payload SHA-256:
  `36a805eeeff2caa28b3aafb175e9ef91c0c44e9d2b4ec7f771da2421c6a43153`

## Scope

This record covers the structural migration of the existing Morpho assessment
into canonical family `morpho`:

| Surface | Status | Primary | Deployments | Surface-scoped factors | Grade / risk score |
| --- | --- | --- | ---: | ---: | --- |
| `v1` | active | yes | 4 | 184 | D / 26.8 |
| `optimizer` | deprecated | no | 3 | 184 | B / 14.3 |

The reviewed payload contains 368 surface-scoped current factor rows, 488
deduplicated current factor-source joins, and seven deployments. Cleanup is
limited to the reviewed stale `morpho-v1` standalone runtime rows and their
dependent history. Every unrelated protocol, family, surface, factor,
deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `morpho` as the canonical family.
- Establish v1 as the sole primary active surface.
- Preserve Optimizer as a deprecated secondary surface.
- Attach all seven reviewed deployments and all 368 current factor rows to
  their reviewed surface scopes.
- Remove the reviewed stale `morpho-v1` standalone runtime rows.

The composed results are `v1=D/26.8` and `optimizer=B/14.3`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, source, history, and cleanup scope
  validated: `yes`
- Exactly one primary surface: `yes`, v1
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `329f045675ef148ab3520e9f502a4b3cca8f3cd42a34f7f68ab67c5a94b9b6c4`
- Production operation plan SHA-256:
  `f3bb0b642d6b1674bdb143707a7938b2441d6eafd6425a00e0138292e45e606b`
- Production cleanup identity SHA-256:
  `ece0262d100c69b9e9a16b1a852fe01cf207e00cb5420f280fda7ecee1d58226`
- Deployment workflow: [run 29330954897](https://github.com/0x-abdul/defirisk/actions/runs/29330954897),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console and page errors: `0`

## Result

The structural migration is complete. The Morpho family remains unpublished
pending assessment review, with `last_refreshed=2026-07-14`. Canonical and
legacy-alias public routes return 404. Tokenized review routes return 200 and
are noindex.

Publication requires a separate future decision.
