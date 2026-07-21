# Babylon Protocol Default Surface Refresh Change Record

- Refresh ID: `2026-07-18-local-remediation-03-babylon-protocol`
- Protocol family: `babylon-protocol`
- Surface: `default`
- Effective date: `2026-07-18`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/210
- Public artifact SHA-256:
  `22d20f38064169cd54a13b7f050fa1a45019dcf89c53684b4cf98732233fbfd8`
- Public payload SHA-256:
  `5ec23e16f19264a36edfb5f901d15e41c18d97c0639269e9dab24f6df7bb1479`

## Scope

This record covers only Babylon Protocol's canonical `default` surface and the
following factor replacements: `RD-F-001`, `RD-F-006`, `RD-F-008`, `RD-F-017`,
`RD-F-077`, `RD-F-078`, `RD-F-079`, `RD-F-080`, `RD-F-082`, `RD-F-084`,
`RD-F-085`, `RD-F-134`, `RD-F-172`, and `RD-F-182`. Every other protocol,
surface, deployment, factor, and field is out of scope. The refresh preserves
canonical topology.

## Accepted Changes

- Replace unsupported certainty with factor-specific public evidence or a
  `not_assessed` disposition where the required public evidence is absent.
- Record gray outcomes where the available public material establishes a
  relevant control or dependency but not the factor's required proof.
- Preserve the existing topology and make no protocol, deployment, or generated
  API edit in this PR.

## Verification

- Approved public handoff revalidated: `yes`
- Family/surface/factor scope validated: `yes`
- Production backup, apply, parity, generated-output, and live checks:
  pending separate authorization

## Result

The public handoff is approved only for a separately authorized, scoped
production operation. This record does not state that the refresh is deployed
or complete.
