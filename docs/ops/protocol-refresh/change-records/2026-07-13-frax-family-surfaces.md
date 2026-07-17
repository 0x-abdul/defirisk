# Frax Family Surface Migration Change Record

- Refresh ID: `2026-07-13-frax-family-surfaces`
- Protocol family: `frax`
- Surfaces: `usd` (primary), `ether`, `stablecoin`, `fraxlend`
- Effective date: `2026-07-13`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/177`
- Public artifact file SHA-256:
  `a23815e04ae0e0e0af2d5f31150240d2b4501d97c0e04304e83f2b58a247a8f9`
- Public payload SHA-256:
  `42564d9c35154073d6c315e1cde6eb08597ed9b2f54d8b6006332834efa48f92`

## Scope

This record covers the structural migration of the existing Frax assessment
into canonical family `frax`:

| Surface | Status | Primary | Legacy alias | Deployments | Grade / risk score |
| --- | --- | --- | --- | ---: | --- |
| `usd` | active | yes | `frax-usd` | 4 | C / 26.00 |
| `ether` | active | no | `frax-ether` | 2 | C / 22.61 |
| `stablecoin` | active | no | `frax` | 3 | C / 23.87 |
| `fraxlend` | active | no | `fraxlend` | 1 | C / 30.51 |

The reviewed payload contains 507 current factor rows, 849 factor-source joins,
and 10 deployments. Cleanup is limited to the reviewed obsolete default surface
and its dependent historical data. Every unrelated protocol, family, surface,
factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `frax` as the canonical family.
- Establish `usd` as the sole primary surface, with `ether`, `stablecoin`, and
  `fraxlend` as active secondary surfaces.
- Preserve the reviewed legacy selected-surface aliases for future publication.
- Attach all 10 reviewed deployments and 507 current factor rows to their
  reviewed family or surface scopes.
- Remove the obsolete default surface after replacement and temporary alias
  compatibility checks.

The composed results are `usd=C/26.00`, `ether=C/22.61`,
`stablecoin=C/23.87`, and `fraxlend=C/30.51`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `usd`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 196 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `02c8f59664a6c719caca2833dba900e239abdb16c79b22d7b268b81ad6cd5464`
- Production operation plan SHA-256:
  `9a5353b15148b3109335a6f492ef66b1e4ded826280577031a11073a5b08dbd6`
- Production cleanup identity SHA-256:
  `29f91c4d842de51fcf491a1a2783903022388b45e2c7b5ef0e4f202bc78b53b9`
- Deployment workflow: [run 29266293452](https://github.com/0x-abdul/defirisk/actions/runs/29266293452),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Frax family remains unpublished
pending assessment review, with `last_refreshed=2026-07-13`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
