# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from typing import Any

from .models import (
    AnalyticalLens,
    ExitPolicy,
    ExitVerdict,
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
        return QuantitativeFindings(lens_name=lens.name, iteration=lens.iteration, observations=["No entry — skipping exit review"])

    entry_price = trade.entry.price
    entry_ts = trade.entry.timestamp

    if lens.name == "basic_bars":
        minute_bars: list[MinuteBar] = data.get("minute_bars", [])
        post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
        if post_entry:
            highs = [b.high for b in post_entry]
            lows = [b.low for b in post_entry]
            max_high = max(highs)
            min_low = min(lows)

            # MFE / MAE (Max Favorable / Adverse Excursion)
            mfe_pct = (max_high - entry_price) / entry_price * 100
            mae_pct = (entry_price - min_low) / entry_price * 100
            metrics["mfe_pct"] = mfe_pct
            metrics["mae_pct"] = mae_pct
            metrics["max_high_post_entry"] = max_high
            metrics["min_low_post_entry"] = min_low

            # Time to MFE
            mfe_idx = highs.index(max_high)
            if mfe_idx < len(post_entry):
                mfe_bar = post_entry[mfe_idx]
                time_to_mfe_min = (mfe_bar.timestamp - entry_ts).total_seconds() / 60
                metrics["time_to_mfe_minutes"] = time_to_mfe_min

            if trade.exit:
                actual_pnl = (trade.exit.price - entry_price) / entry_price * 100
                metrics["actual_pnl_pct"] = actual_pnl
                metrics["captured_mfe_pct"] = actual_pnl / mfe_pct * 100 if mfe_pct > 0 else 0
                if metrics["captured_mfe_pct"] < 50:
                    observations.append(f"Only captured {metrics['captured_mfe_pct']:.0f}% of MFE — left money on table")

    # -- TP/SL simulation at different percentages ------------------------
    elif lens.name == "alt_tp_sl_sim":
        minute_bars = data.get("minute_bars", [])
        post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
        if post_entry:
            tp_levels = [0.02, 0.03, 0.05, 0.07, 0.10]
            sl_levels = [0.02, 0.03, 0.05]
            sim_results: dict[str, Any] = {}

            for tp_pct in tp_levels:
                for sl_pct in sl_levels:
                    tp_price = entry_price * (1 + tp_pct)
                    sl_price = entry_price * (1 - sl_pct)
                    result = _simulate_exit(post_entry, entry_price=entry_price, tp_price=tp_price, sl_price=sl_price)
                    key = f"tp{tp_pct * 100:.0f}_sl{sl_pct * 100:.0f}"
                    sim_results[key] = result

            metrics["tp_sl_simulations"] = sim_results

            # Find best TP/SL combo by PnL
            best_key = ""
            best_pnl = -999.0
            for key, res in sim_results.items():
                if res["pnl_pct"] > best_pnl:
                    best_pnl = res["pnl_pct"]
                    best_key = key
            if best_key:
                metrics["best_tp_sl_combo"] = best_key
                metrics["best_tp_sl_pnl"] = best_pnl
                observations.append(f"Best fixed TP/SL: {best_key} → {best_pnl:+.2f}%")

    # -- trailing stop simulation -----------------------------------------
    elif lens.name == "trailing_stop_sim":
        minute_bars = data.get("minute_bars", [])
        post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
        if post_entry:
            trail_pcts = [0.01, 0.02, 0.03, 0.05]
            trail_results: dict[str, Any] = {}

            for trail_pct in trail_pcts:
                result = _simulate_trailing_stop(post_entry, entry_price, trail_pct)
                key = f"trail_{trail_pct * 100:.0f}pct"
                trail_results[key] = result

            metrics["trailing_stop_simulations"] = trail_results

            best_trail_key = ""
            best_trail_pnl = -999.0
            for key, res in trail_results.items():
                if res["pnl_pct"] > best_trail_pnl:
                    best_trail_pnl = res["pnl_pct"]
                    best_trail_key = key
            if best_trail_key:
                metrics["best_trailing_combo"] = best_trail_key
                metrics["best_trailing_pnl"] = best_trail_pnl
                observations.append(f"Best trailing stop: {best_trail_key} → {best_trail_pnl:+.2f}%")

    # -- time-based exit simulation ---------------------------------------
    elif lens.name == "time_exit_sim":
        minute_bars = data.get("minute_bars", [])
        post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
        if post_entry:
            time_exits = [15, 30, 60, 120]
            time_results: dict[str, Any] = {}

            for minutes in time_exits:
                if len(post_entry) > minutes:
                    exit_bar = post_entry[minutes - 1]
                    pnl = (exit_bar.close - entry_price) / entry_price * 100
                    time_results[f"exit_{minutes}min"] = {"exit_price": exit_bar.close, "pnl_pct": pnl}

            metrics["time_exit_simulations"] = time_results

            if time_results:
                best_time_key = max(time_results, key=lambda k: time_results[k]["pnl_pct"])
                metrics["best_time_exit"] = best_time_key
                metrics["best_time_exit_pnl"] = time_results[best_time_key]["pnl_pct"]
                observations.append(f"Best time-based exit: {best_time_key} → {time_results[best_time_key]['pnl_pct']:+.2f}%")

    elif lens.name == "vwap_analysis":
        minute_bars = data.get("minute_bars", [])
        if minute_bars:
            post_entry = [b for b in minute_bars if b.timestamp >= entry_ts]
            if post_entry:
                # Track when price crosses below VWAP after entry
                vwap_cross_below = None
                cum_vol = 0
                cum_pv = 0.0
                for b in minute_bars:
                    typical = (b.high + b.low + b.close) / 3
                    cum_pv += typical * b.volume
                    cum_vol += b.volume
                    if cum_vol == 0:
                        continue
                    running_vwap = cum_pv / cum_vol
                    if b.timestamp >= entry_ts and b.close < running_vwap and vwap_cross_below is None:
                        vwap_cross_below = b.timestamp
                        pnl_at_cross = (b.close - entry_price) / entry_price * 100
                        metrics["vwap_cross_below_time"] = str(vwap_cross_below)
                        metrics["pnl_at_vwap_cross"] = pnl_at_cross
                        observations.append(f"Price crossed below VWAP at {vwap_cross_below.strftime('%H:%M')} ({pnl_at_cross:+.2f}%)")
                        break

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


def synthesize(trade: ParsedTrade, all_findings: list[QuantitativeFindings]) -> ExitVerdict:
    """Rule-based baseline — LLM enhancement in decision_review_service.py."""
    all_metrics: dict[str, Any] = {}
    all_observations: list[str] = []
    for f in all_findings:
        all_metrics.update(f.metrics)
        all_observations.extend(f.observations)

    verdict = ExitVerdict(reasons=list(all_observations))

    verdict.max_favorable_excursion_pct = all_metrics.get("mfe_pct")
    verdict.max_adverse_excursion_pct = all_metrics.get("mae_pct")

    # Determine recommended policy from simulations
    best_fixed = all_metrics.get("best_tp_sl_pnl", -999)
    best_trail = all_metrics.get("best_trailing_pnl", -999)
    best_time = all_metrics.get("best_time_exit_pnl", -999)

    best_overall = max(best_fixed, best_trail, best_time)
    if best_overall == best_trail and best_trail > 0:
        verdict.recommended_policy = ExitPolicy.TRAILING_STOP
    elif best_overall == best_time and best_time > 0:
        verdict.recommended_policy = ExitPolicy.TIME_BASED
    elif best_fixed > 0:
        verdict.recommended_policy = ExitPolicy.FIXED_TP
    else:
        verdict.recommended_policy = ExitPolicy.HYBRID

    if all_metrics.get("best_tp_sl_combo"):
        tp_sl = all_metrics["best_tp_sl_combo"]
        tp_pct_str = tp_sl.split("_")[0].replace("tp", "")
        try:
            verdict.tp_pct_recommendation = float(tp_pct_str)
        except ValueError:
            pass

    verdict.simulations = {
        "fixed_tp_sl": all_metrics.get("tp_sl_simulations", {}),
        "trailing_stop": all_metrics.get("trailing_stop_simulations", {}),
        "time_based": all_metrics.get("time_exit_simulations", {}),
    }

    if all_metrics.get("max_high_post_entry") and trade.entry:
        verdict.optimal_exit_price = all_metrics["max_high_post_entry"]

    return verdict


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _simulate_exit(bars: list[MinuteBar], *, entry_price: float, tp_price: float, sl_price: float) -> dict[str, Any]:
    for i, b in enumerate(bars):
        if b.high >= tp_price and b.low <= sl_price:
            return {"exit_price": sl_price, "pnl_pct": (sl_price - entry_price) / entry_price * 100 if entry_price > 0 else 0, "exit_type": "sl", "bars_held": i + 1}
        if b.high >= tp_price:
            return {"exit_price": tp_price, "pnl_pct": (tp_price - entry_price) / entry_price * 100 if entry_price > 0 else 0, "exit_type": "tp", "bars_held": i + 1}
        if b.low <= sl_price:
            return {"exit_price": sl_price, "pnl_pct": (sl_price - entry_price) / entry_price * 100 if entry_price > 0 else 0, "exit_type": "sl", "bars_held": i + 1}
    # Never hit TP or SL — mark-to-market at last bar
    last = bars[-1].close
    return {"exit_price": last, "pnl_pct": (last - entry_price) / entry_price * 100 if entry_price > 0 else 0, "exit_type": "eod", "bars_held": len(bars)}


def _simulate_trailing_stop(bars: list[MinuteBar], entry_price: float, trail_pct: float) -> dict[str, Any]:
    peak = entry_price
    for i, b in enumerate(bars):
        stop_level = peak * (1 - trail_pct)
        if b.low <= stop_level:
            exit_price = stop_level
            return {"exit_price": exit_price, "pnl_pct": (exit_price - entry_price) / entry_price * 100, "peak": peak, "bars_held": i + 1}
        if b.high > peak:
            peak = b.high
    last = bars[-1].close
    return {"exit_price": last, "pnl_pct": (last - entry_price) / entry_price * 100, "peak": peak, "bars_held": len(bars)}


def _compute_confidence(metrics: dict[str, Any], observations: list[str]) -> float:
    if not metrics and not observations:
        return 0.0
    base = 0.3
    base += min(0.3, len(metrics) * 0.05)
    base += min(0.3, len(observations) * 0.1)
    return min(1.0, base)
