"""Tests for src.community.finance.trade_log_parser — regex patterns and parsing logic."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.community.finance.models import ReconcileType, SignalType, TradeOutcome
from src.community.finance.trade_log_parser import (
    RE_DD_WATCH,
    RE_ENTRY,
    RE_EXIT_STATUS,
    RE_EXIT_SUBMIT,
    RE_RECONCILE_GENERIC,
    RE_RECONCILE_GHOST,
    RE_RECONCILE_ORPHAN,
    RE_RECONCILE_POS,
    RE_RECONCILE_SELL_SYNC,
    RE_RECONCILE_SNAPSHOT,
    RE_RECONCILE_TP_SKIP,
    RE_SELL_VERIFY,
    RE_SIGNAL,
    RE_TP_PRICE,
    _safe_float,
    _safe_int,
    get_available_log_dates,
    parse_log_file,
    parse_log_range,
)

# ---------------------------------------------------------------------------
# Regex pattern tests (against known real log lines)
# ---------------------------------------------------------------------------


class TestSignalRegex:
    def test_main_signal(self):
        line = "2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: AMPX | score=10.889 | pwin=100.0% | bars=190 | ret5m=5.4% | dd=0.5% | tvr=13.0M"
        m = RE_SIGNAL.search(line)
        assert m is not None
        assert m.group("ts") == "2026-03-05 09:31:26"
        assert m.group("stype") == "MAIN"
        assert m.group("sym") == "AMPX"
        assert m.group("score") == "10.889"
        assert m.group("pwin") == "100.0"
        assert m.group("bars") == "190"
        assert m.group("ret5m") == "5.4"
        assert m.group("dd") == "0.5"
        assert m.group("tvr") == "13.0"

    def test_dd_reclaim_signal(self):
        line = "2026-03-05 10:15:00 | INFO     |   SIGNAL[DD_RECLAIM]: PDYN | score=7.5 | pwin=75.0% | bars=50 | ret5m=2.1% | dd=1.2% | tvr=8.0M"
        m = RE_SIGNAL.search(line)
        assert m is not None
        assert m.group("stype") == "DD_RECLAIM"
        assert m.group("sym") == "PDYN"

    def test_dd_bounce_signal(self):
        line = "2026-03-05 11:00:00 | INFO     |   SIGNAL[DD_BOUNCE]: XYZ | score=6.0 | pwin=60.0% | bars=300 | ret5m=1.5% | dd=2.0% | tvr=5.5M"
        m = RE_SIGNAL.search(line)
        assert m is not None
        assert m.group("stype") == "DD_BOUNCE"


class TestDDWatchRegex:
    def test_dd_watch_reclaim(self):
        line = "2026-03-05 06:44:00 | INFO     |   DD_WATCH_RECLAIM: PDYN | close=10.5300 | dd=0.9% | tvr=8.4M | bar=06:44 | anchor_hod=10.4200 | anchor_dd=8.1%"
        m = RE_DD_WATCH.search(line)
        assert m is not None
        assert m.group("sym") == "PDYN"
        assert m.group("close") == "10.5300"
        assert m.group("dd") == "0.9"
        assert m.group("bar") == "06:44"


class TestEntryRegex:
    def test_entry_submit(self):
        line = "2026-03-05 09:31:28 | INFO     |   ENTRY_SUBMIT | order_id=198 symbol=AMPX action=BUY type=MKT status=Filled filled=144.0 avg=13.8978 commission=1.0000"
        m = RE_ENTRY.search(line)
        assert m is not None
        assert m.group("sym") == "AMPX"
        assert m.group("filled") == "144.0"
        assert m.group("avg") == "13.8978"
        assert m.group("comm") == "1.0000"


class TestSellVerifyRegex:
    def test_sell_verify(self):
        line = "2026-03-05 09:31:30 | INFO     |   SELL_VERIFY | AMPX — position synced after 1.00s, proceeding with sell qty=144"
        m = RE_SELL_VERIFY.search(line)
        assert m is not None
        assert m.group("sym") == "AMPX"
        assert m.group("latency") == "1.00"
        assert m.group("qty") == "144"


class TestTPPriceRegex:
    def test_tp_price(self):
        line = "2026-03-05 09:31:30 | INFO     |   TP_PRICE | AMPX entry_avg=13.8978 tp_mult=1.0500 limit_price=14.59 qty=144"
        m = RE_TP_PRICE.search(line)
        assert m is not None
        assert m.group("sym") == "AMPX"
        assert m.group("entry_avg") == "13.8978"
        assert m.group("tp_mult") == "1.0500"
        assert m.group("limit") == "14.59"
        assert m.group("qty") == "144"


class TestExitRegex:
    def test_exit_submit(self):
        line = "2026-03-05 09:31:32 | INFO     |   EXIT_SUBMIT | order_id=200 symbol=AMPX action=SELL type=LMT status=Submitted filled=0.0 avg=0.0000 commission=None"
        m = RE_EXIT_SUBMIT.search(line)
        assert m is not None
        assert m.group("sym") == "AMPX"
        assert m.group("otype") == "LMT"
        assert m.group("status") == "Submitted"

    def test_exit_status_filled(self):
        line = "2026-03-05 09:45:00 | INFO     |   EXIT_STATUS | order_id=200 symbol=AMPX status=Filled filled=144.0 avg=14.5900 commission=0.0000"
        m = RE_EXIT_STATUS.search(line)
        assert m is not None
        assert m.group("sym") == "AMPX"
        assert m.group("status") == "Filled"
        assert m.group("filled") == "144.0"
        assert m.group("avg") == "14.5900"


class TestReconcileRegex:
    def test_orphan(self):
        line = "2026-03-06 09:30:05 | WARNING  |   RECONCILE_ORPHAN | MOBX has 1798 shares in IBKR but not tracked — importing"
        m = RE_RECONCILE_ORPHAN.search(line)
        assert m is not None
        assert m.group("sym") == "MOBX"
        assert m.group("shares") == "1798"

    def test_ghost(self):
        line = "2026-03-06 10:00:00 | WARNING  |   RECONCILE_GHOST | MOBX tracked locally but 0 in IBKR"
        m = RE_RECONCILE_GHOST.search(line)
        assert m is not None
        assert m.group("sym") == "MOBX"

    def test_tp_skip(self):
        line = "2026-03-06 09:30:10 | WARNING  |   RECONCILE_TP_SKIP | MOBX no open SELL and no valid entry price"
        m = RE_RECONCILE_TP_SKIP.search(line)
        assert m is not None
        assert m.group("sym") == "MOBX"

    def test_sell_sync(self):
        line = "2026-03-05 11:00:00 | INFO     |   RECONCILE_SELL_SYNC | MOBX linked to open SELL orders 204 (status=Submitted)"
        m = RE_RECONCILE_SELL_SYNC.search(line)
        assert m is not None
        assert m.group("sym") == "MOBX"
        assert m.group("oid") == "204"

    def test_reconcile_pos(self):
        line = "2026-03-05 11:00:00 | INFO     |   RECONCILE_POS | symbol=MOBX shares=1798.0 avgCost=None"
        m = RE_RECONCILE_POS.search(line)
        assert m is not None
        assert m.group("sym") == "MOBX"
        assert m.group("shares") == "1798.0"
        assert m.group("avgcost") == "None"

    def test_reconcile_snapshot(self):
        line = "2026-03-05 11:00:00 | INFO     |   RECONCILE_SNAPSHOT[periodic] | positions=1 open_buy=0 open_sell=0"
        m = RE_RECONCILE_SNAPSHOT.search(line)
        assert m is not None

    def test_reconcile_generic(self):
        line = "2026-03-05 11:00:00 | WARNING  |   RECONCILE | PENN has some warning message"
        m = RE_RECONCILE_GENERIC.search(line)
        assert m is not None
        assert m.group("sym") == "PENN"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_safe_float_normal(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_safe_float_none_string(self):
        assert _safe_float("None") == 0.0

    def test_safe_float_none_value(self):
        assert _safe_float(None) == 0.0

    def test_safe_float_custom_default(self):
        assert _safe_float("None", default=-1.0) == -1.0

    def test_safe_int_normal(self):
        assert _safe_int("144.0") == 144

    def test_safe_int_none(self):
        assert _safe_int("None") == 0

    def test_safe_int_empty(self):
        assert _safe_int("") == 0


# ---------------------------------------------------------------------------
# Full log parsing tests with temp files
# ---------------------------------------------------------------------------

# A realistic log snippet covering the full trade lifecycle
_SAMPLE_LOG = """\
2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: AMPX | score=10.889 | pwin=100.0% | bars=190 | ret5m=5.4% | dd=0.5% | tvr=13.0M
2026-03-05 09:31:28 | INFO     |   ENTRY_SUBMIT | order_id=198 symbol=AMPX action=BUY type=MKT status=Filled filled=144.0 avg=13.8978 commission=1.0000
2026-03-05 09:31:30 | INFO     |   SELL_VERIFY | AMPX — position synced after 1.00s, proceeding with sell qty=144
2026-03-05 09:31:30 | INFO     |   TP_PRICE | AMPX entry_avg=13.8978 tp_mult=1.0500 limit_price=14.59 qty=144
2026-03-05 09:31:32 | INFO     |   EXIT_SUBMIT | order_id=200 symbol=AMPX action=SELL type=LMT status=Submitted filled=0.0 avg=0.0000 commission=None
2026-03-05 09:45:00 | INFO     |   EXIT_STATUS | order_id=200 symbol=AMPX status=Filled filled=144.0 avg=14.5900 commission=0.0000
"""


class TestParseLogFile:
    def test_complete_trade_lifecycle(self, tmp_path):
        log_file = tmp_path / "live.log.2026-03-05"
        log_file.write_text(_SAMPLE_LOG)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 5))

        assert len(trades) == 1
        trade = trades[0]
        assert trade.symbol == "AMPX"
        assert trade.signal is not None
        assert trade.signal.signal_type == SignalType.MAIN
        assert trade.signal.score == pytest.approx(10.889)
        assert trade.signal.pwin == pytest.approx(100.0)
        assert trade.entry is not None
        assert trade.entry.price == pytest.approx(13.8978)
        assert trade.entry.quantity == 144
        assert trade.sell_verify is not None
        assert trade.sell_verify.latency_s == pytest.approx(1.0)
        assert trade.tp_event is not None
        assert trade.tp_event.tp_mult == pytest.approx(1.05)
        assert trade.tp_price == pytest.approx(14.59)
        assert trade.exit is not None
        assert trade.exit.price == pytest.approx(14.59)
        assert trade.outcome == TradeOutcome.TP_FILLED

    def test_stranded_trade(self, tmp_path):
        log = """\
2026-03-05 09:35:00 | INFO     |   SIGNAL[MAIN]: MOBX | score=7.0 | pwin=80.0% | bars=100 | ret5m=2.0% | dd=1.5% | tvr=10.0M
2026-03-05 09:35:02 | INFO     |   ENTRY_SUBMIT | order_id=201 symbol=MOBX action=BUY type=MKT status=Filled filled=1798.0 avg=1.1150 commission=1.0000
2026-03-05 09:35:04 | INFO     |   TP_PRICE | MOBX entry_avg=1.1150 tp_mult=1.0500 limit_price=1.17 qty=1798
2026-03-05 09:35:06 | INFO     |   EXIT_SUBMIT | order_id=202 symbol=MOBX action=SELL type=LMT status=Submitted filled=0.0 avg=0.0000 commission=None
2026-03-05 11:00:00 | INFO     |   EXIT_STATUS | order_id=202 symbol=MOBX status=Submitted filled=0.0 avg=0.0000 commission=None
"""
        log_file = tmp_path / "live.log.2026-03-05"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 5))

        assert len(trades) == 1
        trade = trades[0]
        assert trade.symbol == "MOBX"
        assert trade.outcome == TradeOutcome.STRANDED
        assert trade.exit is None

    def test_missing_log_file(self, tmp_path):
        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 1, 1))
        assert trades == []

    def test_dd_watch_attached_to_signal(self, tmp_path):
        log = """\
2026-03-05 06:44:00 | INFO     |   DD_WATCH_RECLAIM: PDYN | close=10.5300 | dd=0.9% | tvr=8.4M | bar=06:44 | anchor_hod=10.4200 | anchor_dd=8.1%
2026-03-05 10:15:00 | INFO     |   SIGNAL[DD_RECLAIM]: PDYN | score=7.5 | pwin=75.0% | bars=50 | ret5m=2.1% | dd=1.2% | tvr=8.0M
2026-03-05 10:15:02 | INFO     |   ENTRY_SUBMIT | order_id=205 symbol=PDYN action=BUY type=MKT status=Filled filled=100.0 avg=10.50 commission=1.0000
"""
        log_file = tmp_path / "live.log.2026-03-05"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 5))

        assert len(trades) == 1
        trade = trades[0]
        assert trade.dd_watch is not None
        assert trade.dd_watch.symbol == "PDYN"
        assert trade.dd_watch.details["close"] == pytest.approx(10.53)

    def test_reconcile_orphan_trade_kept(self, tmp_path):
        log = """\
2026-03-06 09:30:05 | WARNING  |   RECONCILE_ORPHAN | MOBX has 1798 shares in IBKR but not tracked — importing
2026-03-06 09:30:10 | INFO     |   RECONCILE_POS | symbol=MOBX shares=1798.0 avgCost=None
"""
        log_file = tmp_path / "live.log.2026-03-06"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 6))

        # Orphan trades should be kept (they're continuations)
        assert len(trades) == 1
        trade = trades[0]
        assert trade.symbol == "MOBX"
        assert any(r.event_type == ReconcileType.ORPHAN for r in trade.reconcile_events)

    def test_ghost_marks_manual_exit(self, tmp_path):
        log = """\
2026-03-06 09:30:05 | WARNING  |   RECONCILE_ORPHAN | MOBX has 1798 shares in IBKR but not tracked — importing
2026-03-06 10:00:00 | WARNING  |   RECONCILE_GHOST | MOBX tracked locally but 0 in IBKR
"""
        log_file = tmp_path / "live.log.2026-03-06"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 6))

        assert len(trades) == 1
        assert trades[0].outcome == TradeOutcome.MANUAL_EXIT

    def test_negative_position_skipped(self, tmp_path):
        log = """\
2026-03-05 11:00:00 | INFO     |   RECONCILE_POS | symbol=PENN shares=-50.0 avgCost=None
"""
        log_file = tmp_path / "live.log.2026-03-05"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 5))

        # Negative positions should be skipped (no signal, no entry, no orphan)
        assert trades == []

    def test_negative_position_warning_skipped(self, tmp_path):
        log = """\
2026-03-05 11:00:00 | WARNING  |   RECONCILE | PENN has negative position -50 shares
"""
        log_file = tmp_path / "live.log.2026-03-05"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 5))

        assert trades == []

    def test_multiple_trades_in_one_day(self, tmp_path):
        log = """\
2026-03-05 09:31:26 | INFO     |   SIGNAL[MAIN]: AMPX | score=10.889 | pwin=100.0% | bars=190 | ret5m=5.4% | dd=0.5% | tvr=13.0M
2026-03-05 09:31:28 | INFO     |   ENTRY_SUBMIT | order_id=198 symbol=AMPX action=BUY type=MKT status=Filled filled=144.0 avg=13.8978 commission=1.0000
2026-03-05 09:45:00 | INFO     |   EXIT_STATUS | order_id=200 symbol=AMPX status=Filled filled=144.0 avg=14.5900 commission=0.0000
2026-03-05 10:00:00 | INFO     |   SIGNAL[MAIN]: MOBX | score=7.0 | pwin=80.0% | bars=100 | ret5m=2.0% | dd=1.5% | tvr=10.0M
2026-03-05 10:00:02 | INFO     |   ENTRY_SUBMIT | order_id=201 symbol=MOBX action=BUY type=MKT status=Filled filled=1798.0 avg=1.1150 commission=1.0000
"""
        log_file = tmp_path / "live.log.2026-03-05"
        log_file.write_text(log)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_file(date(2026, 3, 5))

        assert len(trades) == 2
        symbols = {t.symbol for t in trades}
        assert symbols == {"AMPX", "MOBX"}


# ---------------------------------------------------------------------------
# Multi-day parse tests
# ---------------------------------------------------------------------------


class TestParseLogRange:
    def test_stranded_trade_linked_across_days(self, tmp_path):
        day1 = """\
2026-03-05 09:35:00 | INFO     |   SIGNAL[MAIN]: MOBX | score=7.0 | pwin=80.0% | bars=100 | ret5m=2.0% | dd=1.5% | tvr=10.0M
2026-03-05 09:35:02 | INFO     |   ENTRY_SUBMIT | order_id=201 symbol=MOBX action=BUY type=MKT status=Filled filled=1798.0 avg=1.1150 commission=1.0000
"""
        day2 = """\
2026-03-06 09:30:05 | WARNING  |   RECONCILE_ORPHAN | MOBX has 1798 shares in IBKR but not tracked — importing
2026-03-06 10:00:00 | WARNING  |   RECONCILE_GHOST | MOBX tracked locally but 0 in IBKR
"""
        (tmp_path / "live.log.2026-03-05").write_text(day1)
        (tmp_path / "live.log.2026-03-06").write_text(day2)

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            trades = parse_log_range(date(2026, 3, 5), date(2026, 3, 6))

        # Should have 1 consolidated trade for MOBX
        mobx_trades = [t for t in trades if t.symbol == "MOBX"]
        assert len(mobx_trades) == 1
        trade = mobx_trades[0]
        assert trade.outcome == TradeOutcome.MANUAL_EXIT
        assert date(2026, 3, 6) in trade.continuation_dates


# ---------------------------------------------------------------------------
# Available log dates
# ---------------------------------------------------------------------------


class TestGetAvailableLogDates:
    def test_finds_log_files(self, tmp_path):
        (tmp_path / "live.log.2026-03-05").touch()
        (tmp_path / "live.log.2026-03-06").touch()
        (tmp_path / "other-file.txt").touch()

        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            dates = get_available_log_dates()

        assert dates == [date(2026, 3, 5), date(2026, 3, 6)]

    def test_empty_dir(self, tmp_path):
        with patch("src.community.finance.trade_log_parser.LOG_DIR", tmp_path):
            dates = get_available_log_dates()
        assert dates == []

    def test_nonexistent_dir(self, tmp_path):
        fake_dir = tmp_path / "nonexistent"
        with patch("src.community.finance.trade_log_parser.LOG_DIR", fake_dir):
            dates = get_available_log_dates()
        assert dates == []
