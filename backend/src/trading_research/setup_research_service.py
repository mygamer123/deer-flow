from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from src.community.research.models import Evidence as RawEvidence
from src.community.research.models import ResearchReport, VerificationStatus
from src.community.research.models import SourceType as RawSourceType
from src.community.research.research_service import ResearchService

from .evidence_service import EvidenceService
from .models import (
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceSourceType,
    Finding,
    Recommendation,
    RecommendationPriority,
    SetupResearchResult,
    SetupType,
    WorkflowKind,
)
from .verifier_service import VerifierService


@dataclass(frozen=True)
class SetupResearchRequest:
    symbol: str
    setup_type: SetupType = SetupType.INTRADAY_BREAKOUT
    trade_date: date | None = None


class SetupResearchService:
    def __init__(
        self,
        *,
        research_service: ResearchService | None = None,
        evidence_service: EvidenceService | None = None,
        verifier_service: VerifierService | None = None,
    ) -> None:
        self._research_service: ResearchService = research_service or ResearchService()
        self._evidence_service: EvidenceService = evidence_service or EvidenceService()
        self._verifier_service: VerifierService = verifier_service or VerifierService(self._evidence_service)

    def research_setup(
        self,
        *,
        symbol: str,
        setup_type: SetupType | str = SetupType.INTRADAY_BREAKOUT,
        trade_date: date | None = None,
    ) -> SetupResearchResult:
        normalized_setup_type = _normalize_setup_type(setup_type)
        request = SetupResearchRequest(symbol=symbol.upper(), setup_type=normalized_setup_type, trade_date=trade_date)
        topic = _build_topic(request)
        report = self._research_service.research_topic(topic, depth=2)

        result_boundary = _derive_boundary_time(request, report)

        evidence_items = self._build_evidence_items(request, report.sources, result_boundary)
        persisted_evidence = self._evidence_service.register_many(evidence_items)
        evidence_lookup = {_evidence_key(item.source_type, item.source_ref, item.content): item.evidence_id for item in persisted_evidence}

        claims = self._build_claims(request, report, evidence_lookup, result_boundary)
        result = SetupResearchResult(
            result_id=f"setup_research_{request.symbol.lower()}_{request.setup_type.value}",
            workflow=WorkflowKind.SETUP_RESEARCH,
            title=f"Setup Research: {request.symbol} {request.setup_type.value}",
            subject=f"{request.symbol} {request.setup_type.value}",
            topic=topic,
            symbol=request.symbol,
            setup_type=request.setup_type,
            trade_date=request.trade_date,
            as_of=report.created_at,
            search_queries=list(report.search_queries),
            pages_fetched=report.pages_fetched,
            findings=self._build_findings(request, report, [item.evidence_id for item in persisted_evidence]),
            claims=claims,
            recommendations=self._build_recommendations(request, claims),
            evidence_ids=[item.evidence_id for item in persisted_evidence],
            limitations=self._build_limitations(report),
            metadata={
                "source_count": len(report.sources),
                "claim_count": len(report.claims),
                "query_count": len(report.search_queries),
                "request_template": request.setup_type.value,
            },
            boundary_time=result_boundary,
        )
        result.verifier = self._verifier_service.verify_result(result)
        return result

    def _build_evidence_items(
        self,
        request: SetupResearchRequest,
        sources: list[RawEvidence],
        result_boundary: datetime,
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for source in sources:
            source_type = EvidenceSourceType.WEB_FETCH if source.source_type == RawSourceType.WEB_FETCH else EvidenceSourceType.WEB_SOURCE
            evidence_time = source.fetched_at
            if evidence_time is not None and evidence_time > result_boundary:
                evidence_time = result_boundary
            items.append(
                EvidenceItem(
                    evidence_type=f"setup_source:{request.setup_type.value}",
                    title=source.source_title or source.source_url or "Research source",
                    content=source.snippet,
                    source_type=source_type,
                    source_ref=source.source_url,
                    provenance={
                        "symbol": request.symbol,
                        "setup_type": request.setup_type.value,
                        "trade_date": request.trade_date.isoformat() if request.trade_date else "",
                        "source_kind": source.source_type.value,
                    },
                    as_of=evidence_time,
                    confidence=source.relevance or None,
                    sample_size=1,
                    observed_at=evidence_time,
                    effective_start=evidence_time,
                    effective_end=evidence_time,
                )
            )
        return items

    def _build_findings(
        self,
        request: SetupResearchRequest,
        report: ResearchReport,
        evidence_ids: list[str],
    ) -> list[Finding]:
        findings = [
            Finding(
                finding_id=f"finding_coverage_{request.symbol.lower()}_{request.setup_type.value}",
                title="Setup research coverage",
                detail=(f"The workflow gathered {len(report.sources)} source excerpts for the `{request.setup_type.value}` template on {request.symbol} across {len(report.search_queries)} fixed queries."),
                evidence_ids=evidence_ids,
                confidence=0.6 if report.sources else 0.0,
                sample_size=len(report.sources),
                limitations=["Coverage depends on Tavily search results and fetched page quality."],
                as_of=report.created_at,
            )
        ]
        if report.summary:
            findings.append(
                Finding(
                    finding_id=f"finding_summary_{request.symbol.lower()}_{request.setup_type.value}",
                    title="Setup summary",
                    detail=report.summary,
                    evidence_ids=evidence_ids[:3],
                    confidence=0.5 if report.sources else 0.0,
                    sample_size=len(report.sources),
                    limitations=["Summary comes from heuristic source aggregation."],
                    as_of=report.created_at,
                )
            )
        return findings

    def _build_claims(
        self,
        request: SetupResearchRequest,
        report: ResearchReport,
        evidence_lookup: dict[tuple[EvidenceSourceType, str, str], str],
        result_boundary: datetime,
    ) -> list[Claim]:
        claims: list[Claim] = []
        for index, raw_claim in enumerate(report.claims, start=1):
            claim_evidence_ids: list[str] = []
            for source in raw_claim.supporting_evidence:
                evidence_id = evidence_lookup.get(
                    _evidence_key(
                        EvidenceSourceType.WEB_FETCH if source.source_type == RawSourceType.WEB_FETCH else EvidenceSourceType.WEB_SOURCE,
                        source.source_url,
                        source.snippet,
                    )
                )
                if evidence_id is not None:
                    claim_evidence_ids.append(evidence_id)

            claims.append(
                Claim(
                    claim_id=f"claim_setup_{request.symbol.lower()}_{request.setup_type.value}_{index}",
                    statement=raw_claim.statement,
                    status=_map_claim_status(raw_claim.status),
                    evidence_ids=claim_evidence_ids,
                    confidence=raw_claim.confidence or (0.4 if claim_evidence_ids else 0.0),
                    sample_size=len(claim_evidence_ids) or None,
                    limitations=[
                        f"This claim is constrained to the `{request.setup_type.value}` setup template.",
                        "Verifier checks evidence linkage only, not semantic truth.",
                    ],
                    as_of=report.created_at,
                    boundary_time=result_boundary,
                )
            )
        return claims

    def _build_recommendations(
        self,
        request: SetupResearchRequest,
        claims: list[Claim],
    ) -> list[Recommendation]:
        if not claims:
            return []

        strongest_claim = max(claims, key=lambda claim: claim.confidence or 0.0)
        return [
            Recommendation(
                recommendation_id=f"rec_{request.symbol.lower()}_{request.setup_type.value}_1",
                summary="Use the strongest verified research claim as the next manual review anchor",
                action=(f"Review the highest-confidence claim for {request.symbol} under the `{request.setup_type.value}` template before treating this setup as actionable."),
                supported_by_claim_ids=[strongest_claim.claim_id],
                evidence_ids=list(strongest_claim.evidence_ids),
                confidence=strongest_claim.confidence,
                priority=RecommendationPriority.MEDIUM,
                limitations=["This recommendation is a research follow-up, not an execution signal."],
                as_of=strongest_claim.as_of,
            )
        ]

    def _build_limitations(self, report: ResearchReport) -> list[str]:
        limitations = [
            "Only the `intraday_breakout` setup template is supported in P0.",
            "Verifier checks evidence linkage and recommendation support, not semantic truth.",
            "Research coverage depends on Tavily search and fetch results.",
        ]
        if report.pages_fetched == 0:
            limitations.append("No full pages were fetched, so the output relies only on search-result snippets.")
        return limitations


def _normalize_setup_type(value: SetupType | str) -> SetupType:
    if isinstance(value, SetupType):
        return value
    try:
        return SetupType(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported setup_type '{value}'. Supported values: {[item.value for item in SetupType]}") from exc


def _build_topic(request: SetupResearchRequest) -> str:
    trade_date_part = f" on {request.trade_date.isoformat()}" if request.trade_date else ""
    return f"{request.symbol} intraday breakout setup research{trade_date_part}; focus on catalysts, breakout quality, relative volume, and failure risks"


def _map_claim_status(status: VerificationStatus) -> ClaimStatus:
    if status == VerificationStatus.SUPPORTED:
        return ClaimStatus.SUPPORTED
    if status == VerificationStatus.CONTRADICTED:
        return ClaimStatus.UNSUPPORTED
    return ClaimStatus.OBSERVATION


def _evidence_key(
    source_type: EvidenceSourceType,
    source_ref: str,
    content: str,
) -> tuple[EvidenceSourceType, str, str]:
    normalized_ref = " ".join(source_ref.split())
    normalized_content = " ".join(content.split())
    return (source_type, normalized_ref, normalized_content)


def _derive_boundary_time(request: SetupResearchRequest, report: ResearchReport) -> datetime:
    if request.trade_date is not None:
        return datetime.combine(request.trade_date, time(23, 59, 59))
    return report.created_at
