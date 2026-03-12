# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from typing import Any

from .models import (
    AnalyticalLens,
    MinuteBar,
    ParsedTrade,
    QuantitativeFindings,
    SelectionVerdict,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-math metrics (runs every iteration that has relevant data)
# ---------------------------------------------------------------------------


def compute_metrics(trade: ParsedTrade, lens: AnalyticalLens, data: dict[str, Any]) -> QuantitativeFindings:
    """Compute selection-related quantitative metrics for the given lens."""
    metrics: dict[str, Any] = {}
    observations: list[str] = []

    signal = trade.signal
    if signal is None:
        return QuantitativeFindings(lens_name=lens.name, iteration=lens.iteration, observations=["No signal data — cannot evaluate selection"])

    # -- basic signal quality metrics (available from iteration 1) ---------
    if lens.name == "basic_bars":
        metrics["score"] = signal.score
        metrics["pwin"] = signal.pwin
        metrics["bars_since_open"] = signal.bars
        metrics["ret5m_predicted"] = signal.ret5m_predicted
        metrics["dd_predicted"] = signal.dd_predicted
        metrics["tvr"] = signal.tvr

        if signal.score >= 8.0:
            observations.append(f"Strong signal score ({signal.score:.1f})")
        elif signal.score >= 5.0:
            observations.append(f"Moderate signal score ({signal.score:.1f})")
        else:
            observations.append(f"Weak signal score ({signal.score:.1f})")

        if signal.pwin >= 80:
            observations.append(f"High predicted win rate ({signal.pwin:.0f}%)")
        elif signal.pwin < 50:
            observations.append(f"Low predicted win rate ({signal.pwin:.0f}%)")

        if signal.dd_predicted > 3.0:
            observations.append(f"High predicted drawdown ({signal.dd_predicted:.1f}%) — risk flag")

    # -- volume profile around signal time --------------------------------
    elif lens.name == "volume_profile":
        minute_bars: list[MinuteBar] = data.get("minute_bars", [])
        if minute_bars and trade.entry:
            entry_ts = trade.entry.timestamp
            pre_entry = [b for b in minute_bars if b.timestamp < entry_ts]
            post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]

            pre_vol = sum(b.volume for b in pre_entry[-10:]) if pre_entry else 0
            post_vol = sum(b.volume for b in post_entry[:10]) if post_entry else 0

            metrics["pre_entry_10bar_volume"] = pre_vol
            metrics["post_entry_10bar_volume"] = post_vol
            metrics["volume_ratio_post_pre"] = post_vol / max(pre_vol, 1)

            if post_vol > pre_vol * 1.5:
                observations.append("Volume accelerated after entry — confirms momentum")
            elif post_vol < pre_vol * 0.5:
                observations.append("Volume dried up after entry — momentum fading")

    # -- market context (SPY/QQQ) -----------------------------------------
    elif lens.name == "market_context":
        spy_bars: list[MinuteBar] = data.get("spy_bars", [])
        qqq_bars: list[MinuteBar] = data.get("qqq_bars", [])
        if spy_bars and trade.entry:
            entry_ts = trade.entry.timestamp
            spy_at_entry = _find_bar_at(spy_bars, entry_ts)
            spy_open = spy_bars[0].open if spy_bars else 0
            if spy_at_entry and spy_open:
                spy_change = (spy_at_entry.close - spy_open) / spy_open * 100
                metrics["spy_change_at_entry_pct"] = spy_change
                if spy_change < -0.5:
                    observations.append(f"SPY was down {spy_change:.2f}% at entry — adverse market")
                elif spy_change > 0.5:
                    observations.append(f"SPY was up {spy_change:.2f}% at entry — supportive market")

        if qqq_bars and trade.entry:
            entry_ts = trade.entry.timestamp
            qqq_at_entry = _find_bar_at(qqq_bars, entry_ts)
            qqq_open = qqq_bars[0].open if qqq_bars else 0
            if qqq_at_entry and qqq_open:
                qqq_change = (qqq_at_entry.close - qqq_open) / qqq_open * 100
                metrics["qqq_change_at_entry_pct"] = qqq_change

    # -- sector peer comparison -------------------------------------------
    elif lens.name == "sector_peers":
        sector_bars: dict[str, list[MinuteBar]] = data.get("sector_bars", {})
        if sector_bars and trade.entry:
            peer_changes: dict[str, float] = {}
            for peer, bars in sector_bars.items():
                if bars and len(bars) >= 2:
                    peer_open = bars[0].open
                    entry_bar = _find_bar_at(bars, trade.entry.timestamp)
                    if entry_bar and peer_open:
                        peer_changes[peer] = (entry_bar.close - peer_open) / peer_open * 100
            metrics["peer_changes_at_entry"] = peer_changes
            if peer_changes:
                avg_peer = sum(peer_changes.values()) / len(peer_changes)
                metrics["avg_peer_change_pct"] = avg_peer
                if avg_peer < -0.5:
                    observations.append(f"Sector peers averaging {avg_peer:.2f}% — weak sector")

    # -- premarket activity -----------------------------------------------
    elif lens.name == "premarket_activity":
        premarket_bars: list[MinuteBar] = data.get("premarket_bars", [])
        if premarket_bars:
            pm_volume = sum(b.volume for b in premarket_bars)
            pm_high = max(b.high for b in premarket_bars)
            pm_low = min(b.low for b in premarket_bars)
            pm_range_pct = (pm_high - pm_low) / pm_low * 100 if pm_low > 0 else 0
            metrics["premarket_volume"] = pm_volume
            metrics["premarket_range_pct"] = pm_range_pct
            if pm_volume > 500_000:
                observations.append(f"Heavy premarket volume ({pm_volume:,}) — high interest")

    # -- gap analysis -----------------------------------------------------
    elif lens.name == "gap_analysis":
        daily_bars: list[MinuteBar] = data.get("daily_bars", [])
        minute_bars_list: list[MinuteBar] = data.get("minute_bars", [])
        if daily_bars and len(daily_bars) >= 2 and minute_bars_list:
            prev_close = daily_bars[-2].close
            today_open = minute_bars_list[0].open if minute_bars_list else daily_bars[-1].open
            gap_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0
            metrics["gap_pct"] = gap_pct
            if abs(gap_pct) > 5:
                observations.append(f"Large gap ({gap_pct:+.1f}%) — elevated volatility")

    # -- news sentiment ---------------------------------------------------
    elif lens.name == "news_sentiment":
        news_items = data.get("news", [])
        if news_items:
            sentiments = [n.sentiment for n in news_items if hasattr(n, "sentiment")]
            pos = sum(1 for s in sentiments if s == "positive")
            neg = sum(1 for s in sentiments if s == "negative")
            metrics["news_positive_count"] = pos
            metrics["news_negative_count"] = neg
            metrics["news_total"] = len(news_items)
            if neg > pos:
                observations.append(f"Negative news sentiment ({neg} neg vs {pos} pos)")

    # -- same-day signals -------------------------------------------------
    elif lens.name == "same_day_signals":
        parsed_trades: list[ParsedTrade] = data.get("parsed_trades", [])
        other_signals = [t for t in parsed_trades if t.symbol != trade.symbol and t.signal]
        metrics["other_signal_count"] = len(other_signals)
        if other_signals:
            outcomes = [t.outcome.value for t in other_signals if t.outcome]
            metrics["other_outcomes"] = outcomes

    # -- float / liquidity ------------------------------------------------
    elif lens.name == "float_liquidity":
        ticker_details = data.get("ticker_details")
        if ticker_details:
            if ticker_details.shares_outstanding:
                metrics["shares_outstanding"] = ticker_details.shares_outstanding
            if ticker_details.float_shares:
                metrics["float_shares"] = ticker_details.float_shares
            if ticker_details.float_shares and signal.tvr:
                # tvr is in millions of dollars traded
                float_turnover = (signal.tvr * 1_000_000) / ticker_details.float_shares
                metrics["float_turnover_ratio"] = float_turnover
                if float_turnover > 1.0:
                    observations.append(f"Float turnover > 1x ({float_turnover:.1f}x) — high conviction")

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


def synthesize(trade: ParsedTrade, all_findings: list[QuantitativeFindings]) -> SelectionVerdict:
    """Combine all quantitative findings into a selection verdict.

    NOTE: In the full system this calls the LLM for nuanced reasoning.
    This implementation provides a rule-based baseline that the LLM wrapper
    in decision_review_service.py will enhance.
    """
    all_metrics: dict[str, Any] = {}
    all_observations: list[str] = []
    for f in all_findings:
        all_metrics.update(f.metrics)
        all_observations.extend(f.observations)

    signal = trade.signal
    should_trade = True
    reasons: list[str] = []

    if signal:
        if signal.score < 5.0:
            should_trade = False
            reasons.append(f"Low signal score ({signal.score:.1f})")
        if signal.pwin < 50:
            should_trade = False
            reasons.append(f"Low win probability ({signal.pwin:.0f}%)")
        if signal.dd_predicted > 5.0:
            reasons.append(f"High predicted drawdown ({signal.dd_predicted:.1f}%)")

    spy_change = all_metrics.get("spy_change_at_entry_pct")
    if spy_change is not None and spy_change < -1.0:
        reasons.append(f"Adverse market (SPY {spy_change:+.2f}%)")

    neg_news = all_metrics.get("news_negative_count", 0)
    pos_news = all_metrics.get("news_positive_count", 0)
    if neg_news > pos_news + 2:
        reasons.append("Predominantly negative news sentiment")

    avg_peer = all_metrics.get("avg_peer_change_pct")
    if avg_peer is not None and avg_peer < -1.0:
        reasons.append(f"Weak sector ({avg_peer:+.2f}%)")

    if not reasons:
        reasons.append("Signal metrics within acceptable range")

    confidence = _synthesis_confidence(all_findings)

    return SelectionVerdict(
        should_trade=should_trade,
        confidence=confidence,
        reasons=reasons,
        market_context={"spy_change_pct": spy_change} if spy_change is not None else {},
        sector_context={"avg_peer_change_pct": avg_peer} if avg_peer is not None else {},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_bar_at(bars: list[MinuteBar], target_ts: Any) -> MinuteBar | None:
    """Find the bar closest to *target_ts* (within same minute or just before)."""
    best: MinuteBar | None = None
    for b in bars:
        if b.timestamp <= target_ts:
            best = b
        else:
            break
    return best


def _compute_confidence(metrics: dict[str, Any], observations: list[str]) -> float:
    if not metrics and not observations:
        return 0.0
    base = 0.3
    base += min(0.3, len(metrics) * 0.05)
    base += min(0.3, len(observations) * 0.1)
    return min(1.0, base)


def _synthesis_confidence(findings: list[QuantitativeFindings]) -> float:
    if not findings:
        return 0.0
    return min(1.0, sum(f.confidence for f in findings) / max(len(findings), 1))
