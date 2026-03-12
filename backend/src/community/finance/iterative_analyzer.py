# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""20-iteration convergence loop — the core analytical engine."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

# Review modules — imported as namespaces so we can dispatch compute_metrics()
from . import entry_review, exit_review, failure_review, selection_review
from .hypothesis import HypothesisTracker
from .market_data_service import MarketDataService, market_datetime_to_ns
from .models import (
    AnalyticalLens,
    IterationResult,
    ParsedTrade,
    QuantitativeFindings,
    TradeOutcome,
)
from .themes.base import ReviewTheme

logger = logging.getLogger(__name__)

# Map module names → compute_metrics functions
_REVIEW_MODULES: dict[str, Any] = {
    "selection": selection_review,
    "entry": entry_review,
    "exit": exit_review,
    "failure": failure_review,
}


class IterativeAnalyzer:
    """Runs up to N iterations per trade, each focused on a different analytical lens.

    On each iteration:
      1. Fetch data required by the lens (if not already cached)
      2. Dispatch to all active review modules' compute_metrics()
      3. Update hypotheses and check for convergence

    Data is cached across iterations so expensive API calls only happen once.
    """

    def __init__(self, market_data: MarketDataService, theme: ReviewTheme) -> None:
        self.market_data = market_data
        self.theme = theme
        self.lenses = theme.get_lenses()
        self.active_modules = theme.get_review_modules()

    def analyze(
        self,
        trade: ParsedTrade,
        all_day_trades: list[ParsedTrade] | None = None,
    ) -> tuple[list[IterationResult], HypothesisTracker, dict[str, list[QuantitativeFindings]]]:
        """Run the full iterative analysis loop for a single trade.

        Returns:
            (iteration_results, hypothesis_tracker, module_findings)
            where module_findings maps module_name → list of QuantitativeFindings
        """
        tracker = HypothesisTracker()
        data_cache: dict[str, Any] = {}  # lens data key → fetched data
        iteration_results: list[IterationResult] = []
        module_findings: dict[str, list[QuantitativeFindings]] = {m: [] for m in self.active_modules}

        # Form initial hypotheses
        self._seed_hypotheses(trade, tracker)

        for lens in self.lenses:
            # Skip final_synthesis — that's handled by the orchestrator
            if lens.name == "final_synthesis":
                continue

            logger.info("Iteration %d: %s for %s", lens.iteration, lens.name, trade.symbol)

            # 1. Fetch data required by this lens
            lens_data = self._fetch_lens_data(lens, trade, data_cache, all_day_trades)

            # 2. Dispatch to all review modules
            iter_findings: dict[str, QuantitativeFindings] = {}
            for module_name in self.active_modules:
                module = _REVIEW_MODULES.get(module_name)
                if module is None:
                    continue

                # Skip failure module for non-stranded trades
                if module_name == "failure" and trade.outcome not in (TradeOutcome.STRANDED, TradeOutcome.OPEN):
                    continue

                try:
                    findings = module.compute_metrics(trade, lens, lens_data)
                    iter_findings[module_name] = findings
                    module_findings[module_name].append(findings)

                    # 3. Update hypotheses
                    tracker.update_with_findings(module_name, findings)
                except Exception:
                    logger.exception("Error in %s.compute_metrics for lens %s", module_name, lens.name)

            # Build iteration result
            cumulative_conf = tracker.overall_confidence()
            converged = self.theme.should_converge(lens.iteration, cumulative_conf, module_findings)

            result = IterationResult(
                iteration=lens.iteration,
                lens=lens,
                findings=iter_findings,
                new_gaps=list(tracker.get_unresolved_gaps()),
                cumulative_confidence=cumulative_conf,
                converged=converged,
            )
            iteration_results.append(result)

            if converged and lens.iteration < self.theme.max_iterations:
                logger.info("Converged at iteration %d (confidence=%.2f) for %s", lens.iteration, cumulative_conf, trade.symbol)
                break

        return iteration_results, tracker, module_findings

    # -----------------------------------------------------------------------
    # Data fetching (cached)
    # -----------------------------------------------------------------------

    def _fetch_lens_data(
        self,
        lens: AnalyticalLens,
        trade: ParsedTrade,
        cache: dict[str, Any],
        all_day_trades: list[ParsedTrade] | None,
    ) -> dict[str, Any]:
        """Fetch and cache data required by this lens."""
        data: dict[str, Any] = {}
        trading_date = trade.trading_date

        for key in lens.required_data:
            if key in cache:
                data[key] = cache[key]
                continue

            fetched = self._fetch_data_key(key, trade, trading_date, all_day_trades)
            if fetched is not None:
                cache[key] = fetched
                data[key] = fetched

        return data

    def _fetch_data_key(
        self,
        key: str,
        trade: ParsedTrade,
        trading_date: date,
        all_day_trades: list[ParsedTrade] | None,
    ) -> Any:
        """Fetch a single data dependency by key name."""
        try:
            if key == "minute_bars":
                return self.market_data.get_minute_bars(trade.symbol, trading_date)

            elif key == "premarket_bars":
                return self.market_data.get_premarket_bars(trade.symbol, trading_date)

            elif key == "daily_bars":
                start = trading_date - timedelta(days=5)
                return self.market_data.get_daily_bars(trade.symbol, start_date=start, end_date=trading_date)

            elif key == "spy_bars":
                return self.market_data.get_spy_bars(trading_date)

            elif key == "qqq_bars":
                return self.market_data.get_qqq_bars(trading_date)

            elif key == "sector_bars":
                return self.market_data.get_sector_peer_bars(trade.symbol, trading_date)

            elif key == "ticker_details":
                return self.market_data.get_ticker_details(trade.symbol)

            elif key == "news":
                return self.market_data.get_news(trade.symbol, around_date=trading_date)

            elif key == "tick_data":
                if trade.entry:
                    # Fetch quote data around entry time (±2 minutes)
                    entry_ns = market_datetime_to_ns(trade.entry.timestamp)
                    window_ns = 2 * 60 * 1_000_000_000  # 2 minutes
                    return self.market_data.get_tick_quotes(
                        trade.symbol,
                        timestamp_gte=str(entry_ns - window_ns),
                        timestamp_lt=str(entry_ns + window_ns),
                    )
                return []

            elif key == "duckdb":
                if trade.signal:
                    score = trade.signal.score
                    tvr = trade.signal.tvr
                    return self.market_data.find_similar_signals(
                        score_min=max(0, score - 2),
                        score_max=score + 2,
                        tvr_min=max(0, (tvr - 5)) * 1_000_000,
                        tvr_max=(tvr + 5) * 1_000_000,
                        limit=30,
                    )
                return []

            elif key == "parsed_trades":
                return all_day_trades or []

            else:
                logger.warning("Unknown data key: %s", key)
                return None

        except Exception:
            logger.exception("Failed to fetch data key '%s' for %s", key, trade.symbol)
            return None

    # -----------------------------------------------------------------------
    # Hypothesis seeding
    # -----------------------------------------------------------------------

    def _seed_hypotheses(self, trade: ParsedTrade, tracker: HypothesisTracker) -> None:
        """Form initial hypotheses based on signal characteristics."""
        signal = trade.signal
        if signal is None:
            return

        # Selection hypotheses
        if signal.score >= 8.0:
            tracker.form_hypothesis("selection", f"Strong signal (score={signal.score:.1f}) suggests good selection", 0.6)
        elif signal.score < 5.0:
            tracker.form_hypothesis("selection", f"Weak signal (score={signal.score:.1f}) suggests poor selection", 0.4)

        if signal.pwin >= 80:
            tracker.form_hypothesis("selection", f"High win probability ({signal.pwin:.0f}%) supports trade", 0.5)

        # Entry hypotheses
        if trade.entry:
            tracker.form_hypothesis("entry", "Entry timing may be suboptimal if above VWAP or at bar high", 0.3)

        # Exit hypotheses
        if trade.outcome == TradeOutcome.TP_FILLED:
            tracker.form_hypothesis("exit", "TP was reached — evaluate if higher TP would have been better", 0.4)
        elif trade.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN):
            tracker.form_hypothesis("exit", "TP never reached — fixed TP may be too aggressive", 0.5)
            tracker.form_hypothesis("failure", "Stranded position — evaluate exit urgency", 0.5)
