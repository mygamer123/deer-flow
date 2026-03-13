from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean

from .log_sources import get_log_source_path
from .models import Signal, SignalType
from .trade_log_parser import parse_log_file


@dataclass(frozen=True)
class SignalSnapshot:
    source_name: str
    symbol: str
    signal_type: SignalType
    timestamp: datetime
    score: float
    pwin: float
    bars: int
    ret5m_predicted: float
    dd_predicted: float
    tvr: float


@dataclass(frozen=True)
class SignalDelta:
    symbol: str
    baseline: SignalSnapshot
    candidate: SignalSnapshot

    @property
    def score_delta(self) -> float:
        return self.candidate.score - self.baseline.score

    @property
    def pwin_delta(self) -> float:
        return self.candidate.pwin - self.baseline.pwin

    @property
    def bars_delta(self) -> int:
        return self.candidate.bars - self.baseline.bars

    @property
    def timestamp_delta_minutes(self) -> float:
        return (self.candidate.timestamp - self.baseline.timestamp).total_seconds() / 60

    @property
    def type_changed(self) -> bool:
        return self.baseline.signal_type != self.candidate.signal_type


@dataclass(frozen=True)
class SignalComparisonResult:
    trading_date: date
    baseline_source: str
    candidate_source: str
    baseline_path: str
    candidate_path: str
    baseline_signals: list[SignalSnapshot]
    candidate_signals: list[SignalSnapshot]
    baseline_only: list[SignalSnapshot]
    candidate_only: list[SignalSnapshot]
    overlaps: list[SignalDelta]
    summary_stats: dict[str, float | int]
    suggestions: list[str]


def compare_signal_sources(
    trading_date: date,
    *,
    baseline_source: str,
    candidate_source: str,
) -> SignalComparisonResult:
    baseline_signals = _load_signals(trading_date, baseline_source)
    candidate_signals = _load_signals(trading_date, candidate_source)

    baseline_map = {signal.symbol: signal for signal in baseline_signals}
    candidate_map = {signal.symbol: signal for signal in candidate_signals}

    baseline_symbols = set(baseline_map)
    candidate_symbols = set(candidate_map)
    overlap_symbols = sorted(baseline_symbols & candidate_symbols)

    overlaps = [
        SignalDelta(
            symbol=symbol,
            baseline=baseline_map[symbol],
            candidate=candidate_map[symbol],
        )
        for symbol in overlap_symbols
    ]
    baseline_only = [baseline_map[symbol] for symbol in sorted(baseline_symbols - candidate_symbols)]
    candidate_only = [candidate_map[symbol] for symbol in sorted(candidate_symbols - baseline_symbols)]

    summary_stats = _build_summary_stats(
        baseline_signals=baseline_signals,
        candidate_signals=candidate_signals,
        baseline_only=baseline_only,
        candidate_only=candidate_only,
        overlaps=overlaps,
    )
    suggestions = _build_suggestions(
        baseline_source=baseline_source,
        candidate_source=candidate_source,
        baseline_only=baseline_only,
        candidate_only=candidate_only,
        summary_stats=summary_stats,
    )

    return SignalComparisonResult(
        trading_date=trading_date,
        baseline_source=baseline_source,
        candidate_source=candidate_source,
        baseline_path=str(get_log_source_path(baseline_source)),
        candidate_path=str(get_log_source_path(candidate_source)),
        baseline_signals=baseline_signals,
        candidate_signals=candidate_signals,
        baseline_only=baseline_only,
        candidate_only=candidate_only,
        overlaps=overlaps,
        summary_stats=summary_stats,
        suggestions=suggestions,
    )


def build_signal_comparison_report(result: SignalComparisonResult) -> str:
    lines: list[str] = []
    stats = result.summary_stats

    lines.append(f"# Signal Comparison - {result.trading_date.isoformat()}")
    lines.append("")
    lines.append(f"- Baseline source: `{result.baseline_source}` ({result.baseline_path})")
    lines.append(f"- Candidate source: `{result.candidate_source}` ({result.candidate_path})")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| {result.baseline_source} signals | {stats['baseline_signal_count']} |")
    lines.append(f"| {result.candidate_source} signals | {stats['candidate_signal_count']} |")
    lines.append(f"| Overlapping symbols | {stats['overlap_count']} |")
    lines.append(f"| {result.baseline_source}-only symbols | {stats['baseline_only_count']} |")
    lines.append(f"| {result.candidate_source}-only symbols | {stats['candidate_only_count']} |")
    lines.append(f"| Overlap ratio | {stats['overlap_ratio_pct']:.0f}% |")
    lines.append(f"| Avg score delta ({result.candidate_source} - {result.baseline_source}) | {stats['avg_score_delta']:+.2f} |")
    lines.append(f"| Avg pwin delta ({result.candidate_source} - {result.baseline_source}) | {stats['avg_pwin_delta']:+.2f} pts |")
    lines.append(f"| Avg bars delta ({result.candidate_source} - {result.baseline_source}) | {stats['avg_bars_delta']:+.1f} |")
    lines.append(f"| Avg timestamp drift ({result.candidate_source} - {result.baseline_source}) | {stats['avg_timestamp_delta_minutes']:+.1f} min |")
    lines.append(f"| Signal type mismatches | {stats['type_mismatch_count']} |")
    lines.append("")

    if result.suggestions:
        lines.append("## Suggestions")
        lines.append("")
        for suggestion in result.suggestions:
            lines.append(f"- {suggestion}")
        lines.append("")

    if result.overlaps:
        lines.append("## Overlapping Symbols")
        lines.append("")
        lines.append("| Symbol | Base | Cand | Score d | Pwin d | Bars d | Drift |")
        lines.append("|--------|------|------|---------|--------|--------|-------|")
        for delta in result.overlaps[:20]:
            lines.append(f"| {delta.symbol} | {delta.baseline.signal_type.value} | {delta.candidate.signal_type.value} | {delta.score_delta:+.2f} | {delta.pwin_delta:+.1f} | {delta.bars_delta:+d} | {delta.timestamp_delta_minutes:+.1f}m |")
        lines.append("")

    _append_signal_list(lines, title=f"{result.baseline_source.title()}-Only Signals", signals=result.baseline_only)
    _append_signal_list(lines, title=f"{result.candidate_source.title()}-Only Signals", signals=result.candidate_only)

    return "\n".join(lines)


def _append_signal_list(lines: list[str], *, title: str, signals: list[SignalSnapshot]) -> None:
    if not signals:
        return

    lines.append(f"## {title}")
    lines.append("")
    lines.append("| Symbol | Type | Time | Score | Pwin | Bars | TVR |")
    lines.append("|--------|------|------|-------|------|------|-----|")
    for signal in signals[:20]:
        lines.append(f"| {signal.symbol} | {signal.signal_type.value} | {signal.timestamp.strftime('%H:%M:%S')} | {signal.score:.2f} | {signal.pwin:.1f}% | {signal.bars} | {signal.tvr:.1f}M |")
    lines.append("")


def _load_signals(trading_date: date, log_source: str) -> list[SignalSnapshot]:
    trades = parse_log_file(trading_date, log_source=log_source)
    signals = [trade.signal for trade in trades if trade.signal is not None]
    snapshots = [_to_snapshot(signal, log_source) for signal in signals]
    return sorted(snapshots, key=lambda item: (item.timestamp, item.symbol))


def _to_snapshot(signal: Signal, source_name: str) -> SignalSnapshot:
    return SignalSnapshot(
        source_name=source_name,
        symbol=signal.symbol,
        signal_type=signal.signal_type,
        timestamp=signal.timestamp,
        score=signal.score,
        pwin=signal.pwin,
        bars=signal.bars,
        ret5m_predicted=signal.ret5m_predicted,
        dd_predicted=signal.dd_predicted,
        tvr=signal.tvr,
    )


def _build_summary_stats(
    *,
    baseline_signals: list[SignalSnapshot],
    candidate_signals: list[SignalSnapshot],
    baseline_only: list[SignalSnapshot],
    candidate_only: list[SignalSnapshot],
    overlaps: list[SignalDelta],
) -> dict[str, float | int]:
    union_count = len({signal.symbol for signal in baseline_signals} | {signal.symbol for signal in candidate_signals})
    return {
        "baseline_signal_count": len(baseline_signals),
        "candidate_signal_count": len(candidate_signals),
        "baseline_only_count": len(baseline_only),
        "candidate_only_count": len(candidate_only),
        "overlap_count": len(overlaps),
        "overlap_ratio_pct": (len(overlaps) / union_count * 100) if union_count else 100.0,
        "avg_score_delta": mean([delta.score_delta for delta in overlaps]) if overlaps else 0.0,
        "avg_pwin_delta": mean([delta.pwin_delta for delta in overlaps]) if overlaps else 0.0,
        "avg_bars_delta": mean([delta.bars_delta for delta in overlaps]) if overlaps else 0.0,
        "avg_timestamp_delta_minutes": mean([delta.timestamp_delta_minutes for delta in overlaps]) if overlaps else 0.0,
        "type_mismatch_count": sum(1 for delta in overlaps if delta.type_changed),
    }


def _build_suggestions(
    *,
    baseline_source: str,
    candidate_source: str,
    baseline_only: list[SignalSnapshot],
    candidate_only: list[SignalSnapshot],
    summary_stats: dict[str, float | int],
) -> list[str]:
    suggestions: list[str] = []

    strong_baseline_only = [signal for signal in baseline_only if signal.score >= 8.0 or signal.pwin >= 80.0]
    low_conviction_candidate_only = [signal for signal in candidate_only if signal.score < 5.0 or signal.pwin < 50.0]

    if summary_stats["baseline_signal_count"] == 0 and summary_stats["candidate_signal_count"] == 0:
        return ["No signals were loaded from either source for this date. Verify the source names, configured paths, and log files before drawing conclusions."]

    if summary_stats["baseline_signal_count"] == 0:
        return [f"No signals were loaded from {baseline_source}. Verify the configured path and make sure the requested date exists in that log source."]

    if summary_stats["candidate_signal_count"] == 0:
        return [f"No signals were loaded from {candidate_source}. Verify the configured path and make sure the requested date exists in that log source."]

    if not baseline_only and not candidate_only and summary_stats["type_mismatch_count"] == 0:
        suggestions.append("The two sources are closely aligned on symbol selection. Focus on execution quality or post-entry handling before changing signal filters.")

    if strong_baseline_only:
        suggestions.append(f"{candidate_source} missed {len(strong_baseline_only)} strong {baseline_source} signal(s). Check filter strictness, warm-up windows, or feed completeness.")

    if low_conviction_candidate_only:
        suggestions.append(f"{candidate_source} produced {len(low_conviction_candidate_only)} extra low-conviction signal(s). Tighten minimum score or win-probability thresholds.")

    if summary_stats["overlap_ratio_pct"] < 60:
        suggestions.append("Signal overlap is low, which usually means the two environments are not using the same filters, data inputs, or timing rules.")

    if summary_stats["type_mismatch_count"] > 0:
        suggestions.append("Some overlapping tickers changed signal type between sources. Audit DD reclaim and bounce classification logic for drift.")

    if summary_stats["avg_score_delta"] <= -1.0:
        suggestions.append(f"{candidate_source} scores overlapping signals materially lower than {baseline_source}. Check feature scaling or scoring calibration.")

    if summary_stats["avg_timestamp_delta_minutes"] >= 2.0 or summary_stats["avg_timestamp_delta_minutes"] <= -2.0:
        suggestions.append("Average signal timing drift exceeds two minutes. Compare candle boundaries, buffering, and event timestamp handling.")

    if not suggestions:
        suggestions.append("The differences are modest. Review the source-only symbols first, then compare score and timing deltas on overlapping names.")

    return suggestions
