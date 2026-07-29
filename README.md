# defirisk.co

defirisk.co is an open-source risk-transparency dashboard for DeFi protocols.
It grades published protocol deployments against a public, versioned rubric and
shows the public evidence behind each assessment.

- Live site: [defirisk.co](https://defirisk.co)
- Rubric version: `v1.7.0`
- Code license: MIT
- Data and methodology license: CC BY 4.0

## Public repository scope

This repository is the reproducible public product:

| Path | Purpose |
|---|---|
| `site/` | Astro static application |
| `data/api/` | Complete reviewed public assessment projection and deterministic manifest |
| `docs/methodology/` | Public methodology and changelog |
| `docs/public-data-boundary.md` | Public/private ownership and publication contract |
| `scripts/rubric.py` | Public scoring rules |
| `scripts/ci/` | Public schema, build, and confidentiality boundary checks |

Unpublished research, review material, operator runbooks, database tooling,
approval receipts, deployments, backups, and live telemetry are not maintained
here.

At the 2026-07-29 boundary cutover, the production database and publication
policy agreed that all 98 covered protocols were unpublished. The verified
published baseline is therefore empty. Protocol assessments appear here only
after private approval and review through a public publication pull request.

## Local development

The site builds exclusively from the committed public API tree. It requires no
database credentials or runtime export.

```bash
cd site
npm install
npm run dev
```

Useful checks:

```bash
python scripts/ci/verify-public-boundary.py
python scripts/ci/build-public-api-manifest.py --check
python -m pytest scripts/tests -q

cd site
npm test
npm run lint
npm run typecheck
npm run build
```

## Public API

The API is static, versioned JSON:

```text
https://defirisk.co/api/v1.7.0/
```

Important endpoints include:

```text
GET /api/v1.7.0/index.json
GET /api/v1.7.0/protocols/{slug}.json
GET /api/v1.7.0/factors.json
GET /api/v1.7.0/factors/{id}.json
GET /api/v1.7.0/hacks.json
GET /api/v1.7.0/rubric.json
GET /api/v1.7.0/changes.json
GET /api/v1.7.0/status.json
```

Only approved published protocols may appear in the protocol index, details,
factor score tables, assessment history, change feed, or incident feed.

`status.json` contains only Git-versioned assessment snapshot metadata. Live
pipeline health, deployment status, monitoring, and calculated freshness belong
to the separate telemetry surface and are not reproducible Git data.

Every committed API file is covered by `data/api/MANIFEST.sha256`. Production
releases must use these exact committed files or deterministic artifacts derived
exclusively from them. Deployment-time database export and runtime API overlays
are prohibited.

## Publication model

Adding a protocol to the production database is private and creates no public
issue or pull request. Research and approval also remain private.

After approval, exactly one protocol-specific publication pull request adds the
sanitized assessment. It records that the public data was reviewed for
publication; it does not contain private review routes, identities, receipts, or
deployment details. The later database publication flag change and release
promotion create no second issue or pull request.

Existing legacy protocols are not replaced by 98 individual pull requests.
Verified publication candidates use consolidated legacy-publication batches.

See [the public data boundary](docs/public-data-boundary.md) for the complete
repository contract.

## Scoring model

Each applicable factor is scored green, yellow, or red. Gray means not
applicable or not assessed and is excluded from the denominator.

```text
severity = (red * 3 + yellow) / (assessed * 3) * 100
```

Category severities are combined into a 0–100 risk score. Core categories have
additional weight, critical-red findings add a capped penalty, and rubric caps
can limit the final letter grade. Factor definitions and the frozen rubric are
published under `data/api/v1.7.0/`.

## Contributing

Pull requests are welcome for the public application, accessibility,
performance, public schemas, methodology, rubric logic, and tests.

Do not directly edit protocol grades or generated assessment files. Use the
public issue templates for coverage requests, factual corrections, grade
disputes, rubric proposals, and security reports. See
[CONTRIBUTING.md](CONTRIBUTING.md).
