# Sky Family Surface Migration Change Record

- Refresh ID: `2026-07-15-sky-family-surfaces`
- Protocol family: `sky`
- Surfaces: `lending` (primary), `money`, `rwa`
- Effective date: `2026-07-15`
- Rubric version: `v1.7.0`
- Public issue: `https://github.com/0x-abdul/defirisk/issues/193`
- Public artifact file SHA-256:
  `7d0276c735da9f2e595170435ff3dd934c3d9d827769b69ed0c9b8f8e40ff3c9`
- Public payload SHA-256:
  `ed60a8b18d3628e34294a2e4f34b9d27def9f0d5a6a648bd1f32ef6bdc73e76a`

## Scope

This record covers the structural migration from standalone `sky-lending` to
canonical family `sky`:

| Surface | Status | Primary | Legacy alias | Deployments |
| --- | --- | --- | --- | ---: |
| `lending` | active | yes | `sky-lending` | 1 |
| `money` | active | no | none | 1 |
| `rwa` | active | no | none | 1 |

The reviewed payload contains 374 current factor rows, 840 current
factor-source joins, and three deployments. Cleanup remaps and preserves the
reviewed standalone history, factors, source joins, grade history, and grade
changes before removing the replaced standalone row. Every other protocol,
family, surface, factor, deployment, and field is out of scope.

Generated API files are deployment outputs and are not part of this tracked
change.

## Accepted Changes

- Establish `sky` as the canonical family.
- Establish `lending` as the sole primary active surface, with `money` and
  `rwa` as active secondary surfaces.
- Preserve `sky-lending` as the selected-surface alias when the family is
  later published.
- Attach the three reviewed deployments and 374 current factor rows to their
  reviewed family or surface scopes.
- Preserve reviewed standalone history and remove the stale standalone row
  after replacement and alias compatibility checks.

The composed results are `lending=B/13.59`, `money=B/14.03`, and
`rwa=B/14.41`.

## Verification

- Approved payload checksum matched: `yes`
- Family, surface, factor, deployment, and source scope validated: `yes`
- Exactly one primary surface: `yes`, `lending`
- Temporary canonical and alias compatibility validated: `yes`
- Cleanup dry-run, preservation remap, and exact identity checks: `yes`
- Unrelated generated API semantic changes: `none`; 194 non-target detail and
  history documents matched apart from approved metadata
- Production backup SHA-256:
  `c5c4194b53f0c27bb8222b420e95e4c9db64a8d2747256cfe7e52b0c4c0b71b0`
- Production operation plan SHA-256:
  `d35e4062022a4460473a612cd799f7d63666f7c0edd10d5bb641806441c5f5ac`
- Production cleanup materializer SHA-256:
  `d63457a6481d281aab420c80caa0a4ea8719fbcf9ce0bcc9b9443deffb9355ff`
- Deployment workflow: [run 29364230332](https://github.com/0x-abdul/defirisk/actions/runs/29364230332),
  `success`
- Live public canonical and alias routes: `404`
- Live private review API, history, and page: `200`
- Review page indexing policy: `noindex`
- Browser console, page, request, and response errors: `0`

## Result

The structural migration is complete. The Sky family remains unpublished
pending assessment review, with `last_refreshed=2026-07-15`. Canonical and alias
public routes return 404. Tokenized review routes return 200 and are noindex.

Publication requires a separate future decision.
