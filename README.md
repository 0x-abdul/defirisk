# Risk Dashboard

Open-source DeFi protocol risk intelligence: 184 risk factors across 13 categories, covering 80 protocols at rubric/API version `v1.7.0`.

**Build status:** pre-launch  
**Active rubric/API version:** `v1.7.0`  
**License:** MIT for code · CC-BY 4.0 for data/methodology

## Start here

Read [`START_HERE.md`](START_HERE.md) before editing or reorganizing the repo. It explains the active source-of-truth paths, generated-data boundaries, research/vault structure, archive conventions, and move-safety rules.

## What lives where

| Path | Purpose |
|---|---|
| `site/` | Astro frontend and static-site code. |
| `data/api/v1.7.0/` | Current generated public API JSON for protocols, factors, hacks, and schemas. |
| `config/rubric-version.json` | Active version/count config used by scripts and site loaders. |
| `db/` | Database migrations and migration metadata. |
| `scripts/` | Repo-root publishing/import/compose/dump/CI utilities. See [`SCRIPTS.md`](SCRIPTS.md). |
| `risk-dashboard/` | Research/spec/evidence vault, protocol-fill workspace, engineering tickets, and research pipeline. |
| `risk-dashboard/.research/protocols/` | Canonical per-protocol evidence and grading fragments. |
| `risk-dashboard/research/outputs/` | Frozen risk taxonomy and scoring-methodology research outputs. |
| `docs/` | Public/maintainer docs: API, deployment, recovery, methodology, release notes, archives. |

## Product and methodology references

- Product spec: [`risk-dashboard/spec.md`](risk-dashboard/spec.md)
- Engineering overview: [`risk-dashboard/engineering/README.md`](risk-dashboard/engineering/README.md)
- Risk taxonomy: [`risk-dashboard/research/outputs/03-taxonomy.md`](risk-dashboard/research/outputs/03-taxonomy.md)
- Scoring/rubric decision: [`risk-dashboard/research/outputs/05-scoring-decision.md`](risk-dashboard/research/outputs/05-scoring-decision.md)
- Public API docs: [`docs/api.md`](docs/api.md)
- Script/CWD guide: [`SCRIPTS.md`](SCRIPTS.md)

## Local development

```bash
# 1. Start local Postgres
./scripts/db-up.sh

# 2. Install dependencies
npm install

# 3. Apply schema + seed
npm run db:push
npm run db:seed

# 4. Run tests
cd site && npm test

# 5. Run all CI gates locally
cd ..
./scripts/ci-local.sh
```

## Generated data warning

The active public data under `data/api/v1.7.0/` is generated release output. Do not hand-edit it unless you are doing an explicit emergency/recovery fix. Normal changes should flow through the research evidence, DB import, compose, and dump pipeline described in `START_HERE.md` and `SCRIPTS.md`.

## License

| Directory | License |
|---|---|
| `site/`, `db/`, `scripts/`, `.github/` | [MIT](LICENSE) |
| `data/`, `docs/methodology/`, methodology outputs | [CC-BY 4.0](LICENSE.data) |

## Launch status

P0 API-contract hardening has been verified clean for the current 80-protocol `v1.7.0` generated data set. Remaining pre-launch work is primarily launch/ops readiness, documentation freshness, public/private boundary cleanup, and deployment cutover.
