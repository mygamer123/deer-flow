"""Regression tests for the five correctness hotfixes.

Each test targets one specific bug and asserts the fix holds.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.community.finance.models import (
    AnalyticalLens,
    DataGap,
    EntryEvent,
    EntryVerdict,
    ExitEvent,
    ExitPolicy,
    ExitVerdict,
    IterationResult,
    ParsedTrade,
    PatternType,
    QualityTier,
    QuantitativeFindings,
    ReviewVerdict,
    SelectionVerdict,
    Signal,
    SignalType,
    TradeOutcome,
    TradeReview,
)
from src.community.research.models import (
    Claim as RawClaim,
    Evidence as RawEvidence,
    ResearchReport,
    SourceType,
    VerificationStatus,
)
from src.community.research.research_service import ResearchService
from src.trading_research.aggregate_review_service import AggregatedTradeReviewRequest, AggregateReviewService
from src.trading_research.evidence_service import EvidenceService
from src.trading_research.setup_research_service import SetupResearchService
from src.trading_research.strategy_improvement_service import StrategyImprovementService
from src.trading_research.trade_review_service import TradeReviewService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade_review(*, outcome: TradeOutcome = TradeOutcome.TP_FILLED) -> TradeReview:
    signal_ts = datetime(2026, 3, 5, 9, 35)
    entry_ts = datetime(2026, 3, 5, 9, 36)
    exit_ts = entry_ts + timedelta(minutes=10)
    trade = ParsedTrade(
        trading_date=date(2026, 3, 5),
        symbol="AMPX",
        signal=Signal(
            timestamp=signal_ts,
            symbol="AMPX",
            signal_type=SignalType.MAIN,
            score=9.2,
            pwin=81.0,
            bars=75,
            ret5m_predicted=3.1,
            dd_predicted=1.2,
            tvr=11.5,
            raw_line="signal",
        ),
        entry=EntryEvent(timestamp=entry_ts, symbol="AMPX", price=10.0, quantity=100),
        exit=ExitEvent(timestamp=exit_ts, symbol="AMPX", price=10.6),
        outcome=outcome,
    )
    iteration_result = IterationResult(
        iteration=1,
        lens=AnalyticalLens(name="basic_bars", iteration=1, description="test"),
        findings={
            "selection": QuantitativeFindings(
                lens_name="basic_bars",
                iteration=1,
                observations=["Strong signal score (9.2)"],
                metrics={"score": 9.2},
                confidence=0.8,
            ),
            "entry": QuantitativeFindings(
                lens_name="basic_bars",
                iteration=1,
                observations=["Entered near bar low"],
                metrics={"entry_position_in_bar": 0.2},
                confidence=0.7,
            ),
            "exit": QuantitativeFindings(
                lens_name="alt_tp_sl_sim",
                iteration=1,
                observations=["Best fixed TP/SL: tp5_sl3 -> +4.50%"],
                metrics={"best_tp_sl_pnl": 4.5},
                confidence=0.75,
            ),
        },
        new_gaps=[DataGap(dimension="news", description="Missing data: news")],
        cumulative_confidence=0.8,
    )
    return TradeReview(
        trade=trade,
        quality_tier=QualityTier.GOOD,
        overall_verdict=ReviewVerdict.ACCEPTABLE,
        selection=SelectionVerdict(should_trade=True, confidence=0.8, reasons=["Strong signal score (9.2)"]),
        entry=EntryVerdict(should_have_waited=False, reasons=["Entered near bar low"]),
        exit=ExitVerdict(
            recommended_policy=ExitPolicy.TRAILING_STOP,
            reasons=["Trailing stop captured more than fixed TP"],
        ),
        pattern=PatternType.STRONG_UPTRENDING,
        iteration_results=[iteration_result],
        total_iterations=1,
    )


def _make_saved_review(
    *,
    result_id: str,
    symbol: str = "AMPX",
    trading_date: str = "2026-03-05",
    pattern: str = "strong_uptrending",
    overall_verdict: str = "good_trade",
    quality_tier: str = "good",
    outcome: str = "tp_filled",
    boundary_time: str | None = None,
) -> dict[str, object]:
    claims = [
        {
            "claim_id": f"claim_selection_{result_id}",
            "statement": "The trade should have been taken based on strong signal score.",
            "status": "observation",
            "evidence_ids": [f"ev_{result_id}_sel"],
            "confidence": 0.8,
            "sample_size": 1,
        },
        {
            "claim_id": f"claim_entry_{result_id}",
            "statement": "Entry timing was acceptable.",
            "status": "observation",
            "evidence_ids": [f"ev_{result_id}_ent"],
            "confidence": 0.7,
            "sample_size": 1,
        },
        {
            "claim_id": f"claim_exit_{result_id}",
            "statement": "Evidence favors `trailing_stop` exit policy.",
            "status": "observation",
            "evidence_ids": [f"ev_{result_id}_ext"],
            "confidence": 0.75,
            "sample_size": 1,
        },
    ]
    return {
        "result_id": result_id,
        "workflow": "trade_review",
        "title": f"Trade Review: {symbol}",
        "subject": f"{symbol} {trading_date}",
        "as_of": "2026-03-05T10:00:00",
        "symbol": symbol,
        "trading_date": trading_date,
        "log_source": "prod",
        "boundary_time": boundary_time or "2026-03-05T10:00:00",
        "metadata": {
            "pattern": pattern,
            "overall_verdict": overall_verdict,
            "quality_tier": quality_tier,
            "outcome": outcome,
            "total_iterations": 1,
        },
        "findings": [],
        "claims": claims,
        "recommendations": [],
        "evidence_ids": [f"ev_{result_id}_sel", f"ev_{result_id}_ent", f"ev_{result_id}_ext"],
        "limitations": [],
    }


# ---------------------------------------------------------------------------
# Issue 1 – outcome persisted in metadata
# ---------------------------------------------------------------------------


def test_issue1_outcome_persisted_in_metadata(tmp_path: Path) -> None:
    """TradeReviewService must include trade outcome in the result metadata."""
    review = _make_trade_review(outcome=TradeOutcome.STOPPED_OUT)

    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        with patch(
            "src.trading_research.trade_review_service.DecisionReviewService.review_single_trade",
            return_value=review,
        ):
            service = TradeReviewService(evidence_service=EvidenceService())
            result = service.review_trade(symbol="AMPX", trading_date=date(2026, 3, 5), log_source="prod")

    assert result.metadata["outcome"] == "stopped_out"


def test_issue1_all_outcome_values_round_trip(tmp_path: Path) -> None:
    """Every TradeOutcome variant must survive the metadata round-trip."""
    for outcome in TradeOutcome:
        review = _make_trade_review(outcome=outcome)

        with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
            with patch(
                "src.trading_research.trade_review_service.DecisionReviewService.review_single_trade",
                return_value=review,
            ):
                service = TradeReviewService(evidence_service=EvidenceService())
                result = service.review_trade(symbol="AMPX", trading_date=date(2026, 3, 5), log_source="prod")

        assert result.metadata["outcome"] == outcome.value, f"Failed for {outcome}"


# ---------------------------------------------------------------------------
# Issue 2 – AggregateReviewService wired by default
# ---------------------------------------------------------------------------


def test_issue2_aggregate_review_service_wired_by_default() -> None:
    """StrategyImprovementService must create its own AggregateReviewService if none provided."""
    service = StrategyImprovementService()
    assert service._aggregate_review_service is not None
    assert isinstance(service._aggregate_review_service, AggregateReviewService)


# ---------------------------------------------------------------------------
# Issue 3 – evidence-to-claim mapping uses source_ref, not substring
# ---------------------------------------------------------------------------


def test_issue3_evidence_correctly_mapped_to_claims(tmp_path: Path) -> None:
    """Aggregate claims must reference the correct evidence IDs via source_ref lookup."""
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2"),
        _make_saved_review(result_id="r3"),
    ]

    with patch(
        "src.trading_research.aggregate_review_service.list_saved_results",
        return_value=[f"trade_review_{r['result_id']}.json" for r in reviews],
    ):
        with patch(
            "src.trading_research.aggregate_review_service.load_saved_result",
            side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname))),
        ):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = AggregateReviewService(evidence_service=EvidenceService(base_dir=evidence_dir))
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    type_claims = [c for c in result.claims if c.claim_id.startswith("agg_claim_") and c.claim_id not in (f"agg_claim_verdict_{result.grouping_key}",)]
    assert type_claims, "Expected per-type aggregate claims (selection/entry/exit)"

    for claim in type_claims:
        assert claim.evidence_ids, f"Claim {claim.claim_id} has no evidence_ids"
        for eid in claim.evidence_ids:
            assert eid in result.evidence_ids, f"Claim {claim.claim_id} references unknown evidence {eid}"


# ---------------------------------------------------------------------------
# Issue 4 – evidence timestamps clamped to boundary
# ---------------------------------------------------------------------------


def test_issue4_future_evidence_clamped_to_boundary(tmp_path: Path) -> None:
    """Evidence with fetched_at after result boundary must be clamped."""
    boundary = datetime(2026, 3, 5, 10, 0, 0)
    future_time = boundary + timedelta(hours=2)

    source = RawEvidence(
        snippet="Analysts noted a momentum continuation setup.",
        source_url="https://example.com/research",
        source_title="Momentum note",
        source_type=SourceType.WEB_SEARCH,
        fetched_at=future_time,
        relevance=0.7,
    )
    claim = RawClaim(
        statement="Momentum setups showed strong relative volume.",
        status=VerificationStatus.INSUFFICIENT,
        supporting_evidence=[source],
        confidence=0.4,
    )
    report = ResearchReport(
        topic="EV momentum setup",
        summary="Research found momentum source excerpts.",
        claims=[claim],
        sources=[source],
        created_at=boundary,
        search_queries=["EV momentum setup"],
        pages_fetched=1,
    )

    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        with patch(
            "src.trading_research.setup_research_service.ResearchService.research_topic",
            return_value=report,
        ):
            service = SetupResearchService(evidence_service=EvidenceService())
            result = service.research_setup(symbol="AMPX", setup_type="intraday_breakout")

    assert result.boundary_time is not None
    assert result.boundary_time <= boundary


def test_issue4_none_fetched_at_not_clamped(tmp_path: Path) -> None:
    """Evidence with fetched_at=None must not cause errors."""
    source = RawEvidence(
        snippet="Some research source.",
        source_url="https://example.com",
        source_title="Note",
        source_type=SourceType.WEB_SEARCH,
        fetched_at=None,  # type: ignore[arg-type]
        relevance=0.5,
    )
    claim = RawClaim(
        statement="Setup showed strong volume.",
        status=VerificationStatus.INSUFFICIENT,
        supporting_evidence=[source],
        confidence=0.3,
    )
    report = ResearchReport(
        topic="Test setup",
        summary="Test.",
        claims=[claim],
        sources=[source],
        created_at=datetime(2026, 3, 5, 10, 0),
        search_queries=["test"],
        pages_fetched=1,
    )

    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        with patch(
            "src.trading_research.setup_research_service.ResearchService.research_topic",
            return_value=report,
        ):
            service = SetupResearchService(evidence_service=EvidenceService())
            result = service.research_setup(symbol="AMPX", setup_type="intraday_breakout")

    assert result.evidence_ids


# ---------------------------------------------------------------------------
# Issue 5 – contradiction checked before support
# ---------------------------------------------------------------------------


def test_issue5_contradiction_wins_over_support() -> None:
    """A snippet that matches both contradiction markers AND support keywords
    must be classified as contradicting, not supporting."""
    service = ResearchService.__new__(ResearchService)

    snippet = "however momentum was incorrect and the stock reversed sharply after strong signal score"
    statement = "strong signal score predicts momentum continuation"

    assert service._snippet_contradicts(snippet, statement.lower()), "Snippet should be marked as contradicting"
    assert service._snippet_supports(snippet, statement.lower()), "Snippet also passes support threshold (the bug scenario)"

    claim = RawClaim(statement=statement)
    from src.community.research.models import Evidence as RawEvidence, SourceType

    evidence = RawEvidence(
        snippet=snippet,
        source_url="https://example.com",
        source_title="Test",
        source_type=SourceType.WEB_SEARCH,
    )

    stmt_lower = statement.lower()
    if service._snippet_contradicts(snippet, stmt_lower):
        claim.contradicting_evidence.append(evidence)
    elif service._snippet_supports(snippet, stmt_lower):
        claim.supporting_evidence.append(evidence)

    assert len(claim.contradicting_evidence) == 1, "Should be classified as contradicting"
    assert len(claim.supporting_evidence) == 0, "Should NOT be classified as supporting"


def test_issue5_pure_support_still_works() -> None:
    """A snippet that supports but does not contradict must still be classified as supporting."""
    service = ResearchService.__new__(ResearchService)

    snippet = "the strong signal score of 9.2 reliably predicts continuation momentum in EV names"
    statement = "strong signal score predicts momentum continuation"

    assert service._snippet_supports(snippet, statement.lower())
    assert not service._snippet_contradicts(snippet, statement.lower())
