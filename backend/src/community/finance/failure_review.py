# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from typing import Any

from .models import (
    AnalyticalLens,
    FailureVerdict,
    MinuteBar,
    ParsedTrade,
    QuantitativeFindings,
    TradeOutcome,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-math metrics
# ---------------------------------------------------------------------------


def compute_metrics(trade: ParsedTrade, lens: AnalyticalLens, data: dict[str, Any]) -> QuantitativeFindings:
    metrics: dict[str, Any] = {}
    observations: list[str] = []

    if trade.entry is None:
        return QuantitativeFindings(lens_name=lens.name, iteration=lens.iteration, observations=["No entry — skipping failure review"])

    # Failure review is most relevant for stranded/open positions
    is_stranded = trade.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN)

    entry_price = trade.entry.price
    entry_ts = trade.entry.timestamp

    if lens.name == "basic_bars":
        minute_bars: list[MinuteBar] = data.get("minute_bars", [])
        if minute_bars:
            post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
            if post_entry:
                last_bar = post_entry[-1]
                current_pnl = (last_bar.close - entry_price) / entry_price * 100
                metrics["unrealized_pnl_pct"] = current_pnl
                metrics["last_price"] = last_bar.close
                metrics["bars_since_entry"] = len(post_entry)

                # How far did it drop from entry?
                min_low = min(b.low for b in post_entry)
                max_drawdown = (entry_price - min_low) / entry_price * 100
                metrics["max_drawdown_from_entry_pct"] = max_drawdown

                if is_stranded:
                    observations.append(f"Stranded position: unrealized PnL {current_pnl:+.2f}%, max DD {max_drawdown:.2f}%")

                    # Did it ever reach TP?
                    if trade.tp_price:
                        max_high = max(b.high for b in post_entry)
                        metrics["closest_to_tp_pct"] = (max_high - entry_price) / entry_price * 100
                        tp_pct = (trade.tp_price - entry_price) / entry_price * 100
                        metrics["tp_target_pct"] = tp_pct
                        gap_to_tp = tp_pct - metrics["closest_to_tp_pct"]
                        if gap_to_tp < 0.5:
                            observations.append(f"Came within {gap_to_tp:.2f}% of TP — near miss")

    elif lens.name == "volume_profile":
        minute_bars = data.get("minute_bars", [])
        if minute_bars and is_stranded:
            post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
            if post_entry:
                # Volume trend after entry — declining volume = drying up interest
                first_half = post_entry[: len(post_entry) // 2]
                second_half = post_entry[len(post_entry) // 2 :]
                vol_first = sum(b.volume for b in first_half) if first_half else 0
                vol_second = sum(b.volume for b in second_half) if second_half else 0

                if vol_first > 0:
                    vol_decay = vol_second / vol_first
                    metrics["volume_decay_ratio"] = vol_decay
                    if vol_decay < 0.5:
                        observations.append(f"Volume decayed to {vol_decay:.0%} of initial — interest dying")

    elif lens.name == "price_micropattern":
        minute_bars = data.get("minute_bars", [])
        if minute_bars and is_stranded:
            post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
            if len(post_entry) >= 10:
                # Check for death pattern: lower highs + lower lows
                last_10 = post_entry[-10:]
                highs = [b.high for b in last_10]
                lows = [b.low for b in last_10]

                lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
                lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

                metrics["lower_highs_last_10"] = lower_highs
                metrics["lower_lows_last_10"] = lower_lows

                if lower_highs >= 7 and lower_lows >= 5:
                    observations.append("Death pattern: consistent lower highs and lower lows — exit immediately")
                elif lower_highs >= 5:
                    observations.append("Weakening pattern: lower highs forming")

    elif lens.name == "vwap_analysis":
        minute_bars = data.get("minute_bars", [])
        if minute_bars and is_stranded:
            # Current price vs VWAP — if well below VWAP, recovery is unlikely
            cum_vol = 0
            cum_pv = 0.0
            last_vwap = 0.0
            for b in minute_bars:
                typical = (b.high + b.low + b.close) / 3
                cum_pv += typical * b.volume
                cum_vol += b.volume
                if cum_vol > 0:
                    last_vwap = cum_pv / cum_vol

            if last_vwap > 0 and minute_bars:
                last_close = minute_bars[-1].close
                pct_below_vwap = (last_close - last_vwap) / last_vwap * 100
                metrics["pct_vs_vwap_current"] = pct_below_vwap
                if pct_below_vwap < -3:
                    observations.append(f"Currently {pct_below_vwap:.1f}% below VWAP — recovery unlikely")

    elif lens.name == "market_context":
        spy_bars: list[MinuteBar] = data.get("spy_bars", [])
        if spy_bars:
            spy_open = spy_bars[0].open
            spy_close = spy_bars[-1].close
            spy_change = (spy_close - spy_open) / spy_open * 100
            metrics["spy_session_change_pct"] = spy_change
            if spy_change < -1.0 and is_stranded:
                observations.append(f"Broad market down {spy_change:.2f}% — stranded position may recover with market")

    elif lens.name == "news_sentiment":
        news_items = data.get("news", [])
        if news_items and is_stranded:
            negative_news = [n for n in news_items if hasattr(n, "sentiment") and n.sentiment == "negative"]
            if negative_news:
                metrics["negative_news_count"] = len(negative_news)
                observations.append(f"{len(negative_news)} negative news article(s) — fundamentals may be impaired")

    elif lens.name == "float_liquidity":
        ticker_details = data.get("ticker_details")
        if ticker_details and is_stranded:
            if ticker_details.shares_outstanding:
                metrics["shares_outstanding"] = ticker_details.shares_outstanding
            if ticker_details.float_shares and trade.entry:
                # Shares held as % of float
                shares_held_pct = (trade.entry.quantity / ticker_details.float_shares) * 100
                metrics["position_as_pct_of_float"] = shares_held_pct
                if shares_held_pct > 0.1:
                    observations.append(f"Holding {shares_held_pct:.3f}% of float — liquidity risk on exit")

    elif lens.name == "historical_similar":
        duckdb_results = data.get("duckdb", [])
        if duckdb_results and is_stranded:
            metrics["similar_historical_count"] = len(duckdb_results)

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


def synthesize(trade: ParsedTrade, all_findings: list[QuantitativeFindings]) -> FailureVerdict:
    """Rule-based baseline — LLM enhancement in decision_review_service.py."""
    all_metrics: dict[str, Any] = {}
    all_observations: list[str] = []
    for f in all_findings:
        all_metrics.update(f.metrics)
        all_observations.extend(f.observations)

    verdict = FailureVerdict(reasons=list(all_observations))

    is_stranded = trade.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN)
    if not is_stranded:
        return verdict

    unrealized_pnl = all_metrics.get("unrealized_pnl_pct", 0)
    max_dd = all_metrics.get("max_drawdown_from_entry_pct", 0)
    vol_decay = all_metrics.get("volume_decay_ratio", 1.0)
    pct_vs_vwap = all_metrics.get("pct_vs_vwap_current", 0)
    lower_highs = all_metrics.get("lower_highs_last_10", 0)

    # Scoring: accumulate exit urgency signals
    exit_signals = 0
    if unrealized_pnl < -5:
        exit_signals += 2
    elif unrealized_pnl < -2:
        exit_signals += 1

    if max_dd > 10:
        exit_signals += 2
    elif max_dd > 5:
        exit_signals += 1

    if vol_decay < 0.3:
        exit_signals += 2
    elif vol_decay < 0.5:
        exit_signals += 1

    if pct_vs_vwap < -5:
        exit_signals += 2
    elif pct_vs_vwap < -3:
        exit_signals += 1

    if lower_highs >= 7:
        exit_signals += 2

    verdict.should_exit_now = exit_signals >= 4
    verdict.bounce_probability = max(0.0, 1.0 - exit_signals * 0.12)
    verdict.max_hold_hours = max(1.0, 8.0 - exit_signals * 0.8)

    if trade.entry:
        last_price = all_metrics.get("last_price", trade.entry.price)
        # Suggest exiting at current market — don't try to recover
        verdict.recommended_exit_price = last_price

    return verdict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_confidence(metrics: dict[str, Any], observations: list[str]) -> float:
    if not metrics and not observations:
        return 0.0
    base = 0.3
    base += min(0.3, len(metrics) * 0.05)
    base += min(0.3, len(observations) * 0.1)
    return min(1.0, base)
