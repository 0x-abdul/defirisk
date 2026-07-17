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
  `0011_active_rubric_factor_score_reads.sql`,
  `0012_runtime_role_grants.sql`, `0013_schema_migration_ledger.sql`, and
  `0014_nightly_ingest_topology_functions.sql` are
  present with the required guards, and the non-mutating export, verification,
  documentation, and issue contracts are present.

Migration files recorded in the production checksum ledger are immutable,
including comments. Later explanatory corrections belong in documentation or a
new migration; never edit a recorded migration file.
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
The public handoff envelope is schema `1.1`; its enclosed accepted-changes
payload remains schema `1.0`.

The exporter fails unless:

- the accepted artifact names exactly one canonical family;
- its declared surfaces and factors exactly contain every changed target;
- its `preserve_canonical` topology attestation matches the approved family
  and canonical surfaces and contains no migration authority;
- family, surface, and deployment factor scopes are internally consistent;
- status is exactly `local_ready_for_review`, locally `approved`, and not
  production-authorized;
- the status checksum equals the canonical SHA-256 of the accepted artifact;
- no secret, credentialed URL, local path, unpublished/review token, or
  private curator material is present.

`not_assessed` and `not_applicable` factor rows may omit sources. Gray evidence
gaps may use a public-safe `curator_note`; supplied curator notes remain subject
to the same path, credential, unpublished-material, and private-review scans as
every other public source. Green, yellow, and red rows require at least one
independently verifiable public source with an HTTP(S) locator, so a curator
note, partner feed, internal memo, or source label without a public locator is
insufficient.

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

The verifier resolves the target by the canonical family slug embedded in its
generated protocol payload. It supports both published
`protocols/<family>.json` output and the existing opaque unpublished review
directory, while requiring exactly one matching target document. The target's
publication location must be identical before and after the refresh: a refresh
cannot publish, unpublish, or rotate its review token.

The verifier ignores only export `generated_at` values and target-family rows.
Only the target detail document and a history document whose payload names the
same canonical family are target-owned files. For the newest-first bounded
`status.json` run projection, it permits new target-owned runs to evict
unchanged unrelated tail rows only at the declared full window capacity. Every
run must have a unique stable ID; retained prior rows must remain an exact
prefix, and every new row must belong to the target family. The deterministic
bucket-freshness aggregate may change only when it exactly derives from the
verified run window. It rejects unrelated additions, mutations, reordering,
middle-row removal, and every non-derived aggregate change. Unpublished paths
are redacted in reports and failures so review tokens do not enter logs or
receipts. A passing comparison does not replace factor, grade, alias, history,
publication-state, or live-site verification.

A receipt-bound migration-manager run is a global audit event, not a
family-owned refresh run. Do not compare a pre-migration dump directly with a
post-refresh dump when such a run occurs between them. First complete and
independently retain the migration plan, authorization, backup/restore, and
ledger proof. Then capture a fresh post-migration baseline dump, run the
family repair or refresh, and compare that baseline with its post-refresh dump.
The verifier must continue to reject a global migration row in a family-scoped
comparison; receipt text, a migration filename, or a broad allowlist must not
make it target-owned. If a migration occurs after a baseline is captured,
discard that baseline and create a new one after the migration.

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
