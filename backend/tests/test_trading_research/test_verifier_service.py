from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import Claim, ClaimStatus, EvidenceItem, EvidenceSourceType, Recommendation, ReviewResult, WorkflowKind
from src.trading_research.verifier_service import VerifierService


def test_verifier_downgrades_claims_with_missing_evidence(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        verifier = VerifierService(EvidenceService())
        result = ReviewResult(
            result_id="review_1",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            claims=[
                Claim(
                    claim_id="claim_1",
                    statement="Unsupported claim",
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=["ev_missing"],
                )
            ],
        )

        verifier_result = verifier.verify_result(result)

        assert verifier_result.passed is False
        assert result.claims[0].status == ClaimStatus.UNSUPPORTED
        assert verifier_result.downgraded_claim_ids == ["claim_1"]


def test_verifier_handles_claims_with_persisted_evidence_and_sample_size(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        evidence_service = EvidenceService()
        stored = evidence_service.register(
            EvidenceItem(
                evidence_type="web_research",
                title="Stored evidence",
                content="Snippet",
                source_type=EvidenceSourceType.WEB_SOURCE,
                source_ref="https://example.com",
                provenance={"symbol": "AMPX"},
            )
        )
        verifier = VerifierService(evidence_service)
        result = ReviewResult(
            result_id="review_2",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            claims=[
                Claim(
                    claim_id="claim_2",
                    statement="Supported claim",
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=[stored.evidence_id],
                    sample_size=None,
                )
            ],
            evidence_ids=[stored.evidence_id],
        )

        verifier_result = verifier.verify_result(result)

        assert result.claims[0].status == ClaimStatus.OBSERVATION
        assert "claim_2" in verifier_result.sample_size_downgraded_claim_ids


def test_verifier_accepts_persisted_claim_evidence_outside_result_index(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        evidence_service = EvidenceService()
        stored = evidence_service.register(
            EvidenceItem(
                evidence_type="web_research",
                title="Stored evidence",
                content="Snippet",
                source_type=EvidenceSourceType.WEB_SOURCE,
                source_ref="https://example.com",
                provenance={"symbol": "AMPX"},
            )
        )
        verifier = VerifierService(evidence_service)
        result = ReviewResult(
            result_id="review_3",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            claims=[
                Claim(
                    claim_id="claim_3",
                    statement="Supported claim",
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=[stored.evidence_id],
                    sample_size=5,
                )
            ],
            evidence_ids=[],
        )

        verifier_result = verifier.verify_result(result)

        assert verifier_result.passed is True
        assert stored.evidence_id in result.evidence_ids


def test_verifier_drops_recommendations_without_verified_claim_support(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        evidence_service = EvidenceService()
        stored = evidence_service.register(
            EvidenceItem(
                evidence_type="trade_snapshot",
                title="Stored evidence",
                content="Snippet",
                source_type=EvidenceSourceType.REVIEW_SUMMARY,
                source_ref="trade:AMPX:2026-03-05:prod",
                provenance={"symbol": "AMPX"},
            )
        )
        verifier = VerifierService(evidence_service)
        result = ReviewResult(
            result_id="review_4",
            workflow=WorkflowKind.TRADE_REVIEW,
            title="Trade Review",
            subject="AMPX 2026-03-05",
            as_of=datetime(2026, 3, 5, 10, 0),
            claims=[
                Claim(
                    claim_id="claim_4",
                    statement="Supported claim",
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=[stored.evidence_id],
                    sample_size=5,
                )
            ],
            recommendations=[
                Recommendation(
                    recommendation_id="rec_4",
                    summary="Bad rec",
                    action="Action",
                    supported_by_claim_ids=["missing_claim"],
                    evidence_ids=[stored.evidence_id],
                )
            ],
        )

        verifier_result = verifier.verify_result(result)

        assert verifier_result.passed is False
        assert verifier_result.dropped_recommendation_ids == ["rec_4"]
        assert result.recommendations == []
