from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from .evidence_service import EvidenceService
from .models import (
    AggregatedReviewResult,
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceSourceType,
    Finding,
    Recommendation,
    RecommendationPriority,
    WorkflowKind,
)
from .store import list_saved_results, load_saved_result
from .verifier_service import VerifierService


@dataclass
class AggregatedTradeReviewRequest:
    trade_result_ids: list[str] | None = None
    symbol: str | None = None
    pattern: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    max_trades: int | None = None
    log_source: str | None = None
    aggregation_mode: str = "by_pattern"  # "by_pattern" or "by_symbol_pattern"


class AggregateReviewService:
    def __init__(
        self,
        *,
        evidence_service: EvidenceService | None = None,
        verifier_service: VerifierService | None = None,
    ) -> None:
        self._evidence_service = evidence_service or EvidenceService()
        self._verifier_service = verifier_service or VerifierService(self._evidence_service)

    def aggregate(self, request: AggregatedTradeReviewRequest) -> AggregatedReviewResult:
        reviews = self._load_reviews(request)
        if not reviews:
            return self._empty_result(request)

        seen_ids: set[str] = set()
        unique_reviews: list[_LoadedReview] = []
        for review in reviews:
            if review.result_id not in seen_ids:
                seen_ids.add(review.result_id)
                unique_reviews.append(review)
        reviews = unique_reviews

        if request.max_trades is not None and len(reviews) > request.max_trades:
            reviews = reviews[: request.max_trades]

        grouping_key = self._compute_grouping_key(reviews, request)
        cohort_stats = self._compute_cohort_stats(reviews)
        now = datetime.now()

        trading_dates = [r.trading_date for r in reviews if r.trading_date is not None]
        date_range_start = min(trading_dates) if trading_dates else None
        date_range_end = max(trading_dates) if trading_dates else None

        boundary_times = [r.boundary_time for r in reviews if r.boundary_time is not None]
        result_boundary = max(boundary_times) if boundary_times else now

        contributing_result_ids = [r.result_id for r in reviews]
        trade_count = len(reviews)

        evidence_items = self._build_evidence(reviews, grouping_key, cohort_stats, now, result_boundary)
        persisted_evidence = self._evidence_service.register_many(evidence_items)
        evidence_ids = [item.evidence_id for item in persisted_evidence]
        evidence_ref_map: dict[str, str] = {}
        for raw_item, persisted_item in zip(evidence_items, persisted_evidence, strict=False):
            evidence_ref_map[raw_item.source_ref] = persisted_item.evidence_id

        findings = self._build_findings(reviews, grouping_key, cohort_stats, evidence_ids, now)
        claims = self._build_claims(reviews, grouping_key, evidence_ids, evidence_ref_map, result_boundary, now)
        recommendations = self._build_recommendations(grouping_key, claims, now)

        symbols = {r.symbol for r in reviews if r.symbol}
        result_symbol = symbols.pop() if len(symbols) == 1 else ""

        result = AggregatedReviewResult(
            result_id=f"agg_trade_review_{grouping_key}_{date_range_start or 'none'}_{date_range_end or 'none'}",
            workflow=WorkflowKind.AGGREGATE_TRADE_REVIEW,
            title=f"Aggregated Trade Review: {grouping_key} ({trade_count} trades)",
            subject=f"aggregate:{grouping_key}",
            as_of=now,
            findings=findings,
            claims=claims,
            recommendations=recommendations,
            evidence_ids=evidence_ids,
            limitations=self._build_limitations(reviews, grouping_key),
            boundary_time=result_boundary,
            trade_count=trade_count,
            contributing_result_ids=contributing_result_ids,
            grouping_key=grouping_key,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            symbol=result_symbol,
            cohort_stats=cohort_stats,
        )
        result.verifier = self._verifier_service.verify_result(result)
        return result

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_reviews(self, request: AggregatedTradeReviewRequest) -> list[_LoadedReview]:
        if request.trade_result_ids is not None:
            return self._load_by_ids(request.trade_result_ids)
        return self._load_from_store(request)

    def _load_by_ids(self, result_ids: list[str]) -> list[_LoadedReview]:
        reviews: list[_LoadedReview] = []
        for filename in list_saved_results():
            data = load_saved_result(filename)
            if data is None:
                continue
            if data.get("workflow") != "trade_review":
                continue
            result_id = str(data.get("result_id", ""))
            if result_id in result_ids:
                loaded = _parse_loaded_review(data)
                if loaded is not None:
                    reviews.append(loaded)
        return reviews

    def _load_from_store(self, request: AggregatedTradeReviewRequest) -> list[_LoadedReview]:
        reviews: list[_LoadedReview] = []
        for filename in list_saved_results():
            data = load_saved_result(filename)
            if data is None:
                continue
            if data.get("workflow") != "trade_review":
                continue
            loaded = _parse_loaded_review(data)
            if loaded is None:
                continue
            if not _matches_filter(loaded, request):
                continue
            reviews.append(loaded)
        return reviews

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    def _compute_grouping_key(self, reviews: list[_LoadedReview], request: AggregatedTradeReviewRequest) -> str:
        if request.pattern:
            base_key = request.pattern
        else:
            patterns = Counter(r.pattern for r in reviews)
            base_key = patterns.most_common(1)[0][0] if patterns else "unclassified"

        if request.aggregation_mode == "by_symbol_pattern" and request.symbol:
            return f"{request.symbol.upper()}:{base_key}"
        return base_key

    # ------------------------------------------------------------------
    # Cohort stats
    # ------------------------------------------------------------------

    def _compute_cohort_stats(self, reviews: list[_LoadedReview]) -> dict[str, object]:
        verdict_counts: Counter[str] = Counter()
        pattern_counts: Counter[str] = Counter()
        quality_counts: Counter[str] = Counter()
        outcome_counts: Counter[str] = Counter()

        for r in reviews:
            verdict_counts[r.verdict] += 1
            pattern_counts[r.pattern] += 1
            quality_counts[r.quality_tier] += 1
            outcome_counts[r.outcome] += 1

        return {
            "trade_count": len(reviews),
            "verdict_distribution": dict(verdict_counts),
            "pattern_distribution": dict(pattern_counts),
            "quality_distribution": dict(quality_counts),
            "outcome_distribution": dict(outcome_counts),
        }

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _build_evidence(
        self,
        reviews: list[_LoadedReview],
        grouping_key: str,
        cohort_stats: dict[str, object],
        now: datetime,
        evidence_boundary: datetime,
    ) -> list[EvidenceItem]:
        contributing_ids = [r.result_id for r in reviews]
        items: list[EvidenceItem] = []

        items.append(
            EvidenceItem(
                evidence_type="cohort_summary",
                title=f"Cohort summary for {grouping_key} ({len(reviews)} trades)",
                content=_format_cohort_content(cohort_stats),
                source_type=EvidenceSourceType.COHORT_SUMMARY,
                source_ref=f"aggregate:{grouping_key}:cohort_summary",
                provenance={
                    "contributing_result_ids": contributing_ids,
                    "grouping_key": grouping_key,
                    "record_type": "cohort_summary",
                },
                as_of=now,
                sample_size=len(reviews),
                observed_at=evidence_boundary,
                effective_start=evidence_boundary,
                effective_end=evidence_boundary,
            )
        )

        verdict_dist = cohort_stats.get("verdict_distribution", {})
        if isinstance(verdict_dist, dict) and verdict_dist:
            items.append(
                EvidenceItem(
                    evidence_type="aggregate_metric",
                    title=f"Verdict distribution for {grouping_key}",
                    content=_format_distribution("verdict", verdict_dist),
                    source_type=EvidenceSourceType.AGGREGATE_METRIC,
                    source_ref=f"aggregate:{grouping_key}:verdict_distribution",
                    provenance={
                        "contributing_result_ids": contributing_ids,
                        "grouping_key": grouping_key,
                        "record_type": "aggregate_metric",
                        "metric": "verdict_distribution",
                    },
                    as_of=now,
                    sample_size=len(reviews),
                    observed_at=evidence_boundary,
                    effective_start=evidence_boundary,
                    effective_end=evidence_boundary,
                )
            )

        for claim_type in ["selection", "entry", "exit"]:
            claim_data = self._collect_claim_type_data(reviews, claim_type)
            if not claim_data:
                continue
            items.append(
                EvidenceItem(
                    evidence_type="aggregate_metric",
                    title=f"Aggregate {claim_type} pattern for {grouping_key}",
                    content=_format_claim_type_evidence(claim_type, claim_data),
                    source_type=EvidenceSourceType.AGGREGATE_METRIC,
                    source_ref=f"aggregate:{grouping_key}:{claim_type}_pattern",
                    provenance={
                        "contributing_result_ids": contributing_ids,
                        "grouping_key": grouping_key,
                        "record_type": "aggregate_metric",
                        "metric": f"{claim_type}_pattern",
                    },
                    as_of=now,
                    sample_size=len(claim_data),
                    observed_at=evidence_boundary,
                    effective_start=evidence_boundary,
                    effective_end=evidence_boundary,
                )
            )

        return items

    def _collect_claim_type_data(self, reviews: list[_LoadedReview], claim_type: str) -> list[dict[str, object]]:
        data: list[dict[str, object]] = []
        for r in reviews:
            for claim in r.claims:
                claim_id = claim.get("claim_id", "")
                if isinstance(claim_id, str) and f"claim_{claim_type}_" in claim_id:
                    data.append(claim)
        return data

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def _build_findings(
        self,
        reviews: list[_LoadedReview],
        grouping_key: str,
        cohort_stats: dict[str, object],
        evidence_ids: list[str],
        now: datetime,
    ) -> list[Finding]:
        trade_count = len(reviews)
        findings: list[Finding] = []

        verdict_dist = cohort_stats.get("verdict_distribution", {})
        findings.append(
            Finding(
                finding_id=f"finding_cohort_{grouping_key}",
                title=f"Cohort overview for {grouping_key}",
                detail=f"Aggregated {trade_count} trade reviews grouped by `{grouping_key}`. Verdict distribution: {_format_dict_inline(verdict_dist)}.",
                evidence_ids=evidence_ids[:1],
                confidence=None,
                sample_size=trade_count,
                as_of=now,
            )
        )

        return findings

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def _build_claims(
        self,
        reviews: list[_LoadedReview],
        grouping_key: str,
        evidence_ids: list[str],
        evidence_ref_map: dict[str, str],
        result_boundary: datetime,
        now: datetime,
    ) -> list[Claim]:
        trade_count = len(reviews)
        claims: list[Claim] = []

        verdict_dist = self._compute_cohort_stats(reviews).get("verdict_distribution", {})
        if isinstance(verdict_dist, dict):
            good_count = 0
            for v in ["good_trade", "acceptable"]:
                val = verdict_dist.get(v)
                if isinstance(val, (int, float)):
                    good_count += int(val)
            total = 0
            for v in verdict_dist.values():
                if isinstance(v, (int, float)):
                    total += int(v)
            if total > 0:
                good_rate = good_count / total
                claims.append(
                    Claim(
                        claim_id=f"agg_claim_verdict_{grouping_key}",
                        statement=f"Across {trade_count} trades in `{grouping_key}`, {good_rate:.0%} received a good_trade or acceptable verdict.",
                        status=ClaimStatus.SUPPORTED,
                        evidence_ids=evidence_ids[:2],
                        confidence=min(0.9, good_rate),
                        sample_size=trade_count,
                        as_of=now,
                        boundary_time=result_boundary,
                    )
                )

        for claim_type in ["selection", "entry", "exit"]:
            claim_data = self._collect_claim_type_data(reviews, claim_type)
            if not claim_data:
                continue
            contributing_count = len(claim_data)
            expected_ref = f"aggregate:{grouping_key}:{claim_type}_pattern"
            type_evidence_ids = [evidence_ref_map[expected_ref]] if expected_ref in evidence_ref_map else []
            claim_evidence = type_evidence_ids or evidence_ids[:1]

            confidences: list[float] = []
            for c in claim_data:
                conf = c.get("confidence")
                if isinstance(conf, (int, float)):
                    confidences.append(float(conf))
            mean_confidence = sum(confidences) / len(confidences) if confidences else None

            statement = _build_aggregate_claim_statement(claim_type, claim_data, grouping_key, contributing_count)
            claims.append(
                Claim(
                    claim_id=f"agg_claim_{claim_type}_{grouping_key}",
                    statement=statement,
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=claim_evidence,
                    confidence=mean_confidence,
                    sample_size=contributing_count,
                    as_of=now,
                    boundary_time=result_boundary,
                )
            )

        return claims

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def _build_recommendations(
        self,
        grouping_key: str,
        claims: list[Claim],
        now: datetime,
    ) -> list[Recommendation]:
        recommendations: list[Recommendation] = []
        claims_by_id = {c.claim_id: c for c in claims}

        verdict_claim = claims_by_id.get(f"agg_claim_verdict_{grouping_key}")
        selection_claim = claims_by_id.get(f"agg_claim_selection_{grouping_key}")
        entry_claim = claims_by_id.get(f"agg_claim_entry_{grouping_key}")
        exit_claim = claims_by_id.get(f"agg_claim_exit_{grouping_key}")

        if selection_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"agg_rec_selection_{grouping_key}",
                    summary=f"Selection pattern for `{grouping_key}` setups",
                    action=f"Based on {selection_claim.sample_size} trades, review selection criteria consistency for `{grouping_key}` setups.",
                    supported_by_claim_ids=[selection_claim.claim_id],
                    evidence_ids=list(selection_claim.evidence_ids),
                    confidence=selection_claim.confidence,
                    priority=RecommendationPriority.MEDIUM,
                    as_of=now,
                )
            )

        if entry_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"agg_rec_entry_{grouping_key}",
                    summary=f"Entry quality pattern for `{grouping_key}` setups",
                    action=f"Based on {entry_claim.sample_size} trades, assess whether entry timing is consistently suboptimal for `{grouping_key}` setups.",
                    supported_by_claim_ids=[entry_claim.claim_id],
                    evidence_ids=list(entry_claim.evidence_ids),
                    confidence=entry_claim.confidence,
                    priority=RecommendationPriority.MEDIUM,
                    as_of=now,
                )
            )

        if exit_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"agg_rec_exit_{grouping_key}",
                    summary=f"Exit policy pattern for `{grouping_key}` setups",
                    action=f"Based on {exit_claim.sample_size} trades, evaluate the most frequently recommended exit policy for `{grouping_key}` setups.",
                    supported_by_claim_ids=[exit_claim.claim_id],
                    evidence_ids=list(exit_claim.evidence_ids),
                    confidence=exit_claim.confidence,
                    priority=RecommendationPriority.MEDIUM,
                    as_of=now,
                )
            )

        if not recommendations and verdict_claim is not None:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"agg_rec_verdict_{grouping_key}",
                    summary=f"Overall verdict pattern for `{grouping_key}` setups",
                    action=f"Based on {verdict_claim.sample_size} trades, the verdict distribution for `{grouping_key}` setups is informative for playbook decisions.",
                    supported_by_claim_ids=[verdict_claim.claim_id],
                    evidence_ids=list(verdict_claim.evidence_ids),
                    confidence=verdict_claim.confidence,
                    priority=RecommendationPriority.LOW,
                    as_of=now,
                )
            )

        return recommendations

    # ------------------------------------------------------------------
    # Limitations
    # ------------------------------------------------------------------

    def _build_limitations(self, reviews: list[_LoadedReview], grouping_key: str) -> list[str]:
        limitations = [
            f"Aggregation covers {len(reviews)} trade(s) grouped by `{grouping_key}`.",
            "Aggregate claims are derived from structured fields only, not from prose re-interpretation.",
            "Verifier only checks evidence linkage, boundary timing, and sample-size thresholds. It does not perform semantic fact-checking.",
        ]
        if len(reviews) < 3:
            limitations.append(f"Only {len(reviews)} trade(s) contributed. Recommendations require at least 3 contributing trades to survive the verifier.")
        return limitations

    # ------------------------------------------------------------------
    # Empty result
    # ------------------------------------------------------------------

    def _empty_result(self, request: AggregatedTradeReviewRequest) -> AggregatedReviewResult:
        now = datetime.now()
        grouping_key = request.pattern or "none"
        return AggregatedReviewResult(
            result_id=f"agg_trade_review_{grouping_key}_empty",
            workflow=WorkflowKind.AGGREGATE_TRADE_REVIEW,
            title=f"Aggregated Trade Review: {grouping_key} (0 trades)",
            subject=f"aggregate:{grouping_key}",
            as_of=now,
            limitations=["No matching trade reviews were found for the given filters."],
            trade_count=0,
            contributing_result_ids=[],
            grouping_key=grouping_key,
            cohort_stats={},
        )


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _LoadedReview:
    result_id: str
    symbol: str
    trading_date: date | None
    pattern: str
    verdict: str
    quality_tier: str
    outcome: str
    log_source: str | None
    claims: list[dict[str, object]]
    evidence_ids: list[str]
    boundary_time: datetime | None


def _parse_loaded_review(data: dict[str, object]) -> _LoadedReview | None:
    result_id = str(data.get("result_id", ""))
    if not result_id:
        return None
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    trading_date_raw = data.get("trading_date")
    trading_date: date | None = None
    if isinstance(trading_date_raw, str) and trading_date_raw:
        try:
            trading_date = date.fromisoformat(trading_date_raw)
        except ValueError:
            pass

    boundary_raw = data.get("boundary_time")
    boundary_time: datetime | None = None
    if isinstance(boundary_raw, str) and boundary_raw:
        try:
            boundary_time = datetime.fromisoformat(boundary_raw)
        except ValueError:
            pass

    raw_claims = data.get("claims", [])
    claims = raw_claims if isinstance(raw_claims, list) else []

    raw_evidence_ids = data.get("evidence_ids", [])
    evidence_ids = raw_evidence_ids if isinstance(raw_evidence_ids, list) else []

    return _LoadedReview(
        result_id=result_id,
        symbol=str(data.get("symbol", "")),
        trading_date=trading_date,
        pattern=str(metadata.get("pattern", "unclassified")),
        verdict=str(metadata.get("overall_verdict", "unknown")),
        quality_tier=str(metadata.get("quality_tier", "unknown")),
        outcome=str(metadata.get("outcome", "unknown")),
        log_source=str(data.get("log_source", "")) or None,
        claims=claims,
        evidence_ids=[str(eid) for eid in evidence_ids],
        boundary_time=boundary_time,
    )


def _matches_filter(review: _LoadedReview, request: AggregatedTradeReviewRequest) -> bool:
    if request.symbol and review.symbol.upper() != request.symbol.upper():
        return False
    if request.pattern and review.pattern != request.pattern:
        return False
    if request.log_source and review.log_source != request.log_source:
        return False
    if request.start_date and review.trading_date is not None and review.trading_date < request.start_date:
        return False
    if request.end_date and review.trading_date is not None and review.trading_date > request.end_date:
        return False
    return True


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_cohort_content(stats: dict[str, object]) -> str:
    parts: list[str] = [f"Trade count: {stats.get('trade_count', 0)}"]
    for key in ["verdict_distribution", "pattern_distribution", "quality_distribution", "outcome_distribution"]:
        dist = stats.get(key, {})
        if isinstance(dist, dict) and dist:
            parts.append(f"{key}: {_format_dict_inline(dist)}")
    return "\n".join(parts)


def _format_distribution(label: str, dist: dict[str, object]) -> str:
    return f"{label.title()} distribution: {_format_dict_inline(dist)}"


def _format_dict_inline(d: object) -> str:
    if not isinstance(d, dict):
        return str(d)
    return ", ".join(f"{k}={v}" for k, v in sorted(d.items()))


def _format_claim_type_evidence(claim_type: str, claim_data: list[dict[str, object]]) -> str:
    statements: list[str] = []
    for claim in claim_data:
        stmt = claim.get("statement", "")
        if isinstance(stmt, str) and stmt:
            statements.append(stmt)
    return f"{claim_type.title()} claims from {len(claim_data)} trades: " + " | ".join(statements[:10])


def _build_aggregate_claim_statement(
    claim_type: str,
    claim_data: list[dict[str, object]],
    grouping_key: str,
    contributing_count: int,
) -> str:
    if claim_type == "selection":
        should_trade_count = sum(1 for c in claim_data if "should have been taken" in str(c.get("statement", "")))
        return f"Across {contributing_count} trades in `{grouping_key}`, {should_trade_count}/{contributing_count} selection claims indicated the trade should have been taken."

    if claim_type == "entry":
        suboptimal_count = sum(1 for c in claim_data if "suboptimal" in str(c.get("statement", "")))
        return f"Across {contributing_count} trades in `{grouping_key}`, {suboptimal_count}/{contributing_count} entry claims indicated suboptimal entry timing."

    if claim_type == "exit":
        policy_counter: Counter[str] = Counter()
        for c in claim_data:
            stmt = str(c.get("statement", ""))
            if "favors `" in stmt:
                start = stmt.index("favors `") + len("favors `")
                end = stmt.index("`", start)
                policy_counter[stmt[start:end]] += 1
        top_policy = policy_counter.most_common(1)[0][0] if policy_counter else "unknown"
        return f"Across {contributing_count} trades in `{grouping_key}`, the most frequently recommended exit policy is `{top_policy}`."

    return f"Across {contributing_count} trades in `{grouping_key}`, {claim_type} claims were aggregated."
