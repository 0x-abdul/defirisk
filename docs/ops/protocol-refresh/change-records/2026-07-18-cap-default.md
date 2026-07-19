# Cap Default Surface Refresh Change Record

- Refresh ID: `2026-07-18-local-remediation-03-cap`
- Protocol family: `cap`
- Surface: `default`
- Effective date: `2026-07-18`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/64
- Public artifact SHA-256:
  `2b0632b74f82d6a962cf6376b8b9a725a0f19342f0ea5a10f10c6d7d9e7a7f66`
- Public payload SHA-256:
  `9f97747d4342d0f9f95964f7a6e2d73505587462e09e8a1a752f2edf198f2945`

## Scope

This record covers only Cap's canonical `default` surface and these twelve
factor replacements: `RD-F-008`, `RD-F-053`, `RD-F-070`, `RD-F-077`,
`RD-F-078`, `RD-F-079`, `RD-F-080`, `RD-F-104`, `RD-F-115`, `RD-F-123`,
`RD-F-158`, and `RD-F-160`. It includes the checksum-bound factor-only
correction record `2026-07-18-local-source-remediation-03-cap`. Every other
protocol, surface, deployment, factor, and field is out of scope. The refresh
preserves canonical topology.

## Accepted Changes

- Replace unsafe or unsupported evidence with factor-specific public evidence
  and retain gray outcomes where the required proof is not public.
- Retain the documented Cap investor-update evidence for `RD-F-070` as green.
- Make no protocol, deployment, factor-score, grade, or generated API edit in
  this public PR.

## Verification

- Approved public handoff revalidated: `yes`
- Family/surface/factor scope validated: `yes`
- Production backup, apply, parity, generated-output, and live checks:
  pending separate authorization

## Result

The public handoff is approved only for a separately authorized, scoped
production operation. This record does not state that the refresh is deployed
or complete.
