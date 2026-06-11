# Contributing

The Risk Dashboard publishes neutral, evidence-based risk intelligence for
DeFi protocols. The contribution model exists to grow coverage and improve
the open governance artifacts (schema, rubric, adapters, frontend) without
ever permitting external writes to per-protocol verdicts.

If you only have five minutes, the rules in one breath:

- Coverage / adapter / docs / frontend / rubric-debate PRs: welcome.
- Direct edits to a protocol's factor scores or letter grade: never.
- Found a factual error on a protocol page? File an issue with the
  "issue-flag" template; do not open a PR against the data.
- Found a security issue? See [SECURITY.md](SECURITY.md).

The full rules below are taken from
`risk-dashboard/research/outputs/06-oss-posture.md` §4 and are non-negotiable
for v1.

## What we accept via PR

You can open a pull request to:

- **Add an ingestion adapter** for an uncovered protocol. Adapter code lives
  under `risk-dashboard/scripts/data-pipeline/fetchers/`. Each adapter must
  return data conforming to the schema in
  `risk-dashboard/scripts/data-pipeline/schemas/data-cache.schema.json`.
- **Improve an existing adapter.** Bug fixes, efficiency improvements, or
  added fields that fit the existing schema.
- **Refine a factor definition** in the taxonomy
  (`risk-dashboard/research/outputs/03-taxonomy.md`). Proposals must come
  with evidence; the canonical taxonomy owner reviews.
- **Propose a rubric threshold change** in
  `risk-dashboard/research/outputs/05-scoring-decision.md`. Public debate is
  expected; merges require maintainer approval after the comment window.
- **Fix a frontend bug or improve accessibility.** The site lives under
  `site/`. We particularly welcome WCAG 2.2 AA accessibility fixes.
- **Improve documentation, examples, or translations.**

## What we never accept via PR

- **Direct writes to per-protocol factor records.** The data layer is
  populated only by pipeline output and curator review. Even a well-meaning
  PR that "corrects a single field" cannot be merged through this path —
  it has to go through the issue-flag → curator review → pipeline rerun
  path described below.
- **Direct rubric-grade overrides.** Letter grades are deterministic
  functions of factor scores; you cannot patch a grade by editing the
  output file.
- **Edits to `data/api/v1.x.x/protocols/*.json`.** These files are
  regenerated from the database on every deploy.

The reasoning is in `06-oss-posture.md` §4.4: the blast radius of a missed
bad PR (a protocol team submitting favourable data about itself) is bigger
than the throughput gain. DeFiLlama accepts adapter PRs because adapter
output is mechanically derivable on-chain data; risk data is opinionated, so
the same model fails.

## Disputes and issue-flags

If you've found an error or you disagree with an assessment, the path is:

1. Open an issue against this repository titled with the protocol slug and
   the disputed claim (e.g. "aave-v3 — RD-F-027 multisig threshold").
   At launch this will route through a "Report an issue" template surfaced
   from every protocol page; until then, a plain issue with the structure
   below is enough.
2. Include the protocol slug, the specific factor or claim under dispute,
   the evidence you're contesting, and what you believe the correct
   reading is.
3. The curator team triages within five business days. The decision and
   reasoning are recorded on the issue thread, which becomes part of the
   public audit trail for that protocol.

For a more extended disagreement with the rubric or methodology, open a
discussion in the methodology forum (see [README.md](README.md) for the
link once launch is live).

## Protocol-team self-service

If you represent a protocol that's covered (or wants to be covered) by the
dashboard, there is a separate verified self-service path documented in
`risk-dashboard/research/outputs/06-oss-posture.md` §4.3. In short:

- You verify identity once via PR from your registered GitHub org, a
  signed message from your registered multisig, or a DNS TXT record on
  your protocol's domain.
- You submit factual updates (audit links, multisig changes, timelock
  changes, oracle config) through a structured form.
- The curator team reviews within five business days. All diffs are
  public.

This path is not yet wired up for v1; the v1 issue-flag path covers the
same need with manual triage.

## Local development

Prerequisites: Node 22, Python 3.11+, Docker (for local Postgres), git.

```bash
# Start local Postgres
./scripts/db-up.sh

# Install JS deps (root and site/)
npm install
cd site && npm install && cd ..

# Apply schema + seed
npm run db:push
npm run db:seed

# Run the site
cd site && npm run dev

# Run all CI gates locally
./scripts/ci-local.sh
```

The data pipeline runs under `risk-dashboard/`:

```bash
cd risk-dashboard
python scripts/data-pipeline/run.py <protocol-slug>
```

See `risk-dashboard/scripts/data-pipeline/README.md` (forthcoming) for the
fetcher list and configuration details.

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
