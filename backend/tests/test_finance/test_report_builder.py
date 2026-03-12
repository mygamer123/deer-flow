"""Tests for src.community.finance.report_builder — markdown report generation."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.community.finance.models import (
    DayReview,
    EntryEvent,
    EntryVerdict,
    ExitEvent,
    ExitPolicy,
    ExitVerdict,
    FailureVerdict,
    ParsedTrade,
    PatternType,
    QualityTier,
    ReviewVerdict,
    SelectionVerdict,
    Signal,
    SignalType,
    TradeOutcome,
    TradeReview,
)
from src.community.finance.report_builder import build_day_report, build_trade_report

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_TS = datetime(2026, 3, 5, 9, 36, 0)


def _make_trade_review(
    symbol: str = "AMPX",
    outcome: TradeOutcome = TradeOutcome.TP_FILLED,
    entry_price: float = 13.90,
    exit_price: float | None = 14.59,
    quality: QualityTier = QualityTier.GOOD,
    verdict: ReviewVerdict = ReviewVerdict.ACCEPTABLE,
    include_failure: bool = False,
    iterations: int = 15,
) -> TradeReview:
    signal = Signal(timestamp=_TS - timedelta(minutes=1), symbol=symbol, signal_type=SignalType.MAIN, score=10.0, pwin=85.0, bars=100, ret5m_predicted=3.5, dd_predicted=1.0, tvr=12.0, raw_line="test")
    entry = EntryEvent(timestamp=_TS, symbol=symbol, price=entry_price, quantity=144)
    trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol=symbol, signal=signal, entry=entry, outcome=outcome)
    if exit_price is not None:
        trade.exit = ExitEvent(timestamp=_TS + timedelta(minutes=24), symbol=symbol, price=exit_price, exit_type="SELL LMT")

    review = TradeReview(
        trade=trade,
        quality_tier=quality,
        overall_verdict=verdict,
        selection=SelectionVerdict(should_trade=True, confidence=0.8, reasons=["Strong signal score (10.0)"]),
        entry=EntryVerdict(should_have_waited=False, optimal_entry_price=13.80, actual_vs_optimal_slippage_pct=0.72, reasons=["Entry near bar low"]),
        exit=ExitVerdict(
            recommended_policy=ExitPolicy.TRAILING_STOP,
            max_favorable_excursion_pct=6.5,
            max_adverse_excursion_pct=1.2,
            tp_pct_recommendation=5.0,
            optimal_exit_price=14.80,
            reasons=["Best trailing stop: trail_2pct → +4.50%"],
            simulations={
                "fixed_tp_sl": {"tp5_sl3": {"pnl_pct": 4.5, "exit_type": "tp", "bars_held": 12}},
                "trailing_stop": {"trail_2pct": {"pnl_pct": 4.5, "peak": 14.8, "bars_held": 18}},
                "time_based": {"exit_30min": {"pnl_pct": 3.2, "exit_price": 14.33}},
            },
        ),
        pattern=PatternType.STRONG_UPTRENDING,
        total_iterations=iterations,
    )

    if include_failure:
        review.failure = FailureVerdict(
            should_exit_now=True,
            recommended_exit_price=9.50,
            bounce_probability=0.15,
            max_hold_hours=2.0,
            reasons=["Volume decayed to 20%", "Death pattern detected"],
        )

    return review


# ---------------------------------------------------------------------------
# build_trade_report
# ---------------------------------------------------------------------------


class TestBuildTradeReport:
    def test_contains_symbol_and_outcome(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "AMPX" in report
        assert "tp_filled" in report

    def test_contains_signal_info(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "score=10.0" in report
        assert "pwin=85%" in report

    def test_contains_entry_info(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "$13.9000" in report
        assert "qty=144" in report

    def test_contains_exit_info(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "$14.5900" in report
        assert "SELL LMT" in report

    def test_contains_pnl(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "PnL" in report

    def test_contains_quality_and_verdict(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "GOOD" in report
        assert "acceptable" in report

    def test_contains_selection_section(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "### Selection" in report
        assert "Should trade: **Yes**" in report

    def test_contains_entry_section(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "### Entry" in report
        assert "Optimal entry: $13.8000" in report

    def test_contains_exit_section(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "### Exit" in report
        assert "Trailing Stop" in report
        assert "MFE: 6.50%" in report

    def test_contains_simulation_tables(self):
        review = _make_trade_review()
        report = build_trade_report(review)
        assert "#### Exit Simulations" in report
        assert "**Fixed TP/SL:**" in report
        assert "**Trailing Stop:**" in report
        assert "**Time-Based:**" in report

    def test_no_failure_section_for_normal_trade(self):
        review = _make_trade_review(include_failure=False)
        report = build_trade_report(review)
        assert "### Failure" not in report

    def test_failure_section_for_stranded(self):
        review = _make_trade_review(include_failure=True, outcome=TradeOutcome.STRANDED, exit_price=None)
        report = build_trade_report(review)
        assert "### Failure Analysis" in report
        assert "EXIT NOW" in report
        assert "Bounce probability" in report

    def test_index_prefix(self):
        review = _make_trade_review()
        report = build_trade_report(review, index=3)
        assert "## Trade 3:" in report

    def test_no_index_prefix(self):
        review = _make_trade_review()
        report = build_trade_report(review, index=None)
        assert "## Trade " not in report or "## AMPX" in report

    def test_iterations_displayed(self):
        review = _make_trade_review(iterations=18)
        report = build_trade_report(review)
        assert "18" in report


# ---------------------------------------------------------------------------
# build_day_report
# ---------------------------------------------------------------------------


class TestBuildDayReport:
    def test_contains_date_header(self):
        day = DayReview(trading_date=date(2026, 3, 5), trades=[_make_trade_review()])
        report = build_day_report(day)
        assert "# Trade Review — 2026-03-05" in report

    def test_contains_summary_table(self):
        day = DayReview(
            trading_date=date(2026, 3, 5),
            trades=[_make_trade_review()],
            summary_stats={
                "total_trades": 3,
                "winners": 2,
                "losers": 1,
                "stranded": 0,
                "win_rate_pct": 66.7,
                "total_pnl_pct": 8.5,
                "avg_pnl_pct": 2.83,
                "avg_iterations": 15.0,
                "quality_distribution": {"GOOD": 2, "MARGINAL": 1},
            },
        )
        report = build_day_report(day)
        assert "## Summary" in report
        assert "| Total trades | 3 |" in report
        assert "| Winners | 2 |" in report
        assert "Win rate" in report
        assert "Quality distribution" in report

    def test_contains_lessons(self):
        day = DayReview(
            trading_date=date(2026, 3, 5),
            trades=[_make_trade_review()],
            lessons=["2 trades should have been skipped", "1 stranded position should be exited"],
        )
        report = build_day_report(day)
        assert "## Lessons" in report
        assert "2 trades should have been skipped" in report

    def test_contains_trade_sections(self):
        review1 = _make_trade_review(symbol="AMPX")
        review2 = _make_trade_review(symbol="MOBX")
        day = DayReview(trading_date=date(2026, 3, 5), trades=[review1, review2])
        report = build_day_report(day)
        assert "## Trade 1:" in report
        assert "AMPX" in report
        assert "## Trade 2:" in report
        assert "MOBX" in report

    def test_empty_day(self):
        day = DayReview(trading_date=date(2026, 3, 5))
        report = build_day_report(day)
        assert "# Trade Review — 2026-03-05" in report

    def test_no_summary_when_empty(self):
        day = DayReview(trading_date=date(2026, 3, 5))
        report = build_day_report(day)
        assert "## Summary" not in report
