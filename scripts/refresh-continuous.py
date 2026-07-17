#!/usr/bin/env python3
"""Refresh continuous-cadence protocol metrics.

This script updates values that can be refreshed safely from stable,
programmatic sources without rerunning the full manual risk assessment.
It intentionally skips factors whose current evidence is qualitative or whose
source mapping is not machine-readable enough to overwrite.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised by CLI dependency guard
    psycopg = None
    dict_row = None

SCRIPT_NAME = "refresh-continuous.py"
COLLECTED_BY = "refresh-continuous.py"
DEFILLAMA_API = "https://api.llama.fi/protocol/{slug}"
AUTO_FACTOR_IDS = {"RD-F-063", "RD-F-066", "RD-F-080", "RD-F-084"}
COLOR_SCORES = {"green", "yellow", "red"}
SKIP_SCORES = {"gray", "not_assessed", "not_applicable"}
LENDING_MANUAL_OVERRIDE_MARKERS = (
    "100% utilization",
    "withdrawal freeze",
    "individual markets",
    "incident",
    "bad debt",
)


class BatchRefreshError(RuntimeError):
    """Raised to force the outer nightly transaction to roll back."""


def _load_sibling_script(module_name: str, filename: str) -> Any:
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise BatchRefreshError(f"cannot load required nightly step: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    url: str | None
    reference: str
    title: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class LlamaMetrics:
    tvl_usd: Decimal
    data_as_of: datetime
    tvl_30d_change_pct: float | None
    tvl_cov_90d: float | None
    tvl_cov_samples: int
    chain_tvls: dict[str, Decimal]
    supplied_usd: Decimal | None
    borrowed_usd: Decimal | None
    utilization_rate_pct: float | None


@dataclass(frozen=True)
class FactorUpdate:
    factor_id: str
    score: str
    evidence_summary: str
    evidence_detail: str
    data_as_of: datetime
    sources: list[SourceRef]


@dataclass
class ProtocolResult:
    slug: str
    status: str
    db_updates: int = 0
    factor_updates: int = 0
    fetchers: set[str] = field(default_factory=set)
    skipped: list[str] = field(default_factory=list)
    error: str | None = None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_share(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _changed_money(old: Any, new: Decimal) -> bool:
    old_value = _as_decimal(old)
    if old_value is None:
        return True
    return _round_money(old_value) != _round_money(new)


def _timestamp_to_utc(value: Any) -> datetime | None:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_date(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


def _format_usd(value: Decimal) -> str:
    rounded = _round_money(value)
    if rounded >= Decimal("1000000000"):
        return f"${float(rounded / Decimal('1000000000')):.2f}B"
    if rounded >= Decimal("1000000"):
        return f"${float(rounded / Decimal('1000000')):.2f}M"
    if rounded >= Decimal("1000"):
        return f"${float(rounded / Decimal('1000')):.2f}K"
    return f"${rounded:,.2f}"


def _pct(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:+.2f}%"


def _coefficient_of_variation(values: list[Decimal]) -> float | None:
    if len(values) < 30:
        return None
    floats = [float(v) for v in values if v > 0]
    if len(floats) < 30:
        return None
    mean = sum(floats) / len(floats)
    if mean <= 0:
        return None
    variance = sum((v - mean) ** 2 for v in floats) / len(floats)
    return math.sqrt(variance) / mean


def _latest_positive_series_point(series: list[dict[str, Any]]) -> tuple[datetime, Decimal]:
    for point in reversed(series):
        value = _as_decimal(point.get("totalLiquidityUSD"))
        ts = _timestamp_to_utc(point.get("date"))
        if value is not None and ts is not None:
            return ts, value
    raise ValueError("DeFiLlama payload has no positive TVL point")


def _change_pct(days: int, latest_ts: datetime, latest: Decimal, series: list[dict]) -> float | None:
    cutoff = latest_ts.timestamp() - (days * 86_400)
    candidate: Decimal | None = None
    candidate_distance: float | None = None
    for point in series:
        ts = _timestamp_to_utc(point.get("date"))
        value = _as_decimal(point.get("totalLiquidityUSD"))
        if ts is None or value is None:
            continue
        distance = abs(ts.timestamp() - cutoff)
        if candidate_distance is None or distance < candidate_distance:
            candidate = value
            candidate_distance = distance
    if candidate is None or candidate <= 0:
        return None
    return float(((latest - candidate) / candidate) * Decimal("100"))


def _normalize_chain(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


CHAIN_ALIASES: dict[str, tuple[str, ...]] = {
    "binance": ("bsc", "bnb"),
    "bnbchain": ("bsc", "bnb", "binance"),
    "zksyncera": ("zksync",),
    "polygonzkevm": ("polygonzkevm", "polygon"),
    "xdai": ("gnosis",),
    "optimism": ("op",),
}


def _chain_match(chain_name: str, deployment_chains: set[str]) -> str | None:
    normalized = _normalize_chain(chain_name)
    by_norm = {_normalize_chain(chain): chain for chain in deployment_chains}
    if normalized in by_norm:
        return by_norm[normalized]
    for alias in CHAIN_ALIASES.get(normalized, ()):
        if _normalize_chain(alias) in by_norm:
            return by_norm[_normalize_chain(alias)]
    return None


def _plain_chain_values(current_chain_tvls: dict[str, Any]) -> dict[str, Decimal]:
    ignored_suffixes = ("-borrowed", "-staking", "-pool2", "-treasury")
    values: dict[str, Decimal] = {}
    borrowed: dict[str, Decimal] = {}
    for chain, raw_value in current_chain_tvls.items():
        value = _as_decimal(raw_value)
        if value is None:
            continue
        if chain.endswith("-borrowed"):
            borrowed[chain.removesuffix("-borrowed")] = value
            continue
        if chain.endswith(ignored_suffixes):
            continue
        values[chain] = value

    net_values: dict[str, Decimal] = {}
    for chain, value in values.items():
        net = value - borrowed.get(chain, Decimal("0"))
        if net > 0:
            net_values[chain] = _round_money(net)
    return net_values


def _borrow_supply(current_chain_tvls: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    supplied = Decimal("0")
    borrowed = Decimal("0")
    saw_supply = False
    saw_borrowed = False
    for chain, raw_value in current_chain_tvls.items():
        value = _as_decimal(raw_value)
        if value is None:
            continue
        if chain.endswith("-borrowed"):
            borrowed += value
            saw_borrowed = True
        elif not chain.endswith(("-staking", "-pool2", "-treasury")):
            supplied += value
            saw_supply = True
    return (supplied if saw_supply else None, borrowed if saw_borrowed else None)


def parse_defillama_payload(payload: dict[str, Any]) -> LlamaMetrics:
    series = payload.get("tvl")
    if not isinstance(series, list) or not series:
        raise ValueError("DeFiLlama payload missing tvl series")

    latest_ts, latest_tvl = _latest_positive_series_point(series)
    tvl_30d = _change_pct(30, latest_ts, latest_tvl, series)

    positive_points: list[tuple[datetime, Decimal]] = []
    for point in series:
        ts = _timestamp_to_utc(point.get("date"))
        value = _as_decimal(point.get("totalLiquidityUSD"))
        if ts is not None and value is not None:
            positive_points.append((ts, value))
    positive_points.sort(key=lambda item: item[0])
    last_90 = [value for _, value in positive_points[-90:]]
    cov = _coefficient_of_variation(last_90)

    raw_chain_tvls = payload.get("currentChainTvls")
    if not isinstance(raw_chain_tvls, dict):
        raw_chain_tvls = {}
    chain_tvls = _plain_chain_values(raw_chain_tvls)
    supplied, borrowed = _borrow_supply(raw_chain_tvls)
    utilization: float | None = None
    if supplied is not None and borrowed is not None and supplied > 0:
        utilization = float((borrowed / supplied) * Decimal("100"))

    return LlamaMetrics(
        tvl_usd=_round_money(latest_tvl),
        data_as_of=latest_ts,
        tvl_30d_change_pct=round(tvl_30d, 2) if tvl_30d is not None else None,
        tvl_cov_90d=round(cov, 4) if cov is not None else None,
        tvl_cov_samples=len(last_90),
        chain_tvls=chain_tvls,
        supplied_usd=_round_money(supplied) if supplied is not None else None,
        borrowed_usd=_round_money(borrowed) if borrowed is not None else None,
        utilization_rate_pct=round(utilization, 2) if utilization is not None else None,
    )


def fetch_defillama(slug: str, timeout: int = 30) -> dict[str, Any]:
    url = DEFILLAMA_API.format(slug=slug)
    request = urllib.request.Request(url, headers={"User-Agent": "defirisk-refresh/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"DeFiLlama HTTP {exc.code} for {slug}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeFiLlama fetch failed for {slug}: {exc.reason}") from exc


def _score_tvl(tvl_usd: Decimal, change_30d: float | None) -> str:
    if tvl_usd < Decimal("10000000"):
        return "red"
    if change_30d is not None and change_30d <= -50:
        return "red"
    if tvl_usd < Decimal("100000000"):
        return "yellow"
    if change_30d is not None and change_30d <= -20:
        return "yellow"
    return "green"


def _score_cov(cov: float) -> str:
    if cov > 0.35:
        return "red"
    if cov >= 0.15:
        return "yellow"
    return "green"


def _score_utilization(rate: float) -> str:
    if rate >= 95:
        return "red"
    if rate >= 80:
        return "yellow"
    return "green"


def _score_days_since_exploit(has_active_incident: bool, days: int | None) -> str:
    if has_active_incident:
        return "red"
    if days is None or days > 365:
        return "green"
    return "yellow"


def _has_machine_source(score: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    hay = " ".join(
        [
            str(score.get("evidence_summary") or ""),
            str(score.get("evidence_detail") or ""),
            " ".join(str(src.get("url") or "") for src in score.get("sources", [])),
            " ".join(str(src.get("reference") or "") for src in score.get("sources", [])),
        ]
    ).lower()
    return any(keyword in hay for keyword in keywords)


def _refreshable_score(score: dict[str, Any] | None) -> bool:
    return bool(score and score.get("score") in COLOR_SCORES)


def _would_downgrade_manual_utilization(score: dict[str, Any], new_score: str) -> bool:
    old_score = score.get("score")
    if old_score != "red" or new_score == "red":
        return False
    hay = " ".join(
        str(score.get(key) or "") for key in ("evidence_summary", "evidence_detail")
    ).lower()
    return any(marker in hay for marker in LENDING_MANUAL_OVERRIDE_MARKERS)


def build_factor_updates(
    *,
    protocol: dict[str, Any],
    current_scores: dict[str, dict[str, Any]],
    metrics: LlamaMetrics,
    exploit_days: int | None,
    has_active_incident: bool,
    defillama_slug: str,
) -> tuple[list[FactorUpdate], list[str]]:
    updates: list[FactorUpdate] = []
    skipped: list[str] = []
    llama_source = SourceRef(
        source_type="url",
        url=DEFILLAMA_API.format(slug=defillama_slug),
        reference=f"DeFiLlama protocol API for {defillama_slug}",
        title=f"DeFiLlama {defillama_slug} metrics",
    )

    f063 = current_scores.get("RD-F-063")
    if _refreshable_score(f063) and _has_machine_source(f063, ("defillama", "llama.fi")):
        score = _score_tvl(metrics.tvl_usd, metrics.tvl_30d_change_pct)
        updates.append(
            FactorUpdate(
                factor_id="RD-F-063",
                score=score,
                evidence_summary=(
                    f"Current TVL {_format_usd(metrics.tvl_usd)} "
                    f"as of {_format_date(metrics.data_as_of)} per DeFiLlama. "
                    f"30-day change: {_pct(metrics.tvl_30d_change_pct)}."
                ),
                evidence_detail=json.dumps(
                    {
                        "defillama_slug": defillama_slug,
                        "tvl_usd": float(metrics.tvl_usd),
                        "tvl_30d_change_pct": metrics.tvl_30d_change_pct,
                        "data_as_of": _format_ts(metrics.data_as_of),
                    },
                    sort_keys=True,
                ),
                data_as_of=metrics.data_as_of,
                sources=[llama_source],
            )
        )
    elif f063:
        skipped.append("RD-F-063 skipped: current evidence is not DeFiLlama-backed")

    f084 = current_scores.get("RD-F-084")
    if (
        _refreshable_score(f084)
        and _has_machine_source(f084, ("defillama", "00-data-cache", "data cache"))
        and metrics.tvl_cov_90d is not None
    ):
        score = _score_cov(metrics.tvl_cov_90d)
        updates.append(
            FactorUpdate(
                factor_id="RD-F-084",
                score=score,
                evidence_summary=(
                    f"Trailing 90-day TVL coefficient of variation is "
                    f"{metrics.tvl_cov_90d:.4f} using {metrics.tvl_cov_samples} "
                    f"positive DeFiLlama daily samples through "
                    f"{_format_date(metrics.data_as_of)}."
                ),
                evidence_detail=json.dumps(
                    {
                        "defillama_slug": defillama_slug,
                        "tvl_cov_90d": metrics.tvl_cov_90d,
                        "sample_count": metrics.tvl_cov_samples,
                        "data_as_of": _format_ts(metrics.data_as_of),
                    },
                    sort_keys=True,
                ),
                data_as_of=metrics.data_as_of,
                sources=[llama_source],
            )
        )
    elif f084:
        skipped.append("RD-F-084 skipped: no reliable 90-day DeFiLlama series")

    f066 = current_scores.get("RD-F-066")
    if _refreshable_score(f066) and metrics.utilization_rate_pct is not None:
        score = _score_utilization(metrics.utilization_rate_pct)
        if _would_downgrade_manual_utilization(f066, score):
            skipped.append("RD-F-066 skipped: preserved manual incident override")
        else:
            updates.append(
                FactorUpdate(
                    factor_id="RD-F-066",
                    score=score,
                    evidence_summary=(
                        f"Aggregate utilization is {metrics.utilization_rate_pct:.2f}% "
                        f"as of {_format_date(metrics.data_as_of)} "
                        f"(borrowed {_format_usd(metrics.borrowed_usd or Decimal('0'))}; "
                        f"supplied {_format_usd(metrics.supplied_usd or Decimal('0'))})."
                    ),
                    evidence_detail=json.dumps(
                        {
                            "defillama_slug": defillama_slug,
                            "borrowed_usd": float(metrics.borrowed_usd or Decimal("0")),
                            "supplied_usd": float(metrics.supplied_usd or Decimal("0")),
                            "utilization_rate_pct": metrics.utilization_rate_pct,
                            "data_as_of": _format_ts(metrics.data_as_of),
                        },
                        sort_keys=True,
                    ),
                    data_as_of=metrics.data_as_of,
                    sources=[llama_source],
                )
            )
    elif f066 and f066.get("score") not in SKIP_SCORES:
        skipped.append("RD-F-066 skipped: DeFiLlama borrow/supply data unavailable")

    f080 = current_scores.get("RD-F-080")
    if _refreshable_score(f080):
        score = _score_days_since_exploit(has_active_incident, exploit_days)
        if has_active_incident:
            summary = "An active incident is open; days since last exploit is 0."
        elif exploit_days is None:
            summary = "No prior protocol exploit is recorded in the hacks ledger."
        else:
            summary = (
                f"Most recent recorded exploit was {exploit_days} days before "
                f"{date.today().isoformat()}."
            )
        updates.append(
            FactorUpdate(
                factor_id="RD-F-080",
                score=score,
                evidence_summary=summary,
                evidence_detail=json.dumps(
                    {
                        "days_since_last_exploit": exploit_days,
                        "has_active_incident": has_active_incident,
                        "computed_on": date.today().isoformat(),
                    },
                    sort_keys=True,
                ),
                data_as_of=datetime.now(tz=timezone.utc),
                sources=[
                    SourceRef(
                        source_type="curator_note",
                        url=None,
                        reference="Database hacks ledger and active_incidents table",
                        title="DeFiRisk incident ledger",
                    )
                ],
            )
        )
    elif f080:
        skipped.append("RD-F-080 skipped: current score is intentionally non-color")

    known = {update.factor_id for update in updates}
    for factor_id in sorted(AUTO_FACTOR_IDS - known):
        score = current_scores.get(factor_id)
        if score is None:
            skipped.append(f"{factor_id} skipped: no current factor score")

    return updates, skipped


def factor_update_changed(existing: dict[str, Any], update: FactorUpdate) -> bool:
    if existing.get("score") != update.score:
        return True
    if (existing.get("evidence_summary") or "") != update.evidence_summary:
        return True
    if (existing.get("evidence_detail") or "") != update.evidence_detail:
        return True
    return False


class PostgresRepository:
    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self._family_schema: bool | None = None

    def family_schema_present(self) -> bool:
        if self._family_schema is not None:
            return self._family_schema
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT to_regclass('public.protocol_surfaces') IS NOT NULL AS present"
            )
            row = cur.fetchone()
        self._family_schema = bool(row and row["present"])
        return self._family_schema

    def require_nightly_contracts(self) -> None:
        """Fail before writes when the least-privileged function contract is absent."""
        signatures = (
            "public.refresh_sync_family_tvl(text,numeric)",
            "public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)",
        )
        with self.conn.cursor() as cur:
            for signature in signatures:
                cur.execute(
                    """SELECT to_regprocedure(%s) IS NOT NULL
                              AND has_function_privilege(current_user, %s, 'EXECUTE')""",
                    (signature, signature),
                )
                if not bool(cur.fetchone()[0]):
                    raise BatchRefreshError(
                        f"nightly database contract is missing or not executable: {signature}"
                    )

    def transaction(self) -> Any:
        return self.conn.transaction()

    def fetch_protocols(self, slug: str | None) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            if self.family_schema_present():
                where = "WHERE p.slug = %s" if slug else ""
                params = (slug,) if slug else ()
                cur.execute(
                    f"""
                    SELECT p.slug, p.display_name, p.defillama_slug, p.primary_chain,
                           p.total_value_secured_usd, p.has_active_incident,
                           pf.primary_surface_id,
                           count(ps.surface_id)::int AS surface_count
                    FROM protocols p
                    JOIN protocol_families pf ON pf.family_slug = p.slug
                    LEFT JOIN protocol_surfaces ps ON ps.family_slug = p.slug
                    {where}
                    GROUP BY p.slug, pf.primary_surface_id
                    ORDER BY p.slug
                    """,
                    params,
                )
            else:
                where = "WHERE slug = %s" if slug else ""
                params = (slug,) if slug else ()
                cur.execute(
                    f"""
                    SELECT slug, display_name, defillama_slug, primary_chain,
                           total_value_secured_usd, has_active_incident,
                           NULL::uuid AS primary_surface_id,
                           1::int AS surface_count
                    FROM protocols
                    {where}
                    ORDER BY slug
                    """,
                    params,
                )
            return cur.fetchall()

    def fetch_deployments(self, slug: str) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, protocol_slug, chain, tvs_usd, tvs_share
                FROM deployments
                WHERE protocol_slug = %s
                ORDER BY chain
                """,
                (slug,),
            )
            return cur.fetchall()

    def fetch_factor_scores(self, slug: str) -> dict[str, dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            if self.family_schema_present():
                cur.execute(
                    """
                    SELECT fs.id, fs.protocol_slug, fs.scope_level, fs.family_slug,
                           fs.surface_id, fs.deployment_id, fs.factor_id,
                           fs.rubric_version, fs.score, fs.evidence_summary,
                           fs.evidence_detail, fs.collection_mode, fs.collected_at,
                           fs.data_as_of, fs.collected_by, fs.notes,
                           s.source_type, s.url AS source_url,
                           s.reference AS source_reference, s.title AS source_title
                    FROM factor_scores fs
                    JOIN protocol_families pf ON pf.family_slug = fs.protocol_slug
                    LEFT JOIN factor_score_sources fss ON fss.factor_score_id = fs.id
                    LEFT JOIN sources s ON s.id = fss.source_id
                    WHERE fs.protocol_slug = %s
                      AND fs.is_current = true
                      AND fs.scope_level <> 'deployment'
                      AND (
                        (fs.scope_level = 'surface' AND fs.surface_id = pf.primary_surface_id)
                        OR (fs.scope_level = 'family' AND fs.family_slug = pf.family_slug)
                      )
                    ORDER BY fs.factor_id,
                             CASE fs.scope_level WHEN 'surface' THEN 0 ELSE 1 END,
                             fs.id, s.id
                    """,
                    (slug,),
                )
            else:
                cur.execute(
                    """
                SELECT fs.id, fs.protocol_slug, fs.deployment_id, fs.factor_id,
                       fs.rubric_version, fs.score, fs.evidence_summary,
                       fs.evidence_detail, fs.collection_mode, fs.collected_at,
                       fs.data_as_of, fs.collected_by, fs.notes,
                       s.source_type, s.url AS source_url,
                       s.reference AS source_reference, s.title AS source_title
                FROM factor_scores fs
                LEFT JOIN factor_score_sources fss ON fss.factor_score_id = fs.id
                LEFT JOIN sources s ON s.id = fss.source_id
                WHERE fs.protocol_slug = %s AND fs.is_current = true
                ORDER BY fs.factor_id, s.id
                """,
                (slug,),
                )
            rows = cur.fetchall()

        scores: dict[str, dict[str, Any]] = {}
        selected_ids: dict[str, Any] = {}
        for row in rows:
            factor_id = row["factor_id"]
            if factor_id not in scores:
                scores[factor_id] = dict(row)
                scores[factor_id]["sources"] = []
                selected_ids[factor_id] = row["id"]
            if row["id"] != selected_ids[factor_id]:
                continue
            if row["source_type"] is not None:
                scores[factor_id]["sources"].append(
                    {
                        "source_type": row["source_type"],
                        "url": row["source_url"],
                        "reference": row["source_reference"],
                        "title": row["source_title"],
                    }
                )
        return scores

    def fetch_exploit_state(self, slug: str) -> tuple[int | None, bool]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT occurred_at, is_active, status
                FROM hacks
                WHERE protocol_slug = %s
                ORDER BY occurred_at DESC
                LIMIT 1
                """,
                (slug,),
            )
            hack = cur.fetchone()
            cur.execute(
                """
                SELECT 1
                FROM active_incidents
                WHERE protocol_slug = %s AND status = 'open'
                LIMIT 1
                """,
                (slug,),
            )
            has_open_incident = cur.fetchone() is not None
        is_active_hack = bool(hack and (hack["is_active"] or hack["status"] == "open"))
        has_active = has_open_incident or is_active_hack
        if not hack or not hack.get("occurred_at"):
            return None, has_active
        occurred = hack["occurred_at"]
        if isinstance(occurred, datetime):
            occurred_date = occurred.date()
        else:
            occurred_date = occurred
        return max(0, (date.today() - occurred_date).days), has_active

    def update_protocol_tvl(self, slug: str, tvl_usd: Decimal) -> None:
        with self.conn.cursor() as cur:
            rounded = _round_money(tvl_usd)
            cur.execute(
                """
                UPDATE protocols
                SET total_value_secured_usd = %s, updated_at = now()
                WHERE slug = %s
                """,
                (rounded, slug),
            )
            if cur.rowcount != 1:
                raise BatchRefreshError(
                    f"expected one protocol TVL update for {slug}, got {cur.rowcount}"
                )
            cur.execute(
                "SELECT public.refresh_sync_family_tvl(%s, %s)",
                (slug, rounded),
            )

    def update_deployment_tvl(self, deployment_id: Any, tvl_usd: Decimal, share: Decimal) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE deployments
                SET tvs_usd = %s, tvs_share = %s, updated_at = now()
                WHERE id = %s
                """,
                (_round_money(tvl_usd), _round_share(share), deployment_id),
            )

    def _source_id(self, source: SourceRef, retrieved_at: datetime) -> Any:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id
                FROM sources
                WHERE source_type = %s
                  AND COALESCE(url, '') = COALESCE(%s, '')
                  AND reference = %s
                """,
                (source.source_type, source.url, source.reference),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE sources
                    SET retrieved_at = %s, retrieved_by = %s, title = COALESCE(%s, title)
                    WHERE id = %s
                    """,
                    (retrieved_at, COLLECTED_BY, source.title, row["id"]),
                )
                return row["id"]

            cur.execute(
                """
                INSERT INTO sources
                    (source_type, url, reference, title, retrieved_at, retrieved_by, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    source.source_type,
                    source.url,
                    source.reference,
                    source.title,
                    retrieved_at,
                    COLLECTED_BY,
                    source.notes,
                ),
            )
            return cur.fetchone()["id"]

    def replace_factor_score(
        self,
        existing: dict[str, Any],
        update: FactorUpdate,
        collected_at: datetime,
    ) -> None:
        source_ids = [self._source_id(source, collected_at) for source in update.sources]
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE factor_scores SET is_current = false WHERE id = %s",
                (existing["id"],),
            )
            if self.family_schema_present():
                insert_sql = """
                    INSERT INTO factor_scores
                        (protocol_slug, scope_level, family_slug, surface_id,
                         deployment_id, factor_id, rubric_version,
                         score, evidence_summary, evidence_detail, collection_mode,
                         collected_at, collected_by, data_as_of, is_current, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'programmatic',
                            %s, %s, %s, true, %s)
                    RETURNING id
                """
                insert_params = (
                    existing["protocol_slug"], existing.get("scope_level", "surface"),
                    existing.get("family_slug"), existing.get("surface_id"),
                    existing["deployment_id"], update.factor_id, existing["rubric_version"],
                    update.score, update.evidence_summary, update.evidence_detail,
                    collected_at, COLLECTED_BY, update.data_as_of, "continuous refresh",
                )
            else:
                insert_sql = """
                    INSERT INTO factor_scores
                        (protocol_slug, deployment_id, factor_id, rubric_version,
                         score, evidence_summary, evidence_detail, collection_mode,
                         collected_at, collected_by, data_as_of, is_current, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'programmatic',
                            %s, %s, %s, true, %s)
                    RETURNING id
                """
                insert_params = (
                    existing["protocol_slug"], existing["deployment_id"], update.factor_id,
                    existing["rubric_version"], update.score, update.evidence_summary,
                    update.evidence_detail, collected_at, COLLECTED_BY, update.data_as_of,
                    "continuous refresh",
                )
            cur.execute(insert_sql, insert_params)
            new_id = cur.fetchone()["id"]
            cur.executemany(
                """
                INSERT INTO factor_score_sources (factor_score_id, source_id, relation)
                VALUES (%s, %s, 'primary')
                ON CONFLICT DO NOTHING
                """,
                [(new_id, source_id) for source_id in source_ids],
            )
            cur.execute(
                "UPDATE factor_scores SET superseded_by = %s WHERE id = %s",
                (new_id, existing["id"]),
            )

    def create_pipeline_run(self, triggered_by: str) -> Any | None:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs
                    (script_name, cadence_bucket, protocols_touched,
                     fetchers_invoked, success_count, error_count, triggered_by)
                VALUES (%s, 'C', 0, '[]'::jsonb, 0, 0, %s)
                RETURNING id
                """,
                (SCRIPT_NAME, triggered_by),
            )
            return cur.fetchone()["id"]

    def update_pipeline_run(
        self,
        run_id: Any,
        results: list[ProtocolResult],
        duration_seconds: int,
    ) -> None:
        if run_id is None:
            return
        success_count = sum(1 for result in results if result.error is None)
        error_count = sum(1 for result in results if result.error is not None)
        fetchers = sorted({fetcher for result in results for fetcher in result.fetchers})
        errors = [
            {"protocol": result.slug, "error": result.error}
            for result in results
            if result.error is not None
        ]
        notes = {
            "db_updates": sum(result.db_updates for result in results),
            "factor_updates": sum(result.factor_updates for result in results),
        }
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pipeline_runs
                SET protocols_touched = %s,
                    fetchers_invoked = %s::jsonb,
                    success_count = %s,
                    error_count = %s,
                    duration_seconds = %s,
                    error_summary = %s::jsonb,
                    notes = %s
                WHERE id = %s
                """,
                (
                    len(results),
                    json.dumps(fetchers),
                    success_count,
                    error_count,
                    duration_seconds,
                    json.dumps(errors) if errors else None,
                    json.dumps(notes, sort_keys=True),
                    run_id,
                ),
            )


def _deployment_updates(
    deployments: list[dict[str, Any]],
    metrics: LlamaMetrics,
) -> tuple[list[tuple[dict[str, Any], Decimal, Decimal]], list[str]]:
    if not deployments or not metrics.chain_tvls:
        return [], []
    chain_counts: dict[str, int] = {}
    for deployment in deployments:
        chain = str(deployment["chain"])
        chain_counts[chain] = chain_counts.get(chain, 0) + 1
    duplicate_chains = sorted(chain for chain, count in chain_counts.items() if count > 1)
    if duplicate_chains:
        return [], [
            "deployment TVL skipped for chains with multiple deployment keys: "
            + ", ".join(duplicate_chains)
        ]
    deployment_chains = {str(dep["chain"]) for dep in deployments}
    by_chain = {str(dep["chain"]): dep for dep in deployments}
    updates: list[tuple[dict[str, Any], Decimal, Decimal]] = []
    skipped: list[str] = []
    total = sum(metrics.chain_tvls.values(), Decimal("0"))
    if total <= 0:
        return [], ["deployment TVL skipped: chain TVL total was not positive"]

    matched: set[str] = set()
    for llama_chain, tvl in metrics.chain_tvls.items():
        deployment_chain = _chain_match(llama_chain, deployment_chains)
        if deployment_chain is None:
            continue
        matched.add(deployment_chain)
        dep = by_chain[deployment_chain]
        share = tvl / total
        if _changed_money(dep.get("tvs_usd"), tvl) or _round_share(
            _as_decimal(dep.get("tvs_share")) or Decimal("0")
        ) != _round_share(share):
            updates.append((dep, tvl, share))

    missing = sorted(deployment_chains - matched)
    if missing:
        skipped.append(
            "deployment TVL skipped for unmapped chains: " + ", ".join(missing)
        )
    return updates, skipped


def refresh_protocol(
    *,
    repo: Any,
    protocol: dict[str, Any],
    dry_run: bool,
    fetcher: Any = fetch_defillama,
) -> ProtocolResult:
    slug = protocol["slug"]
    result = ProtocolResult(slug=slug, status="ok")
    if int(protocol.get("surface_count") or 1) > 1:
        result.status = "skipped"
        result.skipped.append(
            "multi-surface family requires an explicitly scoped refresh bundle"
        )
        return result
    defillama_slug = protocol.get("defillama_slug")
    if not defillama_slug:
        result.status = "skipped"
        result.skipped.append("missing defillama_slug")
        return result

    payload = fetcher(defillama_slug)
    result.fetchers.add("defillama")
    metrics = parse_defillama_payload(payload)

    deployments = repo.fetch_deployments(slug)
    current_scores = repo.fetch_factor_scores(slug)
    exploit_days, has_active_incident = repo.fetch_exploit_state(slug)
    factor_updates, factor_skips = build_factor_updates(
        protocol=protocol,
        current_scores=current_scores,
        metrics=metrics,
        exploit_days=exploit_days,
        has_active_incident=has_active_incident
        or bool(protocol.get("has_active_incident")),
        defillama_slug=defillama_slug,
    )
    result.skipped.extend(factor_skips)

    deployment_updates, deployment_skips = _deployment_updates(deployments, metrics)
    result.skipped.extend(deployment_skips)

    tvl_changed = _changed_money(protocol.get("total_value_secured_usd"), metrics.tvl_usd)
    changed_factor_updates = [
        update
        for update in factor_updates
        if update.factor_id in current_scores
        and factor_update_changed(current_scores[update.factor_id], update)
    ]

    planned_updates = int(tvl_changed) + len(deployment_updates) + len(changed_factor_updates)
    if planned_updates == 0:
        result.status = "unchanged"
        return result

    result.db_updates = planned_updates
    result.factor_updates = len(changed_factor_updates)
    if dry_run:
        return result

    collected_at = datetime.now(tz=timezone.utc)
    with repo.transaction():
        if tvl_changed:
            repo.update_protocol_tvl(slug, metrics.tvl_usd)
        for deployment, tvl, share in deployment_updates:
            repo.update_deployment_tvl(deployment["id"], tvl, share)
        for update in changed_factor_updates:
            repo.replace_factor_score(current_scores[update.factor_id], update, collected_at)

    return result


def process_protocols(
    *,
    repo: Any,
    protocols: list[dict[str, Any]],
    dry_run: bool,
    all_protocols: bool,
    fetcher: Any = fetch_defillama,
) -> list[ProtocolResult]:
    results: list[ProtocolResult] = []
    for protocol in protocols:
        try:
            result = refresh_protocol(
                repo=repo,
                protocol=protocol,
                dry_run=dry_run,
                fetcher=fetcher,
            )
        except Exception as exc:
            result = ProtocolResult(
                slug=protocol.get("slug", "<unknown>"),
                status="error",
                error=str(exc),
            )
            results.append(result)
            if not all_protocols:
                break
            continue
        results.append(result)
        if result.error and not all_protocols:
            break
    return results


def _run_subprocess(args: list[str], *, dry_run: bool) -> int:
    cmd = [sys.executable, *args]
    printable = " ".join(str(part) for part in cmd)
    if dry_run:
        print(f"[dry-run] would run: {printable}")
        return 0
    print(f"Running: {printable}")
    return subprocess.run(cmd, check=False).returncode


def _post_refresh_steps(
    *,
    protocol_slug: str | None,
    factor_updates: int,
    db_updates: int,
    dry_run: bool,
) -> int:
    if db_updates <= 0:
        print("No DB updates were made; compose.py and dump.py are not needed.")
        return 0

    scripts_dir = Path(__file__).resolve().parent
    if dry_run and factor_updates > 0:
        target = protocol_slug or "all protocols"
        print(f"[dry-run] would compose and detect grade changes for {target} in one transaction")
    return _run_subprocess([str(scripts_dir / "dump.py")], dry_run=dry_run)


def print_summary(results: list[ProtocolResult]) -> None:
    successes = [result for result in results if result.error is None]
    failures = [result for result in results if result.error is not None]
    db_updates = sum(result.db_updates for result in successes)
    factor_updates = sum(result.factor_updates for result in successes)
    print("\nContinuous refresh summary")
    print(f"  protocols processed : {len(results)}")
    print(f"  successes           : {len(successes)}")
    print(f"  failures            : {len(failures)}")
    print(f"  db updates          : {db_updates}")
    print(f"  factor updates      : {factor_updates}")
    if failures:
        print("\nFailures:")
        for result in failures:
            print(f"  {result.slug}: {result.error}")
    skipped = [
        f"{result.slug}: {reason}"
        for result in successes
        for reason in result.skipped
    ]
    if skipped:
        print("\nSkipped or intentionally preserved:")
        for item in skipped[:50]:
            print(f"  {item}")
        if len(skipped) > 50:
            print(f"  ... {len(skipped) - 50} more")


def _connect(conn_str: str) -> Any:
    if psycopg is None:
        print("ERROR: psycopg v3 is not installed. Run: pip install 'psycopg[binary]'")
        sys.exit(1)
    try:
        return psycopg.connect(conn_str, connect_timeout=10)
    except psycopg.Error as exc:
        print(f"ERROR: Cannot connect to database: {exc}", file=sys.stderr)
        sys.exit(1)


def run(*, conn_str: str, all_protocols: bool, protocol_slug: str | None, dry_run: bool) -> int:
    started = time.monotonic()
    conn = _connect(conn_str)
    results: list[ProtocolResult] = []
    run_id: Any | None = None
    db_updates = 0
    factor_updates = 0
    try:
        with conn:
            repo = PostgresRepository(conn)
            repo.require_nightly_contracts()
            protocols = repo.fetch_protocols(None if all_protocols else protocol_slug)
            if not protocols:
                target = protocol_slug or "all protocols"
                raise BatchRefreshError(f"no protocols found for {target}")
            if not dry_run:
                run_id = repo.create_pipeline_run(
                    f"{SCRIPT_NAME}:{'all' if all_protocols else protocol_slug}"
                )

            results = process_protocols(
                repo=repo,
                protocols=protocols,
                dry_run=dry_run,
                all_protocols=all_protocols,
            )
            failures = [result for result in results if result.error is not None]
            successes = [result for result in results if result.error is None]
            db_updates = sum(result.db_updates for result in successes)
            factor_updates = sum(result.factor_updates for result in successes)

            if run_id is not None:
                duration = int(time.monotonic() - started)
                repo.update_pipeline_run(run_id, results, duration)
            if failures:
                raise BatchRefreshError(
                    f"{len(failures)} protocol refresh(es) failed; rolling back the nightly batch"
                )

            if not dry_run and factor_updates > 0:
                compose = _load_sibling_script("nightly_compose", "compose.py")
                compose_code = compose.run(
                    conn_str,
                    slug=protocol_slug if not all_protocols else None,
                    dry_run=False,
                    connection=conn,
                )
                if compose_code != 0:
                    raise BatchRefreshError("compose step failed")

                detector = _load_sibling_script(
                    "nightly_detect_grade_changes", "detect-grade-changes.py"
                )
                detector_code = detector.run(
                    conn_str,
                    dry_run=False,
                    snapshot_date=None,
                    backfill=False,
                    connection=conn,
                )
                if detector_code != 0:
                    raise BatchRefreshError("grade-change detection failed")
    except Exception as exc:
        conn.close()
        print_summary(results)
        print(f"ERROR: nightly refresh rolled back: {exc}", file=sys.stderr)
        return 1

    conn.close()
    print_summary(results)
    return _post_refresh_steps(
        protocol_slug=protocol_slug if not all_protocols else None,
        factor_updates=factor_updates,
        db_updates=db_updates,
        dry_run=dry_run,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh continuous-cadence DeFiRisk metrics"
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="Refresh all protocols")
    scope.add_argument("--protocol", metavar="SLUG", help="Refresh one protocol")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn_str = os.environ.get("DATABASE_URL") or os.environ.get("LOCAL_DATABASE_URL")
    if not conn_str:
        print(
            "ERROR: Set DATABASE_URL or LOCAL_DATABASE_URL before running.",
            file=sys.stderr,
        )
        return 1
    # Keep tests free to pass fake repos while production always uses Postgres.
    with nullcontext():
        return run(
            conn_str=conn_str,
            all_protocols=args.all,
            protocol_slug=args.protocol,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    raise SystemExit(main())
