# PancakeSwap Family Surface Migration Change Record

- Refresh ID: `2026-07-15-pancakeswap-family-surfaces`
- Protocol family: `pancakeswap`
- Surfaces: `v2` (primary), `v3`, `infinity`
- Effective date: `2026-07-15`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/185`
- Public artifact file SHA-256:
  `0eceb52dc1cf007a00c0ed6ed4f93aae47ee008e3d82045c315d7abcf96ca29e`
- Public payload SHA-256:
  `8027651f0f7f67ac8c6e4364b93d19a2700a28b9c68d5bbb09be38ff0b544dca`

## Scope

This record covers the structural migration of the existing PancakeSwap
assessment into canonical family `pancakeswap`:

| Surface | Status | Primary | Legacy alias | Deployments | Grade / risk score |
| --- | --- | --- | --- | ---: | --- |
| `v2` | legacy | yes | none | 7 | C / 22.19 |
| `v3` | active | no | none | 8 | C / 23.83 |
| `infinity` | active | no | none | 2 | C / 29.17 |

The reviewed payload contains 414 current factor rows, 466 factor-source joins,
and 17 deployments. Cleanup removes the obsolete `default` surface and eight
stale deployments while preserving and remapping reviewed factor, grade, and
protocol history. No legacy aliases, hack remaps, or active-incident remaps are
part of this migration. Every unrelated protocol, family, surface, factor,
deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `pancakeswap` as the canonical family.
- Establish `v2` as the sole primary legacy surface, with `v3` and `infinity`
  as active secondary surfaces.
- Attach all 17 reviewed deployments and 414 current factor rows to their
  reviewed family or surface scopes.
- Remove the obsolete `default` surface and eight stale deployments.
- Preserve and remap 233 factor scores, 5,888 factor-history rows, 47 grade-
  history rows, 32 protocol-grade-history rows, and 2 grade-change rows.

The composed results are `v2=C/22.19`, `v3=C/23.83`, and
`infinity=C/29.17`.

## Verification

- Approved public artifact checksum matched: `yes`
- Family, surface, factor, deployment, source, and cleanup scope validated: `yes`
- Exactly one primary surface: `yes`, `v2`
- Temporary canonical compatibility validated: `yes`; no aliases exist
- Cleanup dry-run, exact identity, and rollback checks: `yes`
- Unrelated generated API semantic changes: `none`; the normalized non-target
  detail and history manifest matched apart from approved metadata
- Production backup SHA-256:
  `3f547afefd57c0a69dabdb800bdbecaaef5c10833fababcb70149a9aec73fddc`
- Production operation plan SHA-256:
  `a21a50abbc596e8a37eac9292413bb836bbf27b6c36189537cd301600b2dae27`
- Grade-change scope amendment SHA-256:
  `75da6006771272b9c4c3b749e807f32643dd185ec15f2a765a2b45762c5732aa`
- Deployment workflow: [run 29414040909](https://github.com/0x-abdul/defirisk/actions/runs/29414040909),
  `success`
- Live public canonical route: `404`; legacy alias count: `0`
- Live private review API, history, and all surface pages: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The PancakeSwap family remains unpublished
pending assessment review, with `last_refreshed=2026-07-15`. The canonical
public route returns 404; tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
