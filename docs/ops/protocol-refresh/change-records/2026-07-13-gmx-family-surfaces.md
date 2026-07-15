# GMX Family Surface Migration Change Record

- Refresh ID: `2026-07-13-gmx-family-surfaces`
- Protocol family: `gmx`
- Surfaces: `v2` (primary), `v1`
- Effective date: `2026-07-13`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/179`
- Public artifact file SHA-256:
  `6eec316b56e910c207b1b8c90c51e1c1d94437066741e1dfcee533192bc00117`
- Public payload SHA-256:
  `38cdc5b549798a601eeb0bb63fc4fc9fc262d0ed65fc715af15dacf381c07183`

## Scope

This record covers the structural migration of the existing GMX assessments
into canonical family `gmx`:

| Surface | Status | Primary | Legacy alias | Deployments | Grade / risk score |
| --- | --- | --- | --- | ---: | --- |
| `v2` | active | yes | `gmx-v2` | 4 | A / 10.76 |
| `v1` | deprecated | no | — | 2 | C / 27.22 |

The reviewed payload contains 368 current factor rows, 607 factor-source joins,
and 6 deployments. Cleanup is limited to the reviewed stale `gmx-v2`
standalone assessment and its dependent historical data, with the reviewed hack
and grade-change references remapped to canonical `gmx`. Every unrelated
protocol, family, surface, factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `gmx` as the canonical family.
- Establish `v2` as the sole primary active surface and `v1` as the deprecated
  secondary surface.
- Preserve the reviewed `gmx-v2` selected-surface alias for future publication.
- Attach all 6 reviewed deployments and 368 current factor rows to their
  reviewed family or surface scopes.
- Remap the reviewed hack and grade-change references before removing the stale
  standalone assessment and its dependent history.

The composed results are `v2=A/10.76` and `v1=C/27.22`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, source, hack, and grade-change scope
  validated: `yes`
- Exactly one primary surface: `yes`, `v2`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 196 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `c744c6b7d8be6e884906869cabe1559948d0e3038e4bbc6f1b6e7fc9050c4910`
- Production operation plan SHA-256:
  `46644dab51788e7b2d8175ee2c657cc80c0dfca132c5e9ae585b7e2a1858c160`
- Production cleanup identity SHA-256:
  `681b8b18830857c1adb3c0acbfdbf0291ae29a98a6f277e33e86903d8f5508e4`
- Deployment workflow: [run 29276176161](https://github.com/0x-abdul/defirisk/actions/runs/29276176161),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The GMX family remains unpublished
pending assessment review, with `last_refreshed=2026-07-13`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
