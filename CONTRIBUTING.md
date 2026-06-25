# Contributing

defirisk.co is an open-source risk transparency dashboard for defi protocols.
Contributions improve the site, docs, schemas, scoring pipeline, rubric, and
coverage process without allowing direct external writes to protocol verdicts.

The canonical public guide lives at
<https://defirisk.co/contributions/>. This file adds repo-specific development
and pull-request expectations.

## Quick paths

Use the path that matches what you want to change:

| You want to | Use |
|-------------|-----|
| Improve code, docs, schemas, migrations, or scoring scripts | Pull request |
| Request coverage for a protocol | [Coverage Request](.github/ISSUE_TEMPLATE/coverage-request.md) |
| Fix a wrong data point | [Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md) |
| Challenge how the rubric was applied | [Grade Dispute](.github/ISSUE_TEMPLATE/grade-dispute.md) |
| Propose a rubric change | [Rubric Proposal](.github/ISSUE_TEMPLATE/rubric-proposal.md) |
| Report a security issue | [SECURITY.md](SECURITY.md) |

If you file in the wrong place, maintainers can route it to the correct
channel and say so on the thread.

## What we accept via PR

Pull requests are welcome for:

- **Site improvements.** The Astro site lives in `site/`. Accessibility fixes,
  especially WCAG 2.2 AA issues, and performance improvements are welcome.
- **Scoring pipeline improvements.** `scripts/compose.py`,
  `scripts/dump.py`, `scripts/rubric.py`, and `db/migrations/` are open to
  focused changes.
- **Documentation, examples, and translations.**
- **Schemas and developer ergonomics.** Keep changes compatible with the
  published API envelope unless the PR is explicitly for a versioned breaking
  change.
- **Rubric proposals.** Open a public issue first when the change would alter
  factor meaning, thresholds, critical status, or grade outcomes.

Keep one topic per PR. Include tests for new code paths and a short
description of what changed and why.

## What we never accept via PR

Pull requests cannot write to per-protocol factor scores or letter grades.
They also cannot change generated files under `data/api/` as a way to alter
an assessment. The generated data tree is rebuilt from the pipeline.

To change what a protocol page says, use the correction and dispute channels
below. A successful challenge targets the underlying factor or rubric rule.
The letter grade recomputes from there.

## Request coverage

To request a new protocol, open a
[Coverage Request](.github/ISSUE_TEMPLATE/coverage-request.md) with:

- protocol name and official links
- chain or chains
- approximate TVL
- known audits
- conflict-of-interest disclosure

The baseline scope bar from the live site is: live for more than 12 months,
TVL over $50M, and on an EVM or otherwise supported chain. Requests are logged
and prioritized against the published criteria.

## Corrections and disputes

Everything defirisk.co publishes about a protocol is open to challenge, and
every challenge resolves in public.

There are three channels:

- **[Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md):**
  a specific data point is wrong and you can cite a verifiable source, such as
  a URL, contract address, audit PDF page, or on-chain transaction. Maintainers
  re-evidence the factor and the letter recomputes.
- **[Grade Dispute](.github/ISSUE_TEMPLATE/grade-dispute.md):** the facts are
  right, but the rubric was applied incorrectly. This is resolved through the
  [appeals process](https://defirisk.co/methodology/#appeals) by
  re-adjudicating the disputed factor.
- **[Rubric Proposal](.github/ISSUE_TEMPLATE/rubric-proposal.md):** the rule
  itself is miscalibrated. Proposals are reviewed publicly and either accepted
  into a future rubric version, deferred, or declined with a public note.

Do not open a PR against generated data for any of these. The public issue is
the audit trail.

## Timelines and audit trail

Every submission is acknowledged and triaged within five business days.

- A straightforward Factual Correction with a clean source is applied at the
  next pipeline run after the evidence is verified.
- A Grade Dispute reaches a published decision within 14 days of filing, with
  full reasoning recorded on the thread.
- A Rubric Proposal has no fixed clock. It is debated in public and resolved
  when a rubric version is cut.

For already-published protocols, an open challenge does not pause the grade or
redact the page. If a challenge succeeds, the historical record shows both the
before and after grade with the date of change.

Every correction and dispute remains a public issue on the source repository.
There is no private channel for changing a grade.

## Local development

Prerequisites: Node 22, Python 3.11+, Postgres 16, and git.

The site can run from the checked-in JSON data. A database is not required for
normal frontend development.

```bash
cd site
npm install
npm run dev
```

Useful site commands:

```bash
npm run build
npm test
npm run typecheck
npm run lint
npm run test:smoke
npm run test:a11y
```

To run the scoring pipeline locally against Postgres:

```bash
export LOCAL_DATABASE_URL=postgresql://user:pass@localhost:5432/risk_dashboard

psql $LOCAL_DATABASE_URL < db/migrations/0000_initial.sql
# Apply the remaining migrations in order.

python scripts/compose.py
python scripts/dump.py
```

`compose.py` recomputes grades from current factor scores. `dump.py`
regenerates the static JSON tree under `data/api/`.

## Pull-request expectations

- One topic per PR.
- Tests for new code paths. Use Vitest for site logic, Playwright for new
  pages or interactive components, and Python tests for new pipeline behavior
  where practical.
- A short PR description that says what changed and why.
- CI should pass before review.
- Signed commits are welcome but not required.

## Code style

- TypeScript strict mode. Avoid `any` unless the surrounding code already
  requires it or the PR includes a clear reason.
- Astro components use `.astro` for static components and `.tsx` for
  interactive islands.
- Python should follow the style of the surrounding file.
- Markdown should be hard-wrapped around 80 columns where practical.
- Comments should explain non-obvious constraints, not restate the code.

## License

By contributing, you agree that your contributions are licensed under the
same terms as the directory you modify:

| Path | License |
|------|---------|
| `site/`, `db/`, `scripts/`, `.github/` | MIT |
| `data/`, methodology, evidence factors, and citation lists | CC BY 4.0 |
