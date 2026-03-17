from __future__ import annotations

from datetime import datetime

from src.trading_research.models import (
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


def test_models_capture_p0_contract_fields() -> None:
    as_of = datetime(2026, 3, 5, 10, 0)
    evidence = EvidenceItem(
        evidence_id="ev_test",
        evidence_type="web_research",
        title="Source",
        content="Snippet",
        source_type=EvidenceSourceType.WEB_SOURCE,
        source_ref="https://example.com",
        provenance={"symbol": "AMPX"},
        as_of=as_of,
        sample_size=3,
    )
    finding = Finding(
        finding_id="finding_1",
        title="Finding",
        detail="Detail",
        evidence_ids=[evidence.evidence_id],
        confidence=0.7,
        sample_size=3,
        limitations=["small sample"],
        as_of=as_of,
    )
    claim = Claim(
        claim_id="claim_1",
        statement="A supported statement",
        status=ClaimStatus.SUPPORTED,
        evidence_ids=[evidence.evidence_id],
        confidence=0.8,
        sample_size=3,
        limitations=["single source"],
        as_of=as_of,
    )
    recommendation = Recommendation(
        recommendation_id="rec_1",
        summary="Recommendation",
        action="Do something",
        supported_by_claim_ids=[claim.claim_id],
        evidence_ids=[evidence.evidence_id],
        confidence=0.6,
        as_of=as_of,
    )
    verifier = VerifierResult(
        passed=True,
        verified_at=as_of,
        checked_claim_count=1,
        checked_evidence_count=1,
    )

    review_result = ReviewResult(
        result_id="review_1",
        workflow=WorkflowKind.TRADE_REVIEW,
        title="Trade Review",
        subject="AMPX 2026-03-05",
        as_of=as_of,
        findings=[finding],
        claims=[claim],
        recommendations=[recommendation],
        evidence_ids=[evidence.evidence_id],
        limitations=["test limitation"],
        verifier=verifier,
        symbol="AMPX",
    )
    setup_result = SetupResearchResult(
        result_id="setup_1",
        workflow=WorkflowKind.SETUP_RESEARCH,
        title="Setup Research",
        subject="EV breakout",
        topic="EV breakout",
        symbol="AMPX",
        setup_type=SetupType.INTRADAY_BREAKOUT,
        as_of=as_of,
    )

    assert review_result.claims[0].evidence_ids == ["ev_test"]
    assert review_result.findings[0].sample_size == 3
    assert review_result.recommendations[0].confidence == 0.6
    assert review_result.recommendations[0].supported_by_claim_ids == ["claim_1"]
    assert setup_result.workflow == WorkflowKind.SETUP_RESEARCH
