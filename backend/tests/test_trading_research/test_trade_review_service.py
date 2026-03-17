from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.community.finance.models import (
    AnalyticalLens,
    DataGap,
    EntryEvent,
    EntryVerdict,
    ExitEvent,
    ExitPolicy,
    ExitVerdict,
    IterationResult,
    ParsedTrade,
    PatternType,
    QualityTier,
    QuantitativeFindings,
    ReviewVerdict,
    SelectionVerdict,
    Signal,
    SignalType,
    TradeOutcome,
    TradeReview,
)
from src.trading_research.evidence_service import EvidenceService
from src.trading_research.trade_review_service import TradeReviewService


def _make_trade_review() -> TradeReview:
    signal_ts = datetime(2026, 3, 5, 9, 35)
    entry_ts = datetime(2026, 3, 5, 9, 36)
    exit_ts = entry_ts + timedelta(minutes=10)
    trade = ParsedTrade(
        trading_date=date(2026, 3, 5),
        symbol="AMPX",
        signal=Signal(
            timestamp=signal_ts,
            symbol="AMPX",
            signal_type=SignalType.MAIN,
            score=9.2,
            pwin=81.0,
            bars=75,
            ret5m_predicted=3.1,
            dd_predicted=1.2,
            tvr=11.5,
            raw_line="signal",
        ),
        entry=EntryEvent(timestamp=entry_ts, symbol="AMPX", price=10.0, quantity=100),
        exit=ExitEvent(timestamp=exit_ts, symbol="AMPX", price=10.6),
        outcome=TradeOutcome.TP_FILLED,
    )
    iteration_result = IterationResult(
        iteration=1,
        lens=AnalyticalLens(name="basic_bars", iteration=1, description="test"),
        findings={
            "selection": QuantitativeFindings(
                lens_name="basic_bars",
                iteration=1,
                observations=["Strong signal score (9.2)"],
                metrics={"score": 9.2},
                confidence=0.8,
            ),
            "entry": QuantitativeFindings(
                lens_name="basic_bars",
                iteration=1,
                observations=["Entered near bar low"],
                metrics={"entry_position_in_bar": 0.2},
                confidence=0.7,
            ),
            "exit": QuantitativeFindings(
                lens_name="alt_tp_sl_sim",
                iteration=1,
                observations=["Best fixed TP/SL: tp5_sl3 -> +4.50%"],
                metrics={"best_tp_sl_pnl": 4.5},
                confidence=0.75,
            ),
        },
        new_gaps=[DataGap(dimension="news", description="Missing data: news")],
        cumulative_confidence=0.8,
    )
    return TradeReview(
        trade=trade,
        quality_tier=QualityTier.GOOD,
        overall_verdict=ReviewVerdict.ACCEPTABLE,
        selection=SelectionVerdict(should_trade=True, confidence=0.8, reasons=["Strong signal score (9.2)"]),
        entry=EntryVerdict(should_have_waited=False, reasons=["Entered near bar low"]),
        exit=ExitVerdict(
            recommended_policy=ExitPolicy.TRAILING_STOP,
            reasons=["Trailing stop captured more than fixed TP"],
        ),
        pattern=PatternType.STRONG_UPTRENDING,
        iteration_results=[iteration_result],
        total_iterations=1,
    )


def test_trade_review_service_builds_structured_verified_result(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        with patch(
            "src.trading_research.trade_review_service.DecisionReviewService.review_single_trade",
            return_value=_make_trade_review(),
        ):
            service = TradeReviewService(evidence_service=EvidenceService())
            result = service.review_trade(symbol="AMPX", trading_date=date(2026, 3, 5), log_source="prod")

        assert result.symbol == "AMPX"
        assert result.workflow.value == "trade_review"
        assert result.findings
        assert result.claims
        assert all(claim.sample_size == 1 for claim in result.claims)
        assert result.evidence_ids
        assert result.verifier is not None
        assert result.verifier.passed is False
        assert len(result.verifier.sample_size_downgraded_claim_ids) == len(result.claims)
        assert result.recommendations == []
        assert "Missing data: news" in result.limitations
