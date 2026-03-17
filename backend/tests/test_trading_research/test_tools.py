from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from tavily.errors import MissingAPIKeyError

from src.trading_research.models import (
    StrategyActionCandidate,
    StrategyActionStatus,
    StrategyActionType,
    StrategyChangeRecord,
    StrategyImprovementLoopResult,
    WorkflowKind,
)
from src.trading_research.tools import (
    run_aggregate_trade_review_tool,
    run_setup_research_tool,
    run_strategy_improvement_loop_tool,
    run_trade_review_tool,
)


def test_run_trade_review_tool_returns_rendered_markdown() -> None:
    with patch("src.trading_research.tools.TradeReviewService.review_trade", return_value="result"):
        with patch("src.trading_research.tools.save_result"):
            with patch("src.trading_research.tools.build_review_markdown", return_value="# Trade Review"):
                result = run_trade_review_tool.run(
                    {
                        "symbol": "AMPX",
                        "trading_date": "2026-03-05",
                    }
                )

    assert result == "# Trade Review"


def test_run_setup_research_tool_returns_rendered_markdown() -> None:
    with patch("src.trading_research.tools.SetupResearchService.research_setup", return_value="result"):
        with patch("src.trading_research.tools.save_result"):
            with patch("src.trading_research.tools.build_setup_research_markdown", return_value="# Setup Research"):
                result = run_setup_research_tool.run(
                    {
                        "symbol": "AMPX",
                        "setup_type": "intraday_breakout",
                        "trade_date": "2026-03-05",
                    }
                )

    assert result == "# Setup Research"


def test_run_setup_research_tool_surfaces_tavily_config_errors() -> None:
    with patch(
        "src.trading_research.tools.SetupResearchService.research_setup",
        side_effect=MissingAPIKeyError(),
    ):
        result = run_setup_research_tool.run(
            {
                "symbol": "AMPX",
                "setup_type": "intraday_breakout",
            }
        )

    assert result == "Error: Tavily web search is not configured. Set `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."


def test_run_aggregate_trade_review_tool_returns_rendered_markdown() -> None:
    with patch("src.trading_research.tools.AggregateReviewService.aggregate", return_value="result"):
        with patch("src.trading_research.tools.save_result"):
            with patch("src.trading_research.tools.build_aggregate_review_markdown", return_value="# Aggregate Review"):
                result = run_aggregate_trade_review_tool.run(
                    {
                        "pattern": "strong_uptrending",
                    }
                )

    assert result == "# Aggregate Review"


def test_run_strategy_improvement_loop_tool_persists_change_records() -> None:
    now = datetime(2026, 3, 5, 10, 0)
    candidate = StrategyActionCandidate(
        action_id="candidate_1",
        action_type=StrategyActionType.REFINE_EXIT_RULE,
        rationale="Exit logic overreacts after reversals.",
        status=StrategyActionStatus.VERIFIED_CANDIDATE,
        sample_size=4,
        minimum_sample_size_met=True,
        as_of=now,
    )
    loop_result = StrategyImprovementLoopResult(
        result_id="loop_1",
        workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
        title="Strategy Improvement Loop",
        as_of=now,
        trade_count=4,
        pattern_count=1,
        candidate_count=1,
        change_records=[
            StrategyChangeRecord(
                record_id="change_1",
                candidate=candidate,
                created_at=now,
                source_loop_result_id="loop_1",
                source_trade_count=4,
            )
        ],
    )

    with patch("src.trading_research.tools.StrategyImprovementService.run_loop", return_value=loop_result):
        with patch("src.trading_research.tools.save_strategy_improvement_result"):
            with patch("src.trading_research.tools.save_strategy_change_records", create=True) as save_change_records:
                with patch("src.trading_research.tools.build_strategy_improvement_markdown", return_value="# Strategy Improvement"):
                    result = run_strategy_improvement_loop_tool.run({})

    assert result == "# Strategy Improvement"
    save_change_records.assert_called_once_with(loop_result.change_records)
