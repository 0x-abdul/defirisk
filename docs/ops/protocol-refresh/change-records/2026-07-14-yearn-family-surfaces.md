# Yearn Family Surface Migration Change Record

- Refresh ID: `2026-07-14-yearn-family-surfaces`
- Protocol family: `yearn`
- Surfaces: `yearn-finance` (primary), `yearn-curating`
- Effective date: `2026-07-14`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/200`
- Public artifact file SHA-256:
  `c6c823b58ee29a0e4fadfd19a30edf60279cb3c5c791bf0cecf3777674d35bb0`
- Public payload SHA-256:
  `6ccdbec251a7e60c6f1715a332ba3382984c6f29ab8f80c60b6e14570fb42d01`

## Scope

This record covers the structural migration from standalone `yearn-finance`
to canonical family `yearn`:

| Surface | Status | Primary | Legacy alias | Deployments |
| --- | --- | --- | --- | ---: |
| `yearn-finance` | active | yes | `yearn-finance` | 7 |
| `yearn-curating` | active | no | none | 5 |

The reviewed payload contains 345 current factor rows, 656 factor-source joins,
and 12 deployments. Cleanup is limited to the replaced standalone row and its
reviewed dependent data. Every other protocol, family, surface, factor,
deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `yearn` as the canonical family.
- Establish `yearn-finance` as the sole primary active surface and
  `yearn-curating` as the active secondary surface.
- Preserve `yearn-finance` as the selected-surface alias when the family is
  later published.
- Attach the 12 reviewed deployments and 345 current factor rows to their
  reviewed family or surface scopes.
- Remove the stale standalone row after replacement and alias compatibility
  checks.

The composed results are `yearn-finance=B/19.31` and
`yearn-curating=F/35.52`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `yearn-finance`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `8cba8b749a38562b85b0198631cbc6e7ddb956081dff6329ebf99d69a8107b23`
- Production operation plan SHA-256:
  `2bb0e02d84618047e2a8dbce4eacb990f0080a3895057f1f49a80a9f6e00618f`
- Production cleanup identity SHA-256:
  `c7595155026c0c56ddd54a13f7c3e0c1eb38284917ae53c10447c0e63cd5da67`
- Deployment workflow: [run 29357218046](https://github.com/0x-abdul/defirisk/actions/runs/29357218046),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Yearn family remains unpublished
pending assessment review, with `last_refreshed=2026-07-14`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
