# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Markdown report generation from TradeReview and DayReview."""

from __future__ import annotations

from typing import Any

from .models import DayReview, ExitPolicy, TradeReview


def build_day_report(day: DayReview) -> str:
    """Generate a full markdown report for a day's trades."""
    lines: list[str] = []
    lines.append(f"# Trade Review — {day.trading_date.isoformat()}")
    lines.append("")

    stats = day.summary_stats
    if stats:
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total trades | {stats.get('total_trades', 0)} |")
        lines.append(f"| Winners | {stats.get('winners', 0)} |")
        lines.append(f"| Losers | {stats.get('losers', 0)} |")
        lines.append(f"| Stranded | {stats.get('stranded', 0)} |")
        lines.append(f"| Win rate | {stats.get('win_rate_pct', 0):.0f}% |")
        lines.append(f"| Total PnL | {stats.get('total_pnl_pct', 0):+.2f}% |")
        lines.append(f"| Avg PnL | {stats.get('avg_pnl_pct', 0):+.2f}% |")
        lines.append(f"| Avg iterations | {stats.get('avg_iterations', 0):.1f} |")
        lines.append("")

        qual_dist = stats.get("quality_distribution", {})
        if qual_dist:
            lines.append("**Quality distribution:** " + ", ".join(f"{k}: {v}" for k, v in qual_dist.items()))
            lines.append("")

    if day.lessons:
        lines.append("## Lessons")
        lines.append("")
        for lesson in day.lessons:
            lines.append(f"- {lesson}")
        lines.append("")

    for i, review in enumerate(day.trades, 1):
        lines.append("---")
        lines.append("")
        lines.append(build_trade_report(review, index=i))
        lines.append("")

    return "\n".join(lines)


def build_trade_report(review: TradeReview, *, index: int | None = None) -> str:
    """Generate markdown for a single trade review."""
    lines: list[str] = []
    trade = review.trade
    prefix = f"## Trade {index}: " if index else "## "
    lines.append(f"{prefix}{trade.symbol} ({trade.outcome.value})")
    lines.append("")

    # Header info
    sig = trade.signal
    if sig:
        lines.append(f"**Signal:** {sig.signal_type.value} | score={sig.score:.1f} | pwin={sig.pwin:.0f}% | tvr={sig.tvr:.1f}M | bars={sig.bars}")
    if trade.entry:
        lines.append(f"**Entry:** ${trade.entry.price:.4f} @ {trade.entry.timestamp.strftime('%H:%M:%S')} | qty={trade.entry.quantity}")
    if trade.exit:
        lines.append(f"**Exit:** ${trade.exit.price:.4f} @ {trade.exit.timestamp.strftime('%H:%M:%S')} | type={trade.exit.exit_type}")
    if trade.pnl_pct is not None:
        lines.append(f"**PnL:** {trade.pnl_pct:+.2f}%")
    if trade.hold_duration_minutes is not None:
        lines.append(f"**Hold:** {trade.hold_duration_minutes:.0f} min")
    lines.append(f"**Quality:** {review.quality_tier.name} | **Verdict:** {review.overall_verdict.value} | **Pattern:** {review.pattern.value}")
    lines.append(f"**Iterations:** {review.total_iterations}")
    lines.append("")

    # Selection verdict
    if review.selection:
        sel = review.selection
        lines.append("### Selection")
        lines.append(f"Should trade: **{'Yes' if sel.should_trade else 'No'}** (confidence: {sel.confidence:.0%})")
        if sel.reasons:
            for r in sel.reasons:
                lines.append(f"- {r}")
        lines.append("")

    # Entry verdict
    if review.entry:
        ent = review.entry
        lines.append("### Entry")
        if ent.should_have_waited:
            lines.append("**Should have waited** for better entry.")
        else:
            lines.append("Entry timing: acceptable.")
        if ent.optimal_entry_price is not None:
            lines.append(f"- Optimal entry: ${ent.optimal_entry_price:.4f}")
        if ent.actual_vs_optimal_slippage_pct is not None:
            lines.append(f"- Slippage vs optimal: {ent.actual_vs_optimal_slippage_pct:.2f}%")
        if ent.reasons:
            for r in ent.reasons:
                lines.append(f"- {r}")
        lines.append("")

    # Exit verdict
    if review.exit:
        ext = review.exit
        lines.append("### Exit")
        lines.append(f"Recommended policy: **{_exit_policy_label(ext.recommended_policy)}**")
        if ext.max_favorable_excursion_pct is not None:
            lines.append(f"- MFE: {ext.max_favorable_excursion_pct:.2f}%")
        if ext.max_adverse_excursion_pct is not None:
            lines.append(f"- MAE: {ext.max_adverse_excursion_pct:.2f}%")
        if ext.tp_pct_recommendation is not None:
            lines.append(f"- Recommended TP%: {ext.tp_pct_recommendation:.0f}%")
        if ext.optimal_exit_price is not None:
            lines.append(f"- Optimal exit price: ${ext.optimal_exit_price:.4f}")
        _append_simulation_table(lines, ext.simulations)
        if ext.reasons:
            lines.append("")
            for r in ext.reasons:
                lines.append(f"- {r}")
        lines.append("")

    # Failure verdict (stranded only)
    if review.failure:
        fail = review.failure
        lines.append("### Failure Analysis (Stranded Position)")
        if fail.should_exit_now:
            lines.append("**EXIT NOW** — holding is not recommended.")
        else:
            lines.append("Position may recover — monitor closely.")
        if fail.bounce_probability is not None:
            lines.append(f"- Bounce probability: {fail.bounce_probability:.0%}")
        if fail.max_hold_hours is not None:
            lines.append(f"- Max recommended hold: {fail.max_hold_hours:.1f} hours")
        if fail.recommended_exit_price is not None:
            lines.append(f"- Suggested exit price: ${fail.recommended_exit_price:.4f}")
        if fail.reasons:
            for r in fail.reasons:
                lines.append(f"- {r}")
        lines.append("")

    return "\n".join(lines)


def _exit_policy_label(policy: ExitPolicy) -> str:
    labels = {
        ExitPolicy.FIXED_TP: "Fixed TP/SL",
        ExitPolicy.TRAILING_STOP: "Trailing Stop",
        ExitPolicy.TIME_BASED: "Time-Based Exit",
        ExitPolicy.VWAP_RELATIVE: "VWAP-Relative",
        ExitPolicy.HYBRID: "Hybrid",
    }
    return labels.get(policy, policy.value)


def _append_simulation_table(lines: list[str], simulations: dict[str, Any]) -> None:
    """Append a compact simulation results table if data exists."""
    fixed = simulations.get("fixed_tp_sl", {})
    trailing = simulations.get("trailing_stop", {})
    time_based = simulations.get("time_based", {})

    has_data = any([fixed, trailing, time_based])
    if not has_data:
        return

    lines.append("")
    lines.append("#### Exit Simulations")

    if fixed:
        lines.append("")
        lines.append("**Fixed TP/SL:**")
        lines.append("| Combo | PnL% | Exit Type | Bars |")
        lines.append("|-------|------|-----------|------|")
        for key, res in sorted(fixed.items(), key=lambda x: x[1].get("pnl_pct", 0), reverse=True)[:5]:
            lines.append(f"| {key} | {res.get('pnl_pct', 0):+.2f}% | {res.get('exit_type', '?')} | {res.get('bars_held', '?')} |")

    if trailing:
        lines.append("")
        lines.append("**Trailing Stop:**")
        lines.append("| Trail% | PnL% | Peak | Bars |")
        lines.append("|--------|------|------|------|")
        for key, res in sorted(trailing.items(), key=lambda x: x[1].get("pnl_pct", 0), reverse=True):
            lines.append(f"| {key} | {res.get('pnl_pct', 0):+.2f}% | ${res.get('peak', 0):.2f} | {res.get('bars_held', '?')} |")

    if time_based:
        lines.append("")
        lines.append("**Time-Based:**")
        lines.append("| Window | PnL% | Exit Price |")
        lines.append("|--------|------|------------|")
        for key, res in sorted(time_based.items(), key=lambda x: x[1].get("pnl_pct", 0), reverse=True):
            lines.append(f"| {key} | {res.get('pnl_pct', 0):+.2f}% | ${res.get('exit_price', 0):.2f} |")
