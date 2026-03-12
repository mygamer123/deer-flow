# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from .models import (
    AnalyticalLens,
    EntryVerdict,
    MinuteBar,
    ParsedTrade,
    QuantitativeFindings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-math metrics
# ---------------------------------------------------------------------------


def compute_metrics(trade: ParsedTrade, lens: AnalyticalLens, data: dict[str, Any]) -> QuantitativeFindings:
    metrics: dict[str, Any] = {}
    observations: list[str] = []

    if trade.entry is None:
        return QuantitativeFindings(lens_name=lens.name, iteration=lens.iteration, observations=["No entry — skipping entry review"])

    entry_price = trade.entry.price
    entry_ts = trade.entry.timestamp

    if lens.name == "basic_bars":
        minute_bars: list[MinuteBar] = data.get("minute_bars", [])
        if minute_bars:
            bar_at_entry = _find_bar_at(minute_bars, entry_ts)
            if bar_at_entry:
                metrics["entry_bar_open"] = bar_at_entry.open
                metrics["entry_bar_high"] = bar_at_entry.high
                metrics["entry_bar_low"] = bar_at_entry.low
                metrics["entry_bar_close"] = bar_at_entry.close
                metrics["entry_bar_volume"] = bar_at_entry.volume

                bar_range = bar_at_entry.high - bar_at_entry.low
                if bar_at_entry.low > 0:
                    metrics["entry_bar_range_pct"] = bar_range / bar_at_entry.low * 100

                # Did we buy near the high of the bar?
                if bar_range > 0:
                    position_in_bar = (entry_price - bar_at_entry.low) / bar_range
                    metrics["entry_position_in_bar"] = position_in_bar
                    if position_in_bar > 0.8:
                        observations.append(f"Entered near bar high ({position_in_bar:.0%} of range)")
                    elif position_in_bar < 0.3:
                        observations.append(f"Entered near bar low ({position_in_bar:.0%} of range)")

    elif lens.name == "price_micropattern":
        minute_bars = data.get("minute_bars", [])
        if minute_bars and entry_ts:
            # Look at 5 bars before entry for pattern
            pre_bars = [b for b in minute_bars if b.timestamp < entry_ts][-5:]
            if len(pre_bars) >= 3:
                closes = [b.close for b in pre_bars]
                highs = [b.high for b in pre_bars]

                # Consecutive higher closes = uptrend
                higher_closes = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
                metrics["pre_entry_higher_close_count"] = higher_closes

                # New highs in pre-entry bars
                running_high = highs[0]
                new_high_count = 0
                for h in highs[1:]:
                    if h > running_high:
                        new_high_count += 1
                        running_high = h
                metrics["pre_entry_new_high_count"] = new_high_count

                if higher_closes >= 3:
                    observations.append("Strong uptrend into entry (3+ consecutive higher closes)")
                elif higher_closes == 0:
                    observations.append("No upward momentum into entry — bought into weakness")

    elif lens.name == "vwap_analysis":
        minute_bars = data.get("minute_bars", [])
        if minute_bars and entry_ts:
            vwap = _compute_vwap_at(minute_bars, entry_ts)
            if vwap and vwap > 0:
                metrics["vwap_at_entry"] = vwap
                metrics["entry_vs_vwap_pct"] = (entry_price - vwap) / vwap * 100
                if entry_price > vwap * 1.02:
                    observations.append(f"Entered {(entry_price / vwap - 1) * 100:.1f}% above VWAP — chasing")
                elif entry_price < vwap:
                    observations.append("Entered below VWAP — favorable relative value")

    elif lens.name == "bid_ask_spread":
        tick_data: list[dict[str, Any]] = data.get("tick_data", [])
        if tick_data:
            spreads = []
            for t in tick_data:
                ask = t.get("ask_price", t.get("ask", 0))
                bid = t.get("bid_price", t.get("bid", 0))
                if ask and bid:
                    spreads.append(ask - bid)
            if spreads:
                avg_spread = sum(spreads) / len(spreads)
                metrics["avg_spread_at_entry"] = avg_spread
                if entry_price > 0:
                    metrics["spread_pct"] = avg_spread / entry_price * 100
                    if metrics["spread_pct"] > 1.0:
                        observations.append(f"Wide spread at entry ({metrics['spread_pct']:.2f}%) — poor liquidity")

    elif lens.name == "multi_timeframe":
        minute_bars = data.get("minute_bars", [])
        if minute_bars:
            # 5-min aggregation around entry
            bars_5m = _aggregate_bars(minute_bars, 5)
            bar_5m_at_entry = _find_bar_at(bars_5m, entry_ts) if bars_5m else None
            if bar_5m_at_entry:
                metrics["entry_5m_bar_volume"] = bar_5m_at_entry.volume
                metrics["entry_5m_bar_range_pct"] = (bar_5m_at_entry.high - bar_5m_at_entry.low) / max(bar_5m_at_entry.low, 0.01) * 100

    elif lens.name == "time_of_day_edge":
        if entry_ts:
            minutes_after_open = (entry_ts.hour - 9) * 60 + (entry_ts.minute - 30)
            if entry_ts.hour < 9 or (entry_ts.hour == 9 and entry_ts.minute < 30):
                minutes_after_open = -(930 - entry_ts.hour * 100 - entry_ts.minute)
            metrics["minutes_after_open"] = minutes_after_open
            if minutes_after_open < 0:
                observations.append("Pre-market entry")
            elif minutes_after_open <= 15:
                observations.append("Early session entry (first 15 min) — high volatility window")
            elif minutes_after_open > 120:
                observations.append("Late session entry (2+ hours after open) — momentum may be exhausted")

    elif lens.name == "previous_day":
        daily_bars: list[MinuteBar] = data.get("daily_bars", [])
        if daily_bars and len(daily_bars) >= 2:
            prev_day = daily_bars[-2]
            metrics["prev_close"] = prev_day.close
            metrics["prev_volume"] = prev_day.volume
            prev_range = (prev_day.high - prev_day.low) / max(prev_day.low, 0.01) * 100
            metrics["prev_day_range_pct"] = prev_range

    # -- optimal entry search: scan bars after signal for best entry ------
    elif lens.name == "alt_tp_sl_sim":
        minute_bars = data.get("minute_bars", [])
        if minute_bars and trade.signal:
            signal_ts = trade.signal.timestamp
            # Window: signal time to 15 minutes after signal
            window_end = signal_ts + timedelta(minutes=15)
            window_bars = [b for b in minute_bars if signal_ts <= b.timestamp <= window_end]
            if window_bars:
                lowest_in_window = min(b.low for b in window_bars)
                metrics["optimal_entry_in_15min_window"] = lowest_in_window
                if entry_price > 0:
                    slippage = (entry_price - lowest_in_window) / entry_price * 100
                    metrics["entry_vs_optimal_slippage_pct"] = slippage
                    if slippage > 1.0:
                        observations.append(f"Could have entered {slippage:.1f}% lower within 15 min of signal")

    return QuantitativeFindings(
        lens_name=lens.name,
        iteration=lens.iteration,
        metrics=metrics,
        observations=observations,
        confidence=_compute_confidence(metrics, observations),
    )


# ---------------------------------------------------------------------------
# LLM synthesis (runs ONCE after convergence)
# ---------------------------------------------------------------------------


def synthesize(trade: ParsedTrade, all_findings: list[QuantitativeFindings]) -> EntryVerdict:
    """Rule-based baseline — LLM enhancement in decision_review_service.py."""
    all_metrics: dict[str, Any] = {}
    all_observations: list[str] = []
    for f in all_findings:
        all_metrics.update(f.metrics)
        all_observations.extend(f.observations)

    verdict = EntryVerdict(reasons=list(all_observations))

    optimal_entry = all_metrics.get("optimal_entry_in_15min_window")
    if optimal_entry is not None and trade.entry:
        verdict.optimal_entry_price = optimal_entry
        slippage = all_metrics.get("entry_vs_optimal_slippage_pct", 0)
        verdict.actual_vs_optimal_slippage_pct = slippage
        verdict.should_have_waited = slippage > 1.0

    vwap_diff = all_metrics.get("entry_vs_vwap_pct")
    if vwap_diff is not None and vwap_diff > 2.0:
        verdict.should_have_waited = True
        verdict.reasons.append(f"Entry was {vwap_diff:.1f}% above VWAP — consider waiting for pullback")

    return verdict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_bar_at(bars: list[MinuteBar], target_ts: Any) -> MinuteBar | None:
    best: MinuteBar | None = None
    for b in bars:
        if b.timestamp <= target_ts:
            best = b
        else:
            break
    return best


def _compute_vwap_at(bars: list[MinuteBar], up_to_ts: Any) -> float | None:
    """Cumulative VWAP up to the given timestamp."""
    total_vol = 0
    total_pv = 0.0
    for b in bars:
        if b.timestamp > up_to_ts:
            break
        typical = (b.high + b.low + b.close) / 3
        total_pv += typical * b.volume
        total_vol += b.volume
    return total_pv / total_vol if total_vol > 0 else None


def _aggregate_bars(bars: list[MinuteBar], period: int) -> list[MinuteBar]:
    """Aggregate 1-min bars into *period*-min bars."""
    if not bars:
        return []
    result: list[MinuteBar] = []
    for i in range(0, len(bars), period):
        chunk = bars[i : i + period]
        result.append(
            MinuteBar(
                timestamp=chunk[0].timestamp,
                timestamp_ns=chunk[0].timestamp_ns,
                open=chunk[0].open,
                high=max(b.high for b in chunk),
                low=min(b.low for b in chunk),
                close=chunk[-1].close,
                volume=sum(b.volume for b in chunk),
                transactions=sum(b.transactions for b in chunk),
            )
        )
    return result


def _compute_confidence(metrics: dict[str, Any], observations: list[str]) -> float:
    if not metrics and not observations:
        return 0.0
    base = 0.3
    base += min(0.3, len(metrics) * 0.05)
    base += min(0.3, len(observations) * 0.1)
    return min(1.0, base)
