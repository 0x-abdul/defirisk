# BlackRock BUIDL Default Surface Refresh Change Record

- Refresh ID: `2026-07-18-local-remediation-03-blackrock-buidl`
- Protocol family: `blackrock-buidl`
- Surface: `default`
- Effective date: `2026-07-18`
- Rubric version: `v1.7.0`
- Public issue: https://github.com/0x-abdul/defirisk/issues/211
- Public artifact SHA-256:
  `e7064a97ac704fdd8279c29a53512d8c2642f14cbc31c85fa22ef98f241eaa73`
- Public payload SHA-256:
  `2f7b2c424109f0737dcb319a69fb35c385b13b830dd5521999fa4486a88f905e`

## Scope

This record covers only BlackRock BUIDL's canonical `default` surface and the
following factor replacements: `RD-F-099`, `RD-F-147`, `RD-F-148`, `RD-F-149`,
`RD-F-150`, `RD-F-151`, `RD-F-152`, `RD-F-153`, `RD-F-154`, `RD-F-155`,
`RD-F-156`, and `RD-F-157`. Every other protocol, surface, deployment, factor,
and field is out of scope. The refresh preserves canonical topology.

## Accepted Changes

- Record the publicly documented RedStone/Securitize and Wormhole integration
  context while retaining gray outcomes where direct BUIDL endpoint or
  factor-specific control evidence is not public.
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
