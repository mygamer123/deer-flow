"""Tests for src.community.finance.market_data_service — PolygonClient, DuckDBAccessor, MarketDataService."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.community.finance.market_data_service import (
    DuckDBAccessor,
    MarketDataService,
    PolygonClient,
    _date_str,
    _ms_to_datetime,
    market_datetime_to_ns,
)
from src.community.finance.models import MinuteBar, NewsItem, TickerDetails

# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _polygon_bar(t: int, o: float = 10.0, h: float = 10.5, l: float = 9.8, c: float = 10.2, v: int = 1000, n: int = 50) -> dict[str, Any]:  # noqa: E741
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "n": n}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_ms_to_datetime(self):
        ts_ms = 1709654400000  # 2024-03-05 16:00:00 UTC
        dt = _ms_to_datetime(ts_ms)
        assert isinstance(dt, datetime)
        assert dt == datetime(2024, 3, 5, 11, 0)

    def test_market_datetime_to_ns_treats_naive_as_eastern(self):
        ts = datetime(2026, 3, 5, 9, 30)
        assert _ms_to_datetime(market_datetime_to_ns(ts) // 1_000_000) == ts

    def test_date_str_from_date(self):
        assert _date_str(date(2026, 3, 5)) == "2026-03-05"

    def test_date_str_from_string(self):
        assert _date_str("2026-03-05") == "2026-03-05"


# ---------------------------------------------------------------------------
# PolygonClient
# ---------------------------------------------------------------------------


class TestPolygonClient:
    def test_init_raises_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="POLYGON_API_KEY"):
                PolygonClient(api_key="")

    def test_init_with_explicit_key(self):
        client = PolygonClient(api_key="test-key-123")
        assert client.api_key == "test-key-123"

    def test_get_aggs_basic(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [_polygon_bar(1000), _polygon_bar(2000)]}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_aggs("AAPL", 1, "minute", "2026-03-05", "2026-03-05")
        assert len(result) == 2
        assert result[0]["t"] == 1000

    def test_get_aggs_with_pagination(self):
        client = PolygonClient(api_key="test-key")
        page1_resp = MagicMock()
        page1_resp.json.return_value = {"results": [_polygon_bar(1000)], "next_url": "https://api.polygon.io/next?cursor=abc"}
        page1_resp.raise_for_status = MagicMock()

        page2_resp = MagicMock()
        page2_resp.json.return_value = {"results": [_polygon_bar(2000)]}
        page2_resp.raise_for_status = MagicMock()

        client._session = MagicMock()
        client._session.get.side_effect = [page1_resp, page2_resp]

        result = client.get_aggs("AAPL", 1, "minute", "2026-03-05", "2026-03-05")
        assert len(result) == 2

    def test_get_ticker_details(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": {"ticker": "AAPL", "name": "Apple Inc"}}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_ticker_details("AAPL")
        assert result["ticker"] == "AAPL"

    def test_get_news(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"title": "Test News"}]}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_news("AAPL", published_utc_gte="2026-03-04", published_utc_lt="2026-03-06")
        assert len(result) == 1

        _, kwargs = client._session.get.call_args
        assert kwargs["params"]["published_utc.gte"] == "2026-03-04"
        assert kwargs["params"]["published_utc.lt"] == "2026-03-06"

    def test_get_trades(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"price": 150.0}]}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_trades("AAPL", timestamp_gte="123", timestamp_lt="456")
        assert len(result) == 1

    def test_get_quotes(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"bid_price": 149.9, "ask_price": 150.1}]}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_quotes("AAPL", timestamp_gte="123", timestamp_lt="456")
        assert len(result) == 1

    def test_get_sma(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": {"values": [{"value": 150.0}]}}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_sma("AAPL", 20)
        assert len(result) == 1

    def test_get_ticker_snapshot(self):
        client = PolygonClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ticker": {"todaysChangePerc": 1.5}}
        mock_resp.raise_for_status = MagicMock()
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        result = client.get_ticker_snapshot("AAPL")
        assert "todaysChangePerc" in result


# ---------------------------------------------------------------------------
# DuckDBAccessor
# ---------------------------------------------------------------------------


class TestDuckDBAccessor:
    def test_query_returns_list_of_dicts(self):
        accessor = DuckDBAccessor.__new__(DuckDBAccessor)
        mock_conn = MagicMock()
        mock_rel = MagicMock()
        mock_rel.description = [("ticker",), ("date",), ("close",)]
        mock_rel.fetchall.return_value = [("AAPL", date(2026, 3, 5), 150.0)]
        mock_conn.sql.return_value = mock_rel
        accessor._conn = mock_conn
        accessor.db_path = "/fake/path"

        result = accessor.query("SELECT * FROM test")
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_get_minute_bars_calls_query(self):
        accessor = DuckDBAccessor.__new__(DuckDBAccessor)
        mock_conn = MagicMock()
        mock_rel = MagicMock()
        mock_rel.description = [("ticker",), ("trading_date",), ("window_start",), ("ts_ms",), ("open",), ("high",), ("low",), ("close",), ("volume",), ("transactions",)]
        mock_rel.fetchall.return_value = [("AAPL", date(2026, 3, 5), datetime(2026, 3, 5, 9, 30), 1000, 10.0, 10.5, 9.8, 10.2, 5000, 100)]
        mock_conn.sql.return_value = mock_rel
        accessor._conn = mock_conn
        accessor.db_path = "/fake/path"

        result = accessor.get_minute_bars("AAPL", date(2026, 3, 5))
        assert len(result) == 1

    def test_find_similar_signals(self):
        accessor = DuckDBAccessor.__new__(DuckDBAccessor)
        mock_conn = MagicMock()
        mock_rel = MagicMock()
        mock_rel.description = [("ticker",), ("date",), ("open",), ("high",), ("low",), ("close",), ("volume",)]
        mock_rel.fetchall.return_value = []
        mock_conn.sql.return_value = mock_rel
        accessor._conn = mock_conn
        accessor.db_path = "/fake/path"

        result = accessor.find_similar_signals(score_min=5.0, score_max=10.0, tvr_min=1e6, tvr_max=2e7)
        assert result == []

    def test_close(self):
        accessor = DuckDBAccessor.__new__(DuckDBAccessor)
        mock_conn = MagicMock()
        accessor._conn = mock_conn
        accessor.db_path = "/fake/path"

        accessor.close()
        mock_conn.close.assert_called_once()
        assert accessor._conn is None

    def test_close_noop_when_not_connected(self):
        accessor = DuckDBAccessor.__new__(DuckDBAccessor)
        accessor._conn = None
        accessor.db_path = "/fake/path"
        accessor.close()  # should not raise


# ---------------------------------------------------------------------------
# MarketDataService
# ---------------------------------------------------------------------------


class TestMarketDataService:
    def _make_service(self) -> MarketDataService:
        svc = MarketDataService.__new__(MarketDataService)
        svc._polygon = MagicMock(spec=PolygonClient)
        svc._duckdb = MagicMock(spec=DuckDBAccessor)
        svc._polygon_api_key = "test-key"
        return svc

    def test_get_minute_bars_from_polygon(self):
        svc = self._make_service()
        svc._polygon.get_aggs.return_value = [_polygon_bar(1709654400000), _polygon_bar(1709654460000)]

        bars = svc.get_minute_bars("AAPL", date(2026, 3, 5))
        assert len(bars) == 2
        assert all(isinstance(b, MinuteBar) for b in bars)
        svc._polygon.get_aggs.assert_called_once()

    def test_get_minute_bars_falls_back_to_duckdb(self):
        svc = self._make_service()
        svc._polygon.get_aggs.side_effect = Exception("Polygon down")
        svc._duckdb.get_minute_bars.return_value = [
            {"ticker": "AAPL", "window_start": datetime(2026, 3, 5, 9, 30), "window_start_ns": 0, "ts_ms": 1000, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000, "transactions": 50}
        ]

        bars = svc.get_minute_bars("AAPL", date(2026, 3, 5))
        assert len(bars) == 1
        assert bars[0].open == 10.0

    def test_get_minute_bars_returns_empty_on_both_failures(self):
        svc = self._make_service()
        svc._polygon.get_aggs.side_effect = Exception("fail")
        svc._duckdb.get_minute_bars.side_effect = Exception("fail")

        bars = svc.get_minute_bars("AAPL", date(2026, 3, 5))
        assert bars == []

    def test_get_premarket_bars_filters_by_time(self):
        svc = self._make_service()
        all_bars = [
            _polygon_bar(int(datetime(2026, 3, 5, 7, 0).timestamp() * 1000)),  # premarket
            _polygon_bar(int(datetime(2026, 3, 5, 8, 30).timestamp() * 1000)),  # premarket
            _polygon_bar(int(datetime(2026, 3, 5, 9, 30).timestamp() * 1000)),  # regular
            _polygon_bar(int(datetime(2026, 3, 5, 10, 0).timestamp() * 1000)),  # regular
        ]
        svc._polygon.get_aggs.return_value = all_bars

        pm_bars = svc.get_premarket_bars("AAPL", date(2026, 3, 5))
        # Should only include bars with hour 4-9 (before 9:30)
        assert all(b.timestamp.hour < 9 or (b.timestamp.hour == 9 and b.timestamp.minute < 30) for b in pm_bars)

    def test_get_daily_bars_prefers_duckdb(self):
        svc = self._make_service()
        svc._duckdb.get_daily_bars.return_value = [{"ticker": "AAPL", "date": date(2026, 3, 4), "open": 149.0, "high": 151.0, "low": 148.0, "close": 150.0, "volume": 50000, "transactions": 1000}]

        bars = svc.get_daily_bars("AAPL", start_date=date(2026, 3, 1), end_date=date(2026, 3, 5))
        assert len(bars) == 1
        svc._duckdb.get_daily_bars.assert_called_once()
        svc._polygon.get_aggs.assert_not_called()

    def test_get_ticker_details_returns_model(self):
        svc = self._make_service()
        svc._polygon.get_ticker_details.return_value = {
            "ticker": "AAPL",
            "name": "Apple Inc",
            "sic_description": "Technology",
            "market_cap": 2_800_000_000_000,
            "share_class_shares_outstanding": 15_000_000_000,
            "weighted_shares_outstanding": 15_000_000_000,
            "description": "Apple designs...",
        }

        details = svc.get_ticker_details("AAPL")
        assert isinstance(details, TickerDetails)
        assert details.symbol == "AAPL"
        assert details.name == "Apple Inc"

    def test_get_news_returns_news_items(self):
        svc = self._make_service()
        svc._polygon.get_news.return_value = [
            {
                "title": "Apple earnings",
                "published_utc": "2026-03-05T10:00:00Z",
                "article_url": "https://example.com",
                "tickers": ["AAPL"],
                "insights": [{"ticker": "AAPL", "sentiment": "positive", "sentiment_reasoning": "0.8"}],
            }
        ]

        items = svc.get_news("AAPL", around_date=date(2026, 3, 5))
        assert len(items) == 1
        assert isinstance(items[0], NewsItem)
        assert items[0].sentiment == "positive"
        svc._polygon.get_news.assert_called_once_with(
            "AAPL",
            published_utc_gte="2026-03-04T05:00:00Z",
            published_utc_lt="2026-03-06T05:00:00Z",
            limit=10,
        )

    def test_get_tick_quotes_uses_polygon_quotes(self):
        svc = self._make_service()
        svc._polygon.get_quotes.return_value = [{"bid_price": 100.0, "ask_price": 100.1}]

        result = svc.get_tick_quotes("AAPL", timestamp_gte="1", timestamp_lt="2")

        assert result == [{"bid_price": 100.0, "ask_price": 100.1}]
        svc._polygon.get_quotes.assert_called_once_with("AAPL", timestamp_gte="1", timestamp_lt="2", limit=5000)

    def test_get_sector_peer_bars_with_tech_sector(self):
        svc = self._make_service()
        svc._polygon.get_ticker_details.return_value = {
            "ticker": "AAPL",
            "name": "Apple",
            "sic_description": "Technology",
        }
        svc._polygon.get_aggs.return_value = [_polygon_bar(1000)]

        result = svc.get_sector_peer_bars("AAPL", date(2026, 3, 5))
        assert isinstance(result, dict)
        # Should try XLK and/or ARKK
        assert any(k in result for k in ["XLK", "ARKK", "SPY", "IWM"])

    def test_get_sector_peer_bars_falls_back_to_spy_iwm(self):
        svc = self._make_service()
        svc._polygon.get_ticker_details.return_value = {
            "ticker": "ZZZZ",
            "name": "Unknown Corp",
            "sic_description": "Exotic Industry",
        }
        svc._polygon.get_aggs.return_value = [_polygon_bar(1000)]

        result = svc.get_sector_peer_bars("ZZZZ", date(2026, 3, 5))
        # Unknown sector should fall back to SPY, IWM
        assert "SPY" in result or "IWM" in result

    def test_get_sector_peer_bars_handles_details_failure(self):
        svc = self._make_service()
        svc._polygon.get_ticker_details.side_effect = Exception("fail")

        result = svc.get_sector_peer_bars("AAPL", date(2026, 3, 5))
        assert result == {}

    def test_polygon_bars_to_model_static(self):
        raw = [_polygon_bar(1709654400000, o=150.0, h=151.0, l=149.0, c=150.5, v=5000, n=100)]
        bars = MarketDataService._polygon_bars_to_model(raw)
        assert len(bars) == 1
        assert bars[0].open == 150.0
        assert bars[0].high == 151.0
        assert bars[0].volume == 5000

    def test_duckdb_bars_to_model_minute(self):
        raw = [{"window_start": datetime(2026, 3, 5, 9, 30), "window_start_ns": 123456789, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000, "transactions": 50}]
        bars = MarketDataService._duckdb_bars_to_model(raw)
        assert len(bars) == 1
        assert bars[0].timestamp == datetime(2026, 3, 5, 9, 30)

    def test_duckdb_bars_to_model_daily(self):
        raw = [{"date": date(2026, 3, 5), "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000, "transactions": 50}]
        bars = MarketDataService._duckdb_bars_to_model(raw, is_daily=True)
        assert len(bars) == 1
        # date should be converted to datetime
        assert isinstance(bars[0].timestamp, datetime)

    def test_lazy_polygon_init(self):
        svc = MarketDataService(polygon_api_key="test-key-123")
        assert svc._polygon is None
        p = svc.polygon
        assert isinstance(p, PolygonClient)
        assert svc._polygon is p
