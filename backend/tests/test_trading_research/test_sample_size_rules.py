from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import Claim, ClaimStatus, EvidenceItem, EvidenceSourceType, Recommendation, ReviewResult, WorkflowKind
from src.trading_research.verifier_service import MIN_RECOMMENDATION_SAMPLE_SIZE, MIN_SUPPORTED_CLAIM_SAMPLE_SIZE, SAMPLE_SIZE_CONFIDENCE_CAP, VerifierService


def _register_evidence(evidence_service: EvidenceService, suffix: str = "") -> EvidenceItem:
    return evidence_service.register(
        EvidenceItem(
            evidence_type="test_evidence",
            title=f"Test evidence {suffix}",
            content=f"Test content {suffix}",
            source_type=EvidenceSourceType.WEB_SOURCE,
            source_ref=f"https://example.com/sample-test-{suffix}",
            provenance={"test": "sample_size"},
        )
    )


def _make_result(
    claims: list[Claim],
    evidence_ids: list[str],
    recommendations: list[Recommendation] | None = None,
) -> ReviewResult:
    return ReviewResult(
        result_id="sample_size_test_review",
        workflow=WorkflowKind.TRADE_REVIEW,
        title="Sample Size Test Review",
        subject="TEST 2026-03-05",
        as_of=datetime(2026, 3, 5, 10, 0),
        claims=claims,
        evidence_ids=evidence_ids,
        recommendations=recommendations or [],
    )


def test_claim_below_min_sample_size_downgraded_to_observation(tmp_path: Path) -> None:
    """Claims with sample_size < MIN_SUPPORTED_CLAIM_SAMPLE_SIZE get downgraded."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "1")

        claim = Claim(
            claim_id="claim_low_sample",
            statement="Low sample claim",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=1,  # below MIN_SUPPORTED_CLAIM_SAMPLE_SIZE (2)
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.OBSERVATION
        assert claim.claim_id in verifier_result.sample_size_downgraded_claim_ids
        assert any(issue.code == "sample_size_below_threshold" for issue in verifier_result.issues)


def test_claim_with_none_sample_size_downgraded(tmp_path: Path) -> None:
    """Claims with sample_size=None get downgraded."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "none")

        claim = Claim(
            claim_id="claim_none_sample",
            statement="None sample claim",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=None,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.OBSERVATION
        assert claim.claim_id in verifier_result.sample_size_downgraded_claim_ids


def test_confidence_capped_on_sample_size_downgrade(tmp_path: Path) -> None:
    """Downgraded claims have confidence capped at SAMPLE_SIZE_CONFIDENCE_CAP."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "cap")

        claim = Claim(
            claim_id="claim_cap",
            statement="High confidence low sample",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.95,
            sample_size=1,
        )
        result = _make_result([claim], [evidence.evidence_id])

        _ = VerifierService(es).verify_result(result)

        assert result.claims[0].confidence is not None
        assert result.claims[0].confidence <= SAMPLE_SIZE_CONFIDENCE_CAP


def test_confidence_preserved_when_already_below_cap(tmp_path: Path) -> None:
    """If confidence is already below the cap, it stays at its original value."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "low-conf")

        claim = Claim(
            claim_id="claim_low_conf",
            statement="Low confidence low sample",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.2,
            sample_size=1,
        )
        result = _make_result([claim], [evidence.evidence_id])

        _ = VerifierService(es).verify_result(result)

        assert result.claims[0].confidence == 0.2


def test_claim_at_threshold_passes_sample_size_check(tmp_path: Path) -> None:
    """Claims with sample_size == MIN_SUPPORTED_CLAIM_SAMPLE_SIZE are NOT downgraded."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "at-threshold")

        claim = Claim(
            claim_id="claim_threshold",
            statement="At-threshold claim",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=MIN_SUPPORTED_CLAIM_SAMPLE_SIZE,
        )
        result = _make_result([claim], [evidence.evidence_id])

        verifier_result = VerifierService(es).verify_result(result)

        assert result.claims[0].status == ClaimStatus.SUPPORTED
        assert claim.claim_id not in verifier_result.sample_size_downgraded_claim_ids


def test_recommendation_dropped_when_all_claims_below_rec_threshold(tmp_path: Path) -> None:
    """Recommendations are dropped when ALL supporting claims have sample_size < MIN_RECOMMENDATION_SAMPLE_SIZE."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "rec-drop")

        # A claim that passes claim threshold but fails rec threshold
        claim = Claim(
            claim_id="claim_rec_low",
            statement="Passes claim threshold but fails rec threshold",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=MIN_SUPPORTED_CLAIM_SAMPLE_SIZE,  # 2, which is < MIN_RECOMMENDATION_SAMPLE_SIZE (3)
        )
        recommendation = Recommendation(
            recommendation_id="rec_dropped",
            summary="Should be dropped",
            action="Action",
            supported_by_claim_ids=["claim_rec_low"],
            evidence_ids=[evidence.evidence_id],
        )
        result = _make_result([claim], [evidence.evidence_id], [recommendation])

        verifier_result = VerifierService(es).verify_result(result)

        assert "rec_dropped" in verifier_result.dropped_recommendation_ids
        assert result.recommendations == []


def test_recommendation_kept_when_supporting_claim_meets_rec_threshold(tmp_path: Path) -> None:
    """Recommendations survive when at least one supporting claim has sample_size >= MIN_RECOMMENDATION_SAMPLE_SIZE."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "rec-keep")

        claim = Claim(
            claim_id="claim_rec_ok",
            statement="Good claim",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=MIN_RECOMMENDATION_SAMPLE_SIZE,
        )
        recommendation = Recommendation(
            recommendation_id="rec_kept",
            summary="Should survive",
            action="Action",
            supported_by_claim_ids=["claim_rec_ok"],
            evidence_ids=[evidence.evidence_id],
        )
        result = _make_result([claim], [evidence.evidence_id], [recommendation])

        verifier_result = VerifierService(es).verify_result(result)

        assert "rec_kept" not in verifier_result.dropped_recommendation_ids
        assert len(result.recommendations) == 1


def test_recommendation_dropped_when_claim_downgraded_by_sample_size(tmp_path: Path) -> None:
    """Recommendations are dropped when their only supporting claim was downgraded from supported to observation."""
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        es = EvidenceService()
        evidence = _register_evidence(es, "rec-chain")

        claim = Claim(
            claim_id="claim_chain",
            statement="Will be downgraded",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
            sample_size=1,  # triggers sample-size downgrade
        )
        recommendation = Recommendation(
            recommendation_id="rec_chain",
            summary="Should be dropped because claim is downgraded",
            action="Action",
            supported_by_claim_ids=["claim_chain"],
            evidence_ids=[evidence.evidence_id],
        )
        result = _make_result([claim], [evidence.evidence_id], [recommendation])

        verifier_result = VerifierService(es).verify_result(result)

        # Claim is observation, not supported -> recommendation dropped
        assert result.claims[0].status == ClaimStatus.OBSERVATION
        assert "rec_chain" in verifier_result.dropped_recommendation_ids
        assert result.recommendations == []


def test_thresholds_have_expected_values() -> None:
    """Verify the module-level threshold constants are set to plan values."""
    assert MIN_SUPPORTED_CLAIM_SAMPLE_SIZE == 2
    assert MIN_RECOMMENDATION_SAMPLE_SIZE == 3
    assert SAMPLE_SIZE_CONFIDENCE_CAP == 0.49
