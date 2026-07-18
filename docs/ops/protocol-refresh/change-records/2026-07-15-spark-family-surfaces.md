# Spark Family Surface Migration Change Record

- Refresh ID: `2026-07-15-spark-family-surfaces`
- Protocol family: `spark`
- Surfaces: `sparklend` (primary), `liquidity-layer`, `savings`
- Effective date: `2026-07-15`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/195`
- Public artifact file SHA-256:
  `e1a2e890caa8a0ad94645a614e23d4d35faf5615c65efdd078a37e5cb09060a6`
- Public payload SHA-256:
  `67b4317f8da535037573365481bbd15cd8dc3a16ebbfc2339d336164a99fa38c`

## Scope

This record covers the reviewed Spark family topology:

| Surface | Status | Primary | Deployments |
| --- | --- | --- | ---: |
| `sparklend` | active | yes | 1 |
| `liquidity-layer` | active | no | 5 |
| `savings` | active | no | 1 |

The reviewed payload contains 426 current factor rows, 1,047 current
factor-source joins, and seven deployments. Cleanup preserves and remaps the
reviewed legacy history before removing one deprecated `default` surface and
one obsolete deployment. Every other protocol, family, surface, factor,
deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `sparklend` as the sole primary active surface.
- Establish `liquidity-layer` and `savings` as active secondary surfaces.
- Attach the seven reviewed deployments and 426 current factor rows to their
  reviewed family or surface scopes.
- Remap 220 current factor rows, 5,888 factor-history rows, 51 grade-history
  rows, 32 protocol-grade-history rows, and two grade-change rows.
- Remove the deprecated `default` surface and obsolete Savings deployment
  after preservation and compatibility checks.

The composed results are `sparklend=B/12.68`,
`liquidity-layer=B/17.18`, and `savings=B/17.50`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `sparklend`
- Cleanup dry-run, preservation remap, and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `6637026a6ef906e58c1c79087a0c2c6986ffd6de9c26f635af1b90d02cbddb66`
- Production operation plan SHA-256:
  `b6a490209b2276d0a37dab86b9ba6dc6c6ef785e67ee9ae34e0a83e63c89e491`
- Production operator SHA-256:
  `f2438f10206a1e12414845b09b2ec61e8a4a85bca806f43af2cba14049f976d3`
- Deployment workflow: [run 29376732656](https://github.com/0x-abdul/defirisk/actions/runs/29376732656),
  `success`
- Live public canonical route: `404`
- Live private review API, history, and pages: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Spark family remains unpublished
pending assessment review, with `last_refreshed=2026-07-15`. The canonical
public route returns 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
