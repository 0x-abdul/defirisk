# Fluid Family Surface Migration Change Record

- Refresh ID: `2026-07-13-fluid-family-surfaces`
- Protocol family: `fluid`
- Surfaces: `lending` (primary), `dex`, `lite`
- Effective date: `2026-07-13`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/175`
- Public artifact file SHA-256:
  `5061a7490a245365e6cb7fdb39dfa3a6c5c733649c0c041e1fa4168d78f64e2d`
- Public payload SHA-256:
  `034cb99533dc906702bc0bedb4802fcfb728368cae275cbc42823a7307279a0e`

## Scope

This record covers the structural migration of the existing Fluid assessment
into canonical family `fluid`:

| Surface | Status | Primary | Legacy alias | Deployments | Grade / risk score |
| --- | --- | --- | --- | ---: | --- |
| `lending` | active | yes | `fluid` | 5 | B / 18.20 |
| `dex` | active | no | `fluid-dex` | 5 | B / 18.59 |
| `lite` | active | no | `fluid-lite` | 1 | B / 17.41 |

The reviewed payload contains 450 current factor rows, 475 factor-source joins,
and 11 deployments. Cleanup is limited to the reviewed obsolete default surface
and its dependent historical data. Every unrelated protocol, family, surface,
factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `fluid` as the canonical family.
- Establish `lending` as the sole primary surface, with `dex` and `lite` as
  active secondary surfaces.
- Preserve `fluid-dex` and `fluid-lite` as selected-surface aliases when the
  family is later published.
- Attach the 11 reviewed deployments and 450 current factor rows to their
  reviewed family or surface scopes.
- Remove the obsolete default surface after replacement and temporary alias
  compatibility checks.

The composed results are `lending=B/18.20`, `dex=B/18.59`, and `lite=B/17.41`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `lending`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 196 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `c24d1ef45624218c3c801bf40b9f2a8dd94f9641d27c2d97e088f4668f503466`
- Production operation plan SHA-256:
  `a8d45d7e00f0ea13bb11a98d4d4c48d96b820654723f124049b2bd8a1c4ad7e9`
- Production cleanup audit SHA-256:
  `9e57bee3ec43cee93645ef043aea99f013d207f410a7725ad8a04c0dc4b1f2ef`
- Deployment workflow: [run 29254548823](https://github.com/0x-abdul/defirisk/actions/runs/29254548823),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Fluid family remains unpublished
pending assessment review, with `last_refreshed=2026-07-13`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
