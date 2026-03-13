# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Community tools for intraday trade decision review.

Follows the Tavily reference pattern: @tool() decorated functions that return strings.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from langchain.tools import tool

from .decision_review_service import DecisionReviewService
from .log_sources import get_log_source_path
from .report_builder import build_day_report, build_trade_report
from .review_store import save_day_review, save_trade_review
from .signal_compare import build_signal_comparison_report, compare_signal_sources

logger = logging.getLogger(__name__)


def _get_service(log_source: str | None = None) -> DecisionReviewService:
    return DecisionReviewService(
        polygon_api_key=os.getenv("POLYGON_API_KEY"),
        log_source=log_source,
    )


def _parse_date(date_str: str) -> date:
    return date.fromisoformat(date_str)


def _validate_log_source(log_source: str | None) -> str | None:
    try:
        get_log_source_path(log_source)
    except ValueError as exc:
        return f"Error: {exc}"
    return None


@tool("review_today_trades", parse_docstring=True)
def review_today_trades_tool(log_source: str | None = None) -> str:
    """Review all of today's trades from the production strategy log.

    Parses today's log file, runs 20-iteration analysis on each trade,
    and returns a detailed markdown report with selection, entry, exit,
    and failure verdicts for every trade.

    Args:
        log_source: Named source from `finance.log_sources`. Defaults to `finance.default_log_source`.
    """
    source_error = _validate_log_source(log_source)
    if source_error:
        return source_error

    try:
        svc = _get_service(log_source)
        day_review = svc.review_day(date.today())
        save_day_review(day_review, log_source=log_source)
        return build_day_report(day_review)
    except Exception:
        logger.exception("Failed to review today's trades")
        return f"Error: Failed to review today's trades. Check that POLYGON_API_KEY is set and log files exist at {get_log_source_path(log_source)}."


@tool("review_date_trades", parse_docstring=True)
def review_date_trades_tool(trading_date: str, log_source: str | None = None) -> str:
    """Review all trades from a specific date's production strategy log.

    Args:
        trading_date: The date to review in YYYY-MM-DD format (e.g. '2026-03-05').
        log_source: Named source from `finance.log_sources`. Defaults to `finance.default_log_source`.
    """
    source_error = _validate_log_source(log_source)
    if source_error:
        return source_error

    try:
        td = _parse_date(trading_date)
        svc = _get_service(log_source)
        day_review = svc.review_day(td)
        save_day_review(day_review, log_source=log_source)
        return build_day_report(day_review)
    except ValueError:
        return f"Error: Invalid date format '{trading_date}'. Use YYYY-MM-DD."
    except Exception:
        logger.exception("Failed to review trades for %s", trading_date)
        return f"Error: Failed to review trades for {trading_date}. Check logs and API key."


@tool("review_stranded_positions", parse_docstring=True)
def review_stranded_positions_tool(
    trading_date: str | None = None,
    lookback_days: int = 3,
    log_source: str | None = None,
) -> str:
    """Review stranded (open/stuck) positions that haven't hit their take-profit.

    Looks back across multiple days to find positions that are still open
    and provides failure analysis with exit urgency recommendations.

    Args:
        trading_date: Date to check from in YYYY-MM-DD format. Defaults to today.
        lookback_days: Number of days to look back for stranded positions. Defaults to 3.
        log_source: Named source from `finance.log_sources`. Defaults to `finance.default_log_source`.
    """
    source_error = _validate_log_source(log_source)
    if source_error:
        return source_error

    try:
        td = _parse_date(trading_date) if trading_date else date.today()
        svc = _get_service(log_source)
        day_review = svc.review_stranded(td, lookback_days=lookback_days)

        if not day_review.trades:
            return f"No stranded positions found in the {lookback_days}-day window ending {td.isoformat()}."

        save_day_review(day_review, log_source=log_source)
        return build_day_report(day_review)
    except Exception:
        logger.exception("Failed to review stranded positions")
        return "Error: Failed to review stranded positions. Check logs and API key."


@tool("review_single_trade", parse_docstring=True)
def review_single_trade_tool(symbol: str, trading_date: str, log_source: str | None = None) -> str:
    """Review a single trade by ticker symbol and date.

    Runs the full 20-iteration analysis on one specific trade and returns
    a detailed markdown report.

    Args:
        symbol: The ticker symbol (e.g. 'AMPX').
        trading_date: The date of the trade in YYYY-MM-DD format (e.g. '2026-03-05').
        log_source: Named source from `finance.log_sources`. Defaults to `finance.default_log_source`.
    """
    source_error = _validate_log_source(log_source)
    if source_error:
        return source_error

    try:
        td = _parse_date(trading_date)
        svc = _get_service(log_source)
        review = svc.review_single_trade(symbol, td)

        if review is None:
            return f"No trade found for {symbol.upper()} on {trading_date}."

        save_trade_review(review, log_source=log_source)
        return build_trade_report(review)
    except ValueError:
        return f"Error: Invalid date format '{trading_date}'. Use YYYY-MM-DD."
    except Exception:
        logger.exception("Failed to review %s on %s", symbol, trading_date)
        return f"Error: Failed to review {symbol} on {trading_date}. Check logs and API key."


@tool("compare_signal_sources", parse_docstring=True)
def compare_signal_sources_tool(
    trading_date: str,
    baseline_source: str = "prod",
    candidate_source: str = "dev",
) -> str:
    """Compare signals across two configured log sources and suggest improvements.

    This is useful for checking whether your dev strategy is missing strong prod
    setups, producing extra low-conviction signals, or drifting in timing.

    Args:
        trading_date: The trading date to compare in YYYY-MM-DD format.
        baseline_source: Named baseline source from `finance.log_sources`. Defaults to 'prod'.
        candidate_source: Named candidate source from `finance.log_sources`. Defaults to 'dev'.
    """
    try:
        td = _parse_date(trading_date)
        comparison = compare_signal_sources(
            td,
            baseline_source=baseline_source,
            candidate_source=candidate_source,
        )
        return build_signal_comparison_report(comparison)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception:
        logger.exception(
            "Failed to compare signal sources for %s (%s vs %s)",
            trading_date,
            baseline_source,
            candidate_source,
        )
        return f"Error: Failed to compare {baseline_source} vs {candidate_source} signals for {trading_date}. Check configured log sources and log files."
