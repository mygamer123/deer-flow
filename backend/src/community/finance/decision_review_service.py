# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Top-level orchestrator — parses logs, runs iterative analysis per trade, synthesizes verdicts."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from . import entry_review, exit_review, failure_review, selection_review
from .iterative_analyzer import IterativeAnalyzer
from .market_data_service import MarketDataService
from .models import (
    DayReview,
    ParsedTrade,
    PatternType,
    QualityTier,
    ReviewVerdict,
    TradeOutcome,
    TradeReview,
)
from .themes import intraday as _intraday_theme  # noqa: F401  # side-effect: register theme
from .themes.base import ThemeRegistry
from .trade_log_parser import parse_log_file, parse_log_range

logger = logging.getLogger(__name__)


class DecisionReviewService:
    """Orchestrates the full trade review pipeline for a given day or date range."""

    def __init__(self, *, polygon_api_key: str | None = None, theme_name: str = "intraday"):
        self.market_data = MarketDataService(polygon_api_key=polygon_api_key)
        self.theme = ThemeRegistry.get_or_raise(theme_name)
        self.analyzer = IterativeAnalyzer(self.market_data, self.theme)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def review_day(self, trading_date: date) -> DayReview:
        """Parse one day's log and review every eligible trade."""
        trades = parse_log_file(trading_date)
        return self._review_trades(trading_date, trades)

    def review_date_range(self, start_date: date, end_date: date) -> DayReview:
        """Parse a date range (handles stranded trade carry-over) and review."""
        trades = parse_log_range(start_date, end_date)
        return self._review_trades(start_date, trades)

    def review_stranded(self, trading_date: date, *, lookback_days: int = 3) -> DayReview:
        """Focus on stranded/open positions, looking back *lookback_days* for context."""
        start = trading_date - timedelta(days=lookback_days)
        trades = parse_log_range(start, trading_date)
        stranded = [t for t in trades if t.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN)]
        return self._review_trades(trading_date, stranded)

    def review_single_trade(self, symbol: str, trading_date: date) -> TradeReview | None:
        """Review a single trade by symbol and date."""
        trades = parse_log_file(trading_date)
        match = next((t for t in trades if t.symbol.upper() == symbol.upper()), None)
        if match is None:
            logger.warning("No trade found for %s on %s", symbol, trading_date)
            return None
        all_day_trades = trades
        return self._review_one_trade(match, all_day_trades)

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _review_trades(self, trading_date: date, trades: list[ParsedTrade]) -> DayReview:
        eligible = [t for t in trades if self.theme.should_review_trade(t)]
        logger.info("Reviewing %d eligible trades (of %d parsed) for %s", len(eligible), len(trades), trading_date)

        reviews: list[TradeReview] = []
        for trade in eligible:
            try:
                review = self._review_one_trade(trade, eligible)
                reviews.append(review)
            except Exception:
                logger.exception("Failed to review %s", trade.symbol)

        day_review = DayReview(trading_date=trading_date, trades=reviews)
        day_review.summary_stats = self._compute_day_stats(reviews)
        day_review.lessons = self._extract_lessons(reviews)
        return day_review

    def _review_one_trade(self, trade: ParsedTrade, all_day_trades: list[ParsedTrade]) -> TradeReview:
        logger.info("Reviewing %s (%s) on %s", trade.symbol, trade.outcome.value, trade.trading_date)

        # 1. Run iterative analysis (up to 20 lenses)
        iteration_results, tracker, module_findings = self.analyzer.analyze(trade, all_day_trades)

        # 2. Finalize hypotheses
        hypotheses = tracker.finalize()

        # 3. Synthesize verdicts (one call per module — runs ONCE)
        sel_verdict = selection_review.synthesize(trade, module_findings.get("selection", []))
        ent_verdict = entry_review.synthesize(trade, module_findings.get("entry", []))
        ext_verdict = exit_review.synthesize(trade, module_findings.get("exit", []))

        fail_verdict = None
        if trade.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN):
            fail_verdict = failure_review.synthesize(trade, module_findings.get("failure", []))

        # 4. Determine overall quality
        quality = self._assess_quality(trade, sel_verdict, ent_verdict, ext_verdict, fail_verdict)
        overall = self._determine_overall_verdict(trade, sel_verdict, quality)
        pattern = self._classify_pattern(trade, module_findings)

        review = TradeReview(
            trade=trade,
            quality_tier=quality,
            overall_verdict=overall,
            selection=sel_verdict,
            entry=ent_verdict,
            exit=ext_verdict,
            failure=fail_verdict,
            pattern=pattern,
            hypotheses=hypotheses,
            iteration_results=iteration_results,
            total_iterations=len(iteration_results),
        )

        return self.theme.post_process(review)

    # -----------------------------------------------------------------------
    # Quality assessment
    # -----------------------------------------------------------------------

    def _assess_quality(self, trade: ParsedTrade, sel: Any, ent: Any, ext: Any, fail: Any) -> QualityTier:
        score = 0

        # Selection quality
        if sel and sel.should_trade:
            score += 2
        elif sel and not sel.should_trade:
            score -= 2

        # Entry quality
        if ent:
            if ent.should_have_waited:
                score -= 1
            else:
                score += 1

        # Exit quality
        if ext and ext.max_favorable_excursion_pct is not None:
            if trade.pnl_pct is not None:
                captured = trade.pnl_pct / ext.max_favorable_excursion_pct * 100 if ext.max_favorable_excursion_pct > 0 else 0
                if captured >= 60:
                    score += 2
                elif captured >= 30:
                    score += 1
                else:
                    score -= 1

        # Failure penalty
        if fail and fail.should_exit_now:
            score -= 2

        # Outcome bonus/penalty
        if trade.outcome == TradeOutcome.TP_FILLED:
            score += 1
        elif trade.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN):
            score -= 1

        if score >= 4:
            return QualityTier.EXCELLENT
        elif score >= 2:
            return QualityTier.GOOD
        elif score >= 0:
            return QualityTier.MARGINAL
        elif score >= -2:
            return QualityTier.BAD
        else:
            return QualityTier.TERRIBLE

    def _determine_overall_verdict(self, trade: ParsedTrade, sel: Any, quality: QualityTier) -> ReviewVerdict:
        if quality == QualityTier.EXCELLENT:
            return ReviewVerdict.GOOD_TRADE
        elif quality == QualityTier.GOOD:
            return ReviewVerdict.ACCEPTABLE
        elif quality == QualityTier.MARGINAL:
            return ReviewVerdict.MARGINAL
        elif quality == QualityTier.BAD:
            if sel and not sel.should_trade:
                return ReviewVerdict.SHOULD_SKIP
            return ReviewVerdict.MARGINAL
        else:
            return ReviewVerdict.BAD_TRADE

    def _classify_pattern(self, trade: ParsedTrade, module_findings: dict[str, list[Any]]) -> PatternType:
        """Infer pattern type from entry-review observations."""
        entry_findings = module_findings.get("entry", [])
        all_obs = []
        for f in entry_findings:
            all_obs.extend(f.observations)

        obs_text = " ".join(all_obs).lower()
        if "strong uptrend" in obs_text or "consecutive higher closes" in obs_text:
            return PatternType.STRONG_UPTRENDING
        if "pullback" in obs_text and "breakout" in obs_text:
            return PatternType.PULLBACK_BREAKOUT
        if "reclaim" in obs_text:
            return PatternType.PULLBACK_RECLAIM
        return PatternType.UNCLASSIFIED

    # -----------------------------------------------------------------------
    # Day-level stats
    # -----------------------------------------------------------------------

    def _compute_day_stats(self, reviews: list[TradeReview]) -> dict[str, Any]:
        total = len(reviews)
        if total == 0:
            return {"total_trades": 0}

        winners = sum(1 for r in reviews if r.trade.pnl_pct is not None and r.trade.pnl_pct > 0)
        losers = sum(1 for r in reviews if r.trade.pnl_pct is not None and r.trade.pnl_pct < 0)
        stranded = sum(1 for r in reviews if r.trade.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN))
        pnls = [r.trade.pnl_pct for r in reviews if r.trade.pnl_pct is not None]
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / len(pnls) if pnls else 0

        quality_dist: dict[str, int] = {}
        for r in reviews:
            tier = r.quality_tier.name
            quality_dist[tier] = quality_dist.get(tier, 0) + 1

        avg_iterations = sum(r.total_iterations for r in reviews) / total

        return {
            "total_trades": total,
            "winners": winners,
            "losers": losers,
            "stranded": stranded,
            "win_rate_pct": winners / max(winners + losers, 1) * 100,
            "total_pnl_pct": total_pnl,
            "avg_pnl_pct": avg_pnl,
            "quality_distribution": quality_dist,
            "avg_iterations": avg_iterations,
        }

    def _extract_lessons(self, reviews: list[TradeReview]) -> list[str]:
        lessons: list[str] = []
        skip_count = sum(1 for r in reviews if r.overall_verdict == ReviewVerdict.SHOULD_SKIP)
        if skip_count > 0:
            lessons.append(f"{skip_count} trade(s) should have been skipped based on selection criteria")

        bad_entry = sum(1 for r in reviews if r.entry and r.entry.should_have_waited)
        if bad_entry > 0:
            lessons.append(f"{bad_entry} trade(s) had suboptimal entry timing — consider waiting for pullback")

        stranded = sum(1 for r in reviews if r.failure and r.failure.should_exit_now)
        if stranded > 0:
            lessons.append(f"{stranded} stranded position(s) should be exited immediately")

        return lessons
