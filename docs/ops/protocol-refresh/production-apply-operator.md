# Production Protocol Refresh Apply

This procedure plans and applies one approved protocol-family refresh. It does
not authorize a production operation. The sanitized handoff always remains
non-authorizing; `--apply` requires a separate authorization receipt bound to
both the handoff artifact and the exact production plan.

Do not use this procedure until the public refresh foundation checks pass, the
target family/surfaces are present in the merged schema, and the operator has
confirmed there is no concurrent deploy, ingest, migration, or refresh.

## Safety Gate

Before a live apply, state and obtain explicit confirmation for:

- target database identity and canonical family;
- source transaction, protocol-scoped compose, temporary before/after dump,
  semantic output comparison, and receipt writes;
- backup path/ID, SHA-256, size, timestamp, restore command, and successful
  restore-test evidence;
- automatic scoped compensation after a post-commit failure;
- the manual restore path if compensation cannot be proved;
- expected generated-output and live effects.

Planning is read-only and is not approval. Tool elevation, a locally approved
bundle, the handoff's checksum, or an earlier approval for another plan does
not authorize apply.

## Production Plan

Generate a new plan against the intended database:

```powershell
python scripts/apply-protocol-refresh.py public-handoff.json `
  --plan `
  --db-url $env:DATABASE_URL `
  --plan-out production-plan.json
```

`--plan-out` uses create-new semantics and refuses to overwrite an existing
file. Database identity is the same non-secret protocol-apply identity in
`postgresql:<database>:<user>@<host>:<port>` form. The migration manager's
`--expected-database` separately guards the exact database name; it does not
replace full identity binding in plans, backups, or authorization receipts.
The plan core includes:

- `artifact_sha256`, database identity, refresh/family/surface/factor scope;
- effective refresh date and exact operation counts;
- normalized production target and unrelated-protocol hashes;
- normalized current-row hashes for every changed factor target;
- a checksum of the complete retained current-factor baseline; and
- the sanitized normalized target before-state for human review;
- local raw baseline hashes as audit metadata; and
- `plan_sha256` over the complete plan core.

Environment UUIDs and operation timestamps are removed before production
hashing. The complete current-factor baseline is a fail-closed production
precondition: it must match before any factor mutation is planned. This catches
retained, non-target factor drift that would otherwise change the recomposed
result. Per-change `expected_current_sha256` values remain additional scoped
guards; raw local baseline hashes remain audit metadata only.

Review the plan and authorize that exact `plan_sha256`. Any production drift
requires a new plan and new authorization.

## Authorization Receipt

The protocol apply receipt is a separate JSON object:

```json
{
  "schema_version": "1.0",
  "receipt_type": "protocol_refresh_production_authorization",
  "authorization_id": "approval:example-20260711",
  "operation": "apply_protocol_refresh",
  "refresh_id": "2026-07-11-example",
  "family_slug": "example",
  "artifact_sha256": "<public handoff SHA-256>",
  "plan_sha256": "<production plan SHA-256>",
  "database_identity": "<exact plan database identity>",
  "authorized_by": "<operator identity>",
  "authorized_at": "2026-07-11T00:00:00Z",
  "expires_at": "2026-07-11T02:00:00Z"
}
```

The stable pure APIs are
`validate_production_authorization_receipt` and
`load_production_authorization_receipt`. Migration tooling may reuse them with
`expected_operation="apply_refresh_migrations"`, an exact `plan_sha256`, and
an ordered `allowed_migrations`; protocol apply defaults to
`apply_protocol_refresh` and does not accept migration authority.

`rdapp` is a read-only runtime role. It has only `SELECT` on
`protocol_families` and `protocol_surfaces`; migration and production refresh
apply remain explicit operator actions and must not run as `rdapp`.

## Backup Receipt

Create and restore-test the production backup before apply. The apply tool
does not create or restore the backup. It requires the referenced file to be
locally accessible at apply time and reads it to verify the claimed byte size
and SHA-256:

```json
{
  "schema_version": "1.0",
  "receipt_type": "database_backup_receipt",
  "operation": "apply_protocol_refresh",
  "plan_sha256": "<production plan SHA-256>",
  "artifact_sha256": "<public handoff SHA-256>",
  "backup_id": "backup:example-20260711",
  "backup_path": "/secure/backups/example-20260711.dump",
  "sha256": "<backup SHA-256>",
  "size_bytes": 123456,
  "created_at": "2026-07-11T00:05:00Z",
  "database_identity": "<exact plan database identity>",
  "restore_command": "<tested restore command with secrets omitted>",
  "restore_test": {
    "status": "succeeded",
    "tested_at": "2026-07-11T00:15:00Z",
    "evidence": {"scratch_database": "<identity>", "checks": "passed"}
  }
}
```

The stable pure APIs are `validate_backup_receipt` and
`load_backup_receipt`. They require path, ID, SHA-256, positive size,
timezone-aware timestamp, matching database identity, restore command, and
successful restore-test evidence. The loader additionally resolves relative
backup paths against the receipt directory and verifies the actual file size
and digest. A receipt for another operation, plan, or handoff is rejected.

## Apply

After exact confirmation, run:

```powershell
python scripts/apply-protocol-refresh.py public-handoff.json `
  --apply `
  --db-url $env:DATABASE_URL `
  --authorization-receipt production-authorization.json `
  --backup-receipt backup-receipt.json `
  --receipt-out transaction-receipt.json
```

Apply acquires a session-level family advisory lock and holds it across plan
recomputation, source mutation, compose/dump/semantic verification, and any
compensation. It compares the plan SHA with both authorization and backup
receipts before reserving or changing rows. It then reserves one
`pipeline_runs` idempotency key,
`protocol-refresh:<refresh_id>`, and asserts all row counts.

Surface refreshes cannot change `is_primary` or `legacy_slug`; primary-surface
reassignment is a separate migration/curation operation. Factor `data_as_of`
must be timezone-aware; an omitted value becomes midnight UTC on the effective
refresh date.

For a no-change refresh, only `last_refreshed` and audit/idempotency records are
written. Compose, dump, generated output, and site rebuild are skipped.

For changed data, the tool takes a temporary pre-apply dump, commits the scoped
source transaction, runs injected protocol-scoped compose and candidate dump
runners, and runs the injected semantic verifier over the before/after API
trees. It also rechecks the normalized unrelated-protocol invariant. Any runner
failure is fatal. `dump.py` exports `protocols.last_refreshed` into the protocol
detail payload; semantic verification requires it to equal the approved
effective refresh date.

Semantic verification supports both generated detail layouts:

- published: `api/<rubric>/protocols/<family>.json`;
- unpublished: the protocol's existing opaque review directory under
  `api/<rubric>/unpublished/`.

The verifier identifies an unpublished target from the canonical family slug
inside its payload, never from a slug-prefix or review-token guess. Exactly one
target must exist, and its publication location must match before and after, so
the refresh cannot publish, unpublish, or rotate a review token. Reports and
errors redact opaque unpublished directory names. Only the resolved detail file
and a `history.json` payload naming that same family are target-owned; any other
file beneath either directory is unrelated and fails isolation. Do not add
tokenized paths to operator notes, receipts, issue text, or pull-request text.

Treat receipt-bound migration-manager activity as a separate global event.
Retain its plan, authorization, backup/restore, and ledger evidence separately,
then capture the generated-output baseline only after the migration succeeds.
The subsequent family semantic report must compare that post-migration baseline
to the candidate output and must show that no global run occurred between the
two dumps. If a global migration happens after the baseline, discard the
baseline and repeat the comparison from a new post-migration baseline; do not
amend a cross-migration comparison into a passing family-isolation result.

## Failure And Recovery

Before commit, any error rolls back the source transaction. After source
commit, compose, dump, semantic, snapshot, or invariant failure triggers
scoped compensation only when the live target still exactly matches the most
recent accounted snapshot. The expected live state advances after the source
transaction and only after a successful compose transition is proven to
contain grade fields on the target protocol/family/surfaces plus append-only
target grade/factor history. Deployments, factor/source rows and links, TVL,
descriptions, and all other non-grade fields must remain identical. A failed
compose that changed rows, an invalid successful-compose transition, or any
other unaccounted in-place target drift makes compensation
`FAILED/UNPROVED` instead of overwriting those rows. Compensation locks the
target rows and uses serializable isolation so concurrent inserts or other
phantom changes abort recovery. It then restores
the target protocol/family/surface/deployment/factor/source and grade-history
state, verifies the exact recovery snapshot and unrelated-protocol hash, and
records a compensation audit.

The original `pipeline_runs` reservation is preserved and finalized as failed,
so the same refresh ID cannot be silently retried. If compensation or its proof
fails, stop immediately, retain all receipts and temporary output, and follow
the separately approved backup restore command. Do not improvise a roll-forward
or claim completion.

On success, retain the handoff, production plan, authorization, backup receipt,
transaction receipt, and temporary semantic-verification evidence. Verify the
production DB snapshot, generated family/surfaces, aliases, publication state,
history, live page, and `last_refreshed` before completing public workflow
steps.
