from __future__ import annotations

import logging
from datetime import date

from langchain.tools import tool
from tavily.errors import InvalidAPIKeyError, MissingAPIKeyError

from src.community.research.research_service import TavilyAuthError
from src.community.tavily.tools import _format_tavily_error
from .aggregate_review_service import AggregatedTradeReviewRequest, AggregateReviewService
from .diagnostic_service import DiagnosticService
from .report_service import build_aggregate_review_markdown, build_review_markdown, build_setup_research_markdown, build_strategy_improvement_markdown
from .setup_research_service import SetupResearchService
from .store import (
    list_saved_results,
    load_saved_result,
    save_result,
    save_strategy_change_records,
    save_strategy_improvement_result,
)
from .strategy_improvement_service import StrategyImprovementRequest, StrategyImprovementService
from .trade_review_service import TradeReviewService

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _render_tavily_error(error: Exception) -> str:
    if isinstance(error, TavilyAuthError):
        return str(error)
    return _format_tavily_error(error)


@tool("run_trade_review", parse_docstring=True)
def run_trade_review_tool(symbol: str, trading_date: str, log_source: str | None = None) -> str:
    """Run the structured P0 trade-review workflow.

    Args:
        symbol: The ticker symbol to review.
        trading_date: Trade date in YYYY-MM-DD format.
        log_source: Optional named log source from `finance.log_sources`.
    """
    try:
        result = TradeReviewService().review_trade(
            symbol=symbol,
            trading_date=_parse_date(trading_date),
            log_source=log_source,
        )
        save_result(result)
        return build_review_markdown(result)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception:
        logger.exception("Failed to run structured trade review for %s on %s", symbol, trading_date)
        return f"Error: Failed to run structured trade review for {symbol} on {trading_date}."


@tool("run_setup_research", parse_docstring=True)
def run_setup_research_tool(
    symbol: str,
    setup_type: str = "intraday_breakout",
    trade_date: str | None = None,
) -> str:
    """Run the structured P0 setup-research workflow.

    Args:
        symbol: The ticker symbol to research.
        setup_type: Supported setup template. P0 supports only `intraday_breakout`.
        trade_date: Optional trade date in YYYY-MM-DD format.
    """
    try:
        result = SetupResearchService().research_setup(
            symbol=symbol,
            setup_type=setup_type,
            trade_date=_parse_date(trade_date) if trade_date else None,
        )
        save_result(result)
        return build_setup_research_markdown(result)
    except (TavilyAuthError, MissingAPIKeyError, InvalidAPIKeyError) as error:
        return _render_tavily_error(error)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception:
        logger.exception("Failed to run setup research for %s", symbol)
        return f"Error: Failed to run setup research for '{symbol}'."


@tool("run_aggregate_trade_review", parse_docstring=True)
def run_aggregate_trade_review_tool(
    symbol: str | None = None,
    pattern: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_trades: int | None = None,
    log_source: str | None = None,
    aggregation_mode: str = "by_pattern",
) -> str:
    """Aggregate saved trade reviews into a cohort report with multi-trade claims and recommendations.

    Args:
        symbol: Optional symbol to filter trades.
        pattern: Optional setup pattern (grouping key) to filter trades.
        start_date: Optional start date in YYYY-MM-DD format.
        end_date: Optional end date in YYYY-MM-DD format.
        max_trades: Optional cap on number of trades to aggregate.
        log_source: Optional named log source to filter trades.
        aggregation_mode: Aggregation mode: 'by_pattern' or 'by_symbol_pattern'.
    """
    try:
        request = AggregatedTradeReviewRequest(
            symbol=symbol,
            pattern=pattern,
            start_date=_parse_date(start_date) if start_date else None,
            end_date=_parse_date(end_date) if end_date else None,
            max_trades=max_trades,
            log_source=log_source,
            aggregation_mode=aggregation_mode,
        )
        result = AggregateReviewService().aggregate(request)
        save_result(result)
        return build_aggregate_review_markdown(result)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception:
        logger.exception("Failed to run aggregate trade review")
        return "Error: Failed to run aggregate trade review."


@tool("run_trade_diagnostic", parse_docstring=True)
def run_trade_diagnostic_tool(symbol: str, trading_date: str, log_source: str | None = None) -> str:
    """Run single-trade diagnostic decomposition on a saved trade review.

    Args:
        symbol: The ticker symbol to diagnose.
        trading_date: Trade date in YYYY-MM-DD format.
        log_source: Optional named log source to filter by.
    """
    try:
        td = _parse_date(trading_date)
        diagnostic_service = DiagnosticService()
        for filename in list_saved_results():
            data = load_saved_result(filename)
            if data is None or data.get("workflow") != "trade_review":
                continue
            if str(data.get("symbol", "")).upper() != symbol.upper():
                continue
            td_raw = data.get("trading_date")
            if isinstance(td_raw, str) and td_raw:
                try:
                    file_td = _parse_date(td_raw)
                except ValueError:
                    continue
                if file_td != td:
                    continue
            else:
                continue
            if log_source and str(data.get("log_source", "")) != log_source:
                continue
            diag = diagnostic_service.diagnose_trade(data)
            if diag is not None:
                lines = [
                    f"Symbol: {diag.symbol}",
                    f"Date: {diag.trading_date}",
                    f"Grade: {diag.overall_grade.value}",
                    f"Opportunity: {diag.opportunity_quality.value}",
                    f"Execution: {diag.execution_quality.value}",
                    f"Extraction: {diag.extraction_quality.value}",
                    f"Failure reason: {diag.primary_failure_reason.value}",
                    f"Avoid point: {diag.earliest_avoid_point or 'none'}",
                    f"Minimize loss point: {diag.earliest_minimize_loss_point or 'none'}",
                    f"Improvement direction: {diag.improvement_direction.value}",
                    f"Action type: {diag.strategy_action_type.value}",
                ]
                return "\n".join(lines)
        return f"No saved trade review found for {symbol} on {trading_date}"
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception:
        logger.exception("Failed to run trade diagnostic for %s on %s", symbol, trading_date)
        return f"Error: Failed to run trade diagnostic for {symbol} on {trading_date}."


@tool("run_strategy_improvement_loop", parse_docstring=True)
def run_strategy_improvement_loop_tool(
    symbol: str | None = None,
    pattern: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_trades: int | None = None,
    log_source: str | None = None,
) -> str:
    """Run the strategy improvement loop across saved trade reviews.

    Args:
        symbol: Optional symbol to filter trades.
        pattern: Optional setup pattern to filter trades.
        start_date: Optional start date in YYYY-MM-DD format.
        end_date: Optional end date in YYYY-MM-DD format.
        max_trades: Optional cap on number of trades.
        log_source: Optional named log source to filter trades.
    """
    try:
        request = StrategyImprovementRequest(
            symbol=symbol,
            pattern=pattern,
            start_date=_parse_date(start_date) if start_date else None,
            end_date=_parse_date(end_date) if end_date else None,
            max_trades=max_trades,
            log_source=log_source,
        )
        result = StrategyImprovementService().run_loop(request)
        save_strategy_improvement_result(result)
        save_strategy_change_records(result.change_records)
        return build_strategy_improvement_markdown(result)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception:
        logger.exception("Failed to run strategy improvement loop")
        return "Error: Failed to run strategy improvement loop."
