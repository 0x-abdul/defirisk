# Chainlink CCIP Default Surface Refresh Change Record

- Refresh ID: `2026-07-18-local-remediation-03-chainlink-ccip`
- Protocol family: `chainlink-ccip`
- Surface: `default`
- Effective date: `2026-07-18`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/214
- Public artifact SHA-256:
  `2e19e7bb97d65ac453a4172a164b836383affc5e27fad106485d919161644f3e`
- Public payload SHA-256:
  `3b660ff7f25e9202a47eaf0abb3078a9f3692a4da64d9df4ad919044e76be4d3`

## Scope

This record covers only Chainlink CCIP's canonical `default` surface and these
five factor replacements: `RD-F-078`, `RD-F-079`, `RD-F-080`, `RD-F-162`, and
`RD-F-182`. Every other protocol, surface, deployment, factor, and field is
out of scope. The refresh preserves canonical topology.

## Accepted Changes

- Retain gray or `not_assessed` outcomes where available public material does
  not establish the factor's required incident-history or control proof.
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
