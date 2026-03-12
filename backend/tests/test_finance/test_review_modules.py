"""Tests for the 4 review modules — selection, entry, exit, failure compute_metrics() and synthesize()."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from src.community.finance import entry_review, exit_review, failure_review, selection_review
from src.community.finance.models import (
    AnalyticalLens,
    EntryEvent,
    EntryVerdict,
    ExitEvent,
    ExitPolicy,
    ExitVerdict,
    FailureVerdict,
    MinuteBar,
    NewsItem,
    ParsedTrade,
    QuantitativeFindings,
    SelectionVerdict,
    Signal,
    SignalType,
    TickerDetails,
    TradeOutcome,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_ENTRY_TS = datetime(2026, 3, 5, 9, 36, 0)
_SIGNAL_TS = datetime(2026, 3, 5, 9, 35, 0)


def _signal(score: float = 8.0, pwin: float = 85.0, dd: float = 1.0, tvr: float = 12.0) -> Signal:
    return Signal(timestamp=_SIGNAL_TS, symbol="TEST", signal_type=SignalType.MAIN, score=score, pwin=pwin, bars=100, ret5m_predicted=3.5, dd_predicted=dd, tvr=tvr, raw_line="test")


def _entry(price: float = 10.0, qty: int = 100) -> EntryEvent:
    return EntryEvent(timestamp=_ENTRY_TS, symbol="TEST", price=price, quantity=qty)


def _exit(price: float = 10.5) -> ExitEvent:
    return ExitEvent(timestamp=_ENTRY_TS + timedelta(minutes=24), symbol="TEST", price=price)


def _trade(
    *,
    score: float = 8.0,
    pwin: float = 85.0,
    entry_price: float = 10.0,
    exit_price: float | None = 10.5,
    outcome: TradeOutcome = TradeOutcome.TP_FILLED,
    tp_price: float | None = 10.5,
) -> ParsedTrade:
    t = ParsedTrade(
        trading_date=date(2026, 3, 5),
        symbol="TEST",
        signal=_signal(score=score, pwin=pwin),
        entry=_entry(price=entry_price),
        outcome=outcome,
        tp_price=tp_price,
    )
    if exit_price is not None:
        t.exit = _exit(price=exit_price)
    return t


def _minute_bar(ts: datetime, o: float = 10.0, h: float = 10.5, l: float = 9.8, c: float = 10.2, vol: int = 1000) -> MinuteBar:  # noqa: E741
    return MinuteBar(timestamp=ts, timestamp_ns=int(ts.timestamp() * 1e9), open=o, high=h, low=l, close=c, volume=vol)


def _bars_around_entry(n_pre: int = 10, n_post: int = 30, entry_ts: datetime = _ENTRY_TS) -> list[MinuteBar]:
    bars: list[MinuteBar] = []
    for i in range(-n_pre, n_post):
        ts = entry_ts + timedelta(minutes=i)
        # Rising then flat price pattern
        price = 9.8 + i * 0.02 if i < 0 else 10.0 + i * 0.01
        bars.append(_minute_bar(ts, o=price, h=price + 0.1, l=price - 0.05, c=price + 0.05, vol=1000 + abs(i) * 100))
    return bars


def _lens(name: str, iteration: int = 1) -> AnalyticalLens:
    return AnalyticalLens(name=name, iteration=iteration, description=f"Test lens {name}")


# ---------------------------------------------------------------------------
# Selection review
# ---------------------------------------------------------------------------


class TestSelectionComputeMetrics:
    def test_basic_bars_strong_signal(self):
        trade = _trade(score=10.0, pwin=90.0)
        findings = selection_review.compute_metrics(trade, _lens("basic_bars"), {})
        assert findings.metrics["score"] == 10.0
        assert any("Strong" in o for o in findings.observations)

    def test_basic_bars_weak_signal(self):
        trade = _trade(score=3.0, pwin=40.0)
        findings = selection_review.compute_metrics(trade, _lens("basic_bars"), {})
        assert any("Weak" in o for o in findings.observations)
        assert any("Low predicted win" in o for o in findings.observations)

    def test_basic_bars_high_dd(self):
        trade = _trade()
        trade.signal.dd_predicted = 5.0
        findings = selection_review.compute_metrics(trade, _lens("basic_bars"), {})
        assert any("drawdown" in o.lower() for o in findings.observations)

    def test_no_signal(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", entry=_entry())
        findings = selection_review.compute_metrics(trade, _lens("basic_bars"), {})
        assert any("No signal" in o for o in findings.observations)

    def test_volume_profile_acceleration(self):
        trade = _trade()
        bars = _bars_around_entry(n_pre=10, n_post=10)
        # Make post-entry volume much higher
        for b in bars:
            if b.timestamp >= _ENTRY_TS:
                b.volume = 5000
        findings = selection_review.compute_metrics(trade, _lens("volume_profile"), {"minute_bars": bars})
        assert findings.metrics.get("volume_ratio_post_pre", 0) > 1.0

    def test_market_context_spy_down(self):
        trade = _trade()
        spy_bars = [
            _minute_bar(_ENTRY_TS - timedelta(minutes=6), o=450.0, h=450.5, l=449.5, c=450.0),
            _minute_bar(_ENTRY_TS, o=445.0, h=445.5, l=444.0, c=444.0),
        ]
        findings = selection_review.compute_metrics(trade, _lens("market_context"), {"spy_bars": spy_bars, "qqq_bars": []})
        assert findings.metrics.get("spy_change_at_entry_pct", 0) < 0

    def test_premarket_heavy_volume(self):
        trade = _trade()
        pm_bars = [_minute_bar(_ENTRY_TS - timedelta(hours=2), vol=300_000) for _ in range(3)]
        findings = selection_review.compute_metrics(trade, _lens("premarket_activity"), {"premarket_bars": pm_bars})
        assert findings.metrics["premarket_volume"] == 900_000
        assert any("Heavy premarket" in o for o in findings.observations)

    def test_news_sentiment_negative(self):
        trade = _trade()
        news = [
            NewsItem(title="Bad news", sentiment="negative"),
            NewsItem(title="More bad", sentiment="negative"),
            NewsItem(title="OK news", sentiment="neutral"),
        ]
        findings = selection_review.compute_metrics(trade, _lens("news_sentiment"), {"news": news})
        assert findings.metrics["news_negative_count"] == 2
        assert any("Negative" in o for o in findings.observations)

    def test_float_liquidity_high_turnover(self):
        trade = _trade()
        details = TickerDetails(symbol="TEST", float_shares=5_000_000)
        findings = selection_review.compute_metrics(trade, _lens("float_liquidity"), {"ticker_details": details})
        assert findings.metrics.get("float_turnover_ratio", 0) > 1.0


class TestSelectionSynthesize:
    def test_should_trade_with_good_signal(self):
        trade = _trade(score=10.0, pwin=90.0)
        findings = [QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={"score": 10.0, "pwin": 90.0}, confidence=0.8)]
        verdict = selection_review.synthesize(trade, findings)
        assert isinstance(verdict, SelectionVerdict)
        assert verdict.should_trade is True

    def test_should_not_trade_with_weak_signal(self):
        trade = _trade(score=3.0, pwin=30.0)
        findings = [QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={}, confidence=0.5)]
        verdict = selection_review.synthesize(trade, findings)
        assert verdict.should_trade is False

    def test_adverse_market(self):
        trade = _trade()
        findings = [QuantitativeFindings(lens_name="market_context", iteration=7, metrics={"spy_change_at_entry_pct": -2.0}, confidence=0.6)]
        verdict = selection_review.synthesize(trade, findings)
        assert any("Adverse market" in r for r in verdict.reasons)


# ---------------------------------------------------------------------------
# Entry review
# ---------------------------------------------------------------------------


class TestEntryComputeMetrics:
    def test_basic_bars_position_in_bar(self):
        trade = _trade(entry_price=10.4)
        bars = _bars_around_entry()
        findings = entry_review.compute_metrics(trade, _lens("basic_bars"), {"minute_bars": bars})
        assert "entry_bar_open" in findings.metrics or "entry_position_in_bar" in findings.metrics

    def test_no_entry_skips(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST", signal=_signal())
        findings = entry_review.compute_metrics(trade, _lens("basic_bars"), {})
        assert any("No entry" in o for o in findings.observations)

    def test_vwap_analysis_above_vwap(self):
        trade = _trade(entry_price=10.5)
        # Create bars where VWAP ends up around 10.0
        bars = [_minute_bar(_ENTRY_TS - timedelta(minutes=i), o=9.8, h=10.0, l=9.6, c=9.8, vol=5000) for i in range(10, 0, -1)]
        findings = entry_review.compute_metrics(trade, _lens("vwap_analysis"), {"minute_bars": bars})
        if findings.metrics.get("vwap_at_entry"):
            assert findings.metrics["entry_vs_vwap_pct"] > 0

    def test_price_micropattern_uptrend(self):
        trade = _trade()
        bars = []
        for i in range(8):
            ts = _ENTRY_TS - timedelta(minutes=8 - i)
            bars.append(_minute_bar(ts, o=9.5 + i * 0.1, h=9.6 + i * 0.1, l=9.4 + i * 0.1, c=9.55 + i * 0.1))
        findings = entry_review.compute_metrics(trade, _lens("price_micropattern"), {"minute_bars": bars})
        assert findings.metrics.get("pre_entry_higher_close_count", 0) >= 3

    def test_time_of_day_early_session(self):
        trade = _trade()
        findings = entry_review.compute_metrics(trade, _lens("time_of_day_edge"), {})
        assert findings.metrics["minutes_after_open"] == 6  # 9:36 - 9:30

    def test_alt_tp_sl_sim_optimal_entry(self):
        trade = _trade(entry_price=10.0)
        bars = []
        # After signal: price dips to 9.7 within 15 min
        for i in range(20):
            ts = _SIGNAL_TS + timedelta(minutes=i)
            price = 10.0 - 0.03 * i if i < 10 else 9.7 + 0.02 * (i - 10)
            bars.append(_minute_bar(ts, o=price, h=price + 0.05, l=price - 0.05, c=price))
        findings = entry_review.compute_metrics(trade, _lens("alt_tp_sl_sim"), {"minute_bars": bars})
        if findings.metrics.get("optimal_entry_in_15min_window"):
            assert findings.metrics["entry_vs_optimal_slippage_pct"] > 0

    def test_bid_ask_spread_uses_polygon_quote_fields(self):
        trade = _trade(entry_price=10.0)
        findings = entry_review.compute_metrics(
            trade,
            _lens("bid_ask_spread"),
            {"tick_data": [{"bid_price": 9.9, "ask_price": 10.1}, {"bid_price": 9.95, "ask_price": 10.15}]},
        )
        assert findings.metrics["avg_spread_at_entry"] > 0
        assert findings.metrics["spread_pct"] > 1.0

    def test_bid_ask_spread_supports_legacy_field_names(self):
        trade = _trade(entry_price=10.0)
        findings = entry_review.compute_metrics(trade, _lens("bid_ask_spread"), {"tick_data": [{"bid": 9.9, "ask": 10.1}]})
        assert findings.metrics["avg_spread_at_entry"] == pytest.approx(0.2)


class TestEntrySynthesize:
    def test_acceptable_entry(self):
        trade = _trade()
        findings = [QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={}, observations=["Entry timing: acceptable"], confidence=0.5)]
        verdict = entry_review.synthesize(trade, findings)
        assert isinstance(verdict, EntryVerdict)
        assert verdict.should_have_waited is False

    def test_should_have_waited(self):
        trade = _trade()
        findings = [QuantitativeFindings(lens_name="alt_tp_sl_sim", iteration=14, metrics={"optimal_entry_in_15min_window": 9.5, "entry_vs_optimal_slippage_pct": 5.0}, confidence=0.7)]
        verdict = entry_review.synthesize(trade, findings)
        assert verdict.should_have_waited is True
        assert verdict.optimal_entry_price == 9.5


# ---------------------------------------------------------------------------
# Exit review
# ---------------------------------------------------------------------------


class TestExitComputeMetrics:
    def test_basic_bars_mfe_mae(self):
        trade = _trade(entry_price=10.0, exit_price=10.5)
        bars = _bars_around_entry(n_pre=0, n_post=30)
        findings = exit_review.compute_metrics(trade, _lens("basic_bars"), {"minute_bars": bars})
        assert "mfe_pct" in findings.metrics
        assert "mae_pct" in findings.metrics

    def test_tp_sl_simulation(self):
        trade = _trade(entry_price=10.0)
        bars = _bars_around_entry(n_pre=0, n_post=100)
        findings = exit_review.compute_metrics(trade, _lens("alt_tp_sl_sim"), {"minute_bars": bars})
        sims = findings.metrics.get("tp_sl_simulations", {})
        assert len(sims) > 0
        assert "best_tp_sl_combo" in findings.metrics

    def test_trailing_stop_simulation(self):
        trade = _trade(entry_price=10.0)
        bars = _bars_around_entry(n_pre=0, n_post=50)
        findings = exit_review.compute_metrics(trade, _lens("trailing_stop_sim"), {"minute_bars": bars})
        assert "trailing_stop_simulations" in findings.metrics

    def test_time_exit_simulation(self):
        trade = _trade(entry_price=10.0)
        bars = _bars_around_entry(n_pre=0, n_post=150)
        findings = exit_review.compute_metrics(trade, _lens("time_exit_sim"), {"minute_bars": bars})
        assert "time_exit_simulations" in findings.metrics

    def test_no_entry_skips(self):
        trade = ParsedTrade(trading_date=date(2026, 3, 5), symbol="TEST")
        findings = exit_review.compute_metrics(trade, _lens("basic_bars"), {})
        assert any("No entry" in o for o in findings.observations)


class TestExitSynthesize:
    def test_recommends_trailing_stop(self):
        trade = _trade()
        findings = [
            QuantitativeFindings(lens_name="alt_tp_sl_sim", iteration=14, metrics={"best_tp_sl_pnl": 3.0, "best_tp_sl_combo": "tp5_sl3"}, confidence=0.6),
            QuantitativeFindings(lens_name="trailing_stop_sim", iteration=15, metrics={"best_trailing_pnl": 5.0, "best_trailing_combo": "trail_2pct"}, confidence=0.6),
            QuantitativeFindings(lens_name="time_exit_sim", iteration=16, metrics={"best_time_exit_pnl": 2.0}, confidence=0.5),
        ]
        verdict = exit_review.synthesize(trade, findings)
        assert isinstance(verdict, ExitVerdict)
        assert verdict.recommended_policy == ExitPolicy.TRAILING_STOP

    def test_recommends_fixed_tp(self):
        trade = _trade()
        findings = [
            QuantitativeFindings(lens_name="alt_tp_sl_sim", iteration=14, metrics={"best_tp_sl_pnl": 5.0, "best_tp_sl_combo": "tp5_sl3"}, confidence=0.6),
            QuantitativeFindings(lens_name="trailing_stop_sim", iteration=15, metrics={"best_trailing_pnl": 2.0}, confidence=0.6),
        ]
        verdict = exit_review.synthesize(trade, findings)
        assert verdict.recommended_policy == ExitPolicy.FIXED_TP

    def test_hybrid_when_all_negative(self):
        trade = _trade()
        findings = [
            QuantitativeFindings(lens_name="alt_tp_sl_sim", iteration=14, metrics={"best_tp_sl_pnl": -1.0, "best_tp_sl_combo": "tp2_sl2"}, confidence=0.4),
        ]
        verdict = exit_review.synthesize(trade, findings)
        assert verdict.recommended_policy == ExitPolicy.HYBRID


# ---------------------------------------------------------------------------
# Failure review
# ---------------------------------------------------------------------------


class TestFailureComputeMetrics:
    def test_basic_bars_stranded(self):
        trade = _trade(exit_price=None, outcome=TradeOutcome.STRANDED, tp_price=10.5)
        bars = _bars_around_entry(n_pre=0, n_post=30)
        # Make price decline
        for i, b in enumerate(bars):
            b.close = 10.0 - i * 0.05
            b.low = b.close - 0.1
            b.high = b.close + 0.05
        findings = failure_review.compute_metrics(trade, _lens("basic_bars"), {"minute_bars": bars})
        assert findings.metrics.get("unrealized_pnl_pct", 0) < 0
        assert any("Stranded" in o for o in findings.observations)

    def test_skips_for_non_stranded(self):
        trade = _trade(outcome=TradeOutcome.TP_FILLED)
        bars = _bars_around_entry(n_pre=0, n_post=10)
        findings = failure_review.compute_metrics(trade, _lens("volume_profile"), {"minute_bars": bars})
        # volume_profile lens skips for non-stranded (no volume_decay_ratio)
        assert "volume_decay_ratio" not in findings.metrics

    def test_death_pattern(self):
        trade = _trade(exit_price=None, outcome=TradeOutcome.STRANDED)
        bars = []
        for i in range(20):
            ts = _ENTRY_TS + timedelta(minutes=i)
            price = 10.0 - i * 0.05  # consistently declining
            bars.append(_minute_bar(ts, o=price + 0.02, h=price + 0.03, l=price - 0.02, c=price))
        findings = failure_review.compute_metrics(trade, _lens("price_micropattern"), {"minute_bars": bars})
        assert findings.metrics.get("lower_highs_last_10", 0) >= 5

    def test_volume_decay(self):
        trade = _trade(exit_price=None, outcome=TradeOutcome.STRANDED)
        bars = []
        for i in range(20):
            ts = _ENTRY_TS + timedelta(minutes=i)
            vol = 5000 if i < 10 else 500  # volume dies in second half
            bars.append(_minute_bar(ts, vol=vol))
        findings = failure_review.compute_metrics(trade, _lens("volume_profile"), {"minute_bars": bars})
        assert findings.metrics.get("volume_decay_ratio", 1.0) < 0.5


class TestFailureSynthesize:
    def test_should_exit_now(self):
        trade = _trade(exit_price=None, outcome=TradeOutcome.STRANDED)
        findings = [
            QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={"unrealized_pnl_pct": -8.0, "max_drawdown_from_entry_pct": 12.0, "last_price": 9.2}, confidence=0.7),
            QuantitativeFindings(lens_name="volume_profile", iteration=2, metrics={"volume_decay_ratio": 0.2}, confidence=0.5),
            QuantitativeFindings(lens_name="vwap_analysis", iteration=4, metrics={"pct_vs_vwap_current": -6.0}, confidence=0.6),
        ]
        verdict = failure_review.synthesize(trade, findings)
        assert isinstance(verdict, FailureVerdict)
        assert verdict.should_exit_now is True
        assert verdict.bounce_probability < 0.5

    def test_non_stranded_returns_empty_verdict(self):
        trade = _trade(outcome=TradeOutcome.TP_FILLED)
        findings = [QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={}, confidence=0.5)]
        verdict = failure_review.synthesize(trade, findings)
        assert verdict.should_exit_now is False

    def test_max_hold_hours_decreases_with_urgency(self):
        trade = _trade(exit_price=None, outcome=TradeOutcome.STRANDED)
        mild = [QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={"unrealized_pnl_pct": -1.0, "max_drawdown_from_entry_pct": 2.0, "last_price": 9.9}, confidence=0.4)]
        severe = [QuantitativeFindings(lens_name="basic_bars", iteration=1, metrics={"unrealized_pnl_pct": -10.0, "max_drawdown_from_entry_pct": 15.0, "last_price": 9.0}, confidence=0.8)]
        verdict_mild = failure_review.synthesize(trade, mild)
        verdict_severe = failure_review.synthesize(trade, severe)
        assert verdict_mild.max_hold_hours > verdict_severe.max_hold_hours


# ---------------------------------------------------------------------------
# Exit simulation helpers (white-box tests)
# ---------------------------------------------------------------------------


class TestSimulationHelpers:
    def test_simulate_exit_tp_hit(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.4, l=9.9, c=10.3),
            _minute_bar(_ENTRY_TS + timedelta(minutes=1), o=10.3, h=10.6, l=10.2, c=10.5),
        ]
        result = exit_review._simulate_exit(bars, entry_price=10.0, tp_price=10.5, sl_price=9.5)
        assert result["exit_type"] == "tp"
        assert result["bars_held"] == 2

    def test_simulate_exit_sl_hit(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.1, l=9.4, c=9.5),
        ]
        result = exit_review._simulate_exit(bars, entry_price=10.0, tp_price=11.0, sl_price=9.5)
        assert result["exit_type"] == "sl"

    def test_simulate_exit_eod(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.2, l=9.9, c=10.1),
            _minute_bar(_ENTRY_TS + timedelta(minutes=1), o=10.1, h=10.2, l=10.0, c=10.1),
        ]
        result = exit_review._simulate_exit(bars, entry_price=10.0, tp_price=12.0, sl_price=8.0)
        assert result["exit_type"] == "eod"

    def test_simulate_exit_uses_actual_entry_price(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=9.5, h=10.6, l=9.5, c=10.4),
        ]
        result = exit_review._simulate_exit(bars, entry_price=10.0, tp_price=10.5, sl_price=9.0)
        assert result["pnl_pct"] == 5.0

    def test_simulate_exit_prefers_stop_on_same_bar_collision(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.6, l=9.4, c=10.1),
        ]
        result = exit_review._simulate_exit(bars, entry_price=10.0, tp_price=10.5, sl_price=9.5)
        assert result["exit_type"] == "sl"

    def test_simulate_trailing_stop(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.5, l=10.0, c=10.4),
            _minute_bar(_ENTRY_TS + timedelta(minutes=1), o=10.4, h=10.8, l=10.3, c=10.7),
            _minute_bar(_ENTRY_TS + timedelta(minutes=2), o=10.7, h=10.7, l=10.0, c=10.3),  # drops, trail triggers
        ]
        result = exit_review._simulate_trailing_stop(bars, entry_price=10.0, trail_pct=0.05)
        assert result["peak"] == 10.8
        # With 5% trail from 10.8, stop at 10.26 — bar 3 low is 10.2 which hits it
        assert result["pnl_pct"] > 0

    def test_simulate_trailing_stop_uses_prior_peak_within_bar(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.5, l=10.0, c=10.4),
            _minute_bar(_ENTRY_TS + timedelta(minutes=1), o=10.4, h=10.8, l=9.9, c=10.2),
        ]
        result = exit_review._simulate_trailing_stop(bars, entry_price=10.0, trail_pct=0.05)
        assert result["peak"] == 10.5
        assert result["exit_price"] == pytest.approx(9.975)

    def test_entry_aggregate_bars(self):
        bars = [_minute_bar(_ENTRY_TS + timedelta(minutes=i), o=10.0 + i * 0.01, h=10.1 + i * 0.01, l=9.9, c=10.0 + i * 0.01, vol=1000) for i in range(10)]
        agg = entry_review._aggregate_bars(bars, 5)
        assert len(agg) == 2
        assert agg[0].volume == 5000

    def test_entry_compute_vwap_at(self):
        bars = [
            _minute_bar(_ENTRY_TS, o=10.0, h=10.5, l=9.5, c=10.0, vol=1000),
            _minute_bar(_ENTRY_TS + timedelta(minutes=1), o=10.0, h=11.0, l=9.0, c=10.5, vol=2000),
        ]
        vwap = entry_review._compute_vwap_at(bars, _ENTRY_TS + timedelta(minutes=2))
        assert vwap is not None
        assert vwap > 0
