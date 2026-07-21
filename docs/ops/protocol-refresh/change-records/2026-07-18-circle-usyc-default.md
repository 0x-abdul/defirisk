# Circle USYC Default Surface Refresh Change Record

- Base refresh ID: `2026-07-18-local-remediation-03-circle-usyc`
- Bound source-remediation refresh ID:
  `2026-07-19-local-source-remediation-05-circle-usyc`
- Protocol family: `circle-usyc`
- Surface: `default`
- Effective correction date: `2026-07-19`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/217
- Public correction artifact SHA-256:
  `cb1edd33c74993b882495e0217eb597c304443e1d811f72a5ea2549bf6ee5e35`
- Public correction payload SHA-256:
  `4b92279113d161e2f1c4b145d89462d1768f5685b1b3860616c58c6ee1e3aa24`

## Scope

This correction covers only Circle USYC's canonical `default` surface and the
public-evidence re-adjudication of `RD-F-087`. It supersedes no topology,
protocol field, family field, deployment, or other factor claim. The linked
issue contains the full evidence-refresh claim list for the base refresh.

## Accepted Change

- `RD-F-087` remains `not_assessed`: the reviewed public contract
  documentation and explorer endpoint do not provide a complete, attributable
  pause or operational-interruption history for the approved surface.
- This PR adds a public change record only. It does not edit factors, grades,
  generated API output, or production data.

## Verification

- Public-safe correction handoff revalidated: `yes`
- Family/surface/factor scope validated: `yes`
- Exact-scope verification completed: `yes`
- Production backup, apply, parity, generated-output, and live checks:
  pending separate authorization

## Result

The public correction handoff is evidence readiness for the separately
authorized production refresh. This record does not state that production is
updated or that the refresh is complete.
