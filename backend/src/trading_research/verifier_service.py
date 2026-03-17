from __future__ import annotations

from datetime import datetime

from .evidence_service import EvidenceService
from .models import ClaimStatus, EvidenceItem, StructuredResult, VerifierIssue, VerifierResult

MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2
MIN_RECOMMENDATION_SAMPLE_SIZE = 3
SAMPLE_SIZE_CONFIDENCE_CAP = 0.49


class VerifierService:
    def __init__(self, evidence_service: EvidenceService | None = None) -> None:
        self._evidence_service = evidence_service or EvidenceService()

    def verify_result(self, result: StructuredResult) -> VerifierResult:
        issues: list[VerifierIssue] = []
        downgraded_claim_ids: list[str] = []
        dropped_recommendation_ids: list[str] = []
        boundary_violation_claim_ids: list[str] = []
        sample_size_downgraded_claim_ids: list[str] = []
        boundary_status = "passed"
        known_evidence_ids = {evidence_id for evidence_id in result.evidence_ids if self._evidence_service.get(evidence_id) is not None}

        for claim in result.claims:
            if not claim.evidence_ids:
                issues.append(
                    VerifierIssue(
                        code="claim_without_evidence",
                        message="Claim has no evidence references and was downgraded.",
                        severity="error",
                        claim_id=claim.claim_id,
                    )
                )
                claim.status = ClaimStatus.UNSUPPORTED
                downgraded_claim_ids.append(claim.claim_id)
                continue

            missing_evidence_ids: list[str] = []
            claim_evidence_items: list[EvidenceItem] = []
            for evidence_id in claim.evidence_ids:
                if evidence_id in known_evidence_ids:
                    item = self._evidence_service.get(evidence_id)
                    if item is not None:
                        claim_evidence_items.append(item)
                    continue
                evidence_item = self._evidence_service.get(evidence_id)
                if evidence_item is None:
                    missing_evidence_ids.append(evidence_id)
                    continue
                known_evidence_ids.add(evidence_id)
                claim_evidence_items.append(evidence_item)
                if evidence_id not in result.evidence_ids:
                    result.evidence_ids.append(evidence_id)

            if missing_evidence_ids:
                issues.append(
                    VerifierIssue(
                        code="missing_evidence_ids",
                        message="Claim references evidence that does not exist in the evidence store.",
                        severity="error",
                        claim_id=claim.claim_id,
                        evidence_ids=missing_evidence_ids,
                    )
                )
                claim.status = ClaimStatus.UNSUPPORTED
                downgraded_claim_ids.append(claim.claim_id)
                continue

            boundary_result = _check_claim_boundary(claim.claim_id, claim.boundary_time, claim_evidence_items)
            if boundary_result.violation and boundary_result.issue is not None:
                issues.append(boundary_result.issue)
                claim.status = ClaimStatus.UNSUPPORTED
                downgraded_claim_ids.append(claim.claim_id)
                boundary_violation_claim_ids.append(claim.claim_id)
                boundary_status = "failed"
                continue
            if boundary_result.limited and boundary_result.issue is not None:
                issues.append(boundary_result.issue)
                if claim.status != ClaimStatus.UNSUPPORTED:
                    claim.status = ClaimStatus.OBSERVATION
                    if claim.claim_id not in downgraded_claim_ids:
                        downgraded_claim_ids.append(claim.claim_id)
                boundary_status = _merge_boundary_status(boundary_status, "limited")

            sample_result = _check_sample_size(claim.claim_id, claim.sample_size)
            if sample_result.downgraded and sample_result.issue is not None:
                issues.append(sample_result.issue)
                if claim.status == ClaimStatus.SUPPORTED:
                    claim.status = ClaimStatus.OBSERVATION
                if claim.confidence is not None:
                    claim.confidence = min(claim.confidence, SAMPLE_SIZE_CONFIDENCE_CAP)
                if claim.claim_id not in downgraded_claim_ids:
                    downgraded_claim_ids.append(claim.claim_id)
                sample_size_downgraded_claim_ids.append(claim.claim_id)

        eligible_claim_ids = {claim.claim_id for claim in result.claims if claim.status == ClaimStatus.SUPPORTED}
        filtered_recommendations = []
        for recommendation in result.recommendations:
            if not recommendation.supported_by_claim_ids:
                issues.append(
                    VerifierIssue(
                        code="recommendation_without_claim_support",
                        message="Recommendation has no supporting verified claims and was dropped.",
                        severity="error",
                    )
                )
                dropped_recommendation_ids.append(recommendation.recommendation_id)
                continue

            unsupported_claim_ids = [claim_id for claim_id in recommendation.supported_by_claim_ids if claim_id not in eligible_claim_ids]
            if unsupported_claim_ids:
                issues.append(
                    VerifierIssue(
                        code="recommendation_with_unsupported_claims",
                        message="Recommendation depends on claims that did not survive verification and was dropped.",
                        severity="error",
                        evidence_ids=unsupported_claim_ids,
                    )
                )
                dropped_recommendation_ids.append(recommendation.recommendation_id)
                continue

            supporting_claims = [claim for claim in result.claims if claim.claim_id in recommendation.supported_by_claim_ids]
            if supporting_claims and all((claim.sample_size or 0) < MIN_RECOMMENDATION_SAMPLE_SIZE for claim in supporting_claims):
                issues.append(
                    VerifierIssue(
                        code="recommendation_insufficient_sample_size",
                        message="Recommendation dropped because all supporting claims have sample size below the recommendation threshold.",
                        severity="error",
                    )
                )
                dropped_recommendation_ids.append(recommendation.recommendation_id)
                continue

            filtered_recommendations.append(recommendation)

        result.recommendations = filtered_recommendations

        passed = not any(issue.severity == "error" for issue in issues)
        summary = "All claims and recommendations reference persisted support." if passed else (f"Verifier downgraded {len(downgraded_claim_ids)} claim(s) and dropped {len(dropped_recommendation_ids)} recommendation(s).")
        return VerifierResult(
            passed=passed,
            verified_at=datetime.now(),
            checked_claim_count=len(result.claims),
            checked_evidence_count=len(known_evidence_ids),
            downgraded_claim_ids=downgraded_claim_ids,
            dropped_recommendation_ids=dropped_recommendation_ids,
            issues=issues,
            summary=summary,
            boundary_status=boundary_status,
            boundary_violation_claim_ids=boundary_violation_claim_ids,
            sample_size_downgraded_claim_ids=sample_size_downgraded_claim_ids,
        )


class _BoundaryCheckResult:
    __slots__ = ("violation", "limited", "issue")

    def __init__(self, *, violation: bool = False, limited: bool = False, issue: VerifierIssue | None = None) -> None:
        self.violation = violation
        self.limited = limited
        self.issue = issue  # type: ignore[assignment]


_BOUNDARY_OK = _BoundaryCheckResult()


def _check_claim_boundary(claim_id: str, boundary_time: datetime | None, evidence_items: list[EvidenceItem]) -> _BoundaryCheckResult:
    if boundary_time is None:
        return _BOUNDARY_OK

    has_any_timing = False
    violating_ids: list[str] = []

    for item in evidence_items:
        timestamps = [item.observed_at, item.effective_start, item.effective_end]
        item_has_timing = any(ts is not None for ts in timestamps)
        if item_has_timing:
            has_any_timing = True
        for ts in timestamps:
            if ts is not None and ts > boundary_time:
                violating_ids.append(item.evidence_id)
                break

    if violating_ids:
        return _BoundaryCheckResult(
            violation=True,
            issue=VerifierIssue(
                code="boundary_violation",
                message="Evidence timestamps fall after claim boundary time.",
                severity="error",
                claim_id=claim_id,
                evidence_ids=violating_ids,
            ),
        )

    if not has_any_timing:
        return _BoundaryCheckResult(
            limited=True,
            issue=VerifierIssue(
                code="boundary_timing_missing",
                message="Referenced evidence has no timing metadata; boundary check is incomplete.",
                severity="warning",
                claim_id=claim_id,
            ),
        )

    return _BOUNDARY_OK


class _SampleSizeCheckResult:
    __slots__ = ("downgraded", "issue")

    def __init__(self, *, downgraded: bool = False, issue: VerifierIssue | None = None) -> None:
        self.downgraded = downgraded
        self.issue = issue  # type: ignore[assignment]


_SAMPLE_OK = _SampleSizeCheckResult()


def _check_sample_size(claim_id: str, sample_size: int | None) -> _SampleSizeCheckResult:
    if sample_size is not None and sample_size >= MIN_SUPPORTED_CLAIM_SAMPLE_SIZE:
        return _SAMPLE_OK

    return _SampleSizeCheckResult(
        downgraded=True,
        issue=VerifierIssue(
            code="sample_size_below_threshold",
            message=f"Claim sample size ({sample_size}) is below the minimum ({MIN_SUPPORTED_CLAIM_SAMPLE_SIZE}) for supported status.",
            severity="warning",
            claim_id=claim_id,
        ),
    )


def _merge_boundary_status(current: str, incoming: str) -> str:
    if current == "failed" or incoming == "failed":
        return "failed"
    if current == "limited" or incoming == "limited":
        return "limited"
    return "passed"
