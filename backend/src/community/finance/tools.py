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
from .report_builder import build_day_report, build_trade_report
from .review_store import save_day_review, save_trade_review

logger = logging.getLogger(__name__)


def _get_service() -> DecisionReviewService:
    return DecisionReviewService(polygon_api_key=os.getenv("POLYGON_API_KEY"))


def _parse_date(date_str: str) -> date:
    return date.fromisoformat(date_str)


@tool("review_today_trades", parse_docstring=True)
def review_today_trades_tool() -> str:
    """Review all of today's trades from the production strategy log.

    Parses today's log file, runs 20-iteration analysis on each trade,
    and returns a detailed markdown report with selection, entry, exit,
    and failure verdicts for every trade.
    """
    try:
        svc = _get_service()
        day_review = svc.review_day(date.today())
        save_day_review(day_review)
        return build_day_report(day_review)
    except Exception:
        logger.exception("Failed to review today's trades")
        return "Error: Failed to review today's trades. Check that POLYGON_API_KEY is set and log files exist at ~/Documents/prod/fms/logs/"


@tool("review_date_trades", parse_docstring=True)
def review_date_trades_tool(trading_date: str) -> str:
    """Review all trades from a specific date's production strategy log.

    Args:
        trading_date: The date to review in YYYY-MM-DD format (e.g. '2026-03-05').
    """
    try:
        td = _parse_date(trading_date)
        svc = _get_service()
        day_review = svc.review_day(td)
        save_day_review(day_review)
        return build_day_report(day_review)
    except ValueError:
        return f"Error: Invalid date format '{trading_date}'. Use YYYY-MM-DD."
    except Exception:
        logger.exception("Failed to review trades for %s", trading_date)
        return f"Error: Failed to review trades for {trading_date}. Check logs and API key."


@tool("review_stranded_positions", parse_docstring=True)
def review_stranded_positions_tool(trading_date: str | None = None, lookback_days: int = 3) -> str:
    """Review stranded (open/stuck) positions that haven't hit their take-profit.

    Looks back across multiple days to find positions that are still open
    and provides failure analysis with exit urgency recommendations.

    Args:
        trading_date: Date to check from in YYYY-MM-DD format. Defaults to today.
        lookback_days: Number of days to look back for stranded positions. Defaults to 3.
    """
    try:
        td = _parse_date(trading_date) if trading_date else date.today()
        svc = _get_service()
        day_review = svc.review_stranded(td, lookback_days=lookback_days)

        if not day_review.trades:
            return f"No stranded positions found in the {lookback_days}-day window ending {td.isoformat()}."

        save_day_review(day_review)
        return build_day_report(day_review)
    except Exception:
        logger.exception("Failed to review stranded positions")
        return "Error: Failed to review stranded positions. Check logs and API key."


@tool("review_single_trade", parse_docstring=True)
def review_single_trade_tool(symbol: str, trading_date: str) -> str:
    """Review a single trade by ticker symbol and date.

    Runs the full 20-iteration analysis on one specific trade and returns
    a detailed markdown report.

    Args:
        symbol: The ticker symbol (e.g. 'AMPX').
        trading_date: The date of the trade in YYYY-MM-DD format (e.g. '2026-03-05').
    """
    try:
        td = _parse_date(trading_date)
        svc = _get_service()
        review = svc.review_single_trade(symbol, td)

        if review is None:
            return f"No trade found for {symbol.upper()} on {trading_date}."

        save_trade_review(review)
        return build_trade_report(review)
    except ValueError:
        return f"Error: Invalid date format '{trading_date}'. Use YYYY-MM-DD."
    except Exception:
        logger.exception("Failed to review %s on %s", symbol, trading_date)
        return f"Error: Failed to review {symbol} on {trading_date}. Check logs and API key."
