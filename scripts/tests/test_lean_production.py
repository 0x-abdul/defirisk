from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import subprocess
from types import SimpleNamespace

import pytest

from lean_protocol_refresh.contracts import (
    CANONICAL_FACTOR_IDS,
    ContractError,
    Evidence,
    FactorChange,
    MixedRecovery,
    ProtocolRefresh,
    RefreshBatch,
    validate_change_set,
)
from lean_protocol_refresh.production import ProductionOperations, _run, create_operations
from lean_protocol_refresh.planning import BaselineClassification


def batch() -> RefreshBatch:
    return RefreshBatch("batch / unsafe", "2026-07-23", "v1.7.0", ())


def factor_change(factor_id: str) -> FactorChange:
    return FactorChange(
        factor_id,
        "surface",
        "default",
        {"factor_id": factor_id, "score": "yellow", "sources": []},
        {
            "factor_id": factor_id,
            "score": "green",
            "sources": [{"url": f"https://example.org/{factor_id}"}],
        },
        (Evidence(f"https://example.org/{factor_id}"),),
        "green",
        "B",
    )


def protocol_with_changes(count: int) -> ProtocolRefresh:
    return ProtocolRefresh(
        "falcon",
        ("default",),
        (),
        "changed",
        "2026-07-23",
        "B",
        "v1.7.0",
        tuple(
            factor_change(factor_id)
            for factor_id in sorted(CANONICAL_FACTOR_IDS)[:count]
        ),
        "C",
    )


def protocol_with_mixed_recovery(*, changed: bool = True) -> ProtocolRefresh:
    target_rows = tuple(
        FactorChange(
            factor_id,
            "surface",
            "default",
            {
                "factor_id": factor_id,
                "score": "green",
                "evidence_summary": f"Evidence for {factor_id}",
                "collection_mode": "manual",
                "sources": [
                    {
                        "source_type": "url",
                        "url": f"https://example.org/{factor_id}",
                        "reference": f"https://example.org/{factor_id}",
                    }
                ],
            },
            {
                "factor_id": factor_id,
                "score": "green",
                "evidence_summary": f"Evidence for {factor_id}",
                "collection_mode": "manual",
                "sources": [
                    {
                        "source_type": "url",
                        "url": f"https://example.org/{factor_id}",
                        "reference": f"https://example.org/{factor_id}",
                    }
                ],
            },
            (Evidence(f"https://example.org/{factor_id}"),),
            "green",
            "B",
        )
        for factor_id in sorted(CANONICAL_FACTOR_IDS)
    )
    changes = (factor_change("RD-F-001"),) if changed else ()
    if changed:
        target_rows = (
            FactorChange(
                target_rows[0].factor_id,
                target_rows[0].scope_level,
                target_rows[0].target,
                changes[0].new_value,
                changes[0].new_value,
                changes[0].evidence,
                changes[0].resulting_score,
                changes[0].resulting_grade,
            ),
            *target_rows[1:],
        )
    return ProtocolRefresh(
        "falcon",
        ("default",),
        (),
        "changed" if changed else "no_change",
        "2026-07-23",
        "B",
        "v1.7.0",
        changes,
        "C",
        MixedRecovery(
            "lean-protocol-refresh/mixed-recovery/v1",
            "v1.5.0",
            "v1.7.0",
            "prefer_target_then_source",
            target_rows,
            "1" * 64,
            "2" * 64,
        ),
    )


class BaselineCursor:
    def __init__(self, rows: tuple[tuple[str, int], ...]) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql, _params):
        return None

    def fetchall(self):
        result = []
        factor_ids = sorted(CANONICAL_FACTOR_IDS)
        for version, count in self.rows:
            result.extend(
                (version, factor_id, "surface", "default")
                for factor_id in factor_ids[:count]
            )
        return tuple(result)


class BaselineConnection:
    def __init__(self, rows: tuple[tuple[str, int], ...]) -> None:
        self.rows = rows

    def cursor(self):
        return BaselineCursor(self.rows)


def baseline_operations(
    tmp_path: Path, rows: tuple[tuple[str, int], ...]
) -> ProductionOperations:
    return ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: BaselineConnection(rows),
    )


class ExactBaselineCursor(BaselineCursor):
    def __init__(self, rows):
        self.exact_rows = rows
        super().__init__(())

    def fetchall(self):
        return self.exact_rows


class ExactBaselineConnection(BaselineConnection):
    def __init__(self, rows):
        self.exact_rows = rows
        super().__init__(())

    def cursor(self):
        return ExactBaselineCursor(self.exact_rows)


def exact_baseline_operations(tmp_path: Path, rows) -> ProductionOperations:
    return ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: ExactBaselineConnection(rows),
    )


def test_selected_production_binding_prefers_v17_and_hashes_all_rows(
    tmp_path: Path,
) -> None:
    protocol = protocol_with_changes(1)
    factor_ids = sorted(CANONICAL_FACTOR_IDS)

    def rows(v17_score: str):
        result = [
            (
                f"v15-{factor_id}",
                "v1.5.0",
                factor_id,
                "surface",
                "default",
                {"score": "yellow"},
            )
            for factor_id in factor_ids
        ]
        result.append(
            (
                "v17-RD-F-001",
                "v1.7.0",
                "RD-F-001",
                "surface",
                "default",
                {"score": v17_score},
            )
        )
        return tuple(result)

    class SelectedCursor:
        def __init__(self, selected_rows):
            self.selected_rows = selected_rows

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql, _params):
            return None

        def fetchall(self):
            return self.selected_rows

    class SelectedConnection:
        def __init__(self, selected_rows):
            self.selected_rows = selected_rows

        def cursor(self):
            return SelectedCursor(self.selected_rows)

    def operations(selected_rows):
        ops = ProductionOperations(
            batch(),
            "postgresql://x",
            tmp_path,
            "o/r",
            "main",
            connect=lambda _url: SelectedConnection(selected_rows),
        )
        ops._actual_old_value = lambda _cur, _protocol, **kwargs: {
            "factor_id": kwargs["factor_id"],
            "category": 1,
            "family_slug": protocol.family_slug,
            "scope_level": kwargs["scope_level"],
            "surface_slug": kwargs["target"],
            "score": kwargs["old"]["score"],
            "evidence_summary": "Public production evidence.",
            "evidence_detail": None,
            "collection_mode": "manual",
            "gap_reason": None,
            "notes": None,
            "sources": [
                {
                    "source_type": "docs",
                    "url": "https://example.org/production",
                    "reference": "Production evidence",
                    "relation": "primary",
                }
            ],
        }
        return ops

    first_hash, changed_old_values = operations(rows("yellow"))._selected_production_binding(
        protocol
    )
    second_hash, _ = operations(rows("red"))._selected_production_binding(protocol)

    assert changed_old_values[0][3]["score"] == "yellow"
    assert first_hash != second_hash


class HistoricalOldCursor:
    def __init__(self, sources=()) -> None:
        self.query = 0
        self.sources = sources

    def execute(self, _sql, _params):
        self.query += 1

    def fetchone(self):
        assert self.query == 1
        return (1,)

    def fetchall(self):
        assert self.query == 2
        return tuple(
            source if len(source) == 7 else (*source, "primary")
            for source in self.sources
        )


def test_historical_old_projection_preserves_production_baseline_check(
    tmp_path: Path,
) -> None:
    remediation = {
        "schema_version": "lean-protocol-refresh/historical-old-remediation/v1",
        "mode": "historical_evidence_unavailable",
        "specialist": "code-security-analyst",
        "baseline_fragment_semantic_sha256": "1" * 64,
        "baseline_row_semantic_sha256": "2" * 64,
        "explanation": (
            "The retained score is immutable historical state and is not "
            "presented as a publicly substantiated claim."
        ),
        "evidence_summary": (
            "No public-safe evidence can substantiate the retained historical "
            "score; it is shown only as immutable baseline state."
        ),
        "evidence_detail": None,
        "notes": None,
        "sources": [],
    }
    change = FactorChange(
        "RD-F-001",
        "surface",
        "default",
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "surface_slug": "default",
            "score": "yellow",
            "collection_mode": "manual",
            "gap_reason": None,
            "sources": [],
        },
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "sources": [{"url": "https://example.org/current"}],
        },
        (Evidence("https://example.org/current"),),
        "green",
        "B",
        remediation,
    )
    protocol = protocol_with_changes(1)
    operations = baseline_operations(tmp_path, (("v1.7.0", 184),))
    operations._verify_public_old_row(
        HistoricalOldCursor(),
        protocol,
        change,
        "old-score-id",
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "score": "yellow",
            "collection_mode": "manual",
            "evidence_summary": "Retained private historical text",
            "evidence_detail": None,
            "gap_reason": None,
            "notes": None,
        },
    )
    operations.batch = RefreshBatch(
        "batch-1",
        "2026-07-23",
        "v1.7.0",
        (replace(protocol, changes=(change,)),),
    )
    operations._selected_change_old_values[protocol.family_slug] = {
        operations._factor_key(change): change.old_value
    }
    public_record = operations._public_record(
        replace(protocol, changes=(change,))
    )
    reparsed = validate_change_set(public_record)
    assert (
        reparsed.protocols[0].changes[0].historical_old_remediation
        == remediation
    )


def test_historical_old_projection_accepts_conservative_remediation(
    tmp_path: Path,
) -> None:
    remediation = {
        "schema_version": "lean-protocol-refresh/historical-old-remediation/v1",
        "mode": "historical_evidence_unavailable",
        "specialist": "code-security-analyst",
        "baseline_fragment_semantic_sha256": "1" * 64,
        "baseline_row_semantic_sha256": "2" * 64,
        "explanation": (
            "The retained score is immutable historical state and is not "
            "presented as a publicly substantiated claim."
        ),
        "evidence_summary": (
            "No public-safe evidence can substantiate the retained historical "
            "score; it is shown only as immutable baseline state."
        ),
        "evidence_detail": None,
        "notes": None,
        "sources": [],
    }
    change = FactorChange(
        "RD-F-001",
        "surface",
        "default",
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "surface_slug": "default",
            "score": "yellow",
            "collection_mode": "manual",
            "gap_reason": None,
            "sources": [],
        },
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "sources": [{"url": "https://example.org/current"}],
        },
        (Evidence("https://example.org/current"),),
        "green",
        "B",
        remediation,
    )
    protocol = protocol_with_changes(1)
    operations = baseline_operations(tmp_path, (("v1.7.0", 184),))
    cursor = HistoricalOldCursor(
        (
            (
                "docs",
                "https://example.org/historical",
                "Published historical evidence",
                "Historical evidence",
                "2026-07-24",
                None,
            ),
        )
    )
    operations._verify_public_old_row(
        cursor,
        protocol,
        change,
        "old-score-id",
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "score": "yellow",
            "collection_mode": "manual",
            "evidence_summary": "Published historical assessment.",
            "evidence_detail": None,
            "gap_reason": None,
            "notes": None,
        },
    )


def test_public_old_source_binding_uses_stable_source_identity(
    tmp_path: Path,
) -> None:
    source_identity = {
        "source_type": "docs",
        "url": "https://example.org/historical",
        "reference": "Published historical evidence",
    }
    change = FactorChange(
        "RD-F-001",
        "surface",
        "default",
        {
            "factor_id": "RD-F-001",
            "scope_level": "surface",
            "surface_slug": "default",
            "score": "yellow",
            "collection_mode": "manual",
            "evidence_summary": "Published historical assessment.",
            "evidence_detail": None,
            "gap_reason": None,
            "notes": None,
            "sources": [source_identity],
        },
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "sources": [{"url": "https://example.org/current"}],
        },
        (Evidence("https://example.org/current"),),
        "green",
        "B",
    )
    protocol = protocol_with_changes(1)
    operations = baseline_operations(tmp_path, (("v1.7.0", 184),))
    production_source = (
        (
            source_identity["source_type"],
            source_identity["url"],
            source_identity["reference"],
            "Additional shared source title",
            "2026-07-24",
            "Additional shared source notes",
        ),
    )
    old_row = {
        "factor_id": "RD-F-001",
        "scope_level": "surface",
        "score": "yellow",
        "collection_mode": "manual",
        "evidence_summary": "Published historical assessment.",
        "evidence_detail": None,
        "gap_reason": None,
        "notes": None,
    }

    operations._verify_public_old_row(
        HistoricalOldCursor(production_source),
        protocol,
        change,
        "old-score-id",
        old_row,
    )

    drifted_change = replace(
        change,
        old_value={
            **change.old_value,
            "sources": [
                {
                    **source_identity,
                    "reference": "Different source identity",
                }
            ],
        },
    )
    with pytest.raises(ContractError, match="public old-source baseline drifted"):
        operations._verify_public_old_row(
            HistoricalOldCursor(production_source),
            protocol,
            drifted_change,
            "old-score-id",
            old_row,
        )


@pytest.mark.parametrize(
    "protocol",
    [
        protocol_with_changes(1),
        ProtocolRefresh(
            "maple",
            ("default",),
            (),
            "no_change",
            "2026-07-23",
            "A",
            "v1.7.0",
            (),
            "A",
        ),
    ],
)
def test_v17_baseline_selects_standard_refresh_for_sparse_and_no_change(
    tmp_path: Path, protocol: ProtocolRefresh
) -> None:
    ops = baseline_operations(tmp_path, (("v1.7.0", 184),))
    assert ops._classify_protocol_baseline(protocol) == "v1.7.0"


def test_v15_baseline_preserves_full_migration_route(tmp_path: Path) -> None:
    ops = baseline_operations(tmp_path, (("v1.5.0", 184),))
    assert ops._classify_protocol_baseline(protocol_with_changes(184)) == "v1.5.0"


def test_completed_full_migration_requires_exact_184_row_history_binding(
    tmp_path: Path,
) -> None:
    protocol = protocol_with_changes(184)
    ops = baseline_operations(tmp_path, (("v1.7.0", 184),))
    ops._legacy_history_binding = lambda *_args, **_kwargs: (184, "a" * 64)
    ops._selected_production_binding = lambda *_args, **_kwargs: (
        "c" * 64,
        tuple(
            (
                change.scope_level,
                change.target,
                change.factor_id,
                change.old_value,
            )
            for change in protocol.changes
        ),
    )
    classification = ops._baseline_classification(
        protocol, include_history_binding=True
    )
    assert classification.rubric_route == "full_v15_migration_complete"
    assert classification.legacy_history_sha256 == "a" * 64

    ops._legacy_history_binding = lambda *_args, **_kwargs: (183, "b" * 64)
    with pytest.raises(ContractError, match="history binding is incomplete"):
        ops._baseline_classification(
            protocol, include_history_binding=True
        )


@pytest.mark.parametrize(
    "protocol",
    [
        protocol_with_changes(1),
        ProtocolRefresh(
            "maple",
            ("default",),
            (),
            "no_change",
            "2026-07-23",
            "A",
            "v1.7.0",
            (),
            "A",
        ),
    ],
)
def test_v15_baseline_requires_changed_outcome_with_all_184_rows(
    tmp_path: Path, protocol: ProtocolRefresh
) -> None:
    ops = baseline_operations(tmp_path, (("v1.5.0", 184),))
    with pytest.raises(ContractError, match="changed outcome.*exactly the 184"):
        ops._classify_protocol_baseline(protocol)


def test_v15_baseline_requires_exact_canonical_change_coverage(
    tmp_path: Path,
) -> None:
    complete = protocol_with_changes(184)
    duplicate = FactorChange(
        complete.changes[0].factor_id,
        "family",
        complete.family_slug,
        complete.changes[-1].old_value,
        complete.changes[-1].new_value,
        complete.changes[-1].evidence,
        complete.changes[-1].resulting_score,
        complete.changes[-1].resulting_grade,
    )
    protocol = ProtocolRefresh(
        complete.family_slug,
        complete.surface_slugs,
        complete.deployment_targets,
        complete.outcome,
        complete.last_refreshed,
        complete.resulting_grade,
        complete.rubric_version,
        (*complete.changes[:-1], duplicate),
        complete.previous_grade,
    )
    ops = baseline_operations(tmp_path, (("v1.5.0", 184),))
    with pytest.raises(ContractError, match="canonical approved factor rows"):
        ops._classify_protocol_baseline(protocol)


@pytest.mark.parametrize(
    "rows",
    [
        (("v1.7.0", 183),),
        (("v1.5.0", 92), ("v1.7.0", 92)),
        (("v1.6.0", 184),),
        (),
    ],
)
def test_mixed_incomplete_and_unsupported_baselines_are_rejected(
    tmp_path: Path, rows: tuple[tuple[str, int], ...]
) -> None:
    ops = baseline_operations(tmp_path, rows)
    with pytest.raises(
        ContractError,
        match="must contain the exact 184 v1.7.0 factor IDs.*or only v1.5.0",
    ):
        ops._classify_protocol_baseline(protocol_with_changes(1))


def test_baseline_rejects_wrong_184_factor_universe(tmp_path: Path) -> None:
    class WrongFactorCursor(BaselineCursor):
        def fetchall(self):
            factor_ids = sorted(CANONICAL_FACTOR_IDS)
            factor_ids[-1] = "RD-F-999"
            return tuple(
                ("v1.7.0", factor_id, "surface", "default")
                for factor_id in factor_ids
            )

    class WrongFactorConnection(BaselineConnection):
        def cursor(self):
            return WrongFactorCursor(())

    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: WrongFactorConnection(()),
    )
    with pytest.raises(ContractError, match="exact 184 v1.7.0 factor IDs"):
        ops._classify_protocol_baseline(protocol_with_changes(1))


def test_standard_baseline_rejects_scoped_target_outside_approved_topology(
    tmp_path: Path,
) -> None:
    factor_ids = sorted(CANONICAL_FACTOR_IDS)
    rows = [
        ("v1.7.0", factor_id, "surface", "default")
        for factor_id in factor_ids
    ]
    rows[-1] = ("v1.7.0", rows[-1][1], "surface", "wrong-surface")
    ops = exact_baseline_operations(tmp_path, tuple(rows))

    with pytest.raises(ContractError, match="exact 184 v1.7.0 factor IDs"):
        ops._classify_protocol_baseline(protocol_with_changes(1))


def test_mixed_baseline_requires_bound_recovery_and_exact_union(
    tmp_path: Path,
) -> None:
    factor_ids = sorted(CANONICAL_FACTOR_IDS)
    rows = tuple(
        [("v1.5.0", factor_id, "surface", "default") for factor_id in factor_ids[:180]]
        + [("v1.7.0", factor_id, "surface", "default") for factor_id in factor_ids[180:]]
    )
    ops = exact_baseline_operations(tmp_path, rows)

    assert (
        ops._classify_protocol_baseline(protocol_with_mixed_recovery())
        == "mixed_recovery"
    )
    classification = ops._baseline_classification(
        protocol_with_mixed_recovery()
    )
    assert (
        classification.current_v15_rows,
        classification.current_v17_rows,
        classification.overlap_rows,
        classification.semantic_change_rows,
        classification.migration_only_rows,
        classification.v17_insert_or_replace_rows,
        classification.v15_retirement_rows,
    ) == (180, 4, 0, 1, 179, 180, 180)
    with pytest.raises(ContractError, match="exact 184 v1.7.0 factor IDs"):
        ops._classify_protocol_baseline(protocol_with_changes(1))


def test_mixed_baseline_accepts_overlap_with_v17_preference(
    tmp_path: Path,
) -> None:
    factor_ids = sorted(CANONICAL_FACTOR_IDS)
    rows = tuple(
        [("v1.5.0", factor_id, "surface", "default") for factor_id in factor_ids]
        + [("v1.7.0", factor_id, "surface", "default") for factor_id in factor_ids[:4]]
    )
    ops = exact_baseline_operations(tmp_path, rows)

    assert (
        ops._classify_protocol_baseline(protocol_with_mixed_recovery())
        == "mixed_recovery"
    )


class ResumeIntegrityCursor:
    def __init__(self, rows) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql, _params):
        return None

    def fetchall(self):
        return self.rows


class ResumeIntegrityConnection:
    def __init__(self, rows) -> None:
        self.rows = rows

    def cursor(self):
        return ResumeIntegrityCursor(self.rows)


def test_legacy_history_binding_preserves_source_join_identities_and_empty_sets(
    tmp_path: Path,
) -> None:
    protocol = protocol_with_mixed_recovery()
    connection = ResumeIntegrityConnection(
        (("legacy-1", ("source-1", "source-2")), ("legacy-2", ()))
    )
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: connection,
    )
    count, history_hash = ops._legacy_history_binding(
        protocol, current_rows=False
    )

    assert count == 2
    assert history_hash is not None
    ops._conn = ResumeIntegrityConnection((("legacy-1", ("source-1",)),))
    assert ops._legacy_history_binding(
        protocol, current_rows=False
    ) != (count, history_hash)


def test_mixed_resume_requires_exact_approved_legacy_history_hash(
    tmp_path: Path,
) -> None:
    protocol = protocol_with_mixed_recovery()
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
    )
    approved_hash = "a" * 64
    ops.bind_approved_plan(
        {
            "protocols": [
                {
                    "family_slug": protocol.family_slug,
                    "rubric_route": "mixed_recovery",
                    "v15_retirement_rows": 180,
                    "legacy_history_sha256": approved_hash,
                    "changes": [
                        {
                            "factor_id": change.factor_id,
                            "scope_level": change.scope_level,
                            "target": change.target,
                            "selected_production_old_value": change.old_value,
                        }
                        for change in protocol.changes
                    ],
                }
            ]
        }
    )
    ops._baseline_classification = lambda *_args, **_kwargs: BaselineClassification(
        protocol.family_slug,
        "mixed_recovery_complete",
        0,
        184,
        0,
        len(protocol.changes),
        0,
        0,
        0,
        protocol.mixed_recovery.full_target_projection_semantic_sha256,
        approved_hash,
    )
    ops._conn = SimpleNamespace(rollback=lambda: None)

    ops.validate_protocol_resume(protocol, SimpleNamespace())
    ops._baseline_classification = lambda *_args, **_kwargs: replace(
        BaselineClassification(
            protocol.family_slug,
            "mixed_recovery_complete",
            0,
            184,
            0,
            len(protocol.changes),
            0,
            0,
            0,
            protocol.mixed_recovery.full_target_projection_semantic_sha256,
            approved_hash,
        ),
        legacy_history_sha256="b" * 64,
    )
    with pytest.raises(ContractError, match="retained v1.5.0 history"):
        ops.validate_protocol_resume(protocol, SimpleNamespace())


def test_precommit_rejects_missing_legacy_row_or_source_join(
    tmp_path: Path,
) -> None:
    protocol = protocol_with_mixed_recovery()
    approved_hash = "a" * 64
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
    )
    ops._planned_classifications[protocol.family_slug] = BaselineClassification(
        protocol.family_slug,
        "mixed_recovery",
        180,
        4,
        0,
        len(protocol.changes),
        179,
        180,
        180,
        protocol.mixed_recovery.full_target_projection_semantic_sha256,
        approved_hash,
    )
    ops._legacy_history_binding = lambda *_args, **_kwargs: (
        180,
        approved_hash,
    )
    ops._verify_legacy_history_postcondition(protocol)

    ops._legacy_history_binding = lambda *_args, **_kwargs: (
        179,
        "b" * 64,
    )
    with pytest.raises(ContractError, match="source-join identities"):
        ops._verify_legacy_history_postcondition(protocol)


def test_mixed_baseline_rejects_union_gap(tmp_path: Path) -> None:
    factor_ids = sorted(CANONICAL_FACTOR_IDS)
    rows = tuple(
        ("v1.5.0", factor_id, "surface", "default")
        for factor_id in factor_ids[:-1]
    )
    rows += (("v1.7.0", factor_ids[0], "surface", "default"),)
    ops = exact_baseline_operations(tmp_path, rows)

    with pytest.raises(ContractError, match="exact approved 184-key"):
        ops._classify_protocol_baseline(protocol_with_mixed_recovery())


class MixedApplyCursor:
    def __init__(self, protocol: ProtocolRefresh) -> None:
        assert protocol.mixed_recovery is not None
        self.targets = {
            row.factor_id: row
            for row in protocol.mixed_recovery.full_target_projection
        }
        self.overlap = set(sorted(CANONICAL_FACTOR_IDS)[:4])
        self.sql = ""
        self.params = ()
        self.rowcount = 0
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params=None):
        self.sql = " ".join(str(sql).split())
        self.params = params or ()
        self.statements.append(self.sql)
        self.rowcount = 1

    def fetchone(self):
        if "SELECT surface_id FROM protocol_surfaces" in self.sql:
            return ("surface-id",)
        if "SELECT category_id FROM factors" in self.sql:
            return (1,)
        if "SELECT id FROM sources" in self.sql:
            return ("source-id",)
        if "INSERT INTO factor_scores" in self.sql:
            return (f"new-{self.params[2]}",)
        raise AssertionError(self.sql)

    def fetchall(self):
        if "SELECT id, rubric_version, to_jsonb(factor_scores)" in self.sql:
            factor_id = self.params[1]
            target = self.targets[factor_id]
            row = {
                "factor_id": factor_id,
                "score": target.new_value["score"],
                "evidence_summary": target.new_value["evidence_summary"],
                "evidence_detail": target.new_value.get("evidence_detail"),
                "collection_mode": target.new_value["collection_mode"],
                "gap_reason": target.new_value.get("gap_reason"),
                "notes": target.new_value.get("notes"),
                "scope_level": "surface",
            }
            rows = [(f"old15-{factor_id}", "v1.5.0", row)]
            if factor_id in self.overlap:
                rows.append((f"old17-{factor_id}", "v1.7.0", row))
            return rows
        if "FROM factor_score_sources" in self.sql:
            factor_id = "RD-F-" + str(self.params[0]).rsplit("RD-F-", 1)[-1]
            url = f"https://example.org/{factor_id}"
            return [("url", url, url, None, None, None)]
        if "count(DISTINCT factor_id)" in self.sql:
            return [("v1.7.0", 184, 184)]
        raise AssertionError(self.sql)


class MixedApplyConnection:
    def __init__(self, protocol: ProtocolRefresh) -> None:
        self.cursor_value = MixedApplyCursor(protocol)

    def cursor(self):
        return self.cursor_value


def test_mixed_no_change_backfills_target_and_retires_legacy_without_delete(
    tmp_path: Path,
) -> None:
    protocol = protocol_with_mixed_recovery(changed=False)
    connection = MixedApplyConnection(protocol)
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: connection,
    )
    ops._protocol_baseline_family = protocol.family_slug
    ops._protocol_baseline_rubric = "mixed_recovery"

    ops.apply_protocol(protocol)

    statements = connection.cursor_value.statements
    assert sum("INSERT INTO factor_scores" in sql for sql in statements) == 180
    assert all("DELETE FROM factor_scores" not in sql for sql in statements)
    assert any("count(DISTINCT factor_id)" in sql for sql in statements)


@pytest.mark.parametrize("baseline_rubric", ["v1.7.0", "v1.5.0"])
def test_apply_supersedes_selected_baseline_and_preserves_history(
    tmp_path: Path, baseline_rubric: str
) -> None:
    class ApplyCursor:
        def __init__(self) -> None:
            self.calls = []
            self.result = None
            self.rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            self.calls.append((sql, params))
            if "SELECT surface_id FROM protocol_surfaces" in sql:
                self.result = ("surface-id",)
            elif "SELECT id, rubric_version" in sql:
                self.result = [("old-id", baseline_rubric, {})]
            elif "INSERT INTO factor_scores" in sql:
                self.result = ("new-id",)
            else:
                self.result = None
            self.rowcount = 1

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

    class ApplyConnection:
        def __init__(self) -> None:
            self.apply_cursor = ApplyCursor()

        def cursor(self):
            return self.apply_cursor

    connection = ApplyConnection()
    protocol = protocol_with_changes(1)
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: connection,
    )
    ops._protocol_baseline_family = protocol.family_slug
    ops._protocol_baseline_rubric = baseline_rubric
    ops._verify_bound_old_row = lambda *_args: None
    ops._get_or_create_source = lambda *_args: "source-id"
    ops._selected_change_old_values[protocol.family_slug] = {
        ops._factor_key(change): change.old_value
        for change in protocol.changes
    }

    ops.apply_protocol(protocol)

    statements = [sql for sql, _params in connection.apply_cursor.calls]
    assert any("INSERT INTO factor_scores" in sql for sql in statements)
    assert any(
        "SET is_current=false, superseded_by=%s" in sql for sql in statements
    )
    assert any(
        "UPDATE factor_scores SET is_current=true" in sql for sql in statements
    )
    assert any("UPDATE protocols SET last_refreshed" in sql for sql in statements)
    assert not any("DELETE FROM factor_scores" in sql for sql in statements)


def test_no_change_apply_updates_only_last_refreshed(tmp_path: Path) -> None:
    class Cursor:
        rowcount = 1

        def __init__(self) -> None:
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            self.calls.append((sql, params))

    class Connection:
        def __init__(self) -> None:
            self.apply_cursor = Cursor()

        def cursor(self):
            return self.apply_cursor

    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    connection = Connection()
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        connect=lambda _url: connection,
    )
    ops._protocol_baseline_family = protocol.family_slug
    ops._protocol_baseline_rubric = "v1.7.0"

    ops.apply_protocol(protocol)

    assert len(connection.apply_cursor.calls) == 1
    assert "UPDATE protocols SET last_refreshed" in connection.apply_cursor.calls[0][0]


def test_process_runner_decodes_public_records_as_utf8(tmp_path: Path) -> None:
    result = _run(
        (
            __import__("sys").executable,
            "-c",
            "import sys; sys.stdout.buffer.write('public — evidence'.encode('utf-8'))",
        ),
        tmp_path,
    )
    assert result.stdout == "public — evidence"


def test_factory_requires_repository_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RISKDASHBOARD_REPOSITORY_ROOT", raising=False)
    with pytest.raises(ContractError, match="repository_root"):
        create_operations(batch(), {"database_url": "postgresql://x", "repository": "o/r", "base_branch": "main"})


def test_backup_is_atomic_private_and_idempotent(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    def runner(command, cwd):
        calls.append(tuple(command))
        if command[0] == "pg_dump":
            Path(command[command.index("--file") + 1]).write_bytes(b"custom")
    ops = ProductionOperations(batch(), "postgresql://x", tmp_path, "o/r", "main", (), (), backup_root=tmp_path / "backups", command_runner=runner)
    ops.verify_batch_backup(batch())
    backup = tmp_path / "backups" / "batch-unsafe.dump"
    assert backup.read_bytes() == b"custom"
    if __import__("os").name != "nt":
        assert backup.stat().st_mode & 0o077 == 0
    ops.verify_batch_backup(batch())
    assert [call[0] for call in calls].count("pg_dump") == 1
    assert [call[0] for call in calls].count("pg_restore") == 2


def test_backup_can_run_on_production_host_while_github_runs_locally(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    ops = ProductionOperations(
        batch(),
        "postgresql://tunnel",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        backup_ssh_host="riskdash-app",
        command_runner=lambda command, _cwd: calls.append(tuple(command)),
    )
    ops.verify_batch_backup(batch())
    assert len(calls) == 1
    command = calls[0]
    assert command[:3] == ("ssh", "-o", "BatchMode=yes")
    assert ("-o", "StrictHostKeyChecking=yes") == command[3:5]
    assert ("-o", "ConnectTimeout=10") == command[5:7]
    assert ("-o", "ServerAliveInterval=15") == command[7:9]
    assert ("-o", "ServerAliveCountMax=2") == command[9:11]
    assert command[11] == "riskdash-app"
    script = command[12]
    assert "readarray -d '' db_parts" in script
    assert 'export PGPASSWORD="${db_parts[3]}"' in script
    assert "pg_dump --format=custom" in script
    assert 'pg_dump --format=custom --file="$temp" "$DATABASE_URL"' not in script
    assert 'PGDATABASE="$db_url"' not in script
    assert "pg_restore --list" in script
    assert "/opt/riskdashboard/.backups/protocol-refresh/batch-unsafe.dump" in script
    assert "postgresql://tunnel" not in script


def test_backup_ssh_host_rejects_option_injection(tmp_path: Path) -> None:
    ops = ProductionOperations(
        batch(),
        "postgresql://tunnel",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        backup_ssh_host="-oProxyCommand=bad",
        command_runner=lambda *_: None,
    )
    with pytest.raises(ContractError, match="backup_ssh_host"):
        ops.verify_batch_backup(batch())


def test_public_record_refuses_local_paths(tmp_path: Path) -> None:
    ops = ProductionOperations(batch(), "postgresql://x", tmp_path, "o/r", "main", (), (), command_runner=lambda *_: None)
    # The adapter's path guard is intentionally public-artifact specific; no network call occurs here.
    protocol = type(
        "P",
        (),
        {"family_slug": "aave-v3", "last_refreshed": "2026-07-22"},
    )()
    assert ops._branch(protocol) == "refresh/aave-v3/2026-07-23"
    body = ops._pull_request_body(protocol)
    assert "One topic: `aave-v3` only." in body
    assert "No direct factor-score or letter-grade edits." in body
    assert "No generated `data/api/` edits." in body
    assert not ops._contains_local_path(
        {
            "notes": "profile: verified",
            "url": "https://example.org/users/public/file.json",
        }
    )
    assert ops._contains_local_path({"notes": "see file:///tmp/private.json"})
    assert ops._contains_local_path({"notes": r"see C:\Users\private.json"})
    assert ops._contains_local_path(
        {"notes": r"see \\private-server\share\secret.json"}
    )
    assert ops._contains_local_path({"notes": r"see ..\private\secret.json"})
    assert ops._contains_local_path({"notes": "see ./private/secret.json"})
    assert ops._contains_local_path(
        {"notes": r"path=\\private-server\share\secret.json"}
    )
    assert ops._contains_local_path({"notes": r"path=..\private\secret.json"})
    assert ops._contains_local_path({"notes": "path:../private/secret.json"})
    assert ops._contains_local_path({"notes": "path=/etc/secret.conf"})
    assert ops._contains_local_path(
        {"notes": "https://example.org,local=/etc/secret.conf"}
    )
    for root in ("/etc/", "/var/", "/srv/", "/root/", "/mnt/", "/workspace/"):
        assert ops._contains_local_path({"notes": f"see {root}private.json"})


def test_factory_uses_builtin_resume_deploy_and_live_operations(tmp_path: Path) -> None:
    operations = create_operations(
        batch(),
        {
            "database_url": "postgresql://x",
            "repository_root": str(tmp_path),
            "repository": "o/r",
            "base_branch": "main",
        },
    )
    assert operations.deploy_command == ()
    assert operations.live_check_command == ()


def test_factory_accepts_remote_backup_host(tmp_path: Path) -> None:
    operations = create_operations(
        batch(),
        {
            "database_url": "postgresql://tunnel",
            "repository_root": str(tmp_path),
            "repository": "o/r",
            "base_branch": "main",
            "backup_ssh_host": "riskdash-app",
        },
    )
    assert operations.backup_ssh_host == "riskdash-app"


def test_semantic_tree_ignores_export_noise(tmp_path: Path) -> None:
    path = tmp_path / "api" / "v1.7.0"
    path.mkdir(parents=True)
    (path / "one.json").write_text('{"generated_at":"a","data_as_of":"b","status":"ok","data":{"x":1}}')
    (path / "status.json").write_text('{"data":{"run":"before"}}')
    nested_status = path / "protocols" / "maple" / "status.json"
    nested_status.parent.mkdir(parents=True)
    nested_status.write_text('{"data":{"protocol":"stable"}}')
    first = ProductionOperations._semantic_tree(tmp_path / "api")
    assert "v1.7.0/status.json" not in first
    assert "v1.7.0/protocols/maple/status.json" in first
    (path / "one.json").write_text('{"generated_at":"c","data_as_of":"d","status":"different","data":{"x":1}}')
    (path / "status.json").write_text('{"data":{"run":"after"}}')
    assert first == ProductionOperations._semantic_tree(tmp_path / "api")


def test_unrelated_output_error_never_exposes_protected_path(tmp_path: Path) -> None:
    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        command_runner=lambda *_: None,
    )
    protected = "v1.7.0/unpublished/other-private-token/index.json"
    ops._output_before = {protected: '{"before":true}'}
    ops._conn = object()
    ops._dump_workspace = __import__("tempfile").TemporaryDirectory()
    root = Path(ops._dump_workspace.name) / "after" / "api"
    target = root / protected
    target.parent.mkdir(parents=True)
    target.write_text('{"after":true}', encoding="utf-8")
    ops._verify_target_semantics = lambda _protocol: None
    ops._verify_dumped_target = lambda _protocol, _root: None

    import compose
    import dump

    original_compose = compose.run
    original_dump = dump.run_dump
    compose.run = lambda *_args, **_kwargs: 0
    dump.run_dump = lambda *_args, **_kwargs: None
    try:
        with pytest.raises(ContractError) as caught:
            ops.compare_target_output(
                ProtocolRefresh(
                    "maple",
                    ("default",),
                    (),
                    "no_change",
                    "2026-07-23",
                    "A",
                    "v1.7.0",
                    (),
                    "A",
                )
            )
    finally:
        compose.run = original_compose
        dump.run_dump = original_dump
        ops._close_dump_workspace()
    assert str(caught.value) == "pipeline changed unrelated semantic output"
    assert "private-token" not in str(caught.value)


def test_no_change_live_document_requires_184_rows_and_freshness() -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "maple",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "A",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": [
                    {"factor_id": f"RD-F-{index:03d}"}
                    for index in range(1, 186)
                    if index != 169
                ],
            }
        }
    }
    ProductionOperations._verify_protocol_document(protocol, payload)
    payload["data"]["protocol_data"]["protocol"]["last_refreshed"] = "2026-07-22"
    with pytest.raises(ContractError, match="metadata"):
        ProductionOperations._verify_protocol_document(protocol, payload)


def test_changed_live_document_preserves_every_unchanged_row() -> None:
    protocol = protocol_with_changes(1)
    expected_change = protocol.changes[0].new_value
    changed_row = {
        "factor_id": expected_change["factor_id"],
        "deployment_id": None,
        "score": expected_change["score"],
        "evidence_summary": expected_change.get("evidence_summary"),
        "evidence_detail": expected_change.get("evidence_detail"),
        "collection_mode": expected_change.get("collection_mode"),
        "collected_at": "2026-07-24T00:00:00Z",
        "data_as_of": "2026-07-23T00:00:00Z",
        "collected_by": "lean-protocol-refresh",
        "gap_reason": expected_change.get("gap_reason"),
        "sources": expected_change["sources"],
    }
    baseline_rows = {
        factor_id: {
            "factor_id": factor_id,
            "score": "yellow",
            "evidence_summary": f"baseline {factor_id}",
            "sources": [{"url": f"https://example.org/baseline/{factor_id}"}],
        }
        for factor_id in CANONICAL_FACTOR_IDS
    }
    baseline_snapshot = {
        factor_id: ProductionOperations._semantic_factor_row(row)
        for factor_id, row in baseline_rows.items()
    }
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "falcon",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "B",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": [
                    (
                        changed_row
                        if factor_id == protocol.changes[0].factor_id
                        else baseline_rows[factor_id]
                    )
                    for factor_id in sorted(CANONICAL_FACTOR_IDS)
                ],
            }
        }
    }
    ProductionOperations._verify_protocol_document(
        protocol,
        payload,
        unchanged_rows_before=baseline_snapshot,
    )
    unchanged = next(
        row
        for row in payload["data"]["protocol_data"]["factor_scores"]
        if row["factor_id"] != protocol.changes[0].factor_id
    )
    unchanged["score"] = "red"
    with pytest.raises(ContractError, match="changed unapproved row"):
        ProductionOperations._verify_protocol_document(
            protocol,
            payload,
            unchanged_rows_before=baseline_snapshot,
        )
    unchanged["score"] = "yellow"
    changed_row["data_as_of"] = "2026-07-22T00:00:00Z"
    with pytest.raises(ContractError, match="freshness differs"):
        ProductionOperations._verify_protocol_document(
            protocol,
            payload,
            unchanged_rows_before=baseline_snapshot,
        )
    changed_row["data_as_of"] = "2026-07-23T00:00:00Z"
    changed_row["notes"] = "unexpected public field"
    with pytest.raises(ContractError, match="fields differ"):
        ProductionOperations._verify_protocol_document(
            protocol,
            payload,
            unchanged_rows_before=baseline_snapshot,
        )
    changed_row.pop("notes")
    payload["data"]["protocol_data"]["factor_scores"].pop()
    with pytest.raises(ContractError, match="complete factor pass"):
        ProductionOperations._verify_protocol_document(
            protocol,
            payload,
            unchanged_rows_before=baseline_snapshot,
        )


def test_mixed_output_allows_verified_reused_v17_row_metadata() -> None:
    protocol = protocol_with_mixed_recovery(changed=False)
    assert protocol.mixed_recovery is not None
    reused = set(sorted(CANONICAL_FACTOR_IDS)[:4])
    rows = []
    for target in protocol.mixed_recovery.full_target_projection:
        expected = target.new_value
        rows.append(
            {
                "factor_id": target.factor_id,
                "deployment_id": None,
                "score": expected["score"],
                "evidence_summary": expected.get("evidence_summary"),
                "evidence_detail": expected.get("evidence_detail"),
                "collection_mode": expected.get("collection_mode"),
                "collected_at": "2026-06-01T00:00:00Z",
                "data_as_of": (
                    "2026-06-01T00:00:00Z"
                    if target.factor_id in reused
                    else "2026-07-23T00:00:00Z"
                ),
                "collected_by": (
                    "factual-correction"
                    if target.factor_id in reused
                    else "lean-protocol-refresh"
                ),
                "gap_reason": expected.get("gap_reason"),
                "sources": expected["sources"],
            }
        )
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "falcon",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "B",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": rows,
            }
        }
    }
    ProductionOperations._verify_protocol_document(
        protocol,
        payload,
        written_factor_ids=set(CANONICAL_FACTOR_IDS) - reused,
    )
    written = next(row for row in rows if row["factor_id"] not in reused)
    written["collected_by"] = "unexpected"
    with pytest.raises(ContractError, match="collector differs"):
        ProductionOperations._verify_protocol_document(
            protocol,
            payload,
            written_factor_ids=set(CANONICAL_FACTOR_IDS) - reused,
        )


def test_protocol_document_rejects_wrong_184_factor_universe() -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    factor_ids = sorted(CANONICAL_FACTOR_IDS)
    factor_ids[-1] = "RD-F-999"
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "maple",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "A",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": [
                    {"factor_id": factor_id} for factor_id in factor_ids
                ],
            }
        }
    }
    with pytest.raises(ContractError, match="factor IDs differ"):
        ProductionOperations._verify_protocol_document(protocol, payload)


def test_unpublished_target_uses_protected_route_without_exposing_token(
    tmp_path: Path,
) -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    payload = {
        "data": {
            "protocol_data": {
                "protocol": {
                    "slug": "maple",
                    "rubric_version": "v1.7.0",
                    "headline_grade": "A",
                    "last_refreshed": "2026-07-23",
                },
                "deployments": [],
                "factor_scores": [
                    {"factor_id": factor_id}
                    for factor_id in sorted(CANONICAL_FACTOR_IDS)
                ],
            }
        }
    }

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql, _params):
            return None

        def fetchone(self):
            return (False, "private-token")

    class Connection:
        def cursor(self):
            return Cursor()

        def rollback(self):
            return None

    ops = ProductionOperations(
        batch(),
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        (),
        (),
        connect=lambda _url: Connection(),
    )
    path = (
        tmp_path
        / "api"
        / "v1.7.0"
        / "unpublished"
        / "maple-private-token"
        / "index.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    ops._verify_dumped_target(protocol, tmp_path / "api")

    seen: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(payload).encode()

    def urlopen(request_url, **_kwargs):
        seen.append(request_url)
        if "/protocols/" in request_url:
            raise __import__("urllib").error.HTTPError(
                request_url, 404, "not found", None, None
            )
        return Response()

    ops.urlopen = urlopen
    assert ops._fetch_live_payload(protocol) == payload
    assert seen == [
        "https://defirisk.co/api/v1.7.0/protocols/maple.json",
        "https://defirisk.co/api/v1.7.0/unpublished/"
        "maple-private-token/index.json"
    ]


def test_source_identity_collision_reuses_one_row_without_global_metadata_write() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls = []
            self.rows = [None, ("source-id",), ("source-id",)]

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return self.rows.pop(0)

    cursor = Cursor()
    first = {
        "source_type": "docs",
        "url": "https://example.org/shared",
        "reference": "Shared source",
        "title": "First title",
        "retrieved_at": "2026-07-22",
    }
    second = {**first, "title": "Different per-factor title", "retrieved_at": "2026-07-23"}
    assert ProductionOperations._get_or_create_source(cursor, first, "2026-07-23") == "source-id"
    assert ProductionOperations._get_or_create_source(cursor, second, "2026-07-23") == "source-id"
    statements = [sql for sql, _params in cursor.calls]
    assert sum("INSERT INTO sources" in sql for sql in statements) == 1
    assert sum("UPDATE sources" in sql for sql in statements) == 0


def test_remote_branch_without_pr_resumes_by_creating_pr(tmp_path: Path) -> None:
    change = FactorChange(
        "RD-F-001",
        "surface",
        "default",
        {"factor_id": "RD-F-001", "score": "yellow", "sources": []},
        {
            "factor_id": "RD-F-001",
            "score": "green",
            "sources": [{"url": "https://example.org/new"}],
        },
        (Evidence("https://example.org/new"),),
        "green",
        "B",
    )
    protocol = ProtocolRefresh(
        "falcon",
        ("default",),
        (),
        "changed",
        "2026-07-23",
        "B",
        "v1.7.0",
        (change,),
        "C",
    )
    refresh_batch = RefreshBatch(
        "batch-2", "2026-07-23", "v1.7.0", (protocol,)
    )
    calls = []
    holder = {}

    def runner(command, cwd):
        command = tuple(command)
        calls.append(command)
        if command[:3] == ("gh", "pr", "view"):
            raise subprocess.CalledProcessError(1, command)
        if command[:3] == ("git", "ls-remote", "--exit-code"):
            return SimpleNamespace(stdout="abc refs/heads/branch\n")
        if command[:2] == ("git", "show"):
            record = holder["ops"]._public_record(protocol)
            return SimpleNamespace(
                stdout=json.dumps(
                    record,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
        if command[:3] == ("git", "diff", "--name-only"):
            return SimpleNamespace(
                stdout="docs/ops/protocol-refresh/change-records/"
                "2026-07-23-falcon.json\n"
            )
        return SimpleNamespace(stdout="")

    ops = ProductionOperations(
        refresh_batch,
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        command_runner=runner,
    )
    holder["ops"] = ops
    ops._selected_change_old_values[protocol.family_slug] = {
        ops._factor_key(change): change.old_value
    }
    ops.ensure_protocol_pull_request(protocol)
    create = next(command for command in calls if command[:3] == ("gh", "pr", "create"))
    assert "--body" in create
    assert "--fill" not in create
    assert "One topic: `falcon` only." in create[create.index("--body") + 1]
    assert not any(command[:2] == ("git", "push") for command in calls)


def test_generated_publication_push_bypasses_unrelated_local_hook(
    tmp_path: Path,
) -> None:
    source = Path(__file__).parents[2]
    production_source = (
        source / "scripts" / "lean_protocol_refresh" / "production.py"
    ).read_text(encoding="utf-8")
    assert '("git", "push", "--no-verify", "-u", "origin", branch)' in production_source


def test_docs_only_or_no_change_batch_dispatches_once_without_new_run_name(
    tmp_path: Path,
) -> None:
    protocol = ProtocolRefresh(
        "maple",
        ("default",),
        (),
        "no_change",
        "2026-07-23",
        "A",
        "v1.7.0",
        (),
        "A",
    )
    refresh_batch = RefreshBatch(
        "later-batch", "2026-07-23", "v1.7.0", (protocol,)
    )
    calls = []
    dispatched = False
    clock = iter((0, 0, 1, 50, 60, 70, 80))

    def runner(command, cwd):
        nonlocal dispatched
        command = tuple(command)
        calls.append(command)
        if command[:4] == ("gh", "api", "--method", "GET"):
            endpoint = command[4]
            if "/commits/" in endpoint:
                return SimpleNamespace(stdout='{"sha":"main-sha"}')
            event = next(
                (
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("event=")
                ),
                "",
            )
            if event == "workflow_dispatch" and dispatched:
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "workflow_runs": [
                                {
                                    "id": 22,
                                    "head_sha": "main-sha",
                                    "display_title": "Deploy to VPS",
                                    "event": "workflow_dispatch",
                                    "status": "completed",
                                    "conclusion": "success",
                                }
                            ]
                        }
                    )
                )
            return SimpleNamespace(stdout='{"workflow_runs":[]}')
        if command[:3] == ("gh", "workflow", "run"):
            dispatched = True
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="")

    def no_live(*_args, **_kwargs):
        raise OSError("not deployed")

    ops = ProductionOperations(
        refresh_batch,
        "postgresql://x",
        tmp_path,
        "o/r",
        "main",
        command_runner=runner,
        urlopen=no_live,
        sleeper=lambda _seconds: None,
        monotonic=lambda: next(clock),
    )
    ops.deploy_batch(refresh_batch, (protocol,))
    dispatches = [
        command for command in calls if command[:3] == ("gh", "workflow", "run")
    ]
    assert len(dispatches) == 1
    assert "reason=later-batch" in dispatches[0]
