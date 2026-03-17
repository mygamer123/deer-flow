from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import Claim, ClaimStatus, EvidenceItem, EvidenceSourceType, Recommendation, ReviewResult, WorkflowKind
from src.trading_research.verifier_service import VerifierService


def _register_evidence(
    evidence_service: EvidenceService,
    *,
    observed_at: datetime | None = None,
    effective_start: datetime | None = None,
    effective_end: datetime | None = None,
) -> EvidenceItem:
    return evidence_service.register(
        EvidenceItem(
            evidence_type="test_evidence",
            title="Test evidence",
            content="Test content",
            source_type=EvidenceSourceType.WEB_SOURCE,
            source_ref="https://example.com/boundary-test",
            provenance={"test": "boundary"},
            observed_at=observed_at,
            effective_start=effective_start,
            effective_end=effective_end,
        )
    )


def _make_result(
    claims: list[Claim],
    evidence_ids: list[str],
    recommendations: list[Recommendation] | None = None,
) -> ReviewResult:
    return ReviewResult(
        result_id="boundary_test_review",
        workflow=WorkflowKind.TRADE_REVIEW,
        title="Boundary Test Review",
        subject="TEST 2026-03-05",
        as_of=datetime(2026, 3, 5, 10, 0),
        claims=claims,
        evidence_ids=evidence_ids,
        recommendations=recommendations or [],
    )


def test_boundary_violation_when_evidence_observed_after_claim_boundary(tmp_path: Path) -> None:
    """Evidence observed_at is after claim boundary -> violation, claim unsupported."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        boundary = datetime(2026, 3, 5, 9, 30)
        evidence = _register_evidence(es, observed_at=boundary + timedelta(minutes=10))

        claim = Claim(
            claim_id="claim_boundary_1",
            statement="Claim with future evidence",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=boundary,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.UNSUPPORTED
        assert verifier_result.boundary_status == "failed"
        assert claim.claim_id in verifier_result.boundary_violation_claim_ids
        assert any(issue.code == "boundary_violation" for issue in verifier_result.issues)


def test_boundary_violation_when_effective_end_after_boundary(tmp_path: Path) -> None:
    """Evidence effective_end extends past claim boundary -> violation."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        boundary = datetime(2026, 3, 5, 9, 30)
        evidence = _register_evidence(
            es,
            observed_at=boundary - timedelta(minutes=5),
            effective_start=boundary - timedelta(minutes=5),
            effective_end=boundary + timedelta(hours=1),
        )

        claim = Claim(
            claim_id="claim_boundary_2",
            statement="Claim with evidence window extending past boundary",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=boundary,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.UNSUPPORTED
        assert verifier_result.boundary_status == "failed"
        assert claim.claim_id in verifier_result.boundary_violation_claim_ids


def test_boundary_violation_when_effective_start_after_boundary(tmp_path: Path) -> None:
    """Evidence effective_start is after claim boundary -> violation."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        boundary = datetime(2026, 3, 5, 9, 30)
        evidence = _register_evidence(
            es,
            observed_at=boundary - timedelta(minutes=5),
            effective_start=boundary + timedelta(minutes=1),
            effective_end=boundary + timedelta(hours=1),
        )

        claim = Claim(
            claim_id="claim_boundary_3",
            statement="Claim with future-starting evidence",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=boundary,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.UNSUPPORTED
        assert verifier_result.boundary_status == "failed"


def test_boundary_limited_when_evidence_has_no_timing(tmp_path: Path) -> None:
    """Evidence with no timing metadata -> limited boundary, claim downgraded to observation."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        boundary = datetime(2026, 3, 5, 9, 30)
        evidence = _register_evidence(es)  # no timing fields

        claim = Claim(
            claim_id="claim_boundary_4",
            statement="Claim with untimed evidence",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=boundary,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.OBSERVATION
        assert verifier_result.boundary_status == "limited"
        assert any(issue.code == "boundary_timing_missing" for issue in verifier_result.issues)


def test_boundary_passes_when_all_evidence_within_boundary(tmp_path: Path) -> None:
    """All evidence timestamps within boundary -> passes, claim stays supported."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        boundary = datetime(2026, 3, 5, 9, 30)
        evidence = _register_evidence(
            es,
            observed_at=boundary - timedelta(minutes=10),
            effective_start=boundary - timedelta(minutes=10),
            effective_end=boundary - timedelta(minutes=1),
        )

        claim = Claim(
            claim_id="claim_boundary_5",
            statement="Claim with good evidence",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=boundary,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.SUPPORTED
        assert verifier_result.boundary_status == "passed"
        assert verifier_result.boundary_violation_claim_ids == []


def test_boundary_not_checked_when_claim_has_no_boundary_time(tmp_path: Path) -> None:
    """Claims without boundary_time skip boundary checking entirely."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        # Evidence with future timestamps, but claim has no boundary
        evidence = _register_evidence(
            es,
            observed_at=datetime(2030, 1, 1),
        )

        claim = Claim(
            claim_id="claim_no_boundary",
            statement="Claim without boundary",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=None,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        # No boundary violation because boundary_time is None
        assert verifier_result.boundary_violation_claim_ids == []
        assert verifier_result.boundary_status == "passed"


def test_boundary_violation_drops_recommendation(tmp_path: Path) -> None:
    """A boundary-violated claim makes dependent recommendations get dropped."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        boundary = datetime(2026, 3, 5, 9, 30)
        evidence = _register_evidence(es, observed_at=boundary + timedelta(hours=1))

        claim = Claim(
            claim_id="claim_boundary_rec",
            statement="Boundary-violated claim",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=5,
            boundary_time=boundary,
        )
        recommendation = Recommendation(
            recommendation_id="rec_boundary",
            summary="Recommendation backed by violated claim",
            action="Do something",
            supported_by_claim_ids=["claim_boundary_rec"],
            evidence_ids=[evidence.evidence_id],
        )
        result = _make_result([claim], [evidence.evidence_id], [recommendation])

        verifier_result = VerifierService(es).verify_result(result)

        assert "rec_boundary" in verifier_result.dropped_recommendation_ids
        assert result.recommendations == []
