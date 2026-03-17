from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.models import AggregatedReviewResult, ReviewResult, WorkflowKind
from src.trading_research.store import list_saved_results, load_saved_result, save_result


def test_store_saves_and_lists_structured_results(tmp_path: Path) -> None:
    with patch("src.trading_research.store._RESULTS_DIR", tmp_path):
        result = ReviewResult(
            result_id="review_1",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            symbol="AMPX",
        )

        path = save_result(result)

        assert path.exists()
        assert list_saved_results() == [path.name]
        loaded = load_saved_result(path.name)
        assert loaded is not None
        assert loaded["result_id"] == "review_1"


def test_store_saves_aggregate_review_result(tmp_path: Path) -> None:
    with patch("src.trading_research.store._RESULTS_DIR", tmp_path):
        result = AggregatedReviewResult(
            result_id="agg_review_1",
            workflow=WorkflowKind.AGGREGATE_TRADE_REVIEW,
            title="Aggregated Trade Review",
            subject="aggregate:strong_uptrending",
            as_of=datetime(2026, 3, 5, 12, 0),
            trade_count=3,
            contributing_result_ids=["r1", "r2", "r3"],
            grouping_key="strong_uptrending",
            cohort_stats={"trade_count": 3},
        )

        path = save_result(result)

        assert path.exists()
        assert "aggregate_trade_review_" in path.name
        loaded = load_saved_result(path.name)
        assert loaded is not None
        assert loaded["result_id"] == "agg_review_1"
        assert loaded["trade_count"] == 3


def test_store_trade_review_filename_includes_log_source(tmp_path: Path) -> None:
    with patch("src.trading_research.store._RESULTS_DIR", tmp_path):
        prod_result = ReviewResult(
            result_id="review_prod",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            symbol="AMPX",
            trading_date=date(2026, 3, 5),
            log_source="prod",
        )
        dev_result = ReviewResult(
            result_id="review_dev",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            symbol="AMPX",
            trading_date=date(2026, 3, 5),
            log_source="dev",
        )

        prod_path = save_result(prod_result)
        dev_path = save_result(dev_result)

        assert "prod" in prod_path.name
        assert "dev" in dev_path.name
        assert prod_path.name != dev_path.name


def test_store_preserves_duplicate_trade_review_reruns(tmp_path: Path) -> None:
    with patch("src.trading_research.store._RESULTS_DIR", tmp_path):
        result = ReviewResult(
            result_id="review_prod",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            symbol="AMPX",
            trading_date=date(2026, 3, 5),
            log_source="prod",
        )

        first_path = save_result(result)
        second_path = save_result(result)

        assert first_path.exists()
        assert second_path.exists()
        assert first_path.name != second_path.name
        assert len(list_saved_results()) == 2
