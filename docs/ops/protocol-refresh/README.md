# Lean Protocol Refresh: Public Task B

This is the public-repository contract for applying and publishing a completed,
public-safe Task A change set. It is intentionally small. Task B does not repeat
research, create correction chains, or require campaign records, receipts,
attempt IDs, plan hashes, packet checksums, fresh sessions, or per-protocol
owner approvals.

Task A must supply either one protocol change set or a simple batch wrapper. Each
protocol must name its canonical family and surfaces, effective refresh date,
exact approved deployment targets, `changed` or `no_change` outcome, and factor
changes with complete public-safe before/after rows. Every graded old and new
row, including gray, must contain at least one genuine public HTTP(S) evidence
source. A URL-less `curator_note` or `commit_sha` may be retained only as
auxiliary context; `curator_note` and `partner_feed` cannot independently
support a graded claim. URL-dependent source types require an explicit valid
public HTTP(S) `url`.

An immutable old row may instead carry the exact
`lean-protocol-refresh/historical-old-remediation/v1` metadata emitted by Task
A. Task A is the authority that binds the specialist and baseline hashes to the
immutable prepared row. The portable parser validates the metadata shape,
reviewed public evidence, or canonical `historical_evidence_unavailable`
no-claim disposition. Before a production write, Task B reconstructs and
semantically binds the retained database row. A conservative, hash-bound
disposition remains valid when stored legacy text happens to pass current
syntactic checks; it must not be discarded merely because that text or its
locator is structurally public-safe. The disposition permits an empty source
list only for the projected old baseline row; it does not excuse a current or
new graded row from the public-evidence requirement. Task B preserves the
metadata in the public change record without changing the retained score or
factor history.

The topology contract must say `preserve`; Task B cannot add, remove, rename,
merge, or split families, surfaces, or deployments.

## Production Baseline Classification

The production adapter classifies current rows before confirmation and repeats
that classification inside the locked per-protocol transaction:

- `standard_v17` means only v1.7.0 rows are current and they exactly cover the
  canonical 184-factor universe on the approved topology, with no duplicate
  scoped key. Every supplied changed key must match its selected current row.
  A `changed` handoff may be sparse and a `no_change` handoff normally updates
  only `last_refreshed`.
- `full_v15_migration` means only v1.5.0 rows are current, they exactly cover
  the canonical 184-factor universe on the approved topology, and the
  `changed` handoff contains all 184 scoped rows.
- `mixed_recovery` means both v1.5.0 and v1.7.0 rows are current, each rubric is
  unique by scoped key, their union exactly covers the approved roster, and at
  least one row exists in each rubric. v1.7.0 wins on overlap. This route
  requires the exact per-protocol
  `lean-protocol-refresh/mixed-recovery/v1` payload described below.
- Any other rubric, missing or unexpected scoped key, duplicate current row,
  incomplete union, or route/payload mismatch is `unsupported` and fails
  before that protocol's production write.

`mixed_recovery` requires:

- `source_rubric_version: v1.5.0`;
- `target_rubric_version: v1.7.0`;
- `selection_policy: prefer_target_then_source`;
- a canonically sorted `full_target_projection` containing exactly 184 complete
  public-safe `{factor_id, scope_level, target, value}` rows;
- `full_target_projection_semantic_sha256`; and
- `protocol_change_semantic_sha256`, calculated over the ordinary protocol
  change object before its `mixed_recovery` field is added.

The portable parser recomputes both hashes, requires the projection to match
the approved topology and scoped roster, validates every projected row through
the public-source boundary, and requires every `change.new` value to equal its
projected target value. The payload is per-protocol so mixed and ordinary
routes may coexist safely in one batch. A legacy top-level `rubric_migration`
declaration may remain parser-compatible, but it does not authorize
`mixed_recovery`.

The read-only plan must report for every protocol its classification; current
v1.5.0, current v1.7.0, and overlap counts; semantic changed-row and
migration-only counts; deduplicated total v1.7.0 insert/replacement count;
current v1.5.0 retirement count; full-target-projection hash; opaque semantic
hash of the v1.5.0 row/source-join identities for route-changing work; and
resulting grade. A generic statement that the route will be selected later at
execution is not an exact confirmation envelope.

Every route also binds the complete selected production baseline with
`selected_production_baseline_sha256`. For mixed recovery, selection follows
`prefer_target_then_source`; ordinary routes select their sole supported
rubric. The hash covers all 184 scoped current rows and their stored semantic
source identities. Each changed row in the plan carries the public-safe
selected production old value that will be used in the public change record.
When a stored selected row itself cannot cross the public-source boundary, Task
B may retain the already accepted Task A public old-row evidence for that exact
factor and scope while rebinding the production identity and retained score.
This does not change the Task A new-row adjudication or manufacture evidence.
Rows with historical remediation retain the exact Task A disposition metadata.
Their selected old-value projection is rebuilt from production with only
factor, scope, target, category, retained score, and an empty source list; the
opaque full-baseline hash still binds all stored production semantics. Task B
does not re-expose or require equality with omitted legacy claim text or source
locators. It recomputes this binding inside the serializable, advisory-locked
transaction before any write.

For route-changing work, the transaction verifies the exact current v1.5.0
row/source ledger bound by the approved legacy-history hash. It records that
same ledger atomically in `change_log` as opaque per-row hashes when the rows
are retired. For mixed recovery, the same audit entry binds the exact written
factor IDs and opaque semantic hashes of pre-existing v1.7.0 rows preserved by
`prefer_target_then_source`. Raw row and source identifiers are not exposed by
the audit entry. This narrow binding lets a later publication-only resume
distinguish the approved retirements from older retained v1.5.0 history and
prove that untouched target-rubric rows did not drift. It is not a new approval
input or executable receipt, and it never replaces the unchanged approved
plan. When a completed route is resumed, read-only classification surfaces
the original legacy-history hash from that verified audit entry, rather than
re-deriving an approval identity from later source-presentation rules.

For `standard_v17`, the runner verifies every selected, plan-bound old row,
applies only the changed subset, and composes and compares the complete 184-row
output. The preserved `full_v15_migration` route applies its complete migration
document.
Route selection is deterministic and remains inside the single exact Task B
batch confirmation; it adds no reviewer, receipt, or governance step.

Validate and show the exact operator plan without side effects:

```powershell
python scripts/apply-lean-protocol-refresh.py <public-change-set.json> --plan --json `
  --operations <reviewed-module>:<factory> `
  --production-target <database/system> `
  --backup <backup-path-or-class> `
  --transaction-command <reviewed-command-class> `
  --repository <owner/repository> `
  --base-branch <branch> `
  --deployment <workflow-or-command-class> `
  --live-check <live-target> `
  --rollback <recovery-command-class>
```

Save that exact UTF-8 JSON output as the approved plan presented for the
single confirmation. Apply must receive the unchanged file through
`--approved-plan`; it recomputes the read-only classification, legacy-history
binding, and operator context before the backup and rejects any difference. A
resume accepts each protocol only in its exact approved pre-state or its
route-specific exact completed state. The production adapter
also compares the classification again inside the serializable, advisory-locked
transaction, closing the preflight-to-write drift window.
The completed state is valid only as a resume transition from the original
approved pre-mutation plan; the runner refuses to create a fresh approval plan
that would bless a post-mutation `mixed_recovery_complete` or
`full_v15_migration_complete` state.

All context flags are required so the output is an exact single-confirmation
envelope, not a generic readiness report. Planning instantiates the reviewed
adapter and may call only its read-only baseline-classification operation; it
must not create a
backup, begin a write transaction, publish, deploy, invoke rollback, or create
another external side effect. Before confirming, the operator checks the
protocols and old/new values, route and baseline/write/retirement counts,
projection hash, production target, backup location/class, transaction command
class, PR targets, deployment workflow, live verification, and rollback path.
Confirmation authorizes only that listed batch.

If an earlier plan did not include mixed-recovery counts, retirements, and
projection hashes, publish the separate framework support, create compliant
exports, present one revised exact batch plan, and obtain one new confirmation.
That single confirmation authorizes recovery and refresh together. Do not
create a standalone reconciliation transaction or request repeated
per-protocol recovery approvals. Any protocol roster, projection, route,
production count, repository, production target, deployment, or other
operator-context drift requires a new plan and confirmation.

## Apply and Resume

Real effects are supplied by an explicitly selected operator adapter:

```powershell
python scripts/apply-lean-protocol-refresh.py <public-change-set.json> `
  --apply --approved-plan <confirmed-plan.json> `
  --operations <reviewed-module>:<factory>
```

To enforce a separate publication gate, add `--stop-before-publication`.
The runner then completes only the backup and serial, verified production
database transactions and returns with `publication_pending: true` before any
protocol branch, push, pull request, merge, deployment, or live verification.
Resuming later with the same approved plan recognizes exact completed protocol
state and continues publication without replaying a completed database write.

The adapter must implement the narrow `BatchOperations` interface in
`scripts/lean_protocol_refresh/execution.py`, including semantic protocol,
deployment, and live-state reads used for resume. Adapter selection is part of
the reviewed Task B command class and must be resolved before the single batch
confirmation. The lean runner then enforces this sequence:

1. Create or locate one production database backup for the entire batch. Prove
   it is non-empty and listable by the restore tooling before any write.
2. Read each protocol's semantic production state. Skip a protocol whose
   route-specific final state already matches. A mixed-recovery protocol is
   already applied only when production has the exact projected 184 current
   v1.7.0 rows, zero current v1.5.0 rows, the expected topology, grade, and
   `last_refreshed`, and the retained v1.5.0 history/source joins. This is the
   resume mechanism; the approved plan plus its atomic hash-bound `change_log`
   audit entry are authoritative, and no attempt or receipt chain is needed.
3. Process protocols serially in independent transactions. Preserve historical
   factor rows, supersede only changed current rows, and always update
   `last_refreshed`. Standard v1.7.0-to-v1.7.0 refreshes may apply a sparse
   changed-row subset; preserved v1.5.0-to-v1.7.0 migrations apply their full
   migration document. For `mixed_recovery`, reclassify under the serializable,
   advisory-locked transaction and require the route, scoped keys, counts, and
   projection hash to match the approved plan. Prefer v1.7.0 on overlap, insert
   missing and replacement v1.7.0 rows only from the bound full target
   projection, preserve every non-written pre-existing v1.7.0 row byte-for-byte,
   retain every v1.5.0 row and source join as history, retire every current
   v1.5.0 row with `is_current=false`, and link `superseded_by` to its
   final matched current v1.7.0 row. Recovery and refresh are one atomic
   transaction.
4. Compose and dump to temporary output, then compare only the target protocol's
   complete 184-row semantic output. Never hand-edit generated `data/api/`
   files. Before a mixed-recovery commit, require exactly 184 current v1.7.0
   rows, zero current v1.5.0 rows, exact projection/grade/topology equality,
   an exact recomputation of the approved v1.5.0 row/source-join identity hash
   and retirement count, and unchanged unrelated output.
5. Commit the successful protocol. On failure, roll back only that protocol,
   record the failure in the run report, and continue with the next protocol.
   Missing recovery payload, missing/extra/duplicate scoped keys, unsupported
   rubric, selected-old/change.old mismatch, change.new/projection mismatch,
   projection/hash/topology/source-safety mismatch, target-v1.7.0 semantic
   drift, or locked classification drift fails before commit. Never reinterpret
   an unsupported mixed baseline as another route or clone an unbound
   production row.
6. For each successfully applied or already-applied changed protocol, create or
   continue exactly one PR and merge it. No-change protocols skip GitHub.
7. Inspect semantic batch deployment/live state. Deploy only if the exact batch
   is not already deployed, then run the final live check for every successfully
   processed protocol. A live-check-only retry does not redeploy.

An adapter failure before transaction start does not trigger rollback. A backup
validation failure stops the whole batch before writes. A rollback failure is
reported prominently and requires operator recovery before retrying that
protocol.

## Publication

- Create one PR for each `changed` protocol.
- Create no PR or issue for `no_change`. A `standard_v17` no-change transaction
  updates only `last_refreshed`; a `mixed_recovery` no-change transaction may
  also perform its exact confirmed migration-only writes and v1.5.0
  retirements. Those rows do not manufacture assessment changes or a PR.
- Do not create a GitHub issue unless a separate genuine factual correction
  needs public discussion.
- Merge successful changed-protocol PRs, deploy once after the batch, and run one
  final live check covering every changed and no-change protocol.
- If publication or deployment is interrupted, inspect semantic production and
  GitHub state, continue existing PRs, and skip only protocols whose
  route-specific final-state checks pass. A partially recovered mixed baseline
  fails closed until a revised plan is confirmed. Never repeat Task A research
  merely because Task B failed; create a new bound export only when the handoff
  contract itself must change.

Public releases must use the repository's explicit publication/export path.
Never push internal research, local paths, private review material, secrets, or
curator working notes to the public repository. Existing backup retention policy
and database factor history remain mandatory.

The VPS deploy builds and validates from a clean detached worktree at the
reviewed target commit. Existing generated API/site output, recovery backups,
tool caches, and the exact retained operator remnants named in
`scripts/ci/deploy-vps-safe.sh` remain outside that staged build. The control
service executes its versioned copy under `/usr/local/lib`, not an untracked
checkout copy. Any untracked path outside that closed list fails preflight.
