from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from src.trading_research.models import (
    StrategyActionCandidate,
    StrategyActionStatus,
    StrategyActionType,
    StrategyChangeRecord,
    StrategyImprovementLoopResult,
    WorkflowKind,
)
from src.trading_research.cli import main


def test_cli_trade_review_path_executes() -> None:
    with patch("src.trading_research.cli.TradeReviewService.review_trade", return_value="result"):
        with patch("src.trading_research.cli.save_result"):
            with patch("src.trading_research.cli.build_review_markdown", return_value="# Trade Review"):
                assert main(["trade-review", "AMPX", "2026-03-05"]) == 0


def test_cli_setup_research_path_executes() -> None:
    with patch("src.trading_research.cli.SetupResearchService.research_setup", return_value="result"):
        with patch("src.trading_research.cli.save_result"):
            with patch("src.trading_research.cli.build_setup_research_markdown", return_value="# Setup Research"):
                assert main(["setup-research", "AMPX", "--setup-type", "intraday_breakout", "--trade-date", "2026-03-05"]) == 0


def test_cli_aggregate_trade_review_path_executes() -> None:
    with patch("src.trading_research.cli.AggregateReviewService.aggregate", return_value="result"):
        with patch("src.trading_research.cli.save_result"):
            with patch("src.trading_research.cli.build_aggregate_review_markdown", return_value="# Aggregate Review"):
                assert main(["aggregate-trade-review", "--pattern", "strong_uptrending"]) == 0


def test_cli_strategy_improvement_loop_persists_change_records() -> None:
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

    with patch("src.trading_research.cli.StrategyImprovementService.run_loop", return_value=loop_result):
        with patch("src.trading_research.cli.save_strategy_improvement_result"):
            with patch("src.trading_research.cli.save_strategy_change_records", create=True) as save_change_records:
                with patch("src.trading_research.cli.build_strategy_improvement_markdown", return_value="# Strategy Improvement"):
                    assert main(["strategy-improvement-loop"]) == 0

    save_change_records.assert_called_once_with(loop_result.change_records)
