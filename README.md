# DeFiRisk

**Open-source DeFi protocol risk intelligence** — 80 protocols graded across 184 risk factors and 13 categories, updated nightly.

**Live site:** [defirisk.co](https://defirisk.co)  
**API version:** `v1.7.0`  
**License:** MIT (code) · CC-BY 4.0 (data/methodology)

---

## What this is

DeFiRisk assigns letter grades (A–F) to DeFi protocols based on a structured rubric — not TVL or reputation. Every grade is evidence-backed, version-stamped, and publicly auditable.

The rubric covers 13 risk categories:

| # | Category |
|---|----------|
| 1 | Smart Contract Security |
| 2 | Oracle & Price Feed Risk |
| 3 | Governance & Decentralization |
| 4 | Custody & Key Management |
| 5 | Incident History |
| 6 | Liquidity & Market Risk |
| 7 | Protocol Complexity |
| 8 | Counterparty & Legal Risk |
| 9 | Dependency Risk |
| 10 | Transparency & Auditability |
| 11 | Operational Security |
| 12 | Economic Design |
| 13 | Regulatory & Compliance |

A single-protocol page shows the letter grade, risk score, per-category grid, factor-level evidence, and incident history inline. The scoring methodology is open and versioned at `data/api/v1.7.0/rubric.json`.

---

## Repository structure

| Path | Contents |
|------|----------|
| `site/` | Astro static site (MIT) |
| `data/api/v1.7.0/` | Generated JSON data tree — protocol grades, factor scores, hacks, history (CC-BY 4.0) |
| `db/migrations/` | Postgres schema migrations |
| `scripts/compose.py` | Grade computation engine (reads DB → writes grades) |
| `scripts/refresh-continuous.py` | Continuous metric refresh (TVL/current factors -> compose/dump) |
| `scripts/dump.py` | JSON export (reads DB → writes `data/api/`) |
| `scripts/rubric.py` | Rubric math — score formula and grade thresholds |
| `.github/` | CI, deploy workflow, issue templates |

---

## Public API

Every protocol has a versioned JSON endpoint:

```
https://defirisk.co/api/v1.7.0/protocols/<slug>.json
https://defirisk.co/api/v1.7.0/index.json
https://defirisk.co/api/v1.7.0/factors.json
https://defirisk.co/api/v1.7.0/hacks.json
```

Every response is enveloped with `rubric_version` and `data_as_of`:

```json
{
  "rubric_version": "v1.7.0",
  "data_as_of": "2026-06-12T08:00Z",
  "risk_score": 17.09,
  "cap_applied": "none",
  "data": { ... }
}
```

---

## Scoring methodology

The risk score is a **core-five-weighted average** of per-category severity, plus a critical-flag penalty:

- Each category severity: `(red×3 + yellow×1) / (denom×3) × 100` (gray excluded from denominator)
- Critical-flag penalty: 5 points per critical red, capped at 15
- Single-category cap: severity ≥ 60 → grade floor D; severity ≥ 90 → floor F

| Score | Grade |
|-------|-------|
| 0–12 | A |
| 13–22 | B |
| 23–32 | C |
| 33–49 | D |
| 50+ | F |

Full factor definitions are at `data/api/v1.7.0/rubric.json`.

---

## Contributing

We welcome:
- **Factual corrections** — wrong data with an on-chain source (use the Factual Correction issue template)
- **Grade disputes** — rubric interpretation disagreements with evidence (use the Grade Dispute template)
- **Coverage requests** — protocols not yet rated
- **Code / site improvements** — open a PR against `site/` or the scoring scripts

We do **not** accept direct edits to `data/api/` — all data flows through the evidence pipeline.

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## Continuous refresh operations

The nightly continuous refresh is intentionally narrower than a full manual
protocol reassessment. It updates regularly changing metrics from durable
programmatic sources, then regenerates exports:

```bash
DATABASE_URL=postgres://... python scripts/refresh-continuous.py --all
DATABASE_URL=postgres://... python scripts/refresh-continuous.py --protocol aave-v3
DATABASE_URL=postgres://... python scripts/refresh-continuous.py --all --dry-run
```

`DATABASE_URL` or `LOCAL_DATABASE_URL` must point at the Postgres database.
The script fetches DeFiLlama by `protocols.defillama_slug`, updates protocol
TVL, mappable deployment TVL, and conservative factor scores such as
RD-F-063, RD-F-084, RD-F-080, and RD-F-066 when the source data is sufficient.
It never overwrites existing values with null or zero on fetch failures.

If factor scores change, `compose.py` runs before export so grades and risk
scores reflect the refreshed factor data. `dump.py` always runs after
successful DB updates so `data/api/v1.7.0/` and `status.json` are regenerated.

Not every current-looking metric is safe to automate yet. Oracle pool depth,
liquidity depth, top depositor concentration, and many episodic event factors
remain manual or future-pipeline work until the source mappings and thresholds
are machine-readable enough to avoid false precision.

---

## License

| Path | License |
|------|---------|
| `site/`, `db/`, `scripts/`, `.github/` | [MIT](LICENSE) |
| `data/`, methodology | [CC-BY 4.0](LICENSE.data) |

Data attribution: **DeFiRisk (defirisk.co), rubric v1.7.0**
