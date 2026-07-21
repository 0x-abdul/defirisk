# Beefy Default Surface Refresh Change Record

- Refresh ID: `2026-07-18-local-remediation-03-beefy`
- Protocol family: `beefy`
- Surfaces: `default`
- Effective date: `2026-07-18`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/208
- Public artifact SHA-256:
  `806b9fb8be34787871efd39742b0d2ff43883c8f7b079b9776ae7cbc91e5996f`
- Public payload SHA-256:
  `ee98d0ab91b8cf54bfad20eb2a4516f800a873ea7f96a7a007c6fa563443e1f0`

## Scope

This record covers only Beefy's canonical `default` surface and these eight
factor replacements: `RD-F-026`, `RD-F-028`, `RD-F-077`, `RD-F-084`,
`RD-F-093`, `RD-F-095`, `RD-F-097`, and `RD-F-123`. Every other protocol,
surface, deployment, factor, and field is out of scope. The refresh preserves
canonical topology.

## Accepted Changes

- Retain documented evidence gaps where the required factor-specific public
  evidence or reproducible calculation is not available.
- Correct `RD-F-123` to `red`: a July 1, 2026 Beefy developer Safe transaction
  changed two LayerZero Revenue Bridge trusted-remote settings without an
  identified preceding public discussion. The linked issue contains the
  transaction, verified adapter, and Beefy documentation sources.

## Verification

- Approved payload checksum matched: `yes`
- Family/surface/factor scope validated: `yes`
- Unrelated generated API semantic changes: `pending production verification`
- Production backup and rollback rehearsal reference: `pending`
- Production state verified: `pending`
- Live family and surface output verified: `pending`

## Result

The public handoff is approved for a separately authorized, scoped production
operation. This record does not state that the refresh is deployed or complete.
