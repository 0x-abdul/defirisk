# Contributing

defirisk.co welcomes contributions to its public application, methodology,
rubric, schemas, accessibility, performance, and boundary tests.

## Choose the right channel

| Goal | Channel |
|---|---|
| Improve public code, UX, docs, schemas, or tests | Pull request |
| Request protocol coverage | [Coverage Request](.github/ISSUE_TEMPLATE/coverage-request.md) |
| Correct a published fact | [Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md) |
| Dispute rubric application | [Grade Dispute](.github/ISSUE_TEMPLATE/grade-dispute.md) |
| Propose a rubric change | [Rubric Proposal](.github/ISSUE_TEMPLATE/rubric-proposal.md) |
| Report a vulnerability | [Security policy](SECURITY.md) |

## Repository boundary

Public pull requests must not contain:

- unpublished assessments or review routes;
- review tokens, private URLs, identities, notes, or working evidence;
- approval receipts, signatures, database identifiers, or transaction details;
- internal repository paths or metadata;
- deployment, backup, rollback, monitoring, or credential material; or
- live telemetry under `data/api/**`.

Operational files under `docs/ops/` are deliberately ignored and are rejected
by the public boundary validator even if force-added.

Protocol grades and factor scores are generated from approved immutable
snapshots. Do not directly edit them to implement a correction or dispute.

## Publication pull requests

A protocol's insertion, research, and review happen outside this public
repository and create no public issue or pull request. After approval,
maintainers open exactly one publication pull request containing the sanitized
public projection. The later publication flag change and release promotion do
not create a second pull request.

Every projection is validated privately before its branch is pushed. Required
public CI repeats the same confidentiality and schema checks before merge.
External contributors should use coverage, correction, or dispute issues rather
than constructing assessment payloads.

## Local development

Prerequisites are Node 22, Python 3.11+, and Git. A database is neither required
nor used to build the public site.

```bash
cd site
npm install
npm run dev
```

Before opening a pull request:

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

## Pull-request expectations

- Keep one topic per pull request.
- Add focused tests for behavior changes.
- Explain what changed and why.
- Preserve the public API envelope unless the change deliberately introduces a
  versioned contract.
- Keep the methodology changelog append-only.
- Ensure every required check passes.

## Style

- Use strict TypeScript.
- Prefer `.astro` for static components and `.tsx` for interactive islands.
- Follow the surrounding Python style.
- Wrap Markdown around 80 columns when practical.
- Explain non-obvious constraints rather than restating code.

## License

Code is MIT licensed. Public data, methodology, factor definitions, and
citations are CC BY 4.0. Contributions use the license applicable to the
directory they modify.
