"""Tests for src.community.finance.review_store — JSON persistence, round-trip, list."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.community.finance.models import (
    DayReview,
    EntryEvent,
    EntryVerdict,
    ExitEvent,
    ExitPolicy,
    ExitVerdict,
    ParsedTrade,
    PatternType,
    QualityTier,
    ReviewVerdict,
    SelectionVerdict,
    Signal,
    SignalType,
    TradeOutcome,
    TradeReview,
)
from src.community.finance.review_store import (
    _ReviewEncoder,
    list_saved_reviews,
    load_day_review_json,
    load_trade_review_json,
    save_day_review,
    save_trade_review,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_TS = datetime(2026, 3, 5, 9, 36, 0)


def _make_signal() -> Signal:
    return Signal(timestamp=_TS, symbol="TEST", signal_type=SignalType.MAIN, score=8.0, pwin=85.0, bars=100, ret5m_predicted=3.5, dd_predicted=1.0, tvr=12.0, raw_line="test")


def _make_trade(symbol: str = "TEST") -> ParsedTrade:
    return ParsedTrade(
        trading_date=date(2026, 3, 5),
        symbol=symbol,
        signal=_make_signal(),
        entry=EntryEvent(timestamp=_TS, symbol=symbol, price=10.0, quantity=100),
        exit=ExitEvent(timestamp=_TS + timedelta(minutes=24), symbol=symbol, price=10.5),
        outcome=TradeOutcome.TP_FILLED,
    )


def _make_trade_review(symbol: str = "TEST") -> TradeReview:
    return TradeReview(
        trade=_make_trade(symbol),
        quality_tier=QualityTier.GOOD,
        overall_verdict=ReviewVerdict.ACCEPTABLE,
        selection=SelectionVerdict(should_trade=True, confidence=0.8, reasons=["Strong signal"]),
        entry=EntryVerdict(should_have_waited=False, reasons=["OK"]),
        exit=ExitVerdict(
            recommended_policy=ExitPolicy.TRAILING_STOP,
            max_favorable_excursion_pct=5.0,
            reasons=["Good exit"],
            simulations={"fixed_tp_sl": {"tp5_sl3": {"pnl_pct": 4.5}}},
        ),
        pattern=PatternType.STRONG_UPTRENDING,
        total_iterations=15,
    )


def _make_day_review() -> DayReview:
    return DayReview(
        trading_date=date(2026, 3, 5),
        trades=[_make_trade_review("AMPX"), _make_trade_review("MOBX")],
        summary_stats={"total_trades": 2, "winners": 2},
        lessons=["All trades profitable"],
    )


# ---------------------------------------------------------------------------
# _ReviewEncoder
# ---------------------------------------------------------------------------


class TestReviewEncoder:
    def test_encodes_enum(self):
        result = json.dumps(SignalType.MAIN, cls=_ReviewEncoder)
        assert result == '"MAIN"'

    def test_encodes_date(self):
        result = json.dumps(date(2026, 3, 5), cls=_ReviewEncoder)
        assert result == '"2026-03-05"'

    def test_encodes_datetime(self):
        result = json.dumps(datetime(2026, 3, 5, 9, 30, 0), cls=_ReviewEncoder)
        assert result == '"2026-03-05T09:30:00"'

    def test_encodes_dataclass(self):
        signal = _make_signal()
        result = json.dumps(signal, cls=_ReviewEncoder)
        data = json.loads(result)
        assert data["symbol"] == "TEST"
        assert data["signal_type"] == "MAIN"
        assert data["score"] == 8.0

    def test_round_trip_trade_review(self):
        review = _make_trade_review()
        json_str = json.dumps(review, cls=_ReviewEncoder, indent=2)
        data = json.loads(json_str)
        assert data["trade"]["symbol"] == "TEST"
        assert data["quality_tier"] == 2  # QualityTier.GOOD.value
        assert data["overall_verdict"] == "acceptable"
        assert data["selection"]["should_trade"] is True
        assert data["pattern"] == "strong_uptrending"

    def test_round_trip_day_review(self):
        day = _make_day_review()
        json_str = json.dumps(day, cls=_ReviewEncoder, indent=2)
        data = json.loads(json_str)
        assert data["trading_date"] == "2026-03-05"
        assert len(data["trades"]) == 2
        assert data["summary_stats"]["total_trades"] == 2

    def test_nested_enum_in_dict(self):
        data = {"policy": ExitPolicy.TRAILING_STOP, "outcome": TradeOutcome.STRANDED}
        result = json.loads(json.dumps(data, cls=_ReviewEncoder))
        assert result["policy"] == "trailing_stop"
        assert result["outcome"] == "stranded"

    def test_nested_dataclass_in_list(self):
        signals = [_make_signal(), _make_signal()]
        result = json.loads(json.dumps(signals, cls=_ReviewEncoder))
        assert len(result) == 2
        assert all(s["signal_type"] == "MAIN" for s in result)


# ---------------------------------------------------------------------------
# Save / Load day review
# ---------------------------------------------------------------------------


class TestDayReviewPersistence:
    def test_save_and_load(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            day = _make_day_review()
            path = save_day_review(day)
            assert path.exists()
            assert path.suffix == ".json"

            loaded = load_day_review_json(date(2026, 3, 5))
            assert loaded is not None
            assert loaded["trading_date"] == "2026-03-05"
            assert len(loaded["trades"]) == 2

    def test_load_nonexistent_returns_none(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            loaded = load_day_review_json(date(2099, 1, 1))
            assert loaded is None

    def test_filename_format(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            day = _make_day_review()
            path = save_day_review(day)
            assert path.name == "day_review_2026-03-05.json"

    def test_overwrites_existing(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            day = _make_day_review()
            save_day_review(day)
            # Save again with modified data
            day.lessons = ["New lesson"]
            save_day_review(day)
            loaded = load_day_review_json(date(2026, 3, 5))
            assert "New lesson" in loaded["lessons"]


# ---------------------------------------------------------------------------
# Save / Load trade review
# ---------------------------------------------------------------------------


class TestTradeReviewPersistence:
    def test_save_and_load(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            review = _make_trade_review("AMPX")
            review.trade.symbol = "AMPX"
            path = save_trade_review(review)
            assert path.exists()

            loaded = load_trade_review_json("AMPX", date(2026, 3, 5))
            assert loaded is not None

    def test_load_nonexistent_returns_none(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            loaded = load_trade_review_json("ZZZZ", date(2099, 1, 1))
            assert loaded is None

    def test_filename_format(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            review = _make_trade_review("AMPX")
            review.trade.symbol = "AMPX"
            path = save_trade_review(review)
            assert path.name == "trade_review_AMPX_2026-03-05.json"


# ---------------------------------------------------------------------------
# list_saved_reviews
# ---------------------------------------------------------------------------


class TestListSavedReviews:
    def test_lists_json_files(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            (tmp_path / "day_review_2026-03-05.json").write_text("{}")
            (tmp_path / "trade_review_AMPX_2026-03-05.json").write_text("{}")
            (tmp_path / "not_a_review.txt").write_text("ignore")

            result = list_saved_reviews()
            assert len(result) == 2
            assert "day_review_2026-03-05.json" in result
            assert "trade_review_AMPX_2026-03-05.json" in result

    def test_empty_when_no_dir(self, tmp_path: Path):
        nonexistent = tmp_path / "does_not_exist"
        with patch("src.community.finance.review_store._STORE_DIR", nonexistent):
            result = list_saved_reviews()
            assert result == []

    def test_sorted_output(self, tmp_path: Path):
        with patch("src.community.finance.review_store._STORE_DIR", tmp_path):
            (tmp_path / "z_review.json").write_text("{}")
            (tmp_path / "a_review.json").write_text("{}")

            result = list_saved_reviews()
            assert result == ["a_review.json", "z_review.json"]
