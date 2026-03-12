# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .models import MinuteBar, NewsItem, TickerDetails

logger = logging.getLogger(__name__)
MARKET_TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# DuckDB path (optional — only used when available)
# ---------------------------------------------------------------------------
_DUCKDB_PATH = os.path.expanduser("~/Documents/github/topgainer_monitor/duckdb/topgainer.duckdb")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms_to_datetime(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(MARKET_TZ).replace(tzinfo=None)


def market_datetime_to_ns(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=MARKET_TZ)
    else:
        ts = ts.astimezone(MARKET_TZ)
    return int(ts.astimezone(UTC).timestamp() * 1_000_000_000)


def _normalize_market_datetime(ts: date | datetime | None) -> datetime:
    if ts is None:
        return datetime.min
    if not isinstance(ts, datetime):
        return datetime(ts.year, ts.month, ts.day)
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(MARKET_TZ).replace(tzinfo=None)


def _market_day_bounds_to_utc(start_day: date, end_day: date) -> tuple[str, str]:
    start_dt = datetime(start_day.year, start_day.month, start_day.day, tzinfo=MARKET_TZ)
    end_dt = datetime(end_day.year, end_day.month, end_day.day, tzinfo=MARKET_TZ)
    start_utc = start_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    end_utc = end_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return start_utc, end_utc


def _date_str(d: date | str) -> str:
    if isinstance(d, date):
        return d.isoformat()
    return d


# ---------------------------------------------------------------------------
# Polygon REST client (thin wrapper)
# ---------------------------------------------------------------------------


class PolygonClient:
    """Thin, stateless wrapper around Polygon.io REST API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY", "")
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY is not set. Add it to .env or export it.")
        self.base_url = "https://api.polygon.io"
        self._session = requests.Session()

    # -- low-level request ------------------------------------------------

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # -- aggregated bars --------------------------------------------------

    def get_aggs(
        self,
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str | date,
        to_date: str | date,
        *,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        """Return OHLCV bars.  Handles pagination via ``next_url``."""
        endpoint = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{_date_str(from_date)}/{_date_str(to_date)}"
        params: dict[str, Any] = {"adjusted": str(adjusted).lower(), "sort": sort, "limit": limit}
        all_results: list[dict[str, Any]] = []
        data = self._get(endpoint, params)
        all_results.extend(data.get("results", []))

        # Follow pagination (Polygon returns ``next_url`` when there are more pages)
        while data.get("next_url"):
            next_url = data["next_url"]
            if "apikey=" not in next_url:
                separator = "&" if "?" in next_url else "?"
                next_url = f"{next_url}{separator}apikey={self.api_key}"
            resp = self._session.get(next_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            all_results.extend(data.get("results", []))
        return all_results

    # -- ticker details ---------------------------------------------------

    def get_ticker_details(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/v3/reference/tickers/{ticker}").get("results", {})

    # -- news -------------------------------------------------------------

    def get_news(
        self,
        ticker: str | None = None,
        *,
        published_utc_gte: str | None = None,
        published_utc_lt: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "order": "desc"}
        if ticker:
            params["ticker"] = ticker
        if published_utc_gte:
            params["published_utc.gte"] = published_utc_gte
        if published_utc_lt:
            params["published_utc.lt"] = published_utc_lt
        return self._get("/v2/reference/news", params).get("results", [])

    # -- trades (tick-level) ---------------------------------------------

    def get_trades(self, ticker: str, *, timestamp_gte: str | None = None, timestamp_lt: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "order": "asc"}
        if timestamp_gte:
            params["timestamp.gte"] = timestamp_gte
        if timestamp_lt:
            params["timestamp.lt"] = timestamp_lt
        return self._get(f"/v3/trades/{ticker}", params).get("results", [])

    def get_quotes(self, ticker: str, *, timestamp_gte: str | None = None, timestamp_lt: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "order": "asc"}
        if timestamp_gte:
            params["timestamp.gte"] = timestamp_gte
        if timestamp_lt:
            params["timestamp.lt"] = timestamp_lt
        return self._get(f"/v3/quotes/{ticker}", params).get("results", [])

    # -- technical indicators ---------------------------------------------

    def get_sma(self, ticker: str, window: int, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"window": window, "timespan": timespan, **extra}
        return self._get(f"/v1/indicators/sma/{ticker}", params).get("results", {}).get("values", [])

    def get_ema(self, ticker: str, window: int, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"window": window, "timespan": timespan, **extra}
        return self._get(f"/v1/indicators/ema/{ticker}", params).get("results", {}).get("values", [])

    def get_rsi(self, ticker: str, window: int = 14, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"window": window, "timespan": timespan, **extra}
        return self._get(f"/v1/indicators/rsi/{ticker}", params).get("results", {}).get("values", [])

    def get_macd(self, ticker: str, *, short_window: int = 12, long_window: int = 26, signal_window: int = 9, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"short_window": short_window, "long_window": long_window, "signal_window": signal_window, "timespan": timespan, **extra}
        return self._get(f"/v1/indicators/macd/{ticker}", params).get("results", {}).get("values", [])

    # -- snapshot ---------------------------------------------------------

    def get_ticker_snapshot(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}").get("ticker", {})


# ---------------------------------------------------------------------------
# DuckDB accessor (lazy — only imported when called)
# ---------------------------------------------------------------------------


class DuckDBAccessor:
    """Read-only accessor for the topgainer DuckDB warehouse."""

    def __init__(self, db_path: str = _DUCKDB_PATH):
        self.db_path = db_path
        self._conn: Any | None = None

    def _ensure_conn(self) -> Any:
        if self._conn is None:
            try:
                import duckdb  # noqa: F811

                self._conn = duckdb.connect(self.db_path, read_only=True)
            except Exception:
                logger.exception("Failed to connect to DuckDB at %s", self.db_path)
                raise
        return self._conn

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        conn = self._ensure_conn()
        rel = conn.sql(sql, params=params) if params else conn.sql(sql)
        columns = [desc[0] for desc in rel.description]
        rows = rel.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_minute_bars(self, ticker: str, trading_date: date) -> list[dict[str, Any]]:
        sql = """
            SELECT ticker, trading_date, window_start, ts_ms, open, high, low, close, volume, transactions
            FROM tg.v_minute_bars
            WHERE ticker = $ticker AND trading_date = $trading_date
            ORDER BY ts_ms
        """
        return self.query(sql, {"ticker": ticker, "trading_date": trading_date})

    def get_daily_bars(self, ticker: str, *, start_date: date, end_date: date) -> list[dict[str, Any]]:
        sql = """
            SELECT ticker, date, open, high, low, close, volume, transactions
            FROM tg.daily_bars
            WHERE ticker = $ticker AND date BETWEEN $start_date AND $end_date
            ORDER BY date
        """
        return self.query(sql, {"ticker": ticker, "start_date": start_date, "end_date": end_date})

    def find_similar_signals(self, *, score_min: float, score_max: float, tvr_min: float, tvr_max: float, limit: int = 50) -> list[dict[str, Any]]:
        """Approximate: finds daily bars with similar volume characteristics."""
        sql = """
            SELECT ticker, date, open, high, low, close, volume
            FROM tg.daily_bars
            WHERE volume BETWEEN $tvr_min AND $tvr_max
            ORDER BY date DESC
            LIMIT $limit
        """
        return self.query(sql, {"tvr_min": int(tvr_min), "tvr_max": int(tvr_max), "limit": limit})

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Unified MarketDataService
# ---------------------------------------------------------------------------


class MarketDataService:
    """Polygon preferred for recent data (real-time); DuckDB for deep historical (no API cost)."""

    def __init__(self, *, polygon_api_key: str | None = None):
        self._polygon: PolygonClient | None = None
        self._duckdb: DuckDBAccessor | None = None
        self._polygon_api_key = polygon_api_key

    # -- lazy init --------------------------------------------------------

    @property
    def polygon(self) -> PolygonClient:
        if self._polygon is None:
            self._polygon = PolygonClient(api_key=self._polygon_api_key)
        return self._polygon

    @property
    def duckdb(self) -> DuckDBAccessor:
        if self._duckdb is None:
            self._duckdb = DuckDBAccessor()
        return self._duckdb

    # -- minute bars (core workhorse) ------------------------------------

    def get_minute_bars(self, ticker: str, trading_date: date, *, prefer_polygon: bool = True) -> list[MinuteBar]:
        """Return 1-minute OHLCV bars for *ticker* on *trading_date*.

        Uses Polygon for recent dates (within 2 days) and DuckDB for older
        dates, unless overridden by ``prefer_polygon``.
        """
        is_recent = (date.today() - trading_date).days <= 2

        if prefer_polygon or is_recent:
            try:
                raw_polygon = self.polygon.get_aggs(ticker, 1, "minute", trading_date, trading_date)
                return self._polygon_bars_to_model(raw_polygon)
            except Exception:
                logger.warning("Polygon minute bars failed for %s %s, falling back to DuckDB", ticker, trading_date, exc_info=True)

        # DuckDB fallback
        try:
            raw_duck = self.duckdb.get_minute_bars(ticker, trading_date)
            return self._duckdb_bars_to_model(raw_duck)
        except Exception:
            logger.warning("DuckDB minute bars also failed for %s %s", ticker, trading_date, exc_info=True)
            return []

    def get_premarket_bars(self, ticker: str, trading_date: date) -> list[MinuteBar]:
        """Return pre-market (04:00–09:30 ET) minute bars from Polygon.

        Polygon includes extended-hours bars in the same aggs endpoint.
        We filter by timestamp.
        """
        all_bars = self.get_minute_bars(ticker, trading_date)
        premarket: list[MinuteBar] = []
        for bar in all_bars:
            hour = bar.timestamp.hour
            minute = bar.timestamp.minute
            # Pre-market: 04:00–09:29
            if (4 <= hour < 9) or (hour == 9 and minute < 30):
                premarket.append(bar)
        return premarket

    # -- multi-timeframe bars (5m, 15m) -----------------------------------

    def get_5min_bars(self, ticker: str, trading_date: date) -> list[MinuteBar]:
        raw = self.polygon.get_aggs(ticker, 5, "minute", trading_date, trading_date)
        return self._polygon_bars_to_model(raw)

    def get_15min_bars(self, ticker: str, trading_date: date) -> list[MinuteBar]:
        raw = self.polygon.get_aggs(ticker, 15, "minute", trading_date, trading_date)
        return self._polygon_bars_to_model(raw)

    # -- daily bars -------------------------------------------------------

    def get_daily_bars(self, ticker: str, *, start_date: date, end_date: date, prefer_polygon: bool = False) -> list[MinuteBar]:
        """Daily OHLCV bars.  Prefer DuckDB for historical breadth."""
        if not prefer_polygon:
            try:
                raw_duck = self.duckdb.get_daily_bars(ticker, start_date=start_date, end_date=end_date)
                return self._duckdb_bars_to_model(raw_duck, is_daily=True)
            except Exception:
                logger.warning("DuckDB daily bars failed for %s, falling back to Polygon", ticker, exc_info=True)

        raw_polygon = self.polygon.get_aggs(ticker, 1, "day", start_date, end_date)
        return self._polygon_bars_to_model(raw_polygon)

    # -- SPY / QQQ (market context) ---------------------------------------

    def get_spy_bars(self, trading_date: date) -> list[MinuteBar]:
        return self.get_minute_bars("SPY", trading_date)

    def get_qqq_bars(self, trading_date: date) -> list[MinuteBar]:
        return self.get_minute_bars("QQQ", trading_date)

    # -- ticker details ---------------------------------------------------

    def get_ticker_details(self, ticker: str) -> TickerDetails:
        raw = self.polygon.get_ticker_details(ticker)
        return TickerDetails(
            symbol=raw.get("ticker", ticker),
            name=raw.get("name", ""),
            sector=raw.get("sic_description", ""),
            industry=raw.get("sic_description", ""),
            market_cap=raw.get("market_cap"),
            shares_outstanding=raw.get("share_class_shares_outstanding"),
            float_shares=raw.get("weighted_shares_outstanding"),
            description=raw.get("description", ""),
        )

    # -- news & sentiment -------------------------------------------------

    def get_news(self, ticker: str, *, around_date: date | None = None, limit: int = 10) -> list[NewsItem]:
        published_gte: str | None = None
        published_lt: str | None = None
        if around_date:
            published_gte, published_lt = _market_day_bounds_to_utc(around_date - timedelta(days=1), around_date + timedelta(days=1))
        raw = self.polygon.get_news(ticker, published_utc_gte=published_gte, published_utc_lt=published_lt, limit=limit)
        items: list[NewsItem] = []
        for article in raw:
            sentiment = ""
            sentiment_score = 0.0
            for insight in article.get("insights", []):
                if insight.get("ticker", "").upper() == ticker.upper():
                    sentiment = insight.get("sentiment", "")
                    sentiment_score = _safe_float(insight.get("sentiment_reasoning", ""), 0.0)
                    break
            items.append(
                NewsItem(
                    title=article.get("title", ""),
                    published_utc=article.get("published_utc", ""),
                    article_url=article.get("article_url", ""),
                    sentiment=sentiment,
                    sentiment_score=sentiment_score,
                    tickers=[t for t in article.get("tickers", [])],
                )
            )
        return items

    # -- tick-level trades ------------------------------------------------

    def get_tick_trades(self, ticker: str, *, timestamp_gte: str | None = None, timestamp_lt: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        """Return raw tick-level trade data from Polygon."""
        return self.polygon.get_trades(ticker, timestamp_gte=timestamp_gte, timestamp_lt=timestamp_lt, limit=limit)

    def get_tick_quotes(self, ticker: str, *, timestamp_gte: str | None = None, timestamp_lt: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        """Return raw NBBO quote data from Polygon."""
        return self.polygon.get_quotes(ticker, timestamp_gte=timestamp_gte, timestamp_lt=timestamp_lt, limit=limit)

    # -- technical indicators ---------------------------------------------

    def get_sma(self, ticker: str, window: int, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        return self.polygon.get_sma(ticker, window, timespan, **extra)

    def get_ema(self, ticker: str, window: int, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        return self.polygon.get_ema(ticker, window, timespan, **extra)

    def get_rsi(self, ticker: str, window: int = 14, timespan: str = "day", **extra: Any) -> list[dict[str, Any]]:
        return self.polygon.get_rsi(ticker, window, timespan, **extra)

    def get_macd(self, ticker: str, **extra: Any) -> list[dict[str, Any]]:
        return self.polygon.get_macd(ticker, **extra)

    # -- snapshot ---------------------------------------------------------

    def get_ticker_snapshot(self, ticker: str) -> dict[str, Any]:
        return self.polygon.get_ticker_snapshot(ticker)

    # -- DuckDB historical query (for similar signals) --------------------

    def find_similar_signals(self, *, score_min: float, score_max: float, tvr_min: float, tvr_max: float, limit: int = 50) -> list[dict[str, Any]]:
        return self.duckdb.find_similar_signals(score_min=score_min, score_max=score_max, tvr_min=tvr_min, tvr_max=tvr_max, limit=limit)

    # -- sector peers -----------------------------------------------------

    def get_sector_peer_bars(self, ticker: str, trading_date: date, *, max_peers: int = 5) -> dict[str, list[MinuteBar]]:
        """Returns minute bars for sector-proxy ETFs (e.g. XLK for tech)."""
        try:
            details = self.get_ticker_details(ticker)
        except Exception:
            logger.warning("Could not get ticker details for %s, skipping sector peers", ticker)
            return {}

        # Sector ETF proxies — lightweight approach
        _sector_etfs: dict[str, list[str]] = {
            "technology": ["XLK", "ARKK"],
            "healthcare": ["XLV", "XBI"],
            "financial": ["XLF"],
            "energy": ["XLE"],
            "consumer": ["XLY", "XLP"],
            "industrial": ["XLI"],
            "communication": ["XLC"],
            "utilities": ["XLU"],
            "materials": ["XLB"],
            "real estate": ["XLRE"],
        }
        sector_lower = (details.sector or "").lower()
        peers: list[str] = []
        for key, etfs in _sector_etfs.items():
            if key in sector_lower:
                peers = etfs[:max_peers]
                break

        if not peers:
            # Default to broad market ETFs
            peers = ["SPY", "IWM"]

        result: dict[str, list[MinuteBar]] = {}
        for peer in peers:
            try:
                result[peer] = self.get_minute_bars(peer, trading_date)
            except Exception:
                logger.warning("Failed to get peer bars for %s", peer)
        return result

    # -- conversion helpers -----------------------------------------------

    @staticmethod
    def _polygon_bars_to_model(raw_bars: list[dict[str, Any]]) -> list[MinuteBar]:
        bars: list[MinuteBar] = []
        for r in raw_bars:
            ts_ms = r.get("t", 0)
            bars.append(
                MinuteBar(
                    timestamp=_ms_to_datetime(ts_ms),
                    timestamp_ns=ts_ms * 1_000_000,  # ms → ns
                    open=r.get("o", 0.0),
                    high=r.get("h", 0.0),
                    low=r.get("l", 0.0),
                    close=r.get("c", 0.0),
                    volume=int(r.get("v", 0)),
                    transactions=int(r.get("n", 0)),
                )
            )
        return bars

    @staticmethod
    def _duckdb_bars_to_model(raw_rows: list[dict[str, Any]], *, is_daily: bool = False) -> list[MinuteBar]:
        bars: list[MinuteBar] = []
        for r in raw_rows:
            if is_daily:
                ts = r.get("date")
                ts_ns = 0
            else:
                ts = r.get("window_start")
                ts_ns = int(r.get("window_start_ns", 0)) if r.get("window_start_ns") else int(r.get("ts_ms", 0)) * 1_000_000

            bars.append(
                MinuteBar(
                    timestamp=_normalize_market_datetime(ts),
                    timestamp_ns=ts_ns,
                    open=float(r.get("open", 0)),
                    high=float(r.get("high", 0)),
                    low=float(r.get("low", 0)),
                    close=float(r.get("close", 0)),
                    volume=int(r.get("volume", 0)),
                    transactions=int(r.get("transactions", 0)),
                )
            )
        return bars


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
