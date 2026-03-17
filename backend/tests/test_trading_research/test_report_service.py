from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import (
    AggregatedReviewResult,
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceSourceType,
    Finding,
    Recommendation,
    ReviewResult,
    SetupResearchResult,
    SetupType,
    VerifierResult,
    WorkflowKind,
)
from src.trading_research.report_service import build_aggregate_review_markdown, build_review_markdown, build_setup_research_markdown


def test_report_service_renders_required_sections(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        evidence_service = EvidenceService()
        evidence = evidence_service.register(
            EvidenceItem(
                evidence_type="trade_review_summary",
                title="Stored evidence",
                content="A persisted evidence snippet.",
                source_type=EvidenceSourceType.REVIEW_SUMMARY,
                source_ref="trade_review:AMPX:2026-03-05:summary",
                provenance={"symbol": "AMPX", "record_type": "review_summary"},
            )
        )
        result = ReviewResult(
            result_id="review_1",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            symbol="AMPX",
            trading_date=date(2026, 3, 5),
            findings=[Finding(finding_id="finding_1", title="Finding", detail="Detail", evidence_ids=[evidence.evidence_id])],
            claims=[Claim(claim_id="claim_1", statement="Statement", status=ClaimStatus.SUPPORTED, evidence_ids=[evidence.evidence_id])],
            recommendations=[
                Recommendation(
                    recommendation_id="rec_1",
                    summary="Recommendation",
                    action="Action",
                    supported_by_claim_ids=["claim_1"],
                    evidence_ids=[evidence.evidence_id],
                )
            ],
            evidence_ids=[evidence.evidence_id],
            limitations=["Test limitation"],
            verifier=VerifierResult(
                passed=True,
                verified_at=datetime(2026, 3, 5, 10, 1),
                checked_claim_count=1,
                checked_evidence_count=1,
                dropped_recommendation_ids=[],
                summary="All claims reference persisted evidence.",
            ),
        )

        markdown = build_review_markdown(result, evidence_service)

        assert "## Findings" in markdown
        assert "## Claims" in markdown
        assert "## Recommendations" in markdown
        assert "## Evidence References" in markdown
        assert "## Verifier Summary" in markdown
        assert "## Limitations" in markdown
        assert "Supported by claims: claim_1" in markdown
        assert "Boundary status: passed" in markdown


def test_setup_research_report_renders_query_context(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        evidence_service = EvidenceService()
        result = SetupResearchResult(
            result_id="setup_1",
            workflow=WorkflowKind.SETUP_RESEARCH,
            title="Setup Research",
            subject="EV setup",
            topic="EV setup",
            symbol="AMPX",
            setup_type=SetupType.INTRADAY_BREAKOUT,
            as_of=datetime(2026, 3, 5, 12, 0),
            search_queries=["EV setup"],
        )

        markdown = build_setup_research_markdown(result, evidence_service)

        assert "## Query Context" in markdown


def test_aggregate_report_renders_cohort_summary(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        evidence_service = EvidenceService()
        result = AggregatedReviewResult(
            result_id="agg_1",
            workflow=WorkflowKind.AGGREGATE_TRADE_REVIEW,
            title="Aggregated Trade Review: strong_uptrending (3 trades)",
            subject="aggregate:strong_uptrending",
            as_of=datetime(2026, 3, 5, 12, 0),
            trade_count=3,
            contributing_result_ids=["r1", "r2", "r3"],
            grouping_key="strong_uptrending",
            date_range_start=date(2026, 3, 1),
            date_range_end=date(2026, 3, 5),
            symbol="AMPX",
            cohort_stats={
                "trade_count": 3,
                "verdict_distribution": {"good_trade": 2, "bad_trade": 1},
            },
            findings=[
                Finding(
                    finding_id="finding_cohort",
                    title="Cohort overview",
                    detail="Aggregated 3 trade reviews.",
                    as_of=datetime(2026, 3, 5, 12, 0),
                )
            ],
            claims=[
                Claim(
                    claim_id="agg_claim_verdict",
                    statement="67% received a good_trade verdict.",
                    status=ClaimStatus.SUPPORTED,
                    sample_size=3,
                    as_of=datetime(2026, 3, 5, 12, 0),
                )
            ],
            verifier=VerifierResult(
                passed=True,
                verified_at=datetime(2026, 3, 5, 12, 1),
                checked_claim_count=1,
                checked_evidence_count=0,
                summary="All claims verified.",
            ),
        )

        markdown = build_aggregate_review_markdown(result, evidence_service)

    assert "## Cohort Summary" in markdown
    assert "Trade count: 3" in markdown
    assert "strong_uptrending" in markdown
    assert "AMPX" in markdown
    assert "r1" in markdown
    assert "## Findings" in markdown
    assert "## Claims" in markdown
    assert "## Verifier Summary" in markdown
