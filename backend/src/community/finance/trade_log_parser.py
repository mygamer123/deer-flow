# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Parse production strategy logs into structured trade objects.

Log location: ~/Documents/prod/fms/logs/live.log.YYYY-MM-DD
Format: YYYY-MM-DD HH:MM:SS | LEVEL | EVENT | details
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .log_sources import DEFAULT_LOG_DIR, get_log_source_path, has_configured_log_sources
from .models import (
    DDWatchEvent,
    EntryEvent,
    ExitEvent,
    ExitStatusEvent,
    ParsedTrade,
    ReconcileEvent,
    ReconcileType,
    SellVerifyEvent,
    Signal,
    SignalType,
    TPPriceEvent,
    TradeOutcome,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_DIR = DEFAULT_LOG_DIR
LOG_PREFIX = "live.log."
TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------

# 2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: AMPX | score=10.889 | pwin=100.0% | bars=190 | ret5m=5.4% | dd=0.5% | tvr=13.0M
RE_SIGNAL = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*SIGNAL\[(?P<stype>\w+)\]:\s*(?P<sym>\w+)\s*\|"
    r"\s*score=(?P<score>[\d.]+)\s*\|\s*pwin=(?P<pwin>[\d.]+)%\s*\|\s*bars=(?P<bars>\d+)\s*\|"
    r"\s*ret5m=(?P<ret5m>[\d.]+|None)%?\s*\|\s*dd=(?P<dd>[\d.]+)%\s*\|\s*tvr=(?P<tvr>[\d.]+)M"
)

# DD_WATCH_RECLAIM: PDYN | close=10.5300 | dd=0.9% | tvr=8.4M | bar=06:44 | anchor_hod=10.4200 | anchor_dd=8.1%
RE_DD_WATCH = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*DD_WATCH_RECLAIM:\s*(?P<sym>\w+)\s*\|"
    r"\s*close=(?P<close>[\d.]+)\s*\|\s*dd=(?P<dd>[\d.]+)%\s*\|\s*tvr=(?P<tvr>[\d.]+)M\s*\|"
    r"\s*bar=(?P<bar>[\d:]+)\s*\|\s*anchor_hod=(?P<anchor_hod>[\d.]+)\s*\|\s*anchor_dd=(?P<anchor_dd>[\d.]+)%"
)

# ENTRY_SUBMIT | order_id=198 symbol=AMPX action=BUY type=MKT status=Filled filled=144.0 avg=13.8978 commission=1.0000
RE_ENTRY = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*ENTRY_SUBMIT\s*\|"
    r"\s*order_id=(?P<oid>\d+)\s+symbol=(?P<sym>\w+)\s+action=BUY\s+type=\w+\s+status=\w+"
    r"\s+filled=(?P<filled>[\d.]+)\s+avg=(?P<avg>[\d.]+)\s+commission=(?P<comm>[\d.]+|None)"
)

# SELL_VERIFY | AMPX — position synced after 1.00s, proceeding with sell qty=144
RE_SELL_VERIFY = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*SELL_VERIFY\s*\|\s*(?P<sym>\w+)\s*—\s*position synced after (?P<latency>[\d.]+)s.*qty=(?P<qty>\d+)")

# TP_PRICE | AMPX entry_avg=13.8978 tp_mult=1.0500 limit_price=14.59 qty=144
RE_TP_PRICE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*TP_PRICE\s*\|\s*(?P<sym>\w+)"
    r"\s+entry_avg=(?P<entry_avg>[\d.]+)\s+tp_mult=(?P<tp_mult>[\d.]+)\s+limit_price=(?P<limit>[\d.]+)\s+qty=(?P<qty>\d+)"
)

# EXIT_SUBMIT | order_id=200 symbol=AMPX action=SELL type=LMT status=Submitted filled=0.0 avg=0.0000 commission=None
RE_EXIT_SUBMIT = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*EXIT_SUBMIT\s*\|"
    r"\s*order_id=(?P<oid>\d+)\s+symbol=(?P<sym>\w+)\s+action=SELL\s+type=(?P<otype>\w+)\s+status=(?P<status>\w+)"
    r"\s+filled=(?P<filled>[\d.]+)\s+avg=(?P<avg>[\d.]+)\s+commission=(?P<comm>[\d.]+|None)"
)

# EXIT_STATUS | order_id=200 symbol=AMPX status=Filled filled=144.0 avg=14.5900 commission=0.0000
RE_EXIT_STATUS = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*EXIT_STATUS\s*\|"
    r"\s*order_id=(?P<oid>\d+)\s+symbol=(?P<sym>\w+)\s+status=(?P<status>\w+)"
    r"\s+filled=(?P<filled>[\d.]+)\s+avg=(?P<avg>[\d.]+)\s+commission=(?P<comm>[\d.]+|None)"
)

# RECONCILE_ORPHAN | MOBX has 1798 shares in IBKR but not tracked — importing
RE_RECONCILE_ORPHAN = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_ORPHAN\s*\|\s*(?P<sym>\w+)\s+has\s+(?P<shares>[\d.]+)\s+shares")

# RECONCILE_GHOST | ... (tracked locally but IBKR has 0 shares)
RE_RECONCILE_GHOST = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_GHOST\s*\|\s*(?P<sym>\w+)")

# RECONCILE_TP_SKIP | ... no open SELL and no valid entry price
RE_RECONCILE_TP_SKIP = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_TP_SKIP\s*\|\s*(?P<sym>\w+)")

# RECONCILE_SELL_SYNC | MOBX linked to open SELL orders 204 (status=Submitted)
RE_RECONCILE_SELL_SYNC = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_SELL_SYNC\s*\|\s*(?P<sym>\w+)\s+linked to open SELL orders\s+(?P<oid>\d+)")

# RECONCILE_POS | symbol=MOBX shares=1798.0 avgCost=None
RE_RECONCILE_POS = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_POS\s*\|\s*symbol=(?P<sym>\w+)\s+shares=(?P<shares>[-\d.]+)\s+avgCost=(?P<avgcost>\S+)")

# RECONCILE_SNAPSHOT[...] | positions=N open_buy=N open_sell=N
RE_RECONCILE_SNAPSHOT = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_SNAPSHOT")

# Generic RECONCILE | ... (warning)
RE_RECONCILE_GENERIC = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*(?:WARNING|INFO)\s*\|\s*RECONCILE\s*\|\s*(?P<sym>\w+)\s+(?P<msg>.+)")

# RECONCILE_ORD_BUY / RECONCILE_ORD_SELL
RE_RECONCILE_ORD = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*\w+\s*\|\s*RECONCILE_ORD_(?P<side>BUY|SELL)\s*\|\s*(?P<rest>.+)")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _parse_ts(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, TIMESTAMP_FMT)


def _safe_float(val: str, default: float = 0.0) -> float:
    if val is None or val == "None":
        return default
    return float(val)


def _safe_int(val: str, default: int = 0) -> int:
    return int(float(val)) if val and val != "None" else default


def _get_log_dir(log_source: str | None = None) -> Path:
    if log_source is None and LOG_DIR != DEFAULT_LOG_DIR:
        return LOG_DIR
    if log_source is None and not has_configured_log_sources():
        return LOG_DIR
    return get_log_source_path(log_source)


def _log_path(trading_date: date, log_source: str | None = None) -> Path:
    return _get_log_dir(log_source) / f"{LOG_PREFIX}{trading_date.isoformat()}"


# ---------------------------------------------------------------------------
# Single-day parser
# ---------------------------------------------------------------------------


def parse_log_file(trading_date: date, *, log_source: str | None = None) -> list[ParsedTrade]:
    """Parse a single day's log file into a list of ParsedTrade objects.

    Returns an empty list if the file doesn't exist (weekends, holidays).
    """
    path = _log_path(trading_date, log_source)
    if not path.exists():
        logger.info("No log file for %s at %s", trading_date, path)
        return []

    # Accumulate events by symbol
    trades_by_symbol: dict[str, ParsedTrade] = {}
    dd_watches: dict[str, DDWatchEvent] = {}  # latest per symbol

    def _get_trade(sym: str) -> ParsedTrade:
        if sym not in trades_by_symbol:
            trades_by_symbol[sym] = ParsedTrade(trading_date=trading_date, symbol=sym)
        return trades_by_symbol[sym]

    with open(path, encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.rstrip("\n")

            # --- DD_WATCH_RECLAIM ---
            m = RE_DD_WATCH.search(line)
            if m:
                dd_watches[m.group("sym")] = DDWatchEvent(
                    timestamp=_parse_ts(m.group("ts")),
                    symbol=m.group("sym"),
                    details={
                        "close": _safe_float(m.group("close")),
                        "dd_pct": _safe_float(m.group("dd")),
                        "tvr_m": _safe_float(m.group("tvr")),
                        "bar": m.group("bar"),
                        "anchor_hod": _safe_float(m.group("anchor_hod")),
                        "anchor_dd_pct": _safe_float(m.group("anchor_dd")),
                    },
                    raw_line=line,
                )
                continue

            # --- SIGNAL ---
            m = RE_SIGNAL.search(line)
            if m:
                sym = m.group("sym")
                stype_str = m.group("stype")
                try:
                    stype = SignalType(stype_str)
                except ValueError:
                    logger.warning("Unknown signal type '%s' on line %d, skipping", stype_str, line_no)
                    continue

                trade = _get_trade(sym)
                signal = Signal(
                    timestamp=_parse_ts(m.group("ts")),
                    symbol=sym,
                    signal_type=stype,
                    score=_safe_float(m.group("score")),
                    pwin=_safe_float(m.group("pwin")),
                    bars=_safe_int(m.group("bars")),
                    ret5m_predicted=_safe_float(m.group("ret5m")),
                    dd_predicted=_safe_float(m.group("dd")),
                    tvr=_safe_float(m.group("tvr")),
                    raw_line=line,
                    line_number=line_no,
                )
                # If trade already has a signal, this symbol appeared again (e.g. DD_BOUNCE after MAIN).
                # Keep the signal that led to the actual entry (the one closest before entry).
                # For now, keep the latest signal — the entry parser will associate correctly.
                trade.signal = signal

                # Attach DD_WATCH if it preceded this signal
                if sym in dd_watches:
                    trade.dd_watch = dd_watches[sym]
                continue

            # --- ENTRY_SUBMIT ---
            m = RE_ENTRY.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                comm = _safe_float(m.group("comm"))
                trade.entry = EntryEvent(
                    timestamp=_parse_ts(m.group("ts")),
                    symbol=sym,
                    price=_safe_float(m.group("avg")),
                    quantity=_safe_int(m.group("filled")),
                    commission=comm,
                    raw_line=line,
                )
                trade.commission += comm
                continue

            # --- SELL_VERIFY ---
            m = RE_SELL_VERIFY.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                trade.sell_verify = SellVerifyEvent(
                    timestamp=_parse_ts(m.group("ts")),
                    symbol=sym,
                    latency_s=_safe_float(m.group("latency")),
                    details={"qty": _safe_int(m.group("qty"))},
                    raw_line=line,
                )
                continue

            # --- TP_PRICE ---
            m = RE_TP_PRICE.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                tp_mult = _safe_float(m.group("tp_mult"))
                limit = _safe_float(m.group("limit"))
                trade.tp_event = TPPriceEvent(
                    timestamp=_parse_ts(m.group("ts")),
                    symbol=sym,
                    entry_avg=_safe_float(m.group("entry_avg")),
                    tp_mult=tp_mult,
                    limit_price=limit,
                    quantity=_safe_int(m.group("qty")),
                    raw_line=line,
                )
                trade.tp_price = limit
                trade.tp_multiplier = tp_mult
                continue

            # --- EXIT_SUBMIT ---
            m = RE_EXIT_SUBMIT.search(line)
            if m:
                # EXIT_SUBMIT is the initial sell order — not a fill. Only store if not already filled.
                continue

            # --- EXIT_STATUS (progressive fills) ---
            m = RE_EXIT_STATUS.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                status = m.group("status")
                filled = _safe_float(m.group("filled"))
                avg = _safe_float(m.group("avg"))
                comm = _safe_float(m.group("comm"))

                evt = ExitStatusEvent(
                    timestamp=_parse_ts(m.group("ts")),
                    symbol=sym,
                    status=status,
                    filled_qty=_safe_int(m.group("filled")),
                    remaining_qty=0,
                    avg_fill_price=avg,
                    raw_line=line,
                )
                trade.exit_status_events.append(evt)

                # If this is the final Filled event, create the ExitEvent
                if status == "Filled" and filled > 0 and avg > 0:
                    trade.exit = ExitEvent(
                        timestamp=evt.timestamp,
                        symbol=sym,
                        price=avg,
                        quantity=_safe_int(m.group("filled")),
                        exit_type="TP_FILL",
                        raw_line=line,
                    )
                    trade.commission += comm
                    trade.outcome = TradeOutcome.TP_FILLED
                continue

            # --- RECONCILE events ---
            m = RE_RECONCILE_ORPHAN.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                trade.reconcile_events.append(ReconcileEvent(timestamp=_parse_ts(m.group("ts")), symbol=sym, event_type=ReconcileType.ORPHAN, details={"shares": _safe_float(m.group("shares"))}, raw_line=line))
                continue

            m = RE_RECONCILE_GHOST.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                trade.reconcile_events.append(ReconcileEvent(timestamp=_parse_ts(m.group("ts")), symbol=sym, event_type=ReconcileType.GHOST, raw_line=line))
                # GHOST means manually sold — mark as manual exit if no exit yet
                if trade.outcome == TradeOutcome.OPEN:
                    trade.outcome = TradeOutcome.MANUAL_EXIT
                continue

            m = RE_RECONCILE_TP_SKIP.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                trade.reconcile_events.append(ReconcileEvent(timestamp=_parse_ts(m.group("ts")), symbol=sym, event_type=ReconcileType.TP_SKIP, raw_line=line))
                if trade.outcome == TradeOutcome.OPEN:
                    trade.outcome = TradeOutcome.STRANDED
                continue

            m = RE_RECONCILE_SELL_SYNC.search(line)
            if m:
                sym = m.group("sym")
                trade = _get_trade(sym)
                trade.reconcile_events.append(ReconcileEvent(timestamp=_parse_ts(m.group("ts")), symbol=sym, event_type=ReconcileType.SELL_SYNC, details={"order_id": _safe_int(m.group("oid"))}, raw_line=line))
                continue

            m = RE_RECONCILE_POS.search(line)
            if m:
                sym = m.group("sym")
                shares = _safe_float(m.group("shares"))
                # Skip negative positions (short — out of scope)
                if shares < 0:
                    continue
                trade = _get_trade(sym)
                trade.reconcile_events.append(ReconcileEvent(timestamp=_parse_ts(m.group("ts")), symbol=sym, event_type=ReconcileType.POS, details={"shares": shares, "avgCost": m.group("avgcost")}, raw_line=line))
                continue

            m = RE_RECONCILE_GENERIC.search(line)
            if m:
                sym = m.group("sym")
                msg = m.group("msg")
                # Skip negative position warnings
                if "negative position" in msg:
                    continue
                trade = _get_trade(sym)
                trade.reconcile_events.append(ReconcileEvent(timestamp=_parse_ts(m.group("ts")), symbol=sym, event_type=ReconcileType.GENERIC, details={"message": msg}, raw_line=line))
                continue

    # Post-process: determine final outcomes for trades still marked OPEN
    result = []
    for trade in trades_by_symbol.values():
        # Skip trades with no signal AND no entry (pure reconcile noise)
        if trade.signal is None and trade.entry is None:
            # But keep if it has ORPHAN events (continuation from prior day)
            has_orphan = any(r.event_type == ReconcileType.ORPHAN for r in trade.reconcile_events)
            if not has_orphan:
                continue

        # If still OPEN and has entry but no exit → stranded (end of day)
        if trade.outcome == TradeOutcome.OPEN and trade.entry is not None and trade.exit is None:
            trade.outcome = TradeOutcome.STRANDED

        result.append(trade)

    return result


# ---------------------------------------------------------------------------
# Multi-day parser (for stranded position tracking)
# ---------------------------------------------------------------------------


def parse_log_range(
    start_date: date,
    end_date: date,
    *,
    log_source: str | None = None,
) -> list[ParsedTrade]:
    """Parse multiple days of logs and link stranded trades across days.

    Returns consolidated trades — stranded trades from day N are enriched
    with reconcile events from day N+1, N+2, etc.
    """
    all_trades: dict[str, ParsedTrade] = {}  # symbol -> primary trade
    current = start_date

    while current <= end_date:
        day_trades = parse_log_file(current, log_source=log_source)
        for trade in day_trades:
            sym = trade.symbol
            if sym in all_trades:
                existing = all_trades[sym]
                # If existing is stranded and this day has reconcile events for it
                if existing.outcome in (TradeOutcome.STRANDED, TradeOutcome.OPEN):
                    existing.continuation_dates.append(current)
                    existing.reconcile_events.extend(trade.reconcile_events)
                    # If the continuation resolved it (GHOST = manual exit)
                    if trade.outcome == TradeOutcome.MANUAL_EXIT:
                        existing.outcome = TradeOutcome.MANUAL_EXIT
                    elif trade.outcome == TradeOutcome.TP_FILLED and trade.exit:
                        existing.exit = trade.exit
                        existing.outcome = TradeOutcome.TP_FILLED
                else:
                    # New trade for same symbol on a different day
                    key = f"{sym}_{current.isoformat()}"
                    all_trades[key] = trade
            else:
                all_trades[sym] = trade

        current += timedelta(days=1)

    return list(all_trades.values())


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def parse_today(*, log_source: str | None = None) -> list[ParsedTrade]:
    """Parse today's log file."""
    return parse_log_file(date.today(), log_source=log_source)


def parse_yesterday(*, log_source: str | None = None) -> list[ParsedTrade]:
    """Parse yesterday's log file."""
    return parse_log_file(date.today() - timedelta(days=1), log_source=log_source)


def get_available_log_dates(*, log_source: str | None = None) -> list[date]:
    """Return sorted list of dates that have log files."""
    dates = []
    log_dir = _get_log_dir(log_source)
    if not log_dir.exists():
        return dates
    for p in log_dir.iterdir():
        if p.name.startswith(LOG_PREFIX) and p.is_file():
            date_str = p.name[len(LOG_PREFIX) :]
            try:
                dates.append(date.fromisoformat(date_str))
            except ValueError:
                continue
    return sorted(dates)
