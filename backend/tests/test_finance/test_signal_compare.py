from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.community.finance.decision_review_service import DecisionReviewService
from src.community.finance.models import DayReview, ParsedTrade, TradeReview
from src.community.finance.review_store import load_day_review_json, load_trade_review_json, save_day_review, save_trade_review
from src.community.finance.signal_compare import build_signal_comparison_report, compare_signal_sources
from src.community.finance.tools import compare_signal_sources_tool, review_date_trades_tool
from src.community.finance.trade_log_parser import get_available_log_dates, parse_log_file


def _make_app_config(
    prod_dir: Path,
    dev_dir: Path,
    *,
    default_source: str = "prod",
) -> MagicMock:
    return MagicMock(
        model_extra={
            "finance": {
                "default_log_source": default_source,
                "log_sources": {
                    "prod": str(prod_dir),
                    "dev": str(dev_dir),
                },
            }
        }
    )


def _write_log(log_dir: Path, trading_date: date, content: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"live.log.{trading_date.isoformat()}").write_text(content, encoding="utf-8")


@patch("src.community.finance.log_sources.get_app_config")
def test_parse_log_file_uses_named_log_source(mock_get_app_config, tmp_path: Path):
    trading_date = date(2026, 3, 5)
    prod_dir = tmp_path / "prod_logs"
    dev_dir = tmp_path / "dev_logs"
    mock_get_app_config.return_value = _make_app_config(prod_dir, dev_dir)

    _write_log(
        prod_dir,
        trading_date,
        "2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: AMPX | score=10.0 | pwin=90.0% | bars=190 | ret5m=5.4% | dd=0.5% | tvr=13.0M\n",
    )
    _write_log(
        dev_dir,
        trading_date,
        "2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: BETA | score=6.0 | pwin=60.0% | bars=120 | ret5m=2.4% | dd=1.5% | tvr=8.0M\n",
    )

    prod_trades = parse_log_file(trading_date, log_source="prod")
    dev_trades = parse_log_file(trading_date, log_source="dev")

    assert [trade.symbol for trade in prod_trades] == ["AMPX"]
    assert [trade.symbol for trade in dev_trades] == ["BETA"]
    assert get_available_log_dates(log_source="dev") == [trading_date]


@patch("src.community.finance.log_sources.get_app_config")
def test_parse_log_file_uses_configured_default_source(mock_get_app_config, tmp_path: Path):
    trading_date = date(2026, 3, 5)
    prod_dir = tmp_path / "prod_logs"
    dev_dir = tmp_path / "dev_logs"
    mock_get_app_config.return_value = _make_app_config(
        prod_dir,
        dev_dir,
        default_source="dev",
    )

    _write_log(
        dev_dir,
        trading_date,
        "2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: DEVX | score=7.0 | pwin=70.0% | bars=130 | ret5m=2.8% | dd=1.0% | tvr=6.5M\n",
    )

    trades = parse_log_file(trading_date)

    assert [trade.symbol for trade in trades] == ["DEVX"]


@patch("src.community.finance.log_sources.get_app_config")
def test_compare_signal_sources_reports_drift_and_suggestions(mock_get_app_config, tmp_path: Path):
    trading_date = date(2026, 3, 5)
    prod_dir = tmp_path / "prod_logs"
    dev_dir = tmp_path / "dev_logs"
    mock_get_app_config.return_value = _make_app_config(prod_dir, dev_dir)

    _write_log(
        prod_dir,
        trading_date,
        "\n".join(
            [
                "2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: AMPX | score=10.0 | pwin=90.0% | bars=190 | ret5m=5.4% | dd=0.5% | tvr=13.0M",
                "2026-03-05 09:35:00 | INFO     |   SIGNAL[MAIN]: BOTH | score=8.0 | pwin=80.0% | bars=100 | ret5m=3.4% | dd=0.7% | tvr=9.0M",
            ]
        )
        + "\n",
    )
    _write_log(
        dev_dir,
        trading_date,
        "\n".join(
            [
                "2026-03-05 09:38:00 | INFO     |   SIGNAL[DD_RECLAIM]: BOTH | score=6.5 | pwin=72.0% | bars=105 | ret5m=2.1% | dd=1.2% | tvr=8.0M",
                "2026-03-05 09:40:00 | INFO     |   SIGNAL[MAIN]: BETA | score=4.0 | pwin=45.0% | bars=140 | ret5m=1.5% | dd=2.0% | tvr=5.5M",
            ]
        )
        + "\n",
    )

    comparison = compare_signal_sources(
        trading_date,
        baseline_source="prod",
        candidate_source="dev",
    )
    report = build_signal_comparison_report(comparison)

    assert comparison.summary_stats["baseline_only_count"] == 1
    assert comparison.summary_stats["candidate_only_count"] == 1
    assert comparison.summary_stats["overlap_count"] == 1
    assert comparison.summary_stats["type_mismatch_count"] == 1
    assert any("missed 1 strong prod signal" in suggestion for suggestion in comparison.suggestions)
    assert any("extra low-conviction signal" in suggestion for suggestion in comparison.suggestions)
    assert "## Suggestions" in report
    assert "## Prod-Only Signals" in report
    assert "## Dev-Only Signals" in report


@patch("src.community.finance.log_sources.get_app_config")
def test_compare_signal_sources_tool_rejects_unknown_source(mock_get_app_config, tmp_path: Path):
    mock_get_app_config.return_value = _make_app_config(tmp_path / "prod_logs", tmp_path / "dev_logs")

    result = compare_signal_sources_tool.run(
        {
            "trading_date": "2026-03-05",
            "baseline_source": "prod",
            "candidate_source": "paper",
        }
    )

    assert result == "Error: Unknown finance log source 'paper'. Available sources: dev, prod."


@patch("src.community.finance.log_sources.get_app_config")
def test_compare_signal_sources_reports_missing_data_clearly(mock_get_app_config, tmp_path: Path):
    trading_date = date(2026, 3, 5)
    mock_get_app_config.return_value = _make_app_config(tmp_path / "prod_logs", tmp_path / "dev_logs")

    comparison = compare_signal_sources(
        trading_date,
        baseline_source="prod",
        candidate_source="dev",
    )

    assert comparison.suggestions == ["No signals were loaded from either source for this date. Verify the source names, configured paths, and log files before drawing conclusions."]


@patch("src.community.finance.decision_review_service.DecisionReviewService._review_trades")
@patch("src.community.finance.decision_review_service.parse_log_file")
def test_decision_review_service_forwards_log_source(mock_parse_log_file, mock_review_trades):
    trading_date = date(2026, 3, 5)
    mock_parse_log_file.return_value = []
    mock_review_trades.return_value = "reviewed"

    service = DecisionReviewService(log_source="dev")
    result = service.review_day(trading_date)

    assert result == "reviewed"
    mock_parse_log_file.assert_called_once_with(trading_date, log_source="dev")


@patch("src.community.finance.tools.build_day_report")
@patch("src.community.finance.tools.save_day_review")
@patch("src.community.finance.tools._get_service")
@patch("src.community.finance.log_sources.get_app_config")
def test_review_date_trades_tool_passes_log_source(
    mock_get_app_config,
    mock_get_service,
    mock_save_day_review,
    mock_build_day_report,
    tmp_path: Path,
):
    mock_get_app_config.return_value = _make_app_config(tmp_path / "prod_logs", tmp_path / "dev_logs")
    day_review = MagicMock()
    mock_get_service.return_value.review_day.return_value = day_review
    mock_build_day_report.return_value = "report"

    result = review_date_trades_tool.run(
        {
            "trading_date": "2026-03-05",
            "log_source": "dev",
        }
    )

    assert result == "report"
    mock_get_service.assert_called_once_with("dev")
    mock_save_day_review.assert_called_once_with(day_review, log_source="dev")


def test_review_store_loads_source_specific_files(tmp_path: Path):
    with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
        trading_date = date(2026, 3, 5)
        trade = ParsedTrade(trading_date=trading_date, symbol="AMPX")
        trade_review = TradeReview(trade=trade)
        day_review = DayReview(trading_date=trading_date, trades=[trade_review])

        save_day_review(day_review, log_source="dev")
        save_trade_review(trade_review, log_source="dev")

        assert load_day_review_json(trading_date, log_source="dev") is not None
        assert load_trade_review_json("AMPX", trading_date, log_source="dev") is not None
