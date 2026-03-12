# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignalType(str, Enum):
    MAIN = "MAIN"
    DD_RECLAIM = "DD_RECLAIM"
    DD_BOUNCE = "DD_BOUNCE"


class PatternType(str, Enum):
    STRONG_UPTRENDING = "strong_uptrending"
    PULLBACK_BREAKOUT = "pullback_breakout"
    PULLBACK_RECLAIM = "pullback_reclaim"
    UNCLASSIFIED = "unclassified"


class TradeOutcome(str, Enum):
    TP_FILLED = "tp_filled"
    MANUAL_EXIT = "manual_exit"
    STRANDED = "stranded"
    STOPPED_OUT = "stopped_out"
    OPEN = "open"


class ReviewVerdict(str, Enum):
    GOOD_TRADE = "good_trade"
    ACCEPTABLE = "acceptable"
    MARGINAL = "marginal"
    SHOULD_SKIP = "should_skip"
    BAD_TRADE = "bad_trade"


class ExitPolicy(str, Enum):
    FIXED_TP = "fixed_tp"
    TRAILING_STOP = "trailing_stop"
    TIME_BASED = "time_based"
    VWAP_RELATIVE = "vwap_relative"
    HYBRID = "hybrid"


class QualityTier(int, Enum):
    EXCELLENT = 1
    GOOD = 2
    MARGINAL = 3
    BAD = 4
    TERRIBLE = 5


class ReconcileType(str, Enum):
    GENERIC = "RECONCILE"
    POS = "RECONCILE_POS"
    ORD_BUY = "RECONCILE_ORD_BUY"
    ORD_SELL = "RECONCILE_ORD_SELL"
    SELL_SYNC = "RECONCILE_SELL_SYNC"
    SNAPSHOT = "RECONCILE_SNAPSHOT"
    ORPHAN = "RECONCILE_ORPHAN"
    GHOST = "RECONCILE_GHOST"
    TP_SKIP = "RECONCILE_TP_SKIP"


# ---------------------------------------------------------------------------
# Log-parsed event models
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    timestamp: datetime
    symbol: str
    signal_type: SignalType
    score: float
    pwin: float
    bars: int
    ret5m_predicted: float
    dd_predicted: float
    tvr: float
    raw_line: str
    line_number: int = 0


@dataclass
class DDWatchEvent:
    """DD_WATCH_RECLAIM observation — optional pre-signal event."""

    timestamp: datetime
    symbol: str
    details: dict[str, Any] = field(default_factory=dict)
    raw_line: str = ""


@dataclass
class EntryEvent:
    timestamp: datetime
    symbol: str
    price: float
    quantity: int = 0
    commission: float = 0.0
    raw_line: str = ""


@dataclass
class SellVerifyEvent:
    """SELL_VERIFY — position sync confirmation after entry."""

    timestamp: datetime
    symbol: str
    latency_s: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    raw_line: str = ""


@dataclass
class TPPriceEvent:
    """TP_PRICE — take-profit limit order details."""

    timestamp: datetime
    symbol: str
    entry_avg: float
    tp_mult: float
    limit_price: float
    quantity: int = 0
    raw_line: str = ""


@dataclass
class ExitEvent:
    timestamp: datetime
    symbol: str
    price: float
    quantity: int = 0
    exit_type: str = ""  # "SELL LMT", "MANUAL", etc.
    raw_line: str = ""


@dataclass
class ExitStatusEvent:
    """EXIT_STATUS — progressive fill updates (Submitted → partial → Filled)."""

    timestamp: datetime
    symbol: str
    status: str = ""  # "Submitted", "PartialFill", "Filled"
    filled_qty: int = 0
    remaining_qty: int = 0
    avg_fill_price: float = 0.0
    raw_line: str = ""


@dataclass
class ReconcileEvent:
    timestamp: datetime
    symbol: str
    event_type: ReconcileType = ReconcileType.GENERIC
    details: dict[str, Any] = field(default_factory=dict)
    raw_line: str = ""


# ---------------------------------------------------------------------------
# Parsed trade (full lifecycle)
# ---------------------------------------------------------------------------


@dataclass
class ParsedTrade:
    trading_date: date
    symbol: str
    signal: Signal | None = None
    dd_watch: DDWatchEvent | None = None
    entry: EntryEvent | None = None
    sell_verify: SellVerifyEvent | None = None
    tp_event: TPPriceEvent | None = None
    exit: ExitEvent | None = None
    exit_status_events: list[ExitStatusEvent] = field(default_factory=list)
    tp_price: float | None = None
    tp_multiplier: float | None = None
    commission: float = 0.0
    reconcile_events: list[ReconcileEvent] = field(default_factory=list)
    outcome: TradeOutcome = TradeOutcome.OPEN
    # Multi-day: a stranded trade may span multiple log files
    continuation_dates: list[date] = field(default_factory=list)

    @property
    def entry_price(self) -> float | None:
        return self.entry.price if self.entry else None

    @property
    def exit_price(self) -> float | None:
        return self.exit.price if self.exit else None

    @property
    def pnl_pct(self) -> float | None:
        if self.entry_price and self.exit_price:
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        return None

    @property
    def hold_duration_minutes(self) -> float | None:
        if self.entry and self.exit:
            return (self.exit.timestamp - self.entry.timestamp).total_seconds() / 60
        return None

    @property
    def is_stranded(self) -> bool:
        return self.outcome == TradeOutcome.STRANDED

    @property
    def is_short(self) -> bool:
        """Negative-share positions (e.g. PENN) — out of scope."""
        return self.entry is not None and self.entry.quantity < 0


# ---------------------------------------------------------------------------
# Market data models
# ---------------------------------------------------------------------------


@dataclass
class MinuteBar:
    timestamp: datetime
    timestamp_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    transactions: int = 0


@dataclass
class TickerDetails:
    symbol: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float | None = None
    shares_outstanding: float | None = None
    float_shares: float | None = None
    description: str = ""


@dataclass
class NewsItem:
    title: str
    published_utc: str = ""
    article_url: str = ""
    sentiment: str = ""  # "positive", "negative", "neutral"
    sentiment_score: float = 0.0
    tickers: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Iterative analysis models
# ---------------------------------------------------------------------------


@dataclass
class DataGap:
    """Represents a missing piece of data identified during iteration."""

    dimension: str  # e.g. "volume_profile", "sector_peers", "news"
    description: str
    priority: float = 0.5  # 0.0 = low, 1.0 = critical
    resolved: bool = False


@dataclass
class AnalyticalLens:
    """Configuration for a single iteration's analytical focus."""

    name: str  # e.g. "volume_profile", "vwap_analysis"
    iteration: int
    description: str
    required_data: list[str] = field(default_factory=list)  # data keys needed
    depends_on: list[str] = field(default_factory=list)  # prior lenses that must complete


@dataclass
class QuantitativeFindings:
    """Output of a review module's compute_metrics() — pure math, no LLM."""

    lens_name: str
    iteration: int
    metrics: dict[str, Any] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    data_gaps: list[DataGap] = field(default_factory=list)
    confidence: float = 0.0  # 0.0–1.0, how confident the findings are


@dataclass
class IterationResult:
    """Result of a single iteration in the convergence loop."""

    iteration: int
    lens: AnalyticalLens
    findings: dict[str, QuantitativeFindings] = field(default_factory=dict)  # module_name -> findings
    new_gaps: list[DataGap] = field(default_factory=list)
    cumulative_confidence: float = 0.0
    converged: bool = False


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


@dataclass
class Hypothesis:
    statement: str
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    verified: bool | None = None
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Review verdicts
# ---------------------------------------------------------------------------


@dataclass
class SelectionVerdict:
    should_trade: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    market_context: dict[str, Any] = field(default_factory=dict)
    sector_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntryVerdict:
    optimal_entry_time: datetime | None = None
    optimal_entry_price: float | None = None
    actual_vs_optimal_slippage_pct: float | None = None
    should_have_waited: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExitVerdict:
    recommended_policy: ExitPolicy = ExitPolicy.FIXED_TP
    optimal_exit_time: datetime | None = None
    optimal_exit_price: float | None = None
    max_favorable_excursion_pct: float | None = None
    max_adverse_excursion_pct: float | None = None
    tp_pct_recommendation: float | None = None
    reasons: list[str] = field(default_factory=list)
    simulations: dict[str, Any] = field(default_factory=dict)  # policy_name -> simulated PnL


@dataclass
class FailureVerdict:
    should_exit_now: bool = False
    recommended_exit_price: float | None = None
    bounce_probability: float | None = None
    max_hold_hours: float | None = None
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Trade review (final output)
# ---------------------------------------------------------------------------


@dataclass
class TradeReview:
    trade: ParsedTrade
    quality_tier: QualityTier = QualityTier.MARGINAL
    overall_verdict: ReviewVerdict = ReviewVerdict.ACCEPTABLE
    selection: SelectionVerdict | None = None
    entry: EntryVerdict | None = None
    exit: ExitVerdict | None = None
    failure: FailureVerdict | None = None
    pattern: PatternType = PatternType.UNCLASSIFIED
    hypotheses: list[Hypothesis] = field(default_factory=list)
    iteration_results: list[IterationResult] = field(default_factory=list)
    total_iterations: int = 0


@dataclass
class DayReview:
    trading_date: date
    trades: list[TradeReview] = field(default_factory=list)
    summary_stats: dict[str, Any] = field(default_factory=dict)
    lessons: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
