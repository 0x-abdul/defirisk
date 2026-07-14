# Aerodrome Family Surface Migration Change Record

- Refresh ID: `2026-07-12-aerodrome-family-surfaces`
- Protocol family: `aerodrome`
- Surfaces: `slipstream` (primary), `v1`, `ignition`
- Effective date: `2026-07-12`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/159`
- Public artifact file SHA-256:
  `51fd96cc648aa22d04fe2c6015bc37e058b9845d7bb760ff93807549265fb59d`
- Public payload SHA-256:
  `257af6254003e56fe225ac5204a6daaac2a744f9b5985ef374e7a919ffb9b616`

## Scope

This record covers the structural migration from the collapsed Aerodrome
assessment to canonical family `aerodrome`:

| Surface | Status | Primary | Legacy alias | Deployments | Current surface factors |
| --- | --- | --- | --- | ---: | ---: |
| `slipstream` | active | yes | `aerodrome-slipstream` | 1 | 62 |
| `v1` | active | no | `aerodrome-v1` | 1 | 73 |
| `ignition` | active | no | `aerodrome-ignition` | 1 | 47 |

Eighty-four current factor rows are family-scoped. The reviewed payload
contains 266 current factor rows, 302 factor-source joins, and three
deployments. Cleanup is limited to the stale `default` surface and its reviewed
dependent data. Every other protocol, family, surface, factor, deployment, and
field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `aerodrome` as the canonical family.
- Establish `slipstream` as the sole primary surface, with `v1` and `ignition`
  retained as active secondary surfaces.
- Preserve `aerodrome-slipstream`, `aerodrome-v1`, and `aerodrome-ignition` as
  selected-surface aliases when the family is later published.
- Attach the three reviewed deployments and 266 current factor rows to their
  reviewed family or surface scopes.
- Remove the stale `default` surface after replacement and alias compatibility
  checks.

The composed results are `slipstream=B/17.80`, `v1=B/17.48`, and
`ignition=D/31.45`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `slipstream`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 188 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `676564b4b7bd4dc6640cb90281612f4aa91af9545ee05ed05bcdb836260ea054`
- Full rollback backup SHA-256:
  `a2ab8827f2f1d39226ec88fa8280d9e0451e208898dc7f44697cacc80d14d33f`
- Production operation plan SHA-256:
  `8559fa0594dd9ebae427c9a21746c20aec635c0b1740eec1ccd06d4813a650a9`
- Cleanup manifest SHA-256:
  `4f924e4ae44f8a9e5f56f1c853170a1dd3b5a1fa5044a1587df76fd343135afe`
- Deployment workflow: [run 29190557760](https://github.com/0x-abdul/defirisk/actions/runs/29190557760),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console errors: `0`
- Public or active-log review-secret matches: `0`

## Result

The structural migration is complete. The Aerodrome family remains
unpublished pending assessment review, with `last_refreshed=2026-07-12`.
Canonical and alias public routes return 404. Tokenized review routes return
200 and are noindex.

Publication requires a separate future decision.
