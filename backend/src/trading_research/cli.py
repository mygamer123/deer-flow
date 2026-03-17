from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date

from tavily.errors import InvalidAPIKeyError, MissingAPIKeyError

from src.community.research.research_service import TavilyAuthError
from src.community.tavily.tools import _format_tavily_error

from .aggregate_review_service import AggregatedTradeReviewRequest, AggregateReviewService
from .diagnostic_service import DiagnosticService
from .report_service import build_aggregate_review_markdown, build_review_markdown, build_setup_research_markdown, build_strategy_improvement_markdown
from .setup_research_service import SetupResearchService
from .store import save_result, save_strategy_change_records, save_strategy_improvement_result
from .strategy_improvement_service import StrategyImprovementRequest, StrategyImprovementService
from .trade_review_service import TradeReviewService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Structured trading research workflows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trade_review = subparsers.add_parser("trade-review", help="Run a structured single-trade review")
    trade_review.add_argument("symbol", help="Ticker symbol to review")
    trade_review.add_argument("trading_date", help="Trade date in YYYY-MM-DD format")
    trade_review.add_argument("--log-source", dest="log_source", default=None, help="Optional named log source")

    setup_research = subparsers.add_parser("setup-research", help="Run a structured setup-research task")
    setup_research.add_argument("symbol", help="Ticker symbol to research")
    setup_research.add_argument(
        "--setup-type",
        dest="setup_type",
        default="intraday_breakout",
        help="Supported setup template. P0 supports only `intraday_breakout`.",
    )
    setup_research.add_argument(
        "--trade-date",
        dest="trade_date",
        default=None,
        help="Optional trade date in YYYY-MM-DD format.",
    )

    aggregate = subparsers.add_parser("aggregate-trade-review", help="Aggregate saved trade reviews into a cohort report")
    aggregate.add_argument("--symbol", default=None, help="Filter to a single symbol")
    aggregate.add_argument("--pattern", default=None, help="Filter to a setup pattern (grouping key)")
    aggregate.add_argument("--start-date", dest="start_date", default=None, help="Start date in YYYY-MM-DD format")
    aggregate.add_argument("--end-date", dest="end_date", default=None, help="End date in YYYY-MM-DD format")
    aggregate.add_argument("--max-trades", dest="max_trades", type=int, default=None, help="Cap number of trades")
    aggregate.add_argument("--log-source", dest="log_source", default=None, help="Filter by log source")
    aggregate.add_argument("--mode", dest="aggregation_mode", default="by_pattern", choices=["by_pattern", "by_symbol_pattern"], help="Aggregation mode")

    diagnose = subparsers.add_parser("diagnose-trade", help="Run single-trade diagnostic decomposition")
    diagnose.add_argument("symbol", help="Ticker symbol to diagnose")
    diagnose.add_argument("trading_date", help="Trade date in YYYY-MM-DD format")
    diagnose.add_argument("--log-source", dest="log_source", default=None, help="Optional named log source")

    strategy_loop = subparsers.add_parser("strategy-improvement-loop", help="Run the strategy improvement loop across saved trade reviews")
    strategy_loop.add_argument("--symbol", default=None, help="Filter to a single symbol")
    strategy_loop.add_argument("--pattern", default=None, help="Filter to a setup pattern")
    strategy_loop.add_argument("--start-date", dest="start_date", default=None, help="Start date in YYYY-MM-DD format")
    strategy_loop.add_argument("--end-date", dest="end_date", default=None, help="End date in YYYY-MM-DD format")
    strategy_loop.add_argument("--max-trades", dest="max_trades", type=int, default=None, help="Cap number of trades")
    strategy_loop.add_argument("--log-source", dest="log_source", default=None, help="Filter by log source")

    subparsers.add_parser("list-strategy-changes", help="List saved strategy change records")

    return parser


def _render_tavily_error(error: Exception) -> str:
    if isinstance(error, TavilyAuthError):
        return str(error)
    return _format_tavily_error(error)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "trade-review":
        result = TradeReviewService().review_trade(
            symbol=args.symbol,
            trading_date=date.fromisoformat(args.trading_date),
            log_source=args.log_source,
        )
        save_result(result)
        print(build_review_markdown(result))
        return 0

    if args.command == "setup-research":
        try:
            result = SetupResearchService().research_setup(
                symbol=args.symbol,
                setup_type=args.setup_type,
                trade_date=date.fromisoformat(args.trade_date) if args.trade_date else None,
            )
        except (TavilyAuthError, MissingAPIKeyError, InvalidAPIKeyError) as error:
            print(_render_tavily_error(error))
            return 1
        save_result(result)
        print(build_setup_research_markdown(result))
        return 0

    if args.command == "aggregate-trade-review":
        request = AggregatedTradeReviewRequest(
            symbol=args.symbol,
            pattern=args.pattern,
            start_date=date.fromisoformat(args.start_date) if args.start_date else None,
            end_date=date.fromisoformat(args.end_date) if args.end_date else None,
            max_trades=args.max_trades,
            log_source=args.log_source,
            aggregation_mode=args.aggregation_mode,
        )
        agg_result = AggregateReviewService().aggregate(request)
        save_result(agg_result)
        print(build_aggregate_review_markdown(agg_result))
        return 0

    if args.command == "diagnose-trade":
        from .store import list_saved_results, load_saved_result

        td = date.fromisoformat(args.trading_date)
        diagnostic_service = DiagnosticService()
        for filename in list_saved_results():
            data = load_saved_result(filename)
            if data is None or data.get("workflow") != "trade_review":
                continue
            if str(data.get("symbol", "")).upper() != args.symbol.upper():
                continue
            td_raw = data.get("trading_date")
            if isinstance(td_raw, str) and td_raw:
                try:
                    file_td = date.fromisoformat(td_raw)
                except ValueError:
                    continue
                if file_td != td:
                    continue
            else:
                continue
            if args.log_source:
                if str(data.get("log_source", "")) != args.log_source:
                    continue
            diag = diagnostic_service.diagnose_trade(data)
            if diag is not None:
                print(f"Symbol: {diag.symbol}")
                print(f"Date: {diag.trading_date}")
                print(f"Grade: {diag.overall_grade.value}")
                print(f"Opportunity: {diag.opportunity_quality.value}")
                print(f"Execution: {diag.execution_quality.value}")
                print(f"Extraction: {diag.extraction_quality.value}")
                print(f"Failure reason: {diag.primary_failure_reason.value}")
                print(f"Avoid point: {diag.earliest_avoid_point or 'none'}")
                print(f"Minimize loss point: {diag.earliest_minimize_loss_point or 'none'}")
                print(f"Improvement direction: {diag.improvement_direction.value}")
                print(f"Action type: {diag.strategy_action_type.value}")
                return 0
        print(f"No saved trade review found for {args.symbol} on {args.trading_date}")
        return 1

    if args.command == "strategy-improvement-loop":
        request = StrategyImprovementRequest(
            symbol=args.symbol,
            pattern=args.pattern,
            start_date=date.fromisoformat(args.start_date) if args.start_date else None,
            end_date=date.fromisoformat(args.end_date) if args.end_date else None,
            max_trades=args.max_trades,
            log_source=args.log_source,
        )
        loop_result = StrategyImprovementService().run_loop(request)
        save_strategy_improvement_result(loop_result)
        save_strategy_change_records(loop_result.change_records)
        print(build_strategy_improvement_markdown(loop_result))
        return 0

    if args.command == "list-strategy-changes":
        from .store import list_strategy_change_records, load_strategy_change_record

        filenames = list_strategy_change_records()
        if not filenames:
            print("No saved strategy change records found.")
            return 0
        for filename in filenames:
            data = load_strategy_change_record(filename)
            if data is None:
                continue
            candidate = data.get("candidate", {})
            if not isinstance(candidate, dict):
                candidate = {}
            record_id = data.get("record_id", "?")
            action_type = candidate.get("action_type", "?")
            status = candidate.get("status", "?")
            source_trades = data.get("source_trade_count", "?")
            created_at = data.get("created_at", "?")
            print(f"{record_id}  action={action_type}  status={status}  trades={source_trades}  created={created_at}")
        return 0

    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
