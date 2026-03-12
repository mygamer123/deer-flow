# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Intraday trade decision review theme — the first concrete theme."""

from __future__ import annotations

from ..models import AnalyticalLens, ParsedTrade
from .base import ReviewTheme, ThemeRegistry

# fmt: off
_INTRADAY_LENSES: list[AnalyticalLens] = [
    AnalyticalLens(name="basic_bars",         iteration=1,  description="Parse logs + load 1-min OHLCV bars",                         required_data=["minute_bars"]),
    AnalyticalLens(name="volume_profile",     iteration=2,  description="Volume distribution around entry/exit",                      required_data=["minute_bars"]),
    AnalyticalLens(name="price_micropattern", iteration=3,  description="Consolidation, breakout, rejection patterns",                required_data=["minute_bars"]),
    AnalyticalLens(name="vwap_analysis",      iteration=4,  description="Price relative to VWAP throughout session",                   required_data=["minute_bars"]),
    AnalyticalLens(name="bid_ask_spread",     iteration=5,  description="Spread quality at entry time (tick data)",                    required_data=["tick_data"]),
    AnalyticalLens(name="sector_peers",       iteration=6,  description="Same-sector stocks' performance at same time",                required_data=["sector_bars", "ticker_details"]),
    AnalyticalLens(name="market_context",     iteration=7,  description="SPY/QQQ broad market at same time",                          required_data=["spy_bars", "qqq_bars"]),
    AnalyticalLens(name="premarket_activity", iteration=8,  description="Pre-market volume and price action",                         required_data=["premarket_bars"]),
    AnalyticalLens(name="previous_day",       iteration=9,  description="Prior day's price action and close",                         required_data=["daily_bars"]),
    AnalyticalLens(name="gap_analysis",       iteration=10, description="Opening gap % and gap-fill risk",                            required_data=["daily_bars", "minute_bars"]),
    AnalyticalLens(name="multi_timeframe",    iteration=11, description="Higher timeframe structure (5m, 15m aggregates)",             required_data=["minute_bars"]),
    AnalyticalLens(name="historical_similar", iteration=12, description="DuckDB: similar signal profiles in history",                 required_data=["duckdb"]),
    AnalyticalLens(name="time_of_day_edge",   iteration=13, description="Systematic entry timing analysis",                           required_data=["duckdb"]),
    AnalyticalLens(name="alt_tp_sl_sim",      iteration=14, description="Simulate different TP/SL percentages",                       required_data=["minute_bars"]),
    AnalyticalLens(name="trailing_stop_sim",  iteration=15, description="Simulate trailing stop variants (ATR-based, pct-based)",     required_data=["minute_bars"]),
    AnalyticalLens(name="time_exit_sim",      iteration=16, description="Simulate time-based exit rules (15m, 30m, 60m)",             required_data=["minute_bars"]),
    AnalyticalLens(name="float_liquidity",    iteration=17, description="Shares outstanding, float turnover ratio",                   required_data=["ticker_details"]),
    AnalyticalLens(name="news_sentiment",     iteration=18, description="Polygon news + sentiment around trade time",                 required_data=["news"]),
    AnalyticalLens(name="same_day_signals",   iteration=19, description="Other signals that day — market regime, correlation",         required_data=["parsed_trades"]),
    AnalyticalLens(name="final_synthesis",    iteration=20, description="LLM combines all evidence into final verdicts",              required_data=[]),
]
# fmt: on


class IntradayTheme(ReviewTheme):
    """Reviews intraday scalp/momentum trades from production strategy logs."""

    name = "intraday"
    description = "Intraday trade decision review — selection, entry, exit, failure analysis with 20-iteration convergence"

    def get_lenses(self) -> list[AnalyticalLens]:
        return list(_INTRADAY_LENSES)

    def get_review_modules(self) -> list[str]:
        return ["selection", "entry", "exit", "failure"]

    def should_review_trade(self, trade: ParsedTrade) -> bool:
        # Skip short positions (negative shares — out of scope)
        if trade.is_short:
            return False
        # Must have at least a signal or entry to review
        return trade.signal is not None or trade.entry is not None

    @property
    def max_iterations(self) -> int:
        return 20

    @property
    def convergence_threshold(self) -> float:
        return 0.85


# Auto-register on import
ThemeRegistry.register(IntradayTheme())
