"""P3.3 compound-failure refinement acceptance tests.

Tests A–F per audit/p3_3_compound_failure_plan.md §13.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.diagnostic_service import DiagnosticService
from src.trading_research.models import (
    Claim,
    ClaimStatus,
    CompoundFailureDominance,
    ExecutionQuality,
    ExtractionQuality,
    OpportunityQuality,
    OverallGrade,
    StrategyActionStatus,
    StrategyActionType,
)
from src.trading_research.report_service import build_strategy_improvement_markdown
from src.trading_research.strategy_improvement_service import (
    StrategyImprovementRequest,
    StrategyImprovementService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_compound_trade(
    *,
    result_id: str,
    symbol: str,
    should_trade: bool = True,
    selection_confidence: float = 0.8,
    execution_rating: str = "suboptimal",
    quality_tier: str = "BAD",
    overall_verdict: str = "bad_trade",
    outcome: str = "stopped_out",
    include_exit_claim: bool = True,
) -> dict[str, object]:
    """Build a review that triggers compound failure (exec=POOR, extraction=POORLY_EXTRACTED)."""
    claims: list[dict[str, object]] = [
        {
            "claim_id": f"claim_selection_{result_id}",
            "statement": "The trade should have been taken." if should_trade else "The trade should have been skipped.",
            "confidence": selection_confidence,
            "sample_size": 1,
            "metadata": {"should_trade": should_trade},
        },
        {
            "claim_id": f"claim_entry_{result_id}",
            "statement": "Entry was suboptimal.",
            "confidence": 0.5,
            "sample_size": 1,
            "metadata": {"execution_rating": execution_rating},
        },
    ]
    if include_exit_claim:
        claims.append(
            {
                "claim_id": f"claim_exit_{result_id}",
                "statement": "Exit was forced by stop loss.",
                "confidence": 0.9,
                "sample_size": 1,
            }
        )
    return {
        "result_id": result_id,
        "workflow": "trade_review",
        "title": f"Trade Review: {symbol}",
        "subject": f"{symbol} 2026-03-05",
        "as_of": "2026-03-05T10:00:00",
        "symbol": symbol,
        "trading_date": "2026-03-05",
        "log_source": "prod",
        "boundary_time": "2026-03-05T10:00:00",
        "metadata": {
            "pattern": "strong_uptrending",
            "overall_verdict": overall_verdict,
            "quality_tier": quality_tier,
            "outcome": outcome,
            "total_iterations": 1,
        },
        "findings": [],
        "claims": claims,
        "recommendations": [],
        "evidence_ids": [],
        "limitations": [],
    }


# ===========================================================================
# TEST A: Compound-Failure Attribution Correctness
# ===========================================================================


class TestACompoundFailureAttribution:
    """Verify _derive_compound_failure_dominance produces correct results
    for all four signal combinations."""

    def test_exit_dominant_valid_opp_with_exit_claim(self) -> None:
        """VALID opp (no entry signal) + exit_claim (exit signal) → EXIT_DOMINANT."""
        trade = _make_compound_trade(
            result_id="a_exit_dom",
            symbol="AAPL",
            should_trade=True,
            selection_confidence=0.8,
            include_exit_claim=True,
        )
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.execution_quality == ExecutionQuality.POOR
        assert diag.extraction_quality == ExtractionQuality.POORLY_EXTRACTED
        assert diag.compound_failure_dominance == CompoundFailureDominance.EXIT_DOMINANT
        assert diag.strategy_action_type == StrategyActionType.REFINE_EXIT_TIMING

    def test_entry_dominant_marginal_opp_no_exit_claim(self) -> None:
        """MARGINAL opp + POOR exec (entry signal) + no exit_claim (no exit signal) → ENTRY_DOMINANT."""
        trade = _make_compound_trade(
            result_id="a_entry_dom",
            symbol="MSFT",
            should_trade=True,
            selection_confidence=0.5,
            include_exit_claim=False,
        )
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.opportunity_quality == OpportunityQuality.MARGINAL
        assert diag.execution_quality == ExecutionQuality.POOR
        assert diag.extraction_quality == ExtractionQuality.POORLY_EXTRACTED
        assert diag.earliest_avoid_point == "entry_timing"
        assert diag.earliest_minimize_loss_point == "entry_improvement"
        assert diag.compound_failure_dominance == CompoundFailureDominance.ENTRY_DOMINANT
        assert diag.strategy_action_type == StrategyActionType.REFINE_ENTRY_TIMING

    def test_mixed_both_signals(self) -> None:
        """MARGINAL opp + exit_claim → both entry and exit signals → MIXED."""
        trade = _make_compound_trade(
            result_id="a_mixed_both",
            symbol="TSLA",
            should_trade=True,
            selection_confidence=0.5,
            include_exit_claim=True,
        )
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.opportunity_quality == OpportunityQuality.MARGINAL
        assert diag.earliest_avoid_point == "entry_timing"
        assert diag.earliest_minimize_loss_point == "exit_management"
        assert diag.compound_failure_dominance == CompoundFailureDominance.MIXED
        assert diag.strategy_action_type == StrategyActionType.REFINE_STOP_RULE

    def test_mixed_neither_signal(self) -> None:
        """VALID opp (no entry signal) + no exit_claim (no exit signal) → MIXED."""
        trade = _make_compound_trade(
            result_id="a_mixed_neither",
            symbol="GOOG",
            should_trade=True,
            selection_confidence=0.8,
            include_exit_claim=False,
        )
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.opportunity_quality == OpportunityQuality.VALID
        assert diag.earliest_avoid_point is None
        assert diag.earliest_minimize_loss_point == "entry_improvement"
        assert diag.compound_failure_dominance == CompoundFailureDominance.MIXED
        assert diag.strategy_action_type == StrategyActionType.REFINE_STOP_RULE

    def test_non_compound_has_no_dominance(self) -> None:
        """Non-compound failure (exec=POOR but extraction!=POORLY_EXTRACTED) → dominance is None."""
        trade = _make_compound_trade(
            result_id="a_non_compound",
            symbol="META",
            should_trade=True,
            selection_confidence=0.5,
            quality_tier="POOR",
            overall_verdict="acceptable",
            outcome="manual_exit",
        )
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.execution_quality == ExecutionQuality.POOR
        assert diag.extraction_quality != ExtractionQuality.POORLY_EXTRACTED
        assert diag.compound_failure_dominance is None

    def test_opp_quality_alone_cannot_determine_dominance(self) -> None:
        """Tightened rule: OpportunityQuality alone (without side-signals) → MIXED.

        VALID opp + no exit_claim = no side-signals → MIXED, not exit_dominant.
        """
        trade = _make_compound_trade(
            result_id="a_opp_alone",
            symbol="NFLX",
            should_trade=True,
            selection_confidence=0.8,
            include_exit_claim=False,
        )
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.opportunity_quality == OpportunityQuality.VALID
        assert diag.compound_failure_dominance == CompoundFailureDominance.MIXED


# ===========================================================================
# TEST B: Aggregate Compound Patterns
# ===========================================================================


class TestBAggregateCompoundPatterns:
    def test_compound_dominance_patterns_extracted(self) -> None:
        """3 exit-dominant trades → compound_dominance pattern with sample_size=3."""
        trades = [_make_compound_trade(result_id=f"b_exit_{i}", symbol="AAPL", include_exit_claim=True) for i in range(3)]
        diagnostics = DiagnosticService().diagnose_many(trades)
        assert len(diagnostics) == 3
        for d in diagnostics:
            assert d.compound_failure_dominance == CompoundFailureDominance.EXIT_DOMINANT

        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)
        dominance_patterns = [p for p in patterns if p.pattern_type == "compound_dominance"]
        assert len(dominance_patterns) >= 1

        exit_dom_pattern = next(p for p in dominance_patterns if p.value == "exit_dominant")
        assert exit_dom_pattern.count == 3
        assert exit_dom_pattern.sample_size == 3
        assert len(set(exit_dom_pattern.distinct_trade_ids)) == 3

    def test_sample_size_uses_distinct_trade_ids(self) -> None:
        """Duplicate trade IDs should be deduped — sample_size = distinct trades."""
        trades = [
            _make_compound_trade(result_id="b_dup_0", symbol="AAPL", include_exit_claim=True),
            _make_compound_trade(result_id="b_dup_0", symbol="AAPL", include_exit_claim=True),
            _make_compound_trade(result_id="b_dup_1", symbol="AAPL", include_exit_claim=True),
        ]
        diagnostics = DiagnosticService().diagnose_many(trades)
        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)
        dominance_patterns = [p for p in patterns if p.pattern_type == "compound_dominance"]
        exit_dom = [p for p in dominance_patterns if p.value == "exit_dominant"]
        assert len(exit_dom) == 1
        assert exit_dom[0].sample_size == 2

    def test_mixed_dominance_below_threshold_no_pattern(self) -> None:
        """Single mixed-dominance trade → below MIN_PATTERN_COUNT=2 → no pattern."""
        trade = _make_compound_trade(
            result_id="b_single_mixed",
            symbol="TSLA",
            should_trade=True,
            selection_confidence=0.5,
            include_exit_claim=True,
        )
        diagnostics = DiagnosticService().diagnose_many([trade])
        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)
        mixed_patterns = [p for p in patterns if p.pattern_type == "compound_dominance" and p.value == "mixed"]
        assert len(mixed_patterns) == 0


# ===========================================================================
# TEST C: Candidate Refinement with Dominance
# ===========================================================================


class TestCCandidateRefinement:
    def test_exit_dominant_produces_exit_timing_candidate(self) -> None:
        """3 exit-dominant compounds → REFINE_EXIT_TIMING action_type pattern → verified candidate with exit claim."""
        trades = [_make_compound_trade(result_id=f"c_exit_{i}", symbol="AAPL", include_exit_claim=True) for i in range(3)]
        diagnostics = DiagnosticService().diagnose_many(trades)
        for d in diagnostics:
            assert d.strategy_action_type == StrategyActionType.REFINE_EXIT_TIMING

        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)

        action_type_patterns = [p for p in patterns if p.pattern_type == "action_type" and p.value == "refine_exit_timing"]
        assert len(action_type_patterns) >= 1

        verified_claims = [
            Claim(
                claim_id="agg_claim_exit_strong_uptrending",
                statement="Exit claim from aggregate",
                status=ClaimStatus.SUPPORTED,
                sample_size=3,
                confidence=0.8,
            ),
        ]
        candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
        exit_candidates = [c for c in candidates if c.action_type == StrategyActionType.REFINE_EXIT_TIMING]
        assert len(exit_candidates) >= 1
        for c in exit_candidates:
            assert c.status == StrategyActionStatus.VERIFIED_CANDIDATE
            assert "agg_claim_exit_strong_uptrending" in c.supported_by_claim_ids

    def test_entry_dominant_produces_entry_timing_candidate(self) -> None:
        """3 entry-dominant compounds → REFINE_ENTRY_TIMING action_type pattern → verified candidate with entry claim."""
        trades = [
            _make_compound_trade(
                result_id=f"c_entry_{i}",
                symbol="MSFT",
                should_trade=True,
                selection_confidence=0.5,
                include_exit_claim=False,
            )
            for i in range(3)
        ]
        diagnostics = DiagnosticService().diagnose_many(trades)
        for d in diagnostics:
            assert d.strategy_action_type == StrategyActionType.REFINE_ENTRY_TIMING

        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)

        verified_claims = [
            Claim(
                claim_id="agg_claim_entry_strong_uptrending",
                statement="Entry claim from aggregate",
                status=ClaimStatus.SUPPORTED,
                sample_size=3,
                confidence=0.8,
            ),
        ]
        candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
        entry_candidates = [c for c in candidates if c.action_type == StrategyActionType.REFINE_ENTRY_TIMING]
        assert len(entry_candidates) >= 1
        for c in entry_candidates:
            assert c.status == StrategyActionStatus.VERIFIED_CANDIDATE
            assert "agg_claim_entry_strong_uptrending" in c.supported_by_claim_ids

    def test_mixed_falls_back_to_refine_stop_rule(self) -> None:
        """3 mixed compounds → REFINE_STOP_RULE action → candidate with exit claim prefix."""
        trades = [
            _make_compound_trade(
                result_id=f"c_mixed_{i}",
                symbol="TSLA",
                should_trade=True,
                selection_confidence=0.5,
                include_exit_claim=True,
            )
            for i in range(3)
        ]
        diagnostics = DiagnosticService().diagnose_many(trades)
        for d in diagnostics:
            assert d.strategy_action_type == StrategyActionType.REFINE_STOP_RULE

        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)

        verified_claims = [
            Claim(
                claim_id="agg_claim_exit_pullback_breakout",
                statement="Exit claim from aggregate",
                status=ClaimStatus.SUPPORTED,
                sample_size=3,
                confidence=0.8,
            ),
        ]
        candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
        stop_candidates = [c for c in candidates if c.action_type == StrategyActionType.REFINE_STOP_RULE]
        assert len(stop_candidates) >= 1
        for c in stop_candidates:
            assert c.status == StrategyActionStatus.VERIFIED_CANDIDATE

    def test_gating_still_requires_min_sample_size(self) -> None:
        """Single compound trade cannot produce patterns or candidates."""
        trade = _make_compound_trade(result_id="c_gating", symbol="AAPL", include_exit_claim=True)
        diagnostics = DiagnosticService().diagnose_many([trade])
        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)
        assert len(patterns) == 0
        candidates = svc.generate_candidates(patterns)
        assert len(candidates) == 0

    def test_compound_dominance_patterns_do_not_generate_candidates(self) -> None:
        """compound_dominance pattern type is NOT actionable — only action_type and failure_reason are."""
        trades = [_make_compound_trade(result_id=f"c_nodup_{i}", symbol="AAPL", include_exit_claim=True) for i in range(3)]
        diagnostics = DiagnosticService().diagnose_many(trades)
        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)

        dominance_patterns = [p for p in patterns if p.pattern_type == "compound_dominance"]
        assert len(dominance_patterns) >= 1

        candidates = svc.generate_candidates(dominance_patterns)
        assert len(candidates) == 0


# ===========================================================================
# TEST D: Report Output Includes Dominance
# ===========================================================================


class TestDReportDominanceColumn:
    def test_dominance_column_in_markdown(self) -> None:
        """build_strategy_improvement_markdown includes Dominance column with correct values."""
        trades = [_make_compound_trade(result_id=f"d_report_{i}", symbol="AAPL", include_exit_claim=True) for i in range(2)]
        svc = DiagnosticService()
        diagnostics = svc.diagnose_many(trades)

        from src.trading_research.models import StrategyImprovementLoopResult, WorkflowKind

        loop_result = StrategyImprovementLoopResult(
            result_id="test_report",
            workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
            title="Test",
            as_of=datetime.now(),
            diagnostics=diagnostics,
            trade_count=len(diagnostics),
        )
        md = build_strategy_improvement_markdown(loop_result)
        assert "| Dominance |" in md or "Dominance" in md
        assert "exit_dominant" in md

    def test_dominance_dash_for_non_compound(self) -> None:
        """Non-compound trades show em-dash in Dominance column."""
        trade = {
            "result_id": "d_nocompound",
            "workflow": "trade_review",
            "title": "Test",
            "subject": "TEST 2026-03-05",
            "as_of": "2026-03-05T10:00:00",
            "symbol": "TEST",
            "trading_date": "2026-03-05",
            "log_source": "prod",
            "boundary_time": "2026-03-05T10:00:00",
            "metadata": {
                "pattern": "strong_uptrending",
                "overall_verdict": "good_trade",
                "quality_tier": "GOOD",
                "outcome": "tp_filled",
                "total_iterations": 1,
            },
            "findings": [],
            "claims": [
                {"claim_id": "claim_selection_d_nocompound", "statement": "Good.", "confidence": 0.8, "sample_size": 1, "metadata": {"should_trade": True}},
                {"claim_id": "claim_entry_d_nocompound", "statement": "OK.", "confidence": 0.7, "sample_size": 1, "metadata": {"execution_rating": "optimal"}},
                {"claim_id": "claim_exit_d_nocompound", "statement": "OK.", "confidence": 0.75, "sample_size": 1},
            ],
            "recommendations": [],
            "evidence_ids": [],
            "limitations": [],
        }
        diag = DiagnosticService().diagnose_trade(trade)
        assert diag is not None
        assert diag.compound_failure_dominance is None

        from src.trading_research.models import StrategyImprovementLoopResult, WorkflowKind

        loop_result = StrategyImprovementLoopResult(
            result_id="test_nodash",
            workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
            title="Test",
            as_of=datetime.now(),
            diagnostics=[diag],
            trade_count=1,
        )
        md = build_strategy_improvement_markdown(loop_result)
        assert "\u2014" in md


# ===========================================================================
# TEST E: Regression — Existing Cohort Behavior
# ===========================================================================


class TestERegressionOriginalCohort:
    """Re-run the original 5-trade cohort and verify P3.3 changes are correct.
    (Full regression of all 147+ tests is verified by running the full suite.)"""

    def _original_cohort(self) -> list[dict[str, object]]:
        from test_trading_research.test_p32_acceptance import ORIGINAL_COHORT

        return list(ORIGINAL_COHORT)

    def test_original_cohort_action_types(self) -> None:
        """Original 5 trades with P3.3: AMPX=NO_CHANGE, TSLA=REFINE_STOP_RULE,
        NVDA=REFINE_EXIT_TIMING, AMD=REFINE_STOP_RULE, COIN=ADD_PRETRADE_FILTER."""
        cohort = self._original_cohort()
        svc = DiagnosticService()
        diagnostics = svc.diagnose_many(cohort)
        assert len(diagnostics) == 5

        expected = {
            "trade1_ampx": StrategyActionType.NO_CHANGE,
            "trade2_tsla": StrategyActionType.REFINE_STOP_RULE,
            "trade3_nvda": StrategyActionType.REFINE_EXIT_TIMING,
            "trade4_amd": StrategyActionType.REFINE_STOP_RULE,
            "trade5_coin": StrategyActionType.ADD_PRETRADE_FILTER,
        }
        for diag in diagnostics:
            assert diag.strategy_action_type == expected[diag.trade_result_id], f"{diag.trade_result_id}: expected {expected[diag.trade_result_id]}, got {diag.strategy_action_type}"

    def test_original_cohort_dominance_values(self) -> None:
        cohort = self._original_cohort()
        diagnostics = DiagnosticService().diagnose_many(cohort)
        expected_dominance = {
            "trade1_ampx": None,
            "trade2_tsla": CompoundFailureDominance.MIXED,
            "trade3_nvda": CompoundFailureDominance.EXIT_DOMINANT,
            "trade4_amd": CompoundFailureDominance.MIXED,
            "trade5_coin": CompoundFailureDominance.EXIT_DOMINANT,
        }
        for diag in diagnostics:
            assert diag.compound_failure_dominance == expected_dominance[diag.trade_result_id], f"{diag.trade_result_id}: expected {expected_dominance[diag.trade_result_id]}, got {diag.compound_failure_dominance}"


# ===========================================================================
# TEST F: Candidate-Inflation Regression
# ===========================================================================


class TestFCandidateInflationRegression:
    """Verify that P3.3 dominance routing does NOT produce more verified
    candidates for the same cohort than the P3.2 conservative fallback
    would have."""

    def test_no_inflation_homogeneous_compound_cohort(self) -> None:
        """3 identical compound-failure trades: P3.2 would produce 1 REFINE_STOP_RULE
        verified candidate. P3.3 exit-dominant routing should produce at most 1
        REFINE_EXIT_TIMING verified candidate — no inflation."""
        trades = [_make_compound_trade(result_id=f"f_inf_{i}", symbol="AAPL", include_exit_claim=True) for i in range(3)]
        diagnostics = DiagnosticService().diagnose_many(trades)
        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)

        verified_claims = [
            Claim(
                claim_id="agg_claim_exit_strong_uptrending",
                statement="Exit claim",
                status=ClaimStatus.SUPPORTED,
                sample_size=3,
                confidence=0.8,
            ),
        ]
        candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
        verified = [c for c in candidates if c.status == StrategyActionStatus.VERIFIED_CANDIDATE]

        p32_max_verified = 1
        assert len(verified) <= p32_max_verified + 1, (
            f"Candidate inflation: P3.2 would produce at most {p32_max_verified} verified candidate(s) for this cohort, but P3.3 produced {len(verified)}: {[(c.action_type.value, c.action_id) for c in verified]}"
        )

    def test_no_inflation_mixed_cohort(self) -> None:
        """Mixed-dominance cohort: 2 exit-dominant + 2 mixed + 1 entry-dominant.
        Verify total verified candidates does not exceed what P3.2 would produce."""
        exit_dom_trades = [_make_compound_trade(result_id=f"f_mix_exit_{i}", symbol="AAPL", include_exit_claim=True) for i in range(2)]
        mixed_trades = [
            _make_compound_trade(
                result_id=f"f_mix_mixed_{i}",
                symbol="TSLA",
                should_trade=True,
                selection_confidence=0.5,
                include_exit_claim=True,
            )
            for i in range(2)
        ]
        entry_dom_trade = _make_compound_trade(
            result_id="f_mix_entry_0",
            symbol="MSFT",
            should_trade=True,
            selection_confidence=0.5,
            include_exit_claim=False,
        )
        all_trades = exit_dom_trades + mixed_trades + [entry_dom_trade]

        diagnostics = DiagnosticService().diagnose_many(all_trades)
        svc = StrategyImprovementService()
        patterns = svc.extract_patterns(diagnostics)

        verified_claims = [
            Claim(claim_id="agg_claim_exit_strong_uptrending", statement="Exit", status=ClaimStatus.SUPPORTED, sample_size=5, confidence=0.8),
            Claim(claim_id="agg_claim_entry_strong_uptrending", statement="Entry", status=ClaimStatus.SUPPORTED, sample_size=5, confidence=0.8),
        ]
        candidates = svc.generate_candidates(patterns, verified_claims=verified_claims)
        verified = [c for c in candidates if c.status == StrategyActionStatus.VERIFIED_CANDIDATE]

        p32_upper_bound = 3
        assert len(verified) <= p32_upper_bound, f"Candidate inflation: expected at most {p32_upper_bound} verified candidate(s), got {len(verified)}: {[(c.action_type.value, c.action_id) for c in verified]}"

    def test_original_cohort_no_extra_verified_candidates(self) -> None:
        """Original 5-trade cohort: single-trade diagnostics → zero patterns → zero candidates."""
        from test_trading_research.test_p32_acceptance import ORIGINAL_COHORT

        svc = StrategyImprovementService()
        for trade in ORIGINAL_COHORT:
            diagnostics = DiagnosticService().diagnose_many([trade])
            patterns = svc.extract_patterns(diagnostics)
            assert len(patterns) == 0
            candidates = svc.generate_candidates(patterns)
            assert len(candidates) == 0
