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
no-claim disposition. Before a production write, Task B reconstructs the
retained database row and rejects the remediation as unnecessary when that row
is already public-safe. The disposition permits an empty source list only for
the projected old baseline row; it does not excuse a current or new graded row
from the public-evidence requirement. Task B preserves the metadata in the
public change record without changing the production baseline comparison,
retained score, or factor history.

The topology contract must say `preserve`; Task B cannot add, remove, rename,
merge, or split families, surfaces, or deployments.

## Version Routing

The production adapter selects one of two paths from the complete semantic
production baseline before that protocol's transaction writes:

- A complete v1.7.0 baseline with a v1.7.0 result uses the standard
  same-rubric refresh path. A `changed` protocol may supply only its changed
  factors; a `no_change` protocol updates only `last_refreshed`.
- A complete v1.5.0 baseline with a v1.7.0 result uses the preserved full
  migration path. Its change set continues to contain all 184 factors.
- A mixed-version or incomplete baseline, or any other version pair, is
  unsupported and fails before that protocol's production write.

The standard path verifies each supplied old row against the accepted
production baseline, applies only the changed subset, and then composes and
compares the complete 184-row protocol output. Route selection is
deterministic and remains inside the existing Task B plan and single batch
confirmation. It adds no confirmation, reviewer, receipt, or governance step.

Validate and show the exact operator plan without side effects:

```powershell
python scripts/apply-lean-protocol-refresh.py <public-change-set.json> --plan `
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

All context flags are required so the output is an exact single-confirmation
envelope, not a generic readiness report. Before confirming, the operator checks
the protocols and old/new values, production target, backup location/class,
transaction command class, PR targets, deployment workflow, live verification,
and rollback path. Confirmation authorizes only that listed batch.

## Apply and Resume

Real effects are supplied by an explicitly selected operator adapter:

```powershell
python scripts/apply-lean-protocol-refresh.py <public-change-set.json> `
  --apply --operations <reviewed-module>:<factory>
```

The adapter must implement the narrow `BatchOperations` interface in
`scripts/lean_protocol_refresh/execution.py`, including semantic protocol,
deployment, and live-state reads used for resume. Adapter selection is part of
the reviewed Task B command class and must be resolved before the single batch
confirmation. The lean runner then enforces this sequence:

1. Create or locate one production database backup for the entire batch. Prove
   it is non-empty and listable by the restore tooling before any write.
2. Read each protocol's semantic production state. Skip a protocol whose
   topology, `last_refreshed`, and changed factor values already match. This is
   the resume mechanism; no attempt or receipt chain is needed.
3. Process protocols serially in independent transactions. Preserve historical
   factor rows, supersede only changed current rows, and always update
   `last_refreshed`. Standard v1.7.0-to-v1.7.0 refreshes may apply a sparse
   changed-row subset; preserved v1.5.0-to-v1.7.0 migrations apply their full
   migration document.
4. Compose and dump to temporary output, then compare only the target protocol's
   complete 184-row semantic output. Never hand-edit generated `data/api/`
   files.
5. Commit the successful protocol. On failure, roll back only that protocol,
   record the failure in the run report, and continue with the next protocol.
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
- Create no PR or issue for `no_change`; its production transaction updates only
  `last_refreshed`.
- Do not create a GitHub issue unless a separate genuine factual correction
  needs public discussion.
- Merge successful changed-protocol PRs, deploy once after the batch, and run one
  final live check covering every changed and no-change protocol.
- If publication or deployment is interrupted, inspect semantic production and
  GitHub state, continue existing PRs, and skip already-applied protocols. Never
  repeat Task A research because Task B failed.

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
