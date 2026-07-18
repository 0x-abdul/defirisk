# Uniswap Family Surface Migration Change Record

- Refresh ID: `2026-07-14-uniswap-family-surfaces`
- Protocol family: `uniswap`
- Surfaces: `v2`, `v3` (primary), `v4`, `uniswapx`
- Effective date: `2026-07-14`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/204`
- Public artifact file SHA-256:
  `c90e0ce534ad0d1bfcbcfc452878662e9d7210186186ab307dbd055e5f2d95f4`
- Public payload SHA-256:
  `66b813f4e0b54e823aa3dc898c28c4b7924fc8490e5f735d3161ae516573a789`

## Scope

This record covers the structural migration of the existing Uniswap
assessments into canonical family `uniswap`:

| Surface | Status | Primary | Deployments | Surface-scoped factors | Grade / risk score |
| --- | --- | --- | ---: | ---: | --- |
| `v2` | active | no | 2 | 30 | A / 8.1 |
| `v3` | active | yes | 5 | 90 | A / 10.5 |
| `v4` | active | no | 4 | 30 | A / 8.1 |
| `uniswapx` | active | no | 4 | 30 | A / 9.2 |

The reviewed payload contains 82 family-scoped and 180 surface-scoped current
factor rows, 370 current factor-source joins, and 15 deployments. Cleanup is
limited to six reviewed placeholder deployments and the obsolete default
surface. The 5,823 reviewed legacy-history references were preserved on v3.
Every unrelated protocol, family, surface, factor, deployment, and field is
out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `uniswap` as the canonical family.
- Establish v3 as the sole primary active surface, with v2, v4, and UniswapX
  as active secondary surfaces.
- Attach all 15 reviewed deployments and all 262 current factor rows to their
  reviewed family or surface scopes.
- Preserve 5,823 reviewed legacy-history references on v3.
- Remove six reviewed placeholder deployments and the obsolete default
  surface.

The composed results are `v2=A/8.1`, `v3=A/10.5`, `v4=A/8.1`, and
`uniswapx=A/9.2`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, source, history, and cleanup scope
  validated: `yes`
- Exactly one primary surface: `yes`, v3
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `f3c3d9d258e3a0b9cde6731fa4817662279511637348199bcb3a9e5c69a49bd2`
- Production operation plan SHA-256:
  `b3543bf680558383bb6bf05b5ec5764b4eee238c47182db86509ac4f2ce30812`
- Production cleanup identity SHA-256:
  `cb056097a0a3880a486a30fe478d7a440722789b3328142f3a7439ff283cb07f`
- Deployment workflow: [run 29327252208](https://github.com/0x-abdul/defirisk/actions/runs/29327252208),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console and page errors: `0`

## Result

The structural migration is complete. The Uniswap family remains unpublished
pending assessment review, with `last_refreshed=2026-07-14`. Canonical and
legacy-alias public routes return 404. Tokenized review routes return 200 and
are noindex.

Publication requires a separate future decision.
