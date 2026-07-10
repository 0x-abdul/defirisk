# defirisk.co

defirisk.co is an open-source risk transparency dashboard for defi protocols.
It grades protocol deployments against a public, versioned rubric and publishes
the evidence trail behind each assessment.

- **Live site:** [defirisk.co](https://defirisk.co)
- **Rubric version:** `v1.7.0`
- **Code license:** MIT
- **Data and methodology license:** CC BY 4.0

## What this project does

defirisk.co grades structural protocol risk. It does not predict exploits, rank
token quality, score marketing, or measure community sentiment.

Each assessment is built from cited evidence: audit reports, on-chain state,
governance forums, public incident records, source repositories, and operator
disclosures. The rubric is deterministic, which means the same evidence should
produce the same letter grade under the same rubric version.

Every published assessment is intended to answer three questions:

- What structural risks are visible from public evidence?
- Which rubric factors drove the result?
- What sources support the finding?

The public product context lives on the
[About](https://defirisk.co/about/) page. The full grading process is documented
in the [Methodology](https://defirisk.co/methodology/).

## Repository layout

| Path | Purpose |
|------|---------|
| `site/` | Astro static site for defirisk.co |
| `data/api/v1.7.0/` | Generated JSON exports, schemas, rubric data, factor data, protocol data, history, and status files |
| `db/migrations/` | Postgres schema migrations for the grading pipeline |
| `scripts/compose.py` | Computes rubric grades from database factor scores |
| `scripts/dump.py` | Exports versioned static JSON under `data/api/` |
| `scripts/import-protocol-assessment.py` | Validates and imports family/surface assessment bundles |
| `scripts/cleanup-multiversion-runtime-artifacts.py` | Audits and removes explicitly manifested legacy runtime artifacts |
| `scripts/rubric.py` | Rubric constants, score formula, thresholds, and grade logic |
| `scripts/refresh-continuous.py` | Refreshes selected programmatic metrics, then recomposes and exports |
| `.github/` | CI, deploy workflow, issue templates, and contribution templates |

## Local development

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

To run the grading pipeline locally, point `DATABASE_URL` or
`LOCAL_DATABASE_URL` at Postgres, apply the migrations, then run:

```bash
python scripts/compose.py
python scripts/dump.py
```

`compose.py` recomputes grades from current factor scores. `dump.py` regenerates
the static API tree consumed by the site.

### Protocol families and surfaces

A canonical protocol slug represents a family. A family may contain one or
more independently scored surfaces, such as protocol versions or product
lines. Existing protocols migrate to one primary `default` surface, so their
current database rows, JSON endpoints, and dashboard URLs remain compatible.
Optional legacy surface slugs export redirect-compatible JSON and history
aliases while canonical family files expose the full `surfaces` array.

Apply `db/migrations/0008_protocol_surfaces.sql` only after creating a database
backup and restoring it into staging. The migration must be run atomically:

```bash
psql "$STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f db/migrations/0008_protocol_surfaces.sql
psql "$STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f scripts/ci/assert-family-staging.sql
```

For a production-clone rehearsal, dump the static API before and after the
migration, then prove that every legacy JSON file remains a recursive subset
of the family-aware export (the only ignored value is `generated_at`):

```bash
python scripts/ci/compare-single-surface-api.py \
  /tmp/before/api/v1.7.0 /tmp/after/api/v1.7.0
```

Assessment imports default to validation-only behavior and intentionally ignore
`DATABASE_URL`. Use `LOCAL_DATABASE_URL`, name the expected database, and pass
the explicit apply flag only after reviewing the dry-run output:

```bash
python scripts/import-protocol-assessment.py family-slug \
  --grading-file path/to/grading.json --dry-run
python scripts/import-protocol-assessment.py family-slug \
  --grading-file path/to/grading.json --apply \
  --expected-database risk_dashboard_family_staging
```

Protected or non-local databases require additional acknowledgement flags. Run
each tool with `--help` for the complete guarded workflow.

## Public API

The public API is static JSON under a versioned base path:

```text
https://defirisk.co/api/v1.7.0/
```

Main endpoints:

```text
GET /api/v1.7.0/index.json
GET /api/v1.7.0/protocols/{slug}.json
GET /api/v1.7.0/factors.json
GET /api/v1.7.0/factors/{id}.json
GET /api/v1.7.0/hacks.json
GET /api/v1.7.0/rubric.json
GET /api/v1.7.0/changes.json
```

Successful responses are wrapped in a stable envelope with:

- `rubric_version`: the rubric used to compute the response.
- `data_as_of`: the data snapshot timestamp.
- `generated_at`: the file generation timestamp.
- `data`: the requested resource payload.

Protocol detail responses also include M1 v4 rubric fields at the envelope
level: `risk_score`, `category_severities`, `cap_applied`, and `cap_reason`.

When citing downstream data, include both `rubric_version` and `data_as_of`.
A grade is only meaningful against the rubric version that produced it.

The live API reference is at [defirisk.co/data](https://defirisk.co/data/).

## Scoring model

Rubric v1.7.0 produces a protocol letter grade from cited factor evidence.
The pipeline has three main steps.

1. Per-category severity

   Each assessed factor is scored green, yellow, red, or gray. Gray means not
   applicable or not assessed and is excluded from the denominator.

   ```text
   severity = (red * 3 + yellow * 1) / (assessed * 3) * 100
   ```

2. Protocol risk score

   Category severities are aggregated into a 0 to 100 risk score. Core-five
   categories are weighted at 1.5x and all other categories at 1.0x. A
   critical-red penalty adds 5 points per critical red, capped at 15.

   The core-five categories are code and audits, governance and admin controls,
   oracle and external dependencies, operational history, and fork or dependency
   lineage.

3. Letter band and caps

   The risk score and critical-red count produce the natural letter grade. A
   weak core-five category can cap the result at D or force F.

| Grade | Meaning | First matching rule |
|-------|---------|---------------------|
| A | Resilient | Risk score <= 12 and no critical flags |
| B | Sound | Risk score <= 20 with no critical flags, or exactly one critical flag with risk score <= 20 |
| C | Watch | Risk score > 20 and <= 35, with no more than one critical flag |
| D | Compromised | Risk score > 35 and <= 55, at least two critical flags, or a core-five category severity >= 60 |
| F | Failing | Risk score > 55, at least three critical flags, or a core-five category severity >= 90 |

The full factor definitions and rubric metadata are published in
`data/api/v1.7.0/factors.json` and `data/api/v1.7.0/rubric.json`. You can also
browse them on the live
[factor library](https://defirisk.co/factors/).

## Contributing

Pull requests are welcome for code, documentation, accessibility,
performance, schemas, migrations, and scoring pipeline improvements.

Direct edits to generated data are not accepted. Do not open a PR that edits
per-protocol factor scores, letter grades, or files under
`data/api/v1.7.0/protocols/`. Those files are pipeline output.

Use the public issue channels instead:

- **Coverage Request:** ask for a protocol to be assessed.
- **Factual Correction:** report a wrong data point with a verifiable source.
- **Grade Dispute:** challenge how the rubric was applied to established facts.
- **Rubric Proposal:** propose a change to the rubric itself.

The canonical guide is [CONTRIBUTING.md](CONTRIBUTING.md), with public process
details at [defirisk.co/contributions](https://defirisk.co/contributions/).

## Continuous refresh operations

`scripts/refresh-continuous.py` updates regularly changing metrics from durable
programmatic sources, then runs the compose and dump steps when needed.

```bash
DATABASE_URL=postgres://... python scripts/refresh-continuous.py --all
DATABASE_URL=postgres://... python scripts/refresh-continuous.py --protocol aave-v3
DATABASE_URL=postgres://... python scripts/refresh-continuous.py --all --dry-run
```

In production, `.github/workflows/ingest.yml` runs this daily at 03:00 UTC by
SSHing into the VPS with `VPS_HOST` and `VPS_SSH_KEY`, sourcing
`/opt/riskdashboard/.env`, and using `DATABASE_URL` or `LOCAL_DATABASE_URL`.
The production Postgres instance is local to the VPS, so the workflow runs the
refresh there and rebuilds the static dashboard so `/api/...` reflects the
refreshed values. The VPS checkout is synchronized to `origin/main` before each
run; generated `data/api` files remain uncommitted and are replaced on the next
run rather than creating a second, divergent Git history on the server.

The refresh script does not overwrite existing values with null or zero when a
fetch fails. It is intentionally narrower than a full reassessment. Metrics
that need judgment, source mapping, or episodic context remain manual until the
pipeline can update them without false precision.

## License and attribution

Code in `site/`, `db/`, `scripts/`, and `.github/` is MIT licensed. Data,
evidence factors, citation lists, and methodology are CC BY 4.0.

For data reuse, attribution to `defirisk.co, rubric v1.7.0` is sufficient.
