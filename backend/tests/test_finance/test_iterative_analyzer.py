"""Tests for src.community.finance.iterative_analyzer — IterativeAnalyzer convergence loop."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from src.community.finance.iterative_analyzer import IterativeAnalyzer
from src.community.finance.market_data_service import MarketDataService
from src.community.finance.models import (
    AnalyticalLens,
    EntryEvent,
    ExitEvent,
    MinuteBar,
    ParsedTrade,
    Signal,
    SignalType,
    TickerDetails,
    TradeOutcome,
)
from src.community.finance.themes.base import ReviewTheme

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ENTRY_TS = datetime(2026, 3, 5, 9, 36, 0)
_SIGNAL_TS = datetime(2026, 3, 5, 9, 35, 0)


def _bar(ts: datetime, o: float = 10.0, h: float = 10.5, l: float = 9.8, c: float = 10.2, vol: int = 1000) -> MinuteBar:  # noqa: E741
    return MinuteBar(timestamp=ts, timestamp_ns=int(ts.timestamp() * 1e9), open=o, high=h, low=l, close=c, volume=vol)


def _make_bars(n: int = 30, base_ts: datetime = _ENTRY_TS) -> list[MinuteBar]:
    return [_bar(base_ts + timedelta(minutes=i)) for i in range(n)]


def _make_trade(outcome: TradeOutcome = TradeOutcome.TP_FILLED) -> ParsedTrade:
    return ParsedTrade(
        trading_date=date(2026, 3, 5),
        symbol="TEST",
        signal=Signal(timestamp=_SIGNAL_TS, symbol="TEST", signal_type=SignalType.MAIN, score=8.0, pwin=85.0, bars=100, ret5m_predicted=3.5, dd_predicted=1.0, tvr=12.0, raw_line="test"),
        entry=EntryEvent(timestamp=_ENTRY_TS, symbol="TEST", price=10.0, quantity=100),
        exit=ExitEvent(timestamp=_ENTRY_TS + timedelta(minutes=24), symbol="TEST", price=10.5),
        outcome=outcome,
    )


class _MinimalTheme(ReviewTheme):
    """Minimal theme with only 3 lenses for fast test execution."""

    name = "test_minimal"
    description = "Test theme"

    def get_lenses(self) -> list[AnalyticalLens]:
        return [
            AnalyticalLens(name="basic_bars", iteration=1, description="test", required_data=["minute_bars"]),
            AnalyticalLens(name="volume_profile", iteration=2, description="test", required_data=["minute_bars"]),
            AnalyticalLens(name="market_context", iteration=3, description="test", required_data=["spy_bars", "qqq_bars"]),
        ]

    def get_review_modules(self) -> list[str]:
        return ["selection", "entry", "exit"]


class _ConvergingTheme(_MinimalTheme):
    """Theme that converges immediately at iteration 1."""

    @property
    def convergence_threshold(self) -> float:
        return 0.0  # always converge


class _FullTheme(_MinimalTheme):
    """Theme with 5 lenses including final_synthesis."""

    def get_lenses(self) -> list[AnalyticalLens]:
        return [
            AnalyticalLens(name="basic_bars", iteration=1, description="test", required_data=["minute_bars"]),
            AnalyticalLens(name="volume_profile", iteration=2, description="test", required_data=["minute_bars"]),
            AnalyticalLens(name="final_synthesis", iteration=3, description="skipped", required_data=[]),
        ]

    def get_review_modules(self) -> list[str]:
        return ["selection", "entry", "exit", "failure"]


class _TickDataTheme(_MinimalTheme):
    def get_lenses(self) -> list[AnalyticalLens]:
        return [AnalyticalLens(name="bid_ask_spread", iteration=1, description="test", required_data=["tick_data"])]


def _mock_market_data() -> MagicMock:
    md = MagicMock(spec=MarketDataService)
    bars = _make_bars(50)
    md.get_minute_bars.return_value = bars
    md.get_premarket_bars.return_value = []
    md.get_daily_bars.return_value = []
    md.get_spy_bars.return_value = bars
    md.get_qqq_bars.return_value = bars
    md.get_sector_peer_bars.return_value = {}
    md.get_ticker_details.return_value = TickerDetails(symbol="TEST")
    md.get_news.return_value = []
    md.get_tick_quotes.return_value = []
    md.find_similar_signals.return_value = []
    return md


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIterativeAnalyzer:
    def test_analyze_returns_results(self):
        md = _mock_market_data()
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        results, tracker, module_findings = analyzer.analyze(trade)

        assert len(results) == 3  # 3 lenses
        assert "selection" in module_findings
        assert "entry" in module_findings
        assert "exit" in module_findings
        # Each module should have findings for each iteration
        assert len(module_findings["selection"]) == 3
        assert len(module_findings["entry"]) == 3

    def test_analyze_caches_data(self):
        md = _mock_market_data()
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        analyzer.analyze(trade)

        # minute_bars is needed by basic_bars and volume_profile — but should only be fetched once
        assert md.get_minute_bars.call_count == 1

    def test_analyze_skips_final_synthesis(self):
        md = _mock_market_data()
        theme = _FullTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        results, _, _ = analyzer.analyze(trade)

        # final_synthesis should be skipped — only 2 iterations should run
        assert len(results) == 2
        assert all(r.lens.name != "final_synthesis" for r in results)

    def test_analyze_skips_failure_for_non_stranded(self):
        md = _mock_market_data()
        theme = _FullTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade(outcome=TradeOutcome.TP_FILLED)

        _, _, module_findings = analyzer.analyze(trade)

        # failure module should have no findings (skipped for TP_FILLED)
        assert all(len(f.observations) == 0 and len(f.metrics) == 0 for f in module_findings.get("failure", []) if f.observations or f.metrics) or len(module_findings.get("failure", [])) == 0

    def test_analyze_runs_failure_for_stranded(self):
        md = _mock_market_data()
        theme = _FullTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade(outcome=TradeOutcome.STRANDED)
        trade.exit = None

        _, _, module_findings = analyzer.analyze(trade)

        # failure module should have findings
        assert len(module_findings.get("failure", [])) > 0

    def test_convergence_stops_early(self):
        md = _mock_market_data()
        theme = _ConvergingTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        results, _, _ = analyzer.analyze(trade)

        # Should converge at iteration 1 (threshold=0.0 means always converge)
        # But iteration 1 may not converge if confidence is 0 and threshold is 0 (0 >= 0 is True)
        # The loop should stop at iteration 1
        assert len(results) <= 2  # at most iteration 1 plus potentially one more

    def test_hypothesis_seeding(self):
        md = _mock_market_data()
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        _, tracker, _ = analyzer.analyze(trade)

        # Should have seeded hypotheses based on signal score >= 8.0
        sel_hyps = tracker.get_hypotheses("selection")
        assert len(sel_hyps) >= 1
        assert any("Strong signal" in h.statement for h in sel_hyps)

    def test_hypothesis_seeding_weak_signal(self):
        md = _mock_market_data()
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()
        trade.signal.score = 3.0

        _, tracker, _ = analyzer.analyze(trade)

        sel_hyps = tracker.get_hypotheses("selection")
        assert any("Weak signal" in h.statement for h in sel_hyps)

    def test_hypothesis_seeding_stranded(self):
        md = _mock_market_data()
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade(outcome=TradeOutcome.STRANDED)
        trade.exit = None

        _, tracker, _ = analyzer.analyze(trade)

        exit_hyps = tracker.get_hypotheses("exit")
        assert any("TP never reached" in h.statement for h in exit_hyps)

    def test_data_fetch_handles_failure_gracefully(self):
        md = _mock_market_data()
        md.get_minute_bars.side_effect = Exception("API down")
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        # Should not raise — just logs and returns empty data
        results, _, _ = analyzer.analyze(trade)
        assert len(results) == 3  # all iterations still run

    def test_tick_data_fetch_uses_quotes(self):
        md = _mock_market_data()
        theme = _TickDataTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        analyzer.analyze(trade)

        md.get_tick_quotes.assert_called_once()
        md.get_tick_trades.assert_not_called()

    def test_all_day_trades_passed_through(self):
        md = _mock_market_data()

        class _ParsedTradesTheme(_MinimalTheme):
            def get_lenses(self):
                return [AnalyticalLens(name="same_day_signals", iteration=1, description="test", required_data=["parsed_trades"])]

        theme = _ParsedTradesTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()
        other_trade = _make_trade()
        other_trade.symbol = "OTHER"

        results, _, _ = analyzer.analyze(trade, all_day_trades=[trade, other_trade])
        # parsed_trades data key should return the all_day_trades list
        assert len(results) == 1

    def test_iteration_result_structure(self):
        md = _mock_market_data()
        theme = _MinimalTheme()
        analyzer = IterativeAnalyzer(md, theme)
        trade = _make_trade()

        results, _, _ = analyzer.analyze(trade)

        for result in results:
            assert result.iteration >= 1
            assert result.lens is not None
            assert isinstance(result.findings, dict)
            assert isinstance(result.cumulative_confidence, float)
