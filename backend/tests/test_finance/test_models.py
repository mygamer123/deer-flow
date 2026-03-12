"""Tests for src.community.finance.models — enums, dataclass properties, construction."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.community.finance.models import (
    AnalyticalLens,
    DataGap,
    DayReview,
    EntryEvent,
    EntryVerdict,
    ExitEvent,
    ExitPolicy,
    ExitVerdict,
    FailureVerdict,
    Hypothesis,
    IterationResult,
    MinuteBar,
    NewsItem,
    ParsedTrade,
    PatternType,
    QualityTier,
    QuantitativeFindings,
    ReconcileType,
    ReviewVerdict,
    SelectionVerdict,
    Signal,
    SignalType,
    TickerDetails,
    TradeOutcome,
    TradeReview,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_signal_type_values(self):
        assert SignalType.MAIN.value == "MAIN"
        assert SignalType.DD_RECLAIM.value == "DD_RECLAIM"
        assert SignalType.DD_BOUNCE.value == "DD_BOUNCE"

    def test_signal_type_is_str(self):
        assert isinstance(SignalType.MAIN, str)
        assert SignalType.MAIN == "MAIN"

    def test_trade_outcome_values(self):
        assert TradeOutcome.TP_FILLED.value == "tp_filled"
        assert TradeOutcome.STRANDED.value == "stranded"
        assert TradeOutcome.MANUAL_EXIT.value == "manual_exit"
        assert TradeOutcome.STOPPED_OUT.value == "stopped_out"
        assert TradeOutcome.OPEN.value == "open"

    def test_review_verdict_values(self):
        assert ReviewVerdict.GOOD_TRADE.value == "good_trade"
        assert ReviewVerdict.BAD_TRADE.value == "bad_trade"

    def test_exit_policy_values(self):
        assert ExitPolicy.FIXED_TP.value == "fixed_tp"
        assert ExitPolicy.TRAILING_STOP.value == "trailing_stop"

    def test_quality_tier_ordering(self):
        assert QualityTier.EXCELLENT.value < QualityTier.GOOD.value
        assert QualityTier.GOOD.value < QualityTier.MARGINAL.value
        assert QualityTier.MARGINAL.value < QualityTier.BAD.value
        assert QualityTier.BAD.value < QualityTier.TERRIBLE.value

    def test_quality_tier_is_int(self):
        assert isinstance(QualityTier.EXCELLENT, int)
        assert QualityTier.EXCELLENT == 1

    def test_reconcile_type_values(self):
        assert ReconcileType.GENERIC.value == "RECONCILE"
        assert ReconcileType.ORPHAN.value == "RECONCILE_ORPHAN"
        assert ReconcileType.GHOST.value == "RECONCILE_GHOST"

    def test_pattern_type_values(self):
        assert PatternType.STRONG_UPTRENDING.value == "strong_uptrending"
        assert PatternType.UNCLASSIFIED.value == "unclassified"


# ---------------------------------------------------------------------------
# ParsedTrade property tests
# ---------------------------------------------------------------------------


def _make_signal(symbol: str = "TEST", score: float = 8.0) -> Signal:
    return Signal(
        timestamp=datetime(2026, 3, 5, 9, 35, 0),
        symbol=symbol,
        signal_type=SignalType.MAIN,
        score=score,
        pwin=85.0,
        bars=100,
        ret5m_predicted=3.5,
        dd_predicted=1.0,
        tvr=12.0,
        raw_line="test",
    )


def _make_entry(symbol: str = "TEST", price: float = 10.0, quantity: int = 100) -> EntryEvent:
    return EntryEvent(
        timestamp=datetime(2026, 3, 5, 9, 36, 0),
        symbol=symbol,
        price=price,
        quantity=quantity,
    )


def _make_exit(symbol: str = "TEST", price: float = 10.5) -> ExitEvent:
    return ExitEvent(
        timestamp=datetime(2026, 3, 5, 10, 0, 0),
        symbol=symbol,
        price=price,
    )


class TestParsedTradeProperties:
    def test_entry_price(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", entry=_make_entry(price=13.50))
        assert trade.entry_price == 13.50

    def test_entry_price_none_without_entry(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST")
        assert trade.entry_price is None

    def test_exit_price(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", exit=_make_exit(price=14.00))
        assert trade.exit_price == 14.00

    def test_exit_price_none_without_exit(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST")
        assert trade.exit_price is None

    def test_pnl_pct_positive(self):
        trade = ParsedTrade(
            trading_date=date(2026, 3, 5),
            symbol="TEST",
            entry=_make_entry(price=10.0),
            exit=_make_exit(price=10.5),
        )
        assert trade.pnl_pct == pytest.approx(5.0)

    def test_pnl_pct_negative(self):
        trade = ParsedTrade(
            trading_date=date(2026, 3, 5),
            symbol="TEST",
            entry=_make_entry(price=10.0),
            exit=_make_exit(price=9.5),
        )
        assert trade.pnl_pct == pytest.approx(-5.0)

    def test_pnl_pct_none_without_exit(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", entry=_make_entry())
        assert trade.pnl_pct is None

    def test_pnl_pct_none_without_entry(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST")
        assert trade.pnl_pct is None

    def test_hold_duration_minutes(self):
        trade = ParsedTrade(
            trading_date=date(2026, 3, 5),
            symbol="TEST",
            entry=_make_entry(),
            exit=_make_exit(),
        )
        # Entry at 09:36, exit at 10:00 = 24 minutes
        assert trade.hold_duration_minutes == pytest.approx(24.0)

    def test_hold_duration_none_without_exit(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", entry=_make_entry())
        assert trade.hold_duration_minutes is None

    def test_is_stranded_true(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", outcome=TradeOutcome.STRANDED)
        assert trade.is_stranded is True

    def test_is_stranded_false(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", outcome=TradeOutcome.TP_FILLED)
        assert trade.is_stranded is False

    def test_is_short_true(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="PENN", entry=_make_entry(quantity=-100))
        assert trade.is_short is True

    def test_is_short_false(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", entry=_make_entry(quantity=100))
        assert trade.is_short is False

    def test_is_short_false_without_entry(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST")
        assert trade.is_short is False


# ---------------------------------------------------------------------------
# Model construction smoke tests
# ---------------------------------------------------------------------------


class TestModelConstruction:
    def test_minute_bar_defaults(self):
        bar = MinuteBar(timestamp=datetime(2026, 3, 5, 9, 30), timestamp_ns=0, open=10.0, high=10.5, low=9.8, close=10.2, volume=1000)
        assert bar.transactions == 0

    def test_ticker_details_defaults(self):
        td = TickerDetails(symbol="TEST")
        assert td.name == ""
        assert td.market_cap is None

    def test_news_item_defaults(self):
        ni = NewsItem(title="Test Article")
        assert ni.sentiment == ""
        assert ni.tickers == []

    def test_data_gap_defaults(self):
        gap = DataGap(dimension="test", description="test gap")
        assert gap.priority == 0.5
        assert gap.resolved is False

    def test_analytical_lens_defaults(self):
        lens = AnalyticalLens(name="test", iteration=1, description="test lens")
        assert lens.required_data == []
        assert lens.depends_on == []

    def test_quantitative_findings_defaults(self):
        qf = QuantitativeFindings(lens_name="test", iteration=1)
        assert qf.metrics == {}
        assert qf.observations == []
        assert qf.confidence == 0.0

    def test_hypothesis_defaults(self):
        h = Hypothesis(statement="test")
        assert h.evidence_for == []
        assert h.evidence_against == []
        assert h.verified is None
        assert h.confidence == 0.0

    def test_selection_verdict_defaults(self):
        sv = SelectionVerdict(should_trade=True, confidence=0.8)
        assert sv.reasons == []

    def test_entry_verdict_defaults(self):
        ev = EntryVerdict()
        assert ev.optimal_entry_time is None
        assert ev.should_have_waited is False

    def test_exit_verdict_defaults(self):
        ev = ExitVerdict()
        assert ev.recommended_policy == ExitPolicy.FIXED_TP
        assert ev.simulations == {}

    def test_failure_verdict_defaults(self):
        fv = FailureVerdict()
        assert fv.should_exit_now is False
        assert fv.bounce_probability is None

    def test_trade_review_defaults(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST")
        review = TradeReview(trade=trade)
        assert review.quality_tier == QualityTier.MARGINAL
        assert review.overall_verdict == ReviewVerdict.ACCEPTABLE
        assert review.total_iterations == 0

    def test_day_review_defaults(self):
        dr = DayReview(trading_date=date(2026, 3, 5))
        assert dr.trades == []
        assert dr.lessons == []

    def test_iteration_result_defaults(self):
        lens = AnalyticalLens(name="test", iteration=1, description="test")
        ir = IterationResult(iteration=1, lens=lens)
        assert ir.converged is False
        assert ir.cumulative_confidence == 0.0
