from __future__ import annotations

import importlib.util
import sys
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "refresh-continuous.py"
SPEC = importlib.util.spec_from_file_location("refresh_continuous", SCRIPT_PATH)
refresh = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = refresh
SPEC.loader.exec_module(refresh)


def llama_payload(latest: Decimal = Decimal("140000000")) -> dict:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tvl = []
    for day in range(100):
        ts = int((start + timedelta(days=day)).timestamp())
        value = Decimal("100000000") + Decimal(day * 1_000_000)
        tvl.append({"date": ts, "totalLiquidityUSD": float(value)})
    tvl[-1]["totalLiquidityUSD"] = float(latest)
    return {
        "name": "Example",
        "tvl": tvl,
        "currentChainTvls": {
            "Ethereum": 100_000_000,
            "Ethereum-borrowed": 30_000_000,
            "Base": 40_000_000,
            "Base-borrowed": 10_000_000,
            "Ethereum-staking": 999_000_000,
        },
    }


class FakeRepo:
    def __init__(self) -> None:
        self.deployments = [
            {
                "id": "eth-id",
                "protocol_slug": "example",
                "chain": "ethereum",
                "tvs_usd": Decimal("1"),
                "tvs_share": Decimal("0.1000"),
            },
            {
                "id": "base-id",
                "protocol_slug": "example",
                "chain": "base",
                "tvs_usd": Decimal("1"),
                "tvs_share": Decimal("0.1000"),
            },
        ]
        self.scores = {
            "RD-F-063": {
                "id": "f063-old",
                "protocol_slug": "example",
                "deployment_id": None,
                "factor_id": "RD-F-063",
                "rubric_version": "v1.7.0",
                "score": "green",
                "evidence_summary": "old defillama evidence",
                "evidence_detail": None,
                "sources": [
                    {
                        "source_type": "url",
                        "url": "https://api.llama.fi/protocol/example",
                        "reference": "DeFiLlama",
                    }
                ],
            },
            "RD-F-084": {
                "id": "f084-old",
                "protocol_slug": "example",
                "deployment_id": None,
                "factor_id": "RD-F-084",
                "rubric_version": "v1.7.0",
                "score": "green",
                "evidence_summary": "old data cache evidence",
                "evidence_detail": None,
                "sources": [{"source_type": "curator_note", "reference": "00-data-cache"}],
            },
            "RD-F-066": {
                "id": "f066-old",
                "protocol_slug": "example",
                "deployment_id": None,
                "factor_id": "RD-F-066",
                "rubric_version": "v1.7.0",
                "score": "green",
                "evidence_summary": "old utilization evidence",
                "evidence_detail": None,
                "sources": [],
            },
            "RD-F-080": {
                "id": "f080-old",
                "protocol_slug": "example",
                "deployment_id": None,
                "factor_id": "RD-F-080",
                "rubric_version": "v1.7.0",
                "score": "green",
                "evidence_summary": "old incident evidence",
                "evidence_detail": None,
                "sources": [],
            },
        }
        self.protocol_tvl_updates: list[tuple[str, Decimal]] = []
        self.deployment_updates: list[tuple[str, Decimal, Decimal]] = []
        self.factor_replacements: list[tuple[str, str]] = []

    def transaction(self):
        return nullcontext()

    def fetch_deployments(self, slug: str):
        assert slug == "example"
        return self.deployments

    def fetch_factor_scores(self, slug: str):
        assert slug == "example"
        return self.scores

    def fetch_exploit_state(self, slug: str):
        assert slug == "example"
        return 400, False

    def update_protocol_tvl(self, slug: str, tvl_usd: Decimal) -> None:
        self.protocol_tvl_updates.append((slug, tvl_usd))

    def update_deployment_tvl(
        self,
        deployment_id: str,
        tvl_usd: Decimal,
        share: Decimal,
    ) -> None:
        self.deployment_updates.append((deployment_id, tvl_usd, share))

    def replace_factor_score(self, existing, update, collected_at) -> None:
        self.factor_replacements.append((existing["id"], update.factor_id))


def test_parse_defillama_payload_extracts_tvl_chains_and_utilization() -> None:
    metrics = refresh.parse_defillama_payload(llama_payload())

    assert metrics.tvl_usd == Decimal("140000000.00")
    assert metrics.chain_tvls == {
        "Ethereum": Decimal("70000000.00"),
        "Base": Decimal("30000000.00"),
    }
    assert metrics.supplied_usd == Decimal("140000000.00")
    assert metrics.borrowed_usd == Decimal("40000000.00")
    assert metrics.utilization_rate_pct == 28.57
    assert metrics.tvl_cov_90d is not None


def test_parse_defillama_rejects_null_or_zero_tvl() -> None:
    payload = {"tvl": [{"date": 1_767_225_600, "totalLiquidityUSD": 0}]}

    try:
        refresh.parse_defillama_payload(payload)
    except ValueError as exc:
        assert "positive TVL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_refresh_protocol_updates_db_values_and_factors() -> None:
    repo = FakeRepo()
    protocol = {
        "slug": "example",
        "defillama_slug": "example",
        "total_value_secured_usd": Decimal("1"),
        "has_active_incident": False,
    }

    result = refresh.refresh_protocol(
        repo=repo,
        protocol=protocol,
        dry_run=False,
        fetcher=lambda slug: llama_payload(),
    )

    assert result.error is None
    assert result.db_updates > 0
    assert result.factor_updates >= 3
    assert repo.protocol_tvl_updates == [("example", Decimal("140000000.00"))]
    assert ("eth-id", Decimal("70000000.00"), Decimal("0.7000")) in repo.deployment_updates
    assert ("base-id", Decimal("30000000.00"), Decimal("0.3000")) in repo.deployment_updates
    assert ("f063-old", "RD-F-063") in repo.factor_replacements
    assert ("f084-old", "RD-F-084") in repo.factor_replacements


def test_refresh_protocol_dry_run_does_not_write() -> None:
    repo = FakeRepo()
    protocol = {
        "slug": "example",
        "defillama_slug": "example",
        "total_value_secured_usd": Decimal("1"),
        "has_active_incident": False,
    }

    result = refresh.refresh_protocol(
        repo=repo,
        protocol=protocol,
        dry_run=True,
        fetcher=lambda slug: llama_payload(),
    )

    assert result.db_updates > 0
    assert repo.protocol_tvl_updates == []
    assert repo.deployment_updates == []
    assert repo.factor_replacements == []


def test_all_mode_keeps_per_protocol_failures_nonfatal() -> None:
    repo = FakeRepo()
    protocols = [
        {
            "slug": "broken",
            "defillama_slug": "broken",
            "total_value_secured_usd": Decimal("1"),
            "has_active_incident": False,
        },
        {
            "slug": "example",
            "defillama_slug": "example",
            "total_value_secured_usd": Decimal("1"),
            "has_active_incident": False,
        },
    ]

    def fetcher(slug: str):
        if slug == "broken":
            raise RuntimeError("upstream unavailable")
        return llama_payload()

    results = refresh.process_protocols(
        repo=repo,
        protocols=protocols,
        dry_run=True,
        all_protocols=True,
        fetcher=fetcher,
    )

    assert len(results) == 2
    assert results[0].slug == "broken"
    assert results[0].error == "upstream unavailable"
    assert results[1].slug == "example"
    assert results[1].error is None


def test_multi_surface_family_is_skipped_before_fetch() -> None:
    repo = FakeRepo()
    called = False

    def fetcher(slug: str):
        nonlocal called
        called = True
        return llama_payload()

    result = refresh.refresh_protocol(
        repo=repo,
        protocol={
            "slug": "example",
            "surface_count": 2,
            "defillama_slug": "example",
        },
        dry_run=False,
        fetcher=fetcher,
    )

    assert result.status == "skipped"
    assert "explicitly scoped refresh bundle" in result.skipped[0]
    assert called is False


def test_duplicate_chain_deployments_are_not_collapsed() -> None:
    deployments = [
        {"id": "one", "chain": "ethereum", "deployment_key": "one"},
        {"id": "two", "chain": "ethereum", "deployment_key": "two"},
    ]

    updates, skipped = refresh._deployment_updates(
        deployments,
        refresh.parse_defillama_payload(llama_payload()),
    )

    assert updates == []
    assert "multiple deployment keys" in skipped[0]


def test_days_since_exploit_scoring() -> None:
    assert refresh._score_days_since_exploit(True, None) == "red"
    assert refresh._score_days_since_exploit(False, None) == "green"
    assert refresh._score_days_since_exploit(False, 90) == "yellow"
    assert refresh._score_days_since_exploit(False, 366) == "green"


class FakeConnection:
    def __init__(self) -> None:
        self.rolled_back = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.rolled_back = exc_type is not None
        return False

    def close(self) -> None:
        self.closed = True


class BatchRepo:
    def __init__(self, _conn) -> None:
        pass

    def require_nightly_contracts(self) -> None:
        pass

    def fetch_protocols(self, _slug):
        return [{"slug": "fixture"}]

    def create_pipeline_run(self, _triggered_by):
        return "run-id"

    def update_pipeline_run(self, _run_id, _results, _duration):
        pass


def test_mixed_failure_rolls_back_and_blocks_export(monkeypatch) -> None:
    conn = FakeConnection()
    exported = False

    def post_refresh(**_kwargs):
        nonlocal exported
        exported = True
        return 0

    monkeypatch.setattr(refresh, "_connect", lambda _url: conn)
    monkeypatch.setattr(refresh, "PostgresRepository", BatchRepo)
    monkeypatch.setattr(
        refresh,
        "process_protocols",
        lambda **_kwargs: [
            refresh.ProtocolResult(slug="ok", status="updated", db_updates=1),
            refresh.ProtocolResult(slug="bad", status="error", error="fetch failed"),
        ],
    )
    monkeypatch.setattr(refresh, "_post_refresh_steps", post_refresh)

    assert refresh.run(
        conn_str="postgresql://fixture",
        all_protocols=True,
        protocol_slug=None,
        dry_run=False,
    ) == 1
    assert conn.rolled_back is True
    assert conn.closed is True
    assert exported is False


def test_compose_failure_rolls_back_and_blocks_export(monkeypatch) -> None:
    conn = FakeConnection()
    exported = False

    def post_refresh(**_kwargs):
        nonlocal exported
        exported = True
        return 0

    monkeypatch.setattr(refresh, "_connect", lambda _url: conn)
    monkeypatch.setattr(refresh, "PostgresRepository", BatchRepo)
    monkeypatch.setattr(
        refresh,
        "process_protocols",
        lambda **_kwargs: [
            refresh.ProtocolResult(
                slug="fixture", status="updated", db_updates=1, factor_updates=1
            )
        ],
    )
    monkeypatch.setattr(
        refresh,
        "_load_sibling_script",
        lambda _name, _filename: SimpleNamespace(run=lambda *_args, **_kwargs: 1),
    )
    monkeypatch.setattr(refresh, "_post_refresh_steps", post_refresh)

    assert refresh.run(
        conn_str="postgresql://fixture",
        all_protocols=False,
        protocol_slug="fixture",
        dry_run=False,
    ) == 1
    assert conn.rolled_back is True
    assert conn.closed is True
    assert exported is False
