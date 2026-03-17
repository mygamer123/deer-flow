from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.diagnostic_service import DiagnosticService
from src.trading_research.models import (
    AggregatePattern,
    Claim,
    ClaimStatus,
    ExecutionQuality,
    ExtractionQuality,
    ImprovementDirection,
    OpportunityQuality,
    OverallGrade,
    PrimaryFailureReason,
    StrategyActionCandidate,
    StrategyActionStatus,
    StrategyActionType,
    StrategyChangeRecord,
    StrategyImprovementLoopResult,
    TradeDiagnosticResult,
    WorkflowKind,
)
from src.trading_research.report_service import build_strategy_improvement_markdown
from src.trading_research.strategy_improvement_service import (
    MIN_CANDIDATE_SAMPLE_SIZE,
    MIN_PATTERN_COUNT,
    MIN_VERIFIED_SAMPLE_SIZE,
    StrategyImprovementRequest,
    StrategyImprovementService,
)


def _make_saved_review(
    *,
    result_id: str,
    symbol: str = "AMPX",
    trading_date: str = "2026-03-05",
    pattern: str = "strong_uptrending",
    overall_verdict: str = "good_trade",
    quality_tier: str = "GOOD",
    outcome: str = "tp_filled",
    log_source: str = "prod",
    boundary_time: str | None = None,
    claims: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if claims is None:
        claims = [
            {
                "claim_id": f"claim_selection_{result_id}",
                "statement": "The trade should have been taken based on strong signal score.",
                "status": "observation",
                "evidence_ids": [f"ev_{result_id}_sel"],
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": f"claim_entry_{result_id}",
                "statement": "Entry timing was acceptable.",
                "status": "observation",
                "evidence_ids": [f"ev_{result_id}_ent"],
                "confidence": 0.7,
                "sample_size": 1,
            },
            {
                "claim_id": f"claim_exit_{result_id}",
                "statement": "Evidence favors `trailing_stop` exit policy.",
                "status": "observation",
                "evidence_ids": [f"ev_{result_id}_ext"],
                "confidence": 0.75,
                "sample_size": 1,
            },
        ]
    return {
        "result_id": result_id,
        "workflow": "trade_review",
        "title": f"Trade Review: {symbol}",
        "subject": f"{symbol} {trading_date}",
        "as_of": "2026-03-05T10:00:00",
        "symbol": symbol,
        "trading_date": trading_date,
        "log_source": log_source,
        "boundary_time": boundary_time or "2026-03-05T10:00:00",
        "metadata": {
            "pattern": pattern,
            "overall_verdict": overall_verdict,
            "quality_tier": quality_tier,
            "outcome": outcome,
            "total_iterations": 1,
        },
        "findings": [],
        "claims": claims,
        "recommendations": [],
        "evidence_ids": [f"ev_{result_id}_sel", f"ev_{result_id}_ent", f"ev_{result_id}_ext"],
        "limitations": [],
    }


def _populate_store(tmp_path: Path, reviews: list[dict[str, object]]) -> None:
    for review in reviews:
        filename = f"trade_review_{review['result_id']}.json"
        with open(tmp_path / filename, "w", encoding="utf-8") as f:
            json.dump(review, f)


# ---------------------------------------------------------------------------
# A. Single-trade diagnostic decomposition
# ---------------------------------------------------------------------------


def test_good_trade_gets_high_grades() -> None:
    review = _make_saved_review(
        result_id="r1",
        overall_verdict="good_trade",
        quality_tier="EXCELLENT",
        outcome="tp_filled",
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.VALID
    assert diag.execution_quality == ExecutionQuality.EXCELLENT
    assert diag.extraction_quality == ExtractionQuality.FULLY_EXTRACTED
    assert diag.overall_grade == OverallGrade.A


def test_dimensions_are_independent_invalid_but_profitable() -> None:
    review = _make_saved_review(
        result_id="r2",
        overall_verdict="good_trade",
        quality_tier="EXCELLENT",
        outcome="tp_filled",
        claims=[
            {
                "claim_id": "claim_selection_r2",
                "statement": "The trade should have been skipped due to weak setup.",
                "confidence": 0.9,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_r2",
                "statement": "Entry timing was acceptable.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_r2",
                "statement": "Evidence favors `trailing_stop` exit policy.",
                "confidence": 0.75,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.INVALID
    assert diag.execution_quality == ExecutionQuality.EXCELLENT
    assert diag.extraction_quality == ExtractionQuality.FULLY_EXTRACTED


def test_valid_but_unprofitable() -> None:
    review = _make_saved_review(
        result_id="r3",
        overall_verdict="bad_trade",
        quality_tier="POOR",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_r3",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_r3",
                "statement": "Entry was suboptimal — waited too long.",
                "confidence": 0.6,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_r3",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.VALID
    assert diag.execution_quality == ExecutionQuality.POOR
    assert diag.extraction_quality == ExtractionQuality.POORLY_EXTRACTED


def test_missing_claims_produce_honest_defaults() -> None:
    review = _make_saved_review(result_id="r4", claims=[])
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.MARGINAL
    assert diag.execution_quality == ExecutionQuality.POOR
    assert diag.extraction_quality == ExtractionQuality.FULLY_EXTRACTED


def test_missing_result_id_returns_none() -> None:
    review = _make_saved_review(result_id="")
    review["result_id"] = ""
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is None


def test_grade_computation_a_through_e() -> None:
    svc = DiagnosticService()

    grade_a = _make_saved_review(
        result_id="ga",
        overall_verdict="good_trade",
        quality_tier="EXCELLENT",
        outcome="tp_filled",
    )
    assert svc.diagnose_trade(grade_a) is not None
    assert svc.diagnose_trade(grade_a).overall_grade == OverallGrade.A

    grade_d = _make_saved_review(
        result_id="gd",
        overall_verdict="bad_trade",
        quality_tier="EXCELLENT",
        outcome="tp_filled",
        claims=[
            {
                "claim_id": "claim_selection_gd",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_gd",
                "statement": "Entry timing was acceptable.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_gd",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag_d = svc.diagnose_trade(grade_d)
    assert diag_d is not None
    assert diag_d.extraction_quality == ExtractionQuality.POORLY_EXTRACTED
    assert diag_d.overall_grade in (OverallGrade.C, OverallGrade.D)


def test_diagnose_many() -> None:
    reviews = [_make_saved_review(result_id=f"m{i}") for i in range(3)]
    results = DiagnosticService().diagnose_many(reviews)
    assert len(results) == 3
    for r in results:
        assert isinstance(r, TradeDiagnosticResult)


# ---------------------------------------------------------------------------
# B. Failure/improvement diagnostics
# ---------------------------------------------------------------------------


def test_avoid_point_for_invalid_opportunity() -> None:
    review = _make_saved_review(
        result_id="av1",
        claims=[
            {
                "claim_id": "claim_selection_av1",
                "statement": "The trade should have been skipped.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.earliest_avoid_point == "pre_trade_selection"


def test_minimize_loss_point_for_poor_extraction() -> None:
    review = _make_saved_review(
        result_id="ml1",
        overall_verdict="bad_trade",
        quality_tier="GOOD",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_ml1",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_ml1",
                "statement": "Entry timing was acceptable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_ml1",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.earliest_minimize_loss_point == "exit_management"


def test_action_type_enum_enforcement() -> None:
    review = _make_saved_review(result_id="at1")
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert isinstance(diag.strategy_action_type, StrategyActionType)
    assert diag.strategy_action_type.value in [e.value for e in StrategyActionType]


def test_failure_reason_matches_worst_dimensions() -> None:
    review = _make_saved_review(
        result_id="fr1",
        overall_verdict="bad_trade",
        quality_tier="POOR",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_fr1",
                "statement": "The trade should have been skipped.",
                "confidence": 0.9,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_fr1",
                "statement": "Entry was suboptimal — waited too long.",
                "confidence": 0.5,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_fr1",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.primary_failure_reason == PrimaryFailureReason.BAD_OPPORTUNITY_AND_EXECUTION
    assert diag.overall_grade == OverallGrade.E


# ---------------------------------------------------------------------------
# C. Aggregate pattern extraction
# ---------------------------------------------------------------------------


def test_repeated_failures_form_patterns() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"pf{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_pf{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
                {
                    "claim_id": f"claim_entry_pf{i}",
                    "statement": "Entry was suboptimal — waited too long.",
                    "confidence": 0.5,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(3)
    ]

    svc = StrategyImprovementService()
    diagnostics = DiagnosticService().diagnose_many(reviews)
    patterns = svc.extract_patterns(diagnostics)
    assert len(patterns) > 0
    for p in patterns:
        assert isinstance(p, AggregatePattern)
        assert p.count >= MIN_PATTERN_COUNT
        assert p.sample_size == len(p.distinct_trade_ids)


def test_single_trade_does_not_produce_patterns() -> None:
    reviews = [_make_saved_review(result_id="sp1")]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    patterns = StrategyImprovementService().extract_patterns(diagnostics)
    assert len(patterns) == 0


def test_pattern_sample_size_is_distinct_trades() -> None:
    reviews = [
        _make_saved_review(
            result_id="ds1",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": "claim_selection_ds1",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        ),
        _make_saved_review(
            result_id="ds2",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": "claim_selection_ds2",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        ),
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    patterns = StrategyImprovementService().extract_patterns(diagnostics)
    for p in patterns:
        unique_ids = set(p.distinct_trade_ids)
        assert len(unique_ids) == p.sample_size


# ---------------------------------------------------------------------------
# D. Strategy action candidate gating
# ---------------------------------------------------------------------------


def test_candidates_from_aggregate_patterns_only() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"cg{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_cg{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(2)
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    candidates = svc.generate_candidates(patterns, datetime.now())
    assert len(candidates) > 0
    for c in candidates:
        assert isinstance(c, StrategyActionCandidate)
        assert c.sample_size >= MIN_CANDIDATE_SAMPLE_SIZE
        assert len(c.supported_by_pattern_ids) > 0


def test_single_trade_cannot_produce_min_met_candidate() -> None:
    reviews = [
        _make_saved_review(
            result_id="sc1",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": "claim_selection_sc1",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        )
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    candidates = svc.generate_candidates(patterns)
    assert len(candidates) == 0


def test_verified_candidate_requires_three_trades() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"vc{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_vc{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(3)
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    verified_claims = [
        Claim(
            claim_id="agg_claim_selection_strong_uptrending",
            statement="Selection pattern observed across cohort",
            status=ClaimStatus.SUPPORTED,
            sample_size=3,
            confidence=0.8,
        ),
    ]
    candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
    verified = [c for c in candidates if c.status == StrategyActionStatus.VERIFIED_CANDIDATE]
    assert len(verified) > 0
    for v in verified:
        assert v.sample_size >= MIN_VERIFIED_SAMPLE_SIZE
        assert v.minimum_sample_size_met is True
        assert len(v.supported_by_claim_ids) > 0


def test_proposed_status_for_two_trades() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"ps{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_ps{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(2)
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    candidates = svc.generate_candidates(patterns)
    for c in candidates:
        assert c.status == StrategyActionStatus.PROPOSED
        assert c.sample_size < MIN_VERIFIED_SAMPLE_SIZE


# ---------------------------------------------------------------------------
# E. Report output
# ---------------------------------------------------------------------------


def test_report_renders_all_sections() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"rr{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_rr{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(3)
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    candidates = svc.generate_candidates(patterns)
    now = datetime.now()

    result = StrategyImprovementLoopResult(
        result_id="test_report",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Test Report",
        as_of=now,
        diagnostics=diagnostics,
        patterns=patterns,
        candidates=candidates,
        trade_count=len(diagnostics),
        pattern_count=len(patterns),
        candidate_count=len(candidates),
        limitations=["Test limitation."],
    )

    md = build_strategy_improvement_markdown(result)
    assert "## Trade Diagnostics" in md
    assert "## Aggregate Patterns" in md
    assert "## Strategy Action Candidates" in md
    assert "## Limitations" in md
    assert "Test limitation." in md


def test_report_renders_empty_sections_gracefully() -> None:
    now = datetime.now()
    result = StrategyImprovementLoopResult(
        result_id="empty_report",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Empty Report",
        as_of=now,
        trade_count=0,
        pattern_count=0,
        candidate_count=0,
    )

    md = build_strategy_improvement_markdown(result)
    assert "No diagnostics were produced." in md
    assert "No recurring patterns were extracted." in md
    assert "No strategy action candidates were produced." in md


# ---------------------------------------------------------------------------
# F. End-to-end flow through the service
# ---------------------------------------------------------------------------


def test_end_to_end_loop(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    reviews = [
        _make_saved_review(
            result_id=f"e2e{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_e2e{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
                {
                    "claim_id": f"claim_entry_e2e{i}",
                    "statement": "Entry was suboptimal — waited too long.",
                    "confidence": 0.5,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(3)
    ]
    _populate_store(store_dir, reviews)

    with patch("src.trading_research.store._RESULTS_DIR", store_dir):
        svc = StrategyImprovementService()
        result = svc.run_loop(StrategyImprovementRequest())

    assert isinstance(result, StrategyImprovementLoopResult)
    assert result.workflow == WorkflowKind.STRATEGY_IMPROVEMENT
    assert result.trade_count == 3
    assert len(result.diagnostics) == 3
    assert result.pattern_count > 0
    assert len(result.patterns) > 0

    md = build_strategy_improvement_markdown(result)
    assert "## Trade Diagnostics" in md
    assert "## Aggregate Patterns" in md


def test_end_to_end_loop_with_filters(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    reviews = [
        _make_saved_review(result_id="f1", symbol="AAPL", trading_date="2026-03-01"),
        _make_saved_review(result_id="f2", symbol="MSFT", trading_date="2026-03-02"),
        _make_saved_review(result_id="f3", symbol="AAPL", trading_date="2026-03-03"),
    ]
    _populate_store(store_dir, reviews)

    with patch("src.trading_research.store._RESULTS_DIR", store_dir):
        svc = StrategyImprovementService()
        result = svc.run_loop(StrategyImprovementRequest(symbol="AAPL"))

    assert result.trade_count == 2
    for diag in result.diagnostics:
        assert diag.symbol == "AAPL"


# ---------------------------------------------------------------------------
# G. Claim-backed candidates (P3.1)
# ---------------------------------------------------------------------------


def test_candidates_with_claims_get_claim_ids_populated() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"cb{i}",
            overall_verdict="acceptable",
            quality_tier="POOR",
            outcome="manual_exit",
            claims=[
                {
                    "claim_id": f"claim_selection_cb{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
                {
                    "claim_id": f"claim_entry_cb{i}",
                    "statement": "Entry timing was acceptable.",
                    "confidence": 0.7,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(3)
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    verified_claims = [
        Claim(
            claim_id="agg_claim_selection_strong_uptrending",
            statement="Selection claim",
            status=ClaimStatus.SUPPORTED,
            sample_size=3,
            confidence=0.8,
        ),
    ]
    candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
    selection_candidates = [c for c in candidates if c.action_type == StrategyActionType.ADD_PRETRADE_FILTER]
    assert len(selection_candidates) > 0
    for c in selection_candidates:
        assert "agg_claim_selection_strong_uptrending" in c.supported_by_claim_ids


def test_candidates_without_claims_downgraded() -> None:
    reviews = [
        _make_saved_review(
            result_id=f"nd{i}",
            overall_verdict="bad_trade",
            quality_tier="POOR",
            outcome="stopped_out",
            claims=[
                {
                    "claim_id": f"claim_selection_nd{i}",
                    "statement": "The trade should have been skipped.",
                    "confidence": 0.9,
                    "sample_size": 1,
                },
            ],
        )
        for i in range(3)
    ]
    diagnostics = DiagnosticService().diagnose_many(reviews)
    svc = StrategyImprovementService()
    patterns = svc.extract_patterns(diagnostics)
    candidates = svc.generate_candidates(patterns, verified_claims=[])
    for c in candidates:
        assert c.status != StrategyActionStatus.VERIFIED_CANDIDATE


def test_collect_more_samples_not_downgraded_without_claims() -> None:
    patterns = [
        AggregatePattern(
            pattern_id="pattern_action_type_collect_more_samples",
            pattern_type="action_type",
            value="collect_more_samples",
            count=3,
            distinct_trade_ids=["t1", "t2", "t3"],
            sample_size=3,
            frequency_pct=1.0,
        ),
    ]
    svc = StrategyImprovementService()
    candidates = svc.generate_candidates(patterns, verified_claims=[])
    collect_candidates = [c for c in candidates if c.action_type == StrategyActionType.COLLECT_MORE_SAMPLES]
    assert len(collect_candidates) > 0
    for c in collect_candidates:
        assert c.status == StrategyActionStatus.VERIFIED_CANDIDATE


def test_tighten_risk_uses_any_surviving_claim() -> None:
    patterns = [
        AggregatePattern(
            pattern_id="pattern_failure_reason_bad_opportunity_and_execution",
            pattern_type="failure_reason",
            value="bad_opportunity_and_execution",
            count=3,
            distinct_trade_ids=["t1", "t2", "t3"],
            sample_size=3,
            frequency_pct=1.0,
        ),
    ]
    verified_claims = [
        Claim(
            claim_id="agg_claim_entry_strong_uptrending",
            statement="Entry claim",
            status=ClaimStatus.SUPPORTED,
            sample_size=3,
        ),
    ]
    svc = StrategyImprovementService()
    candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
    risk_candidates = [c for c in candidates if c.action_type == StrategyActionType.TIGHTEN_RISK_RULE]
    assert len(risk_candidates) > 0
    for c in risk_candidates:
        assert c.status == StrategyActionStatus.VERIFIED_CANDIDATE
        assert "agg_claim_entry_strong_uptrending" in c.supported_by_claim_ids


# ---------------------------------------------------------------------------
# H. Metadata-first diagnostics (P3.1)
# ---------------------------------------------------------------------------


def test_opportunity_quality_from_metadata_should_trade() -> None:
    review = _make_saved_review(
        result_id="mop1",
        claims=[
            {
                "claim_id": "claim_selection_mop1",
                "statement": "Ambiguous statement without substring.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.VALID


def test_opportunity_quality_from_metadata_should_not_trade() -> None:
    review = _make_saved_review(
        result_id="mop2",
        claims=[
            {
                "claim_id": "claim_selection_mop2",
                "statement": "Ambiguous statement without substring.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": False},
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.INVALID


def test_opportunity_quality_falls_back_to_substring() -> None:
    review = _make_saved_review(
        result_id="mop3",
        claims=[
            {
                "claim_id": "claim_selection_mop3",
                "statement": "The trade should have been taken based on strong signal.",
                "confidence": 0.8,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.VALID


def test_execution_quality_from_metadata_rating() -> None:
    review = _make_saved_review(
        result_id="mex1",
        quality_tier="POOR",
        claims=[
            {
                "claim_id": "claim_selection_mex1",
                "statement": "The trade should have been taken.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_mex1",
                "statement": "Ambiguous entry statement.",
                "confidence": 0.7,
                "sample_size": 1,
                "metadata": {"execution_rating": "suboptimal"},
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.execution_quality == ExecutionQuality.POOR


def test_execution_quality_from_metadata_optimal() -> None:
    review = _make_saved_review(
        result_id="mex2",
        claims=[
            {
                "claim_id": "claim_selection_mex2",
                "statement": "The trade should have been taken.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_mex2",
                "statement": "Ambiguous entry statement.",
                "confidence": 0.7,
                "sample_size": 1,
                "metadata": {"execution_rating": "optimal"},
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.execution_quality == ExecutionQuality.EXCELLENT


def test_execution_quality_falls_back_to_substring() -> None:
    review = _make_saved_review(
        result_id="mex3",
        quality_tier="POOR",
        claims=[
            {
                "claim_id": "claim_selection_mex3",
                "statement": "The trade should have been taken.",
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_entry_mex3",
                "statement": "Entry was suboptimal — waited too long.",
                "confidence": 0.5,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.execution_quality == ExecutionQuality.POOR


# ---------------------------------------------------------------------------
# I. Strategy change records (P3.1)
# ---------------------------------------------------------------------------


def test_change_records_created_for_verified_candidates_only() -> None:
    patterns = [
        AggregatePattern(
            pattern_id="pattern_action_type_add_pretrade_filter",
            pattern_type="action_type",
            value="add_pretrade_filter",
            count=3,
            distinct_trade_ids=["t1", "t2", "t3"],
            sample_size=3,
            frequency_pct=1.0,
        ),
        AggregatePattern(
            pattern_id="pattern_action_type_refine_entry_rule",
            pattern_type="action_type",
            value="refine_entry_rule",
            count=2,
            distinct_trade_ids=["t1", "t2"],
            sample_size=2,
            frequency_pct=0.67,
        ),
    ]
    verified_claims = [
        Claim(
            claim_id="agg_claim_selection_strong_uptrending",
            statement="Selection claim",
            status=ClaimStatus.SUPPORTED,
            sample_size=3,
        ),
    ]
    svc = StrategyImprovementService()
    candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
    now = datetime.now()
    records = svc._create_change_records(candidates, "loop_test", 3, now)
    verified_candidates = [c for c in candidates if c.status == StrategyActionStatus.VERIFIED_CANDIDATE]
    assert len(records) == len(verified_candidates)
    for record in records:
        assert isinstance(record, StrategyChangeRecord)
        assert record.candidate.status == StrategyActionStatus.VERIFIED_CANDIDATE
        assert record.source_loop_result_id == "loop_test"
        assert record.source_trade_count == 3


def test_change_records_saved_and_loaded(tmp_path: Path) -> None:
    from src.trading_research.store import list_strategy_change_records, load_strategy_change_record, save_strategy_change_records

    now = datetime.now()
    candidate = StrategyActionCandidate(
        action_id="candidate_add_pretrade_filter_test",
        action_type=StrategyActionType.ADD_PRETRADE_FILTER,
        rationale="Test rationale",
        supported_by_pattern_ids=["p1"],
        supported_by_trade_ids=["t1", "t2", "t3"],
        supported_by_claim_ids=["agg_claim_selection_test"],
        sample_size=3,
        minimum_sample_size_met=True,
        status=StrategyActionStatus.VERIFIED_CANDIDATE,
        as_of=now,
    )
    record = StrategyChangeRecord(
        record_id="change_test",
        candidate=candidate,
        created_at=now,
        source_loop_result_id="loop_test",
        source_trade_count=3,
    )

    with patch("src.trading_research.store._RESULTS_DIR", tmp_path):
        paths = save_strategy_change_records([record])
        assert len(paths) == 1
        assert paths[0].exists()

        filenames = list_strategy_change_records()
        assert len(filenames) == 1
        assert filenames[0].startswith("strategy_change_")

        loaded = load_strategy_change_record(filenames[0])
        assert loaded is not None
        assert loaded["record_id"] == "change_test"
        candidate_data = loaded["candidate"]
        assert isinstance(candidate_data, dict)
        assert candidate_data["action_id"] == "candidate_add_pretrade_filter_test"


# ---------------------------------------------------------------------------
# J. Report hardening (P3.1)
# ---------------------------------------------------------------------------


def test_report_includes_verified_claims_section() -> None:
    now = datetime.now()
    verified_claims = [
        Claim(
            claim_id="agg_claim_selection_test",
            statement="Test aggregate claim",
            status=ClaimStatus.SUPPORTED,
            sample_size=3,
            confidence=0.8,
        ),
    ]
    result = StrategyImprovementLoopResult(
        result_id="report_claims_test",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Test Report",
        as_of=now,
        verified_claims=verified_claims,
        trade_count=3,
        pattern_count=0,
        candidate_count=0,
    )
    md = build_strategy_improvement_markdown(result)
    assert "## Verified Aggregate Claims" in md
    assert "agg_claim_selection_test" in md
    assert "Test aggregate claim" in md


def test_report_includes_change_records_section() -> None:
    now = datetime.now()
    candidate = StrategyActionCandidate(
        action_id="candidate_test",
        action_type=StrategyActionType.ADD_PRETRADE_FILTER,
        rationale="Test",
        status=StrategyActionStatus.VERIFIED_CANDIDATE,
        sample_size=3,
        minimum_sample_size_met=True,
    )
    record = StrategyChangeRecord(
        record_id="change_candidate_test",
        candidate=candidate,
        created_at=now,
        source_loop_result_id="loop_test",
        source_trade_count=3,
    )
    result = StrategyImprovementLoopResult(
        result_id="report_records_test",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Test Report",
        as_of=now,
        change_records=[record],
        trade_count=3,
        pattern_count=0,
        candidate_count=0,
    )
    md = build_strategy_improvement_markdown(result)
    assert "## Strategy Change Records" in md
    assert "change_candidate_test" in md


def test_report_includes_claim_ids_in_candidates_table() -> None:
    now = datetime.now()
    candidate = StrategyActionCandidate(
        action_id="candidate_with_claims",
        action_type=StrategyActionType.ADD_PRETRADE_FILTER,
        rationale="Test rationale",
        supported_by_claim_ids=["agg_claim_selection_test"],
        sample_size=3,
        minimum_sample_size_met=True,
        status=StrategyActionStatus.VERIFIED_CANDIDATE,
    )
    result = StrategyImprovementLoopResult(
        result_id="report_claim_ids_test",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Test Report",
        as_of=now,
        candidates=[candidate],
        trade_count=3,
        pattern_count=0,
        candidate_count=1,
    )
    md = build_strategy_improvement_markdown(result)
    assert "agg_claim_selection_test" in md
    assert "Claim IDs" in md


def test_report_empty_sections_render_gracefully() -> None:
    now = datetime.now()
    result = StrategyImprovementLoopResult(
        result_id="empty_p31",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Empty P3.1 Report",
        as_of=now,
        trade_count=0,
        pattern_count=0,
        candidate_count=0,
    )
    md = build_strategy_improvement_markdown(result)
    assert "No verified aggregate claims were produced." in md
    assert "No strategy change records were produced." in md
    assert "No strategy action candidates were produced." in md


# ---------------------------------------------------------------------------
# P3.2: Action taxonomy refinement
# ---------------------------------------------------------------------------


def test_p32_taxonomy_all_values_serialize() -> None:
    expected = {
        "no_change",
        "add_pretrade_filter",
        "refine_entry_rule",
        "refine_entry_timing",
        "refine_stop_rule",
        "refine_exit_rule",
        "refine_exit_timing",
        "tighten_risk_rule",
        "collect_more_samples",
    }
    actual = {e.value for e in StrategyActionType}
    assert actual == expected


def test_p32_taxonomy_old_values_still_loadable() -> None:
    for old_value in ("tighten_risk_rule", "refine_entry_rule", "refine_exit_rule", "no_change", "add_pretrade_filter", "refine_stop_rule", "collect_more_samples"):
        member = StrategyActionType(old_value)
        assert member.value == old_value


def test_p32_taxonomy_new_values_loadable() -> None:
    assert StrategyActionType("refine_entry_timing") == StrategyActionType.REFINE_ENTRY_TIMING
    assert StrategyActionType("refine_exit_timing") == StrategyActionType.REFINE_EXIT_TIMING


def test_p32_grade_e_poor_execution_with_entry_timing_avoid_point() -> None:
    review = _make_saved_review(
        result_id="p32_et1",
        overall_verdict="acceptable",
        quality_tier="POOR",
        outcome="manual_exit",
        claims=[
            {
                "claim_id": "claim_selection_p32_et1",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.5,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
            {
                "claim_id": "claim_entry_p32_et1",
                "statement": "Entry was suboptimal — waited too long.",
                "confidence": 0.5,
                "sample_size": 1,
                "metadata": {"execution_rating": "poor"},
            },
            {
                "claim_id": "claim_exit_p32_et1",
                "statement": "Exit was acceptable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.execution_quality == ExecutionQuality.POOR
    assert diag.opportunity_quality == OpportunityQuality.MARGINAL
    assert diag.earliest_avoid_point == "entry_timing"
    assert diag.strategy_action_type == StrategyActionType.REFINE_ENTRY_TIMING


def test_p32_poor_execution_without_entry_timing_gets_entry_rule() -> None:
    review = _make_saved_review(
        result_id="p32_er1",
        overall_verdict="acceptable",
        quality_tier="POOR",
        outcome="manual_exit",
        claims=[
            {
                "claim_id": "claim_selection_p32_er1",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
            {
                "claim_id": "claim_entry_p32_er1",
                "statement": "Entry was suboptimal — waited too long.",
                "confidence": 0.5,
                "sample_size": 1,
                "metadata": {"execution_rating": "poor"},
            },
            {
                "claim_id": "claim_exit_p32_er1",
                "statement": "Exit was acceptable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.execution_quality == ExecutionQuality.POOR
    assert diag.extraction_quality != ExtractionQuality.POORLY_EXTRACTED
    assert diag.earliest_avoid_point is None
    assert diag.strategy_action_type == StrategyActionType.REFINE_ENTRY_RULE


def test_p32_poor_extraction_with_exit_management_gets_exit_timing() -> None:
    review = _make_saved_review(
        result_id="p32_ex1",
        overall_verdict="bad_trade",
        quality_tier="GOOD",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_p32_ex1",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
            {
                "claim_id": "claim_entry_p32_ex1",
                "statement": "Entry timing was acceptable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_p32_ex1",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.extraction_quality == ExtractionQuality.POORLY_EXTRACTED
    assert diag.earliest_minimize_loss_point == "exit_management"
    assert diag.strategy_action_type == StrategyActionType.REFINE_EXIT_TIMING


def test_p32_poor_extraction_without_exit_claim_gets_exit_rule() -> None:
    review = _make_saved_review(
        result_id="p32_ex2",
        overall_verdict="bad_trade",
        quality_tier="GOOD",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_p32_ex2",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
            {
                "claim_id": "claim_entry_p32_ex2",
                "statement": "Entry timing was acceptable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.extraction_quality == ExtractionQuality.POORLY_EXTRACTED
    assert diag.earliest_minimize_loss_point is None
    assert diag.strategy_action_type == StrategyActionType.REFINE_EXIT_RULE


def test_p32_invalid_opportunity_gets_pretrade_filter() -> None:
    review = _make_saved_review(
        result_id="p32_pf1",
        overall_verdict="bad_trade",
        quality_tier="POOR",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_p32_pf1",
                "statement": "The trade should have been skipped.",
                "confidence": 0.9,
                "sample_size": 1,
                "metadata": {"should_trade": False},
            },
            {
                "claim_id": "claim_entry_p32_pf1",
                "statement": "Entry was suboptimal.",
                "confidence": 0.5,
                "sample_size": 1,
                "metadata": {"execution_rating": "poor"},
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality == OpportunityQuality.INVALID
    assert diag.overall_grade == OverallGrade.E
    assert diag.strategy_action_type == StrategyActionType.ADD_PRETRADE_FILTER


def test_p32_both_poor_valid_opp_gets_exit_timing() -> None:
    """VALID opp + POOR exec + exit_claim → EXIT_DOMINANT → REFINE_EXIT_TIMING (P3.3)."""
    review = _make_saved_review(
        result_id="p32_sr1",
        overall_verdict="bad_trade",
        quality_tier="POOR",
        outcome="stopped_out",
        claims=[
            {
                "claim_id": "claim_selection_p32_sr1",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
            {
                "claim_id": "claim_entry_p32_sr1",
                "statement": "Entry was suboptimal — waited too long.",
                "confidence": 0.5,
                "sample_size": 1,
                "metadata": {"execution_rating": "poor"},
            },
            {
                "claim_id": "claim_exit_p32_sr1",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.execution_quality == ExecutionQuality.POOR
    assert diag.extraction_quality == ExtractionQuality.POORLY_EXTRACTED
    assert diag.strategy_action_type == StrategyActionType.REFINE_EXIT_TIMING


def test_p32_no_sub_failure_fallback() -> None:
    review = _make_saved_review(
        result_id="p32_tr1",
        overall_verdict="acceptable",
        quality_tier="AVERAGE",
        outcome="manual_exit",
        claims=[
            {
                "claim_id": "claim_selection_p32_tr1",
                "statement": "The trade should have been taken based on strong signal score.",
                "confidence": 0.8,
                "sample_size": 1,
                "metadata": {"should_trade": True},
            },
            {
                "claim_id": "claim_entry_p32_tr1",
                "statement": "Entry timing was acceptable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
            {
                "claim_id": "claim_exit_p32_tr1",
                "statement": "Exit was reasonable.",
                "confidence": 0.7,
                "sample_size": 1,
            },
        ],
    )
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.opportunity_quality != OpportunityQuality.INVALID
    assert diag.execution_quality != ExecutionQuality.POOR
    assert diag.extraction_quality != ExtractionQuality.POORLY_EXTRACTED
    assert diag.strategy_action_type == StrategyActionType.COLLECT_MORE_SAMPLES


def test_p32_grade_ab_unchanged() -> None:
    review = _make_saved_review(result_id="p32_ab1")
    diag = DiagnosticService().diagnose_trade(review)
    assert diag is not None
    assert diag.overall_grade in (OverallGrade.A, OverallGrade.B)
    assert diag.strategy_action_type == StrategyActionType.NO_CHANGE


def test_p32_claim_prefix_new_entry_timing() -> None:
    from src.trading_research.strategy_improvement_service import _find_matching_claim_ids

    claims = [
        Claim(claim_id="agg_claim_entry_test", statement="Entry", status=ClaimStatus.SUPPORTED, sample_size=3),
        Claim(claim_id="agg_claim_exit_test", statement="Exit", status=ClaimStatus.SUPPORTED, sample_size=3),
    ]
    matching = _find_matching_claim_ids(StrategyActionType.REFINE_ENTRY_TIMING, claims)
    assert "agg_claim_entry_test" in matching
    assert "agg_claim_exit_test" not in matching


def test_p32_claim_prefix_new_exit_timing() -> None:
    from src.trading_research.strategy_improvement_service import _find_matching_claim_ids

    claims = [
        Claim(claim_id="agg_claim_entry_test", statement="Entry", status=ClaimStatus.SUPPORTED, sample_size=3),
        Claim(claim_id="agg_claim_exit_test", statement="Exit", status=ClaimStatus.SUPPORTED, sample_size=3),
    ]
    matching = _find_matching_claim_ids(StrategyActionType.REFINE_EXIT_TIMING, claims)
    assert "agg_claim_exit_test" in matching
    assert "agg_claim_entry_test" not in matching


def test_p32_tighten_risk_still_catches_all_claims() -> None:
    from src.trading_research.strategy_improvement_service import _find_matching_claim_ids

    claims = [
        Claim(claim_id="agg_claim_entry_test", statement="Entry", status=ClaimStatus.SUPPORTED, sample_size=3),
        Claim(claim_id="agg_claim_exit_test", statement="Exit", status=ClaimStatus.SUPPORTED, sample_size=3),
        Claim(claim_id="agg_claim_selection_test", statement="Sel", status=ClaimStatus.SUPPORTED, sample_size=3),
    ]
    matching = _find_matching_claim_ids(StrategyActionType.TIGHTEN_RISK_RULE, claims)
    assert len(matching) == 3


def test_p32_candidate_generation_with_refined_pattern() -> None:
    patterns = [
        AggregatePattern(
            pattern_id="pattern_action_type_refine_entry_timing",
            pattern_type="action_type",
            value="refine_entry_timing",
            count=3,
            distinct_trade_ids=["t1", "t2", "t3"],
            sample_size=3,
            frequency_pct=1.0,
        ),
    ]
    verified_claims = [
        Claim(claim_id="agg_claim_entry_test", statement="Entry", status=ClaimStatus.SUPPORTED, sample_size=3),
    ]
    svc = StrategyImprovementService()
    candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
    timing_candidates = [c for c in candidates if c.action_type == StrategyActionType.REFINE_ENTRY_TIMING]
    assert len(timing_candidates) == 1
    assert timing_candidates[0].status == StrategyActionStatus.VERIFIED_CANDIDATE
    assert "agg_claim_entry_test" in timing_candidates[0].supported_by_claim_ids


def test_p32_report_shows_refined_action_types() -> None:
    now = datetime.now()
    candidate = StrategyActionCandidate(
        action_id="candidate_refine_entry_timing_test",
        action_type=StrategyActionType.REFINE_ENTRY_TIMING,
        rationale="Entry timing pattern observed",
        supported_by_claim_ids=["agg_claim_entry_test"],
        sample_size=3,
        minimum_sample_size_met=True,
        status=StrategyActionStatus.VERIFIED_CANDIDATE,
    )
    result = StrategyImprovementLoopResult(
        result_id="p32_report_test",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="P3.2 Report Test",
        as_of=now,
        candidates=[candidate],
        trade_count=3,
        pattern_count=1,
        candidate_count=1,
    )
    md = build_strategy_improvement_markdown(result)
    assert "refine_entry_timing" in md
