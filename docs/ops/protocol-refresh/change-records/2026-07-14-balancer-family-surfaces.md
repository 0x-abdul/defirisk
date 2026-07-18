# Balancer Family Surface Migration Change Record

- Refresh ID: `2026-07-14-balancer-family-surfaces`
- Protocol family: `balancer`
- Surfaces: `v2` (primary), `v3`
- Effective date: `2026-07-14`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/202`
- Public artifact file SHA-256:
  `a577fa41cf96215a4f9892d7f8ae8cceee615d59fc16490452e0c76cf5754c45`
- Public payload SHA-256:
  `c269aa3e73bb685a3eb3e07f142e80529cb59d5a01108b7661c2d0f9eceaeee7`

## Scope

This record covers the structural migration of the existing Balancer
assessments into canonical family `balancer`:

| Surface | Status | Primary | Deployments | Current factors | Grade / risk score |
| --- | --- | --- | ---: | ---: | --- |
| `v2` | legacy | yes | 7 | 172 | C / 23.96 |
| `v3` | active | no | 10 | 140 | B / 15.89 |

The reviewed payload contains 312 current factor rows, 384 current
factor-source joins, and 17 deployments. Cleanup is limited to seven reviewed
placeholder deployments and the obsolete default surface. The 5,972 reviewed
legacy-history references were preserved on v2. Every unrelated protocol,
family, surface, factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `balancer` as the canonical family.
- Establish v2 as the sole primary legacy surface and v3 as the active
  secondary surface.
- Attach all 17 reviewed deployments and all 312 current factor rows to their
  reviewed family or surface scopes.
- Preserve 5,972 reviewed legacy-history references on v2.
- Remove seven reviewed placeholder deployments and the obsolete default
  surface.

The composed results are `v2=C/23.96` and `v3=B/15.89`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, source, history, and cleanup scope
  validated: `yes`
- Exactly one primary surface: `yes`, v2
- Temporary canonical compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `7108a8b98ccb388f556dbdff4ef19d6811547b25f6cbb2630ff4b8069d18e10d`
- Production operation plan SHA-256:
  `41582299aea5e914c07280546578fe701ecd2a2b63e30c087a408256a0cba0c9`
- Production cleanup identity SHA-256:
  `b1cc131826a1a576923e3adbb4fa5b0e05c40f40f543200909dc1bd655768794`
- Deployment workflow: [run 29294011691](https://github.com/0x-abdul/defirisk/actions/runs/29294011691),
  `success`
- Live public canonical route: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console and page errors: `0`

## Result

The structural migration is complete. The Balancer family remains unpublished
pending assessment review, with `last_refreshed=2026-07-14`. The canonical
public route returns 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
