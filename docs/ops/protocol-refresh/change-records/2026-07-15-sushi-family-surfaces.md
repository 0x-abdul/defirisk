# Sushi Family Surface Migration Change Record

- Refresh ID: `2026-07-15-sushi-family-surfaces`
- Protocol family: `sushi`
- Surfaces: `sushiswap` (primary), `sushiswap-v3`
- Effective date: `2026-07-15`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/197`
- Public artifact file SHA-256:
  `2c2c4089726c3f8d4c4b29067ed9c462ad4eb52201154a8826c6abce4900e3ad`
- Public payload SHA-256:
  `596e5f8bc2588f789d9d27ff56036f84be67fbf66d0aa9e809acec63c0f01a46`

## Scope

This record covers the structural migration of the existing Sushi assessment
into canonical family `sushi`:

| Surface | Status | Primary | Legacy alias | Deployments |
| --- | --- | --- | --- | ---: |
| `sushiswap` | active | yes | `sushi` | 5 |
| `sushiswap-v3` | active | no | `sushiswap-v3` | 5 |

The reviewed payload contains 299 current factor rows, 684 current
factor-source joins, and ten deployments. Cleanup preserves 229 legacy factor
rows and 369 source edges, remaps every reviewed history identity, and removes
one obsolete `default` surface and six legacy deployments. Every other
protocol, family, surface, factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `sushi` as the canonical family.
- Establish `sushiswap` as the sole primary active surface and
  `sushiswap-v3` as the active secondary surface.
- Preserve `sushi` and `sushiswap-v3` as selected-surface routes when the
  family is later published.
- Attach the ten reviewed deployments and 299 current factor rows to their
  reviewed family or surface scopes.
- Preserve and remap 43 grade-history rows, 28 protocol-grade-history rows,
  and 5,152 factor-score-history rows: 5,223 reviewed history rows in total.
- Remove the obsolete `default` surface and six legacy deployments only after
  the complete preservation/remap checks pass.

The final history contains 47 grade-history rows, 30 protocol-grade-history
rows, and 5,496 factor-score-history rows. The composed results are
`sushiswap=B/12.82` and `sushiswap-v3=B/15.05`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, source, and history scope validated:
  `yes`
- Exactly one primary surface: `yes`, `sushiswap`
- Cleanup dry-run, complete 5,223-row preservation/remap, and exact identity
  checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `d8e170f4c227a38591c3a3933669d815a4dcab1bbe53b0401f58c50912ce41cf`
- Production operation plan SHA-256:
  `15ddac7d5f26f8d9263381e6692d7ab123790a1dd3299a3aa5ee38f42ce0de52`
- Production operator SHA-256:
  `15d8cd3ecb6085a481fe69f038e1af899f5c51912973a8609c179160654ee833`
- Deployment workflow: [run 29384387651](https://github.com/0x-abdul/defirisk/actions/runs/29384387651),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and pages: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Sushi family remains unpublished
pending assessment review, with `last_refreshed=2026-07-15`. Canonical and
alias public routes return 404. Tokenized review routes return 200 and are
noindex.

Publication requires a separate future decision.
