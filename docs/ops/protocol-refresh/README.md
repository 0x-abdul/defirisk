# Public Protocol Data Refresh

This directory defines the public repository boundary for a data refresh of an
already covered protocol family. The foundation is non-mutating: it validates
an approved local artifact, rejects private material, prepares a review-only
JSON handoff, and proves that temporary generated API changes are isolated to
the named family.

It does not authorize or apply a production change. It does not connect to the
production database or GitHub, run composition or dump jobs, edit generated
`data/api/` files, or publish an issue or pull request.

## Readiness Gates

Readiness is intentionally split into three gates:

- `foundation_ready`: migrations `0008_protocol_surfaces.sql`,
  `0009_protocol_last_refreshed.sql`, `0010_protocol_refresh_idempotency.sql`,
  `0012_runtime_role_grants.sql`, and `0013_schema_migration_ledger.sql` are
  present with the required guards, and the non-mutating export, verification,
  documentation, and issue contracts are present.
- `apply_ready`: the foundation is ready and the separately owned production
  `scripts/apply-protocol-refresh.py` worker, receipt-gated migration manager,
  runtime grant policy verifier, dry-run/apply/backup/rollback support, and
  operator procedure exist and have been rehearsed. A handoff checksum is not
  apply authorization.
- `rollout_ready`: apply readiness is established, the separate 18-family
  import/cleanup work has completed with family/surface parity, and recorded
  pilot refreshes have passed rollback and verification checks.

`production_ready` in the static report is an alias for `rollout_ready`; it is
never inferred from foundation completeness. Check the current static report:

```powershell
python scripts/verify-protocol-refresh-public.py --readiness
python scripts/verify-protocol-refresh-public.py --foundation-only
python scripts/verify-protocol-refresh-public.py --apply-ready
```

The default `--readiness` report exits successfully even when apply or rollout
is not ready. `--foundation-only` and `--apply-ready` make the selected gate an
exit-status requirement without turning an unmet gate into a contract error.
Static checks do not prove database, backup, credential, GitHub, deploy, or
live-site state.

## Input Boundary

The exporter accepts `accepted-changes.json` plus its matching `status.json`
from the internal process. Do not copy internal research folders, review notes,
curator records, protocol packets, or publication queues into this repository.

The exporter fails unless:

- the accepted artifact names exactly one canonical family;
- its declared surfaces and factors exactly contain every changed target;
- family, surface, and deployment factor scopes are internally consistent;
- status is exactly `local_ready_for_review`, locally `approved`, and not
  production-authorized;
- the status checksum equals the canonical SHA-256 of the accepted artifact;
- no secret, credentialed URL, local path, unpublished/review token, or
  curator-only field or value is present.

The exporter removes only the known internal actor/note fields
`factor_scores[].collected_by`, `sources[].retrieved_by`, and
`sources[].notes`. Every other field is governed by an exact public allowlist;
unknown, SQL, command, or nested payload fields are rejected rather than
copied. The source checksum continues to cover the complete approved input,
while `payload_sha256` covers the sanitized payload. Baseline hashes are
retained as opaque local audit fields only; they are not asserted to be
production fingerprints.

Structural surface ownership is outside this channel. Public refresh scope and
payloads reject `is_primary` and `legacy_slug`; primary-surface reassignment and
alias migration belong to the separately reviewed family migration tooling.

Export to a disposable JSON path outside generated API data:

```powershell
python scripts/export-protocol-refresh.py <approved-refresh-directory> `
  --output <scratch-directory>/public-handoff.json
python scripts/verify-protocol-refresh-public.py `
  <scratch-directory>/public-handoff.json
```

The handoff contains `production_authorized: false` and a checksum over both
the public payload and complete artifact. Editing any accepted value after
approval invalidates it and requires local re-review.

## Publication Metadata

Publication metadata is proposed and validated as JSON before any GitHub
operation. The verifier performs no network request and makes no mutation.

A changed refresh proposal has this shape:

```json
{
  "schema_version": "1.0",
  "refresh_id": "2026-07-11-example",
  "family_slug": "example",
  "approval_state": "approved",
  "approved_public_payload_sha256": "<64 lowercase hex characters>",
  "issue": {
    "url": "https://github.com/owner/repository/issues/123",
    "reference": "owner/repository#123",
    "title": "Refresh example protocol data",
    "body": "Exact approved issue body"
  },
  "branch_name": "protocol-refresh-example",
  "worktree_name": "protocol-refresh-example",
  "commit_message": "Refresh example protocol data",
  "pull_request": {
    "title": "Refresh example protocol data",
    "body": "Exact approved pull request body"
  },
  "comments": []
}
```

Changed refreshes require a valid issue URL or reference and an approved public
payload checksum that exactly matches the handoff. Branch, worktree, commit,
issue, pull-request, and comment text must contain no AI, assistant, model, tool,
or vendor attribution. A no-change refresh rejects all issue, branch, commit,
pull-request, and comment metadata because it creates no GitHub activity.

```powershell
python scripts/verify-protocol-refresh-public.py public-handoff.json `
  --publication-metadata publication-proposal.json `
  --require-publication-metadata
```

Passing this check approves nothing. The exact production operation and exact
GitHub payloads still require their own explicit user approvals.

## Generated Output Isolation

Composition and dump tooling must write to temporary before/after roots. Never
edit `data/api/` to apply a refresh. Compare the roots semantically:

```powershell
python scripts/verify-protocol-output.py <before-api-root> <after-api-root> `
  --family <family-slug>
```

The verifier ignores only export `generated_at` values and target-family rows.
It rejects added, removed, or changed JSON files and aggregate rows that cannot
be attributed to the target family. A passing comparison does not replace
factor, grade, alias, history, publication-state, or live-site verification.

## Public Change Record

For a changed refresh, fill in
`templates/change-record.template.md` without private research material. Link
the approved issue and record the public payload checksum, exact family and
surface scope, semantic output verification, and eventual live verification.
No-change refreshes create no issue, pull request, change record, generated
output change, or site rebuild.

Production operation details are maintained separately in
`production-apply-operator.md`. Its presence is required for `apply_ready`, but
neither that document nor an apply-ready report constitutes authorization.
