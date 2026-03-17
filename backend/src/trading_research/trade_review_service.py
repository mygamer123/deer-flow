from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time

from src.community.finance.decision_review_service import DecisionReviewService
from src.community.finance.log_sources import get_default_log_source
from src.community.finance.models import QualityTier, TradeReview

from .evidence_service import EvidenceService
from .models import (
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceSourceType,
    Finding,
    Recommendation,
    RecommendationPriority,
    ReviewResult,
    WorkflowKind,
)
from .verifier_service import VerifierService


class TradeReviewService:
    def __init__(
        self,
        *,
        polygon_api_key: str | None = None,
        evidence_service: EvidenceService | None = None,
        verifier_service: VerifierService | None = None,
    ) -> None:
        self._polygon_api_key: str | None = polygon_api_key or os.getenv("POLYGON_API_KEY")
        self._evidence_service: EvidenceService = evidence_service or EvidenceService()
        self._verifier_service: VerifierService = verifier_service or VerifierService(self._evidence_service)

    def review_trade(
        self,
        *,
        symbol: str,
        trading_date: date,
        log_source: str | None = None,
    ) -> ReviewResult:
        effective_log_source = log_source or get_default_log_source()
        review = DecisionReviewService(
            polygon_api_key=self._polygon_api_key,
            log_source=effective_log_source,
        ).review_single_trade(symbol, trading_date)
        if review is None:
            raise ValueError(f"No trade found for {symbol.upper()} on {trading_date.isoformat()}.")

        evidence_items, evidence_by_key = self._build_evidence(review, effective_log_source)
        persisted_evidence = self._evidence_service.register_many(evidence_items)
        for key, item in zip(evidence_by_key.keys(), persisted_evidence, strict=False):
            evidence_by_key[key] = item.evidence_id

        result_boundary = _trade_as_of(review)
        claims = self._build_claims(review, evidence_by_key, result_boundary)

        result = ReviewResult(
            result_id=f"trade_review_{review.trade.symbol.lower()}_{trading_date.isoformat()}_{effective_log_source}",
            workflow=WorkflowKind.TRADE_REVIEW,
            title=f"Trade Review: {review.trade.symbol} on {trading_date.isoformat()}",
            subject=f"{review.trade.symbol} {trading_date.isoformat()}",
            as_of=_trade_as_of(review),
            symbol=review.trade.symbol,
            trading_date=trading_date,
            log_source=effective_log_source,
            findings=self._build_findings(review, evidence_by_key),
            claims=claims,
            recommendations=self._build_recommendations(review, claims),
            evidence_ids=[item.evidence_id for item in persisted_evidence],
            limitations=self._build_limitations(review),
            metadata={
                "quality_tier": review.quality_tier.name,
                "overall_verdict": review.overall_verdict.value,
                "pattern": review.pattern.value,
                "outcome": review.trade.outcome.value,
                "total_iterations": review.total_iterations,
            },
            boundary_time=result_boundary,
        )
        result.verifier = self._verifier_service.verify_result(result)
        return result

    def _build_evidence(
        self,
        review: TradeReview,
        log_source: str,
    ) -> tuple[list[EvidenceItem], dict[str, str]]:
        module_payloads = _collect_module_payloads(review)
        evidence_items: list[EvidenceItem] = []
        evidence_keys: dict[str, str] = {}

        signal = review.trade.signal
        signal_ts = signal.timestamp if signal is not None else None
        signal_content = (
            f"Signal type={signal.signal_type.value}, score={signal.score:.2f}, pwin={signal.pwin:.1f}, bars={signal.bars}, ret5m={signal.ret5m_predicted:.2f}, dd={signal.dd_predicted:.2f}, tvr={signal.tvr:.2f}M"
            if signal is not None
            else "No signal was recorded for this trade."
        )
        evidence_items.append(
            EvidenceItem(
                evidence_type="trade_snapshot",
                title=f"Trade snapshot for {review.trade.symbol}",
                content=signal_content,
                source_type=EvidenceSourceType.TRADE_METRIC,
                source_ref=f"trade:{review.trade.symbol}:{review.trade.trading_date.isoformat()}:{log_source}",
                provenance={
                    "symbol": review.trade.symbol,
                    "trading_date": review.trade.trading_date.isoformat(),
                    "log_source": log_source,
                    "record_type": "trade_snapshot",
                },
                as_of=_trade_as_of(review),
                sample_size=1,
                observed_at=signal_ts,
                effective_start=signal_ts,
                effective_end=signal_ts,
            )
        )
        evidence_keys["trade_snapshot"] = ""

        review_as_of = _trade_as_of(review)
        evidence_items.append(
            EvidenceItem(
                evidence_type="trade_review_summary",
                title=f"Overall review summary for {review.trade.symbol}",
                content=(f"Quality={review.quality_tier.name}, verdict={review.overall_verdict.value}, pattern={review.pattern.value}, iterations={review.total_iterations}"),
                source_type=EvidenceSourceType.REVIEW_SUMMARY,
                source_ref=f"trade_review:{review.trade.symbol}:{review.trade.trading_date.isoformat()}:summary",
                provenance={
                    "symbol": review.trade.symbol,
                    "trading_date": review.trade.trading_date.isoformat(),
                    "record_type": "review_summary",
                },
                as_of=review_as_of,
                sample_size=1,
                observed_at=review_as_of,
                effective_start=review_as_of,
                effective_end=review_as_of,
            )
        )
        evidence_keys["overall_summary"] = ""

        for module_name, payload in module_payloads.items():
            if not payload.observations and not payload.metrics:
                continue
            module_boundary = _module_boundary_time(review, module_name)
            evidence_items.append(
                EvidenceItem(
                    evidence_type=f"review_lens:{module_name}",
                    title=f"{module_name.title()} evidence for {review.trade.symbol}",
                    content=_module_content(module_name, payload),
                    source_type=EvidenceSourceType.REVIEW_LENS,
                    source_ref=f"trade_review:{review.trade.symbol}:{review.trade.trading_date.isoformat()}:{module_name}",
                    provenance={
                        "symbol": review.trade.symbol,
                        "trading_date": review.trade.trading_date.isoformat(),
                        "module": module_name,
                        "record_type": "review_lens",
                    },
                    as_of=_trade_as_of(review),
                    confidence=payload.confidence,
                    sample_size=payload.findings_count,
                    observed_at=module_boundary,
                    effective_start=module_boundary,
                    effective_end=module_boundary,
                )
            )
            evidence_keys[module_name] = ""

        return evidence_items, evidence_keys

    def _build_findings(self, review: TradeReview, evidence_by_key: dict[str, str]) -> list[Finding]:
        findings = [
            Finding(
                finding_id=f"finding_overall_{review.trade.symbol.lower()}",
                title="Overall trade verdict",
                detail=(f"The review classified this trade as `{review.overall_verdict.value}` with quality tier `{review.quality_tier.name}` after {review.total_iterations} iterations."),
                evidence_ids=_evidence_ids(evidence_by_key, "trade_snapshot", "overall_summary"),
                confidence=_quality_confidence(review.quality_tier),
                sample_size=1,
                as_of=_trade_as_of(review),
            )
        ]

        if review.selection is not None:
            findings.append(
                Finding(
                    finding_id=f"finding_selection_{review.trade.symbol.lower()}",
                    title="Selection review",
                    detail=" ".join(review.selection.reasons) or "Selection review did not provide explicit reasons.",
                    evidence_ids=_evidence_ids(evidence_by_key, "selection"),
                    confidence=review.selection.confidence,
                    sample_size=1,
                    as_of=_trade_as_of(review),
                )
            )

        if review.entry is not None:
            findings.append(
                Finding(
                    finding_id=f"finding_entry_{review.trade.symbol.lower()}",
                    title="Entry review",
                    detail=" ".join(review.entry.reasons) or "Entry review did not provide explicit reasons.",
                    evidence_ids=_evidence_ids(evidence_by_key, "entry"),
                    confidence=_module_confidence(review, "entry"),
                    sample_size=1,
                    as_of=_trade_as_of(review),
                )
            )

        if review.exit is not None:
            findings.append(
                Finding(
                    finding_id=f"finding_exit_{review.trade.symbol.lower()}",
                    title="Exit review",
                    detail=" ".join(review.exit.reasons) or "Exit review did not provide explicit reasons.",
                    evidence_ids=_evidence_ids(evidence_by_key, "exit"),
                    confidence=_module_confidence(review, "exit"),
                    sample_size=1,
                    as_of=_trade_as_of(review),
                )
            )

        if review.failure is not None:
            findings.append(
                Finding(
                    finding_id=f"finding_failure_{review.trade.symbol.lower()}",
                    title="Failure review",
                    detail=" ".join(review.failure.reasons) or "Failure review did not provide explicit reasons.",
                    evidence_ids=_evidence_ids(evidence_by_key, "failure"),
                    confidence=_module_confidence(review, "failure"),
                    sample_size=1,
                    as_of=_trade_as_of(review),
                )
            )

        return findings

    def _build_claims(self, review: TradeReview, evidence_by_key: dict[str, str], result_boundary: datetime) -> list[Claim]:
        signal_ts = review.trade.signal.timestamp if review.trade.signal is not None else None
        entry_ts = review.trade.entry.timestamp if review.trade.entry is not None else None
        exit_ts = review.trade.exit.timestamp if review.trade.exit is not None else None

        overall_boundary = result_boundary
        selection_boundary = signal_ts or entry_ts or result_boundary
        entry_boundary = entry_ts or result_boundary
        exit_boundary = exit_ts or result_boundary
        failure_boundary = result_boundary

        claims = [
            Claim(
                claim_id=f"claim_overall_{review.trade.symbol.lower()}",
                statement=f"The overall review verdict for this trade is `{review.overall_verdict.value}`.",
                status=ClaimStatus.SUPPORTED,
                evidence_ids=_evidence_ids(evidence_by_key, "trade_snapshot", "overall_summary"),
                confidence=_quality_confidence(review.quality_tier),
                sample_size=1,
                as_of=_trade_as_of(review),
                boundary_time=overall_boundary,
            )
        ]

        if review.selection is not None:
            claims.append(
                Claim(
                    claim_id=f"claim_selection_{review.trade.symbol.lower()}",
                    statement=("Selection evidence indicates this trade should have been taken." if review.selection.should_trade else "Selection evidence indicates this trade should have been skipped."),
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=_evidence_ids(evidence_by_key, "selection"),
                    confidence=review.selection.confidence,
                    sample_size=1,
                    as_of=_trade_as_of(review),
                    boundary_time=selection_boundary,
                )
            )

        if review.entry is not None:
            claims.append(
                Claim(
                    claim_id=f"claim_entry_{review.trade.symbol.lower()}",
                    statement=("Entry timing was suboptimal and waiting would likely have improved the fill." if review.entry.should_have_waited else "Entry timing was acceptable relative to the review logic."),
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=_evidence_ids(evidence_by_key, "entry"),
                    confidence=_module_confidence(review, "entry"),
                    sample_size=1,
                    as_of=_trade_as_of(review),
                    boundary_time=entry_boundary,
                )
            )

        if review.exit is not None:
            claims.append(
                Claim(
                    claim_id=f"claim_exit_{review.trade.symbol.lower()}",
                    statement=f"The review favors `{review.exit.recommended_policy.value}` as the better exit policy for this trade.",
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=_evidence_ids(evidence_by_key, "exit"),
                    confidence=_module_confidence(review, "exit"),
                    sample_size=1,
                    as_of=_trade_as_of(review),
                    boundary_time=exit_boundary,
                )
            )

        if review.failure is not None:
            claims.append(
                Claim(
                    claim_id=f"claim_failure_{review.trade.symbol.lower()}",
                    statement=("Failure analysis indicates the position should be exited now." if review.failure.should_exit_now else "Failure analysis indicates the position can be monitored rather than exited immediately."),
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=_evidence_ids(evidence_by_key, "failure"),
                    confidence=_module_confidence(review, "failure"),
                    sample_size=1,
                    as_of=_trade_as_of(review),
                    boundary_time=failure_boundary,
                )
            )

        return claims

    def _build_recommendations(
        self,
        review: TradeReview,
        claims: list[Claim],
    ) -> list[Recommendation]:
        recommendations: list[Recommendation] = []
        claims_by_id = {claim.claim_id: claim for claim in claims}
        selection_claim = claims_by_id.get(f"claim_selection_{review.trade.symbol.lower()}")
        entry_claim = claims_by_id.get(f"claim_entry_{review.trade.symbol.lower()}")
        exit_claim = claims_by_id.get(f"claim_exit_{review.trade.symbol.lower()}")
        failure_claim = claims_by_id.get(f"claim_failure_{review.trade.symbol.lower()}")
        overall_claim = claims_by_id.get(f"claim_overall_{review.trade.symbol.lower()}")

        if review.selection is not None and not review.selection.should_trade and selection_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"rec_selection_{review.trade.symbol.lower()}",
                    summary="Tighten selection filters for similar setups",
                    action="Do not take similar setups until the selection criteria that failed here are explicitly satisfied.",
                    supported_by_claim_ids=[selection_claim.claim_id],
                    evidence_ids=list(selection_claim.evidence_ids),
                    confidence=selection_claim.confidence,
                    priority=RecommendationPriority.HIGH,
                    as_of=_trade_as_of(review),
                )
            )

        if review.entry is not None and review.entry.should_have_waited and entry_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"rec_entry_{review.trade.symbol.lower()}",
                    summary="Wait for a better entry",
                    action="Require a pullback, better VWAP relationship, or improved fill before entering comparable trades.",
                    supported_by_claim_ids=[entry_claim.claim_id],
                    evidence_ids=list(entry_claim.evidence_ids),
                    confidence=entry_claim.confidence,
                    priority=RecommendationPriority.HIGH,
                    as_of=_trade_as_of(review),
                )
            )

        if review.exit is not None and exit_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"rec_exit_{review.trade.symbol.lower()}",
                    summary="Test the recommended exit policy on similar trades",
                    action=f"Use `{review.exit.recommended_policy.value}` as the first exit policy to test against your current fixed-take-profit logic.",
                    supported_by_claim_ids=[exit_claim.claim_id],
                    evidence_ids=list(exit_claim.evidence_ids),
                    confidence=exit_claim.confidence,
                    priority=RecommendationPriority.MEDIUM,
                    as_of=_trade_as_of(review),
                )
            )

        if review.failure is not None and review.failure.should_exit_now and failure_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"rec_failure_{review.trade.symbol.lower()}",
                    summary="Exit the stranded position",
                    action="Treat the current price as the practical exit reference instead of waiting for a full recovery to target.",
                    supported_by_claim_ids=[failure_claim.claim_id],
                    evidence_ids=list(failure_claim.evidence_ids),
                    confidence=failure_claim.confidence,
                    priority=RecommendationPriority.HIGH,
                    as_of=_trade_as_of(review),
                )
            )

        if not recommendations and overall_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"rec_hold_{review.trade.symbol.lower()}",
                    summary="Use this trade as a baseline example",
                    action="Keep the current playbook for this exact setup, but only treat the conclusion as trade-specific unless additional samples confirm it.",
                    supported_by_claim_ids=[overall_claim.claim_id],
                    evidence_ids=list(overall_claim.evidence_ids),
                    confidence=overall_claim.confidence,
                    priority=RecommendationPriority.LOW,
                    limitations=["Single-trade recommendation"],
                    as_of=_trade_as_of(review),
                )
            )

        return recommendations

    def _build_limitations(self, review: TradeReview) -> list[str]:
        limitations: list[str] = []
        seen: set[str] = set()
        for iteration_result in review.iteration_results:
            for gap in iteration_result.new_gaps:
                if gap.description not in seen:
                    limitations.append(gap.description)
                    seen.add(gap.description)
        limitations.append("Verifier only checks evidence linkage and persistence. It does not perform semantic fact-checking.")
        limitations.append("This result covers a single reviewed trade and should not be treated as a general rule without more samples.")
        return limitations


@dataclass
class ModulePayload:
    observations: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)
    findings_count: int = 0
    confidence_total: float = 0.0
    confidence: float | None = None


def _collect_module_payloads(review: TradeReview) -> dict[str, ModulePayload]:
    payloads: dict[str, ModulePayload] = {}
    for iteration_result in review.iteration_results:
        for module_name, finding in iteration_result.findings.items():
            payload = payloads.setdefault(module_name, ModulePayload())
            payload.findings_count += 1
            payload.confidence_total += finding.confidence
            observations = payload.observations
            for observation in finding.observations:
                if observation not in observations:
                    observations.append(observation)
            payload.metrics.update(finding.metrics)

    for payload in payloads.values():
        payload.confidence = payload.confidence_total / payload.findings_count if payload.findings_count else None
    return payloads


def _module_content(module_name: str, payload: ModulePayload) -> str:
    observations = payload.observations
    metrics = payload.metrics
    parts: list[str] = [f"Module: {module_name}"]
    if observations:
        parts.append("Observations: " + " | ".join(str(observation) for observation in observations))
    if metrics:
        metric_text = ", ".join(f"{key}={value}" for key, value in sorted(metrics.items()))
        parts.append("Metrics: " + metric_text)
    return "\n".join(parts)


def _trade_as_of(review: TradeReview) -> datetime:
    if review.trade.exit is not None:
        return review.trade.exit.timestamp
    if review.trade.entry is not None:
        return review.trade.entry.timestamp
    if review.trade.signal is not None:
        return review.trade.signal.timestamp
    return datetime.combine(review.trade.trading_date, time.min)


def _module_boundary_time(review: TradeReview, module_name: str) -> datetime:
    signal_ts = review.trade.signal.timestamp if review.trade.signal is not None else None
    entry_ts = review.trade.entry.timestamp if review.trade.entry is not None else None
    exit_ts = review.trade.exit.timestamp if review.trade.exit is not None else None
    fallback = _trade_as_of(review)

    if module_name == "selection":
        return signal_ts or entry_ts or fallback
    if module_name == "entry":
        return entry_ts or fallback
    if module_name == "exit":
        return exit_ts or fallback
    return fallback


def _quality_confidence(quality_tier: QualityTier) -> float:
    mapping = {
        QualityTier.EXCELLENT: 0.9,
        QualityTier.GOOD: 0.8,
        QualityTier.MARGINAL: 0.6,
        QualityTier.BAD: 0.45,
        QualityTier.TERRIBLE: 0.3,
    }
    return mapping[quality_tier]


def _module_confidence(review: TradeReview, module_name: str) -> float | None:
    payload = _collect_module_payloads(review).get(module_name)
    if payload is None:
        return None
    return payload.confidence


def _evidence_ids(evidence_by_key: dict[str, str], *keys: str) -> list[str]:
    return [evidence_by_key[key] for key in keys if evidence_by_key.get(key)]
