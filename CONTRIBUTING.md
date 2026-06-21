# Contributing

The Risk Dashboard publishes neutral, evidence-based risk intelligence for
DeFi protocols. The contribution model exists to grow coverage and improve
the open governance artifacts (schema, rubric, adapters, frontend) without
ever permitting external writes to per-protocol verdicts.

If you only have five minutes, the rules in one breath:

- Coverage / adapter / docs / frontend / rubric-debate PRs: welcome.
- Direct edits to a protocol's factor scores or letter grade: never.
- Found a factual error on a protocol page? File a
  [Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md); do not
  open a PR against the data.
- Disagree with how the rubric was applied? File a
  [Grade Dispute](.github/ISSUE_TEMPLATE/grade-dispute.md).
- Found a security issue? See [SECURITY.md](SECURITY.md).

The full, canonical guide lives at <https://defirisk.co/contributions/>.

The full rules below are non-negotiable for v1.

## What we accept via PR

You can open a pull request to:

- **Improve site code or accessibility.** The site lives under `site/`. We
  particularly welcome WCAG 2.2 AA accessibility fixes and performance improvements.
- **Improve the scoring scripts.** `scripts/compose.py`, `scripts/dump.py`,
  and `scripts/rubric.py` are MIT-licensed and open to improvement PRs.
- **Propose a rubric threshold change.** Open a discussion issue with evidence;
  public debate is expected before any merge.
- **Improve DB migrations.** Schema improvements via `db/migrations/`.
- **Improve documentation, examples, or translations.**

## What we never accept via PR

- **Direct writes to per-protocol factor records.** The data layer is
  populated only by pipeline output and curator review. Even a well-meaning
  PR that "corrects a single field" cannot be merged through this path —
  it has to go through the Factual Correction → curator review → pipeline
  rerun path described below.
- **Direct rubric-grade overrides.** Letter grades are deterministic
  functions of factor scores; you cannot patch a grade by editing the
  output file.
- **Edits to `data/api/v1.x.x/protocols/*.json`.** These files are
  regenerated from the database on every deploy.

The reasoning: the blast radius of a missed bad PR (a protocol team submitting
favourable data about itself) is bigger than the throughput gain. Risk data is
opinionated — unlike mechanically derivable on-chain metrics, it requires
curator judgment. All data changes flow through the curator review path below.

## Corrections and disputes

If you've found an error or you disagree with an assessment, there are three
channels — pick the one that matches what you're claiming is wrong. The full
public guide is at <https://defirisk.co/contributions/#corrections>.

- **[Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md)** — a
  specific data point is wrong and you can cite a source (URL, contract
  address, audit PDF page, on-chain tx). We re-evidence the factor and the
  letter recomputes.
- **[Grade Dispute](.github/ISSUE_TEMPLATE/grade-dispute.md)** — the facts are
  right but the rubric was applied incorrectly. Resolved through the
  [appeals process](https://defirisk.co/methodology/#appeals) by
  re-adjudicating the disputed factor.
- **[Rubric Proposal](.github/ISSUE_TEMPLATE/rubric-proposal.md)** — the rule
  itself is miscalibrated. Reviewed by the maintainer and either accepted into
  a future rubric version, deferred, or declined with a public note.

Every submission is acknowledged and triaged within **five business days**; a
Grade Dispute reaches a published decision within **14 days** of filing. The
decision and reasoning are recorded on the issue thread, which becomes part of
the public audit trail for that protocol. Every change flows through one of
these channels — never a direct PR against the data.

## Protocol-team self-service

If you represent a protocol covered by the dashboard, use the Factual
Correction issue template to submit updates (audit links, multisig changes,
timelock changes, oracle config). The curator team reviews within five
business days. All changes are public.

## Pre-publication review window

Before a protocol's grade goes public, its team is given a private review
window. The public-facing version of this guide is at
<https://defirisk.co/contributions/#review-window>. If you received a private
link, here's what it means:

- **Your link** looks like `https://defirisk.co/unpublished/<slug>-<token>/`.
  It is unguessable, unlisted, `noindex`, and not linked anywhere on the site —
  the page is **not public** and won't appear in search or on the homepage.
- **You have ~one week** (the exact date is in the message you received) to
  review your protocol's data for factual accuracy.
- **To flag an error**, open a [Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md)
  issue with the factor ID (e.g. `RD-F-027`), the current vs. correct value, and
  a source (URL, contract address, audit PDF page, or on-chain tx). You can also
  reply on the channel the link came from and we'll file it for you.
- **What we can fix:** factual data points with a verifiable source. The letter
  grade itself is computed deterministically from the factor scores — correcting
  a factor may move the grade, but we don't hand-edit grades. If you think the
  rubric was *misapplied* to your assessment, use a
  [Grade Dispute](.github/ISSUE_TEMPLATE/grade-dispute.md); if you think the
  rubric *rule itself* is wrong, use a
  [Rubric Proposal](.github/ISSUE_TEMPLATE/rubric-proposal.md).
- **Going live:** once you've reviewed (or the window closes), your protocol is
  published and moves to its public URL `https://defirisk.co/protocols/<slug>/`.
  Nothing is published until you've had the chance to review.

## Local development

Prerequisites: Node 22, Python 3.11+, Postgres 16, git.

```bash
# Install site dependencies
cd site && npm install

# Run the site (reads from data/api/v1.7.0/ — no DB needed for local preview)
npm run dev

# Run site tests
npm test
```

To run the scoring pipeline locally against a Postgres DB:

```bash
# Set connection string
export LOCAL_DATABASE_URL=postgresql://user:pass@localhost:5432/risk_dashboard

# Apply schema
psql $LOCAL_DATABASE_URL < db/migrations/0000_initial.sql
# ... repeat for 0001–0007

# Recompute grades
python scripts/compose.py

# Regenerate JSON data tree
python scripts/dump.py
```

## Pull-request expectations

- One topic per PR. Refactors that touch unrelated code make review hard.
- Tests for new code paths. Vitest for site logic; a Playwright spec for
  any new page or interactive component; pytest for new fetchers (test
  pattern under construction).
- A short PR description that says what changed and why.
- CI must pass. Visual-regression and smoke jobs are informational at v1
  and don't block merge; everything else does.
- Sign your commits if you have GPG configured. Not required.

## Code style

- TypeScript strict mode. No `any` without an inline justification.
- Astro components: use `.astro` for static, `.tsx` for interactive
  islands. Co-locate styles in `.module.css` for islands.
- Python: follow PEP 8. A repo-wide `ruff` config is on the v1 hardening
  list; for now match the surrounding file.
- Markdown: hard-wrap at ~80 cols where practical.
- No comments that restate what the code does. Reserve comments for
  non-obvious "why" — a hidden constraint, a workaround, a load-bearing
  invariant.

## License

By contributing, you agree that your contributions are licensed under the
same terms as the directory you're modifying:

| Path | License |
|------|---------|
| `site/`, `db/`, `scripts/`, `.github/` | [MIT](LICENSE) |
| `data/`, `docs/methodology/` | [CC-BY 4.0](LICENSE.data) |

## Code of Conduct

All contribution and community spaces follow our
[Code of Conduct](CODE_OF_CONDUCT.md).
