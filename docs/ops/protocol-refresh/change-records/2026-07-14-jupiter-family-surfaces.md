# Jupiter Family Surface Migration Change Record

- Refresh ID: `2026-07-14-jupiter-family-surfaces`
- Protocol family: `jupiter`
- Surfaces: `aggregator` (primary), `perps`
- Effective date: `2026-07-14`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/181`
- Public artifact file SHA-256:
  `9191af5ee5195de1086216ce65e60d0ef66c55d3689eb8aab9efcbf6a76eab13`
- Public payload SHA-256:
  `64529a39299760b173e292d3e26a72490ce7193a7fd7d72ff373fb778982a165`

## Scope

This record covers the structural migration of the existing Jupiter assessments
into canonical family `jupiter`:

| Surface | Status | Primary | Legacy alias | Deployments | Grade / risk score |
| --- | --- | --- | --- | ---: | --- |
| `aggregator` | active | yes | `jupiter` | 1 | C / 31.41 |
| `perps` | active | no | `jupiter-perps` | 1 | D / 37.42 |

The reviewed payload contains 368 current factor rows, 417 factor-source joins,
and 2 deployments. Cleanup is limited to the reviewed stale `jupiter-perps`
standalone assessment, obsolete default surfaces, and their dependent history.
No hack or active-incident remaps were required. Every unrelated protocol,
family, surface, factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `jupiter` as the canonical family.
- Establish `aggregator` as the sole primary active surface and `perps` as the
  active secondary surface.
- Preserve the reviewed `jupiter-perps` selected-surface alias for future
  publication.
- Attach both reviewed deployments and all 368 current factor rows to their
  reviewed family or surface scopes.
- Remove the reviewed stale standalone assessment, obsolete default surfaces,
  and their dependent history.

The composed results are `aggregator=C/31.41` and `perps=D/37.42`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, source, and cleanup scope validated: `yes`
- Exactly one primary surface: `yes`, `aggregator`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `a1752a89e6b7ede6665792bdacd0d1f073e61fa3d2d631f4d4a101724dc5b975`
- Production operation plan SHA-256:
  `b80c364a20fc746b53f28f23229cd93e50f8ee5b0f3cfe2627265824ceb34e3a`
- Production cleanup identity SHA-256:
  `0609512ab10351b0cdb669272d1f3547ddc0e666f409491c3a65545bdd5c7312`
- Deployment workflow: [run 29283611112](https://github.com/0x-abdul/defirisk/actions/runs/29283611112),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Jupiter family remains unpublished
pending assessment review, with `last_refreshed=2026-07-14`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
