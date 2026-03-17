from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .aggregate_review_service import AggregatedTradeReviewRequest, AggregateReviewService
from .diagnostic_service import DiagnosticService
from .models import (
    AggregatePattern,
    Claim,
    ClaimStatus,
    PrimaryFailureReason,
    StrategyActionCandidate,
    StrategyActionStatus,
    StrategyActionType,
    StrategyChangeRecord,
    StrategyImprovementLoopResult,
    TradeDiagnosticResult,
    WorkflowKind,
)
from .store import list_saved_results, load_saved_result

_FAILURE_REASON_TO_ACTION: dict[str, StrategyActionType] = {
    PrimaryFailureReason.BAD_OPPORTUNITY.value: StrategyActionType.ADD_PRETRADE_FILTER,
    PrimaryFailureReason.POOR_EXECUTION.value: StrategyActionType.REFINE_ENTRY_RULE,
    PrimaryFailureReason.POOR_EXTRACTION.value: StrategyActionType.REFINE_EXIT_RULE,
    PrimaryFailureReason.BAD_OPPORTUNITY_AND_EXECUTION.value: StrategyActionType.TIGHTEN_RISK_RULE,
    PrimaryFailureReason.MULTIPLE_FAILURES.value: StrategyActionType.TIGHTEN_RISK_RULE,
}

_ACTION_TO_CLAIM_PREFIX: dict[str, str] = {
    StrategyActionType.ADD_PRETRADE_FILTER.value: "agg_claim_selection_",
    StrategyActionType.REFINE_ENTRY_RULE.value: "agg_claim_entry_",
    StrategyActionType.REFINE_ENTRY_TIMING.value: "agg_claim_entry_",
    StrategyActionType.REFINE_EXIT_RULE.value: "agg_claim_exit_",
    StrategyActionType.REFINE_EXIT_TIMING.value: "agg_claim_exit_",
    StrategyActionType.REFINE_STOP_RULE.value: "agg_claim_exit_",
}

MIN_PATTERN_COUNT = 2
MIN_CANDIDATE_SAMPLE_SIZE = 2
MIN_VERIFIED_SAMPLE_SIZE = 3


@dataclass
class StrategyImprovementRequest:
    symbol: str | None = None
    pattern: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    max_trades: int | None = None
    log_source: str | None = None


class StrategyImprovementService:
    def __init__(
        self,
        *,
        diagnostic_service: DiagnosticService | None = None,
        aggregate_review_service: AggregateReviewService | None = None,
    ) -> None:
        self._diagnostic_service = diagnostic_service or DiagnosticService()
        self._aggregate_review_service = aggregate_review_service or AggregateReviewService()

    def run_loop(self, request: StrategyImprovementRequest) -> StrategyImprovementLoopResult:
        review_data_list = self._load_reviews(request)
        diagnostics = self._diagnostic_service.diagnose_many(review_data_list)

        patterns = self.extract_patterns(diagnostics)

        verified_claims = self._get_verified_claims(request)
        candidates = self.generate_candidates(patterns, datetime.now(), verified_claims=verified_claims)

        now = datetime.now()
        trade_count = len(diagnostics)
        result_id = f"strategy_improvement_{now.strftime('%Y%m%d_%H%M%S')}"

        change_records = self._create_change_records(candidates, result_id, trade_count, now)

        limitations: list[str] = [
            f"Diagnostics cover {trade_count} trade(s).",
            "Patterns are extracted from structured fields only, not from prose re-interpretation.",
            "Strategy action candidates require aggregate pattern backing; single-trade diagnostics cannot produce supported strategy changes.",
        ]
        if trade_count < MIN_VERIFIED_SAMPLE_SIZE:
            limitations.append(f"Only {trade_count} trade(s) diagnosed. Verified candidates require at least {MIN_VERIFIED_SAMPLE_SIZE} trades.")

        return StrategyImprovementLoopResult(
            result_id=result_id,
            workflow=WorkflowKind.STRATEGY_IMPROVEMENT,
            title=f"Strategy Improvement Loop ({trade_count} trades)",
            as_of=now,
            diagnostics=diagnostics,
            patterns=patterns,
            candidates=candidates,
            verified_claims=verified_claims,
            change_records=change_records,
            trade_count=trade_count,
            pattern_count=len(patterns),
            candidate_count=len(candidates),
            limitations=limitations,
        )

    # ------------------------------------------------------------------
    # Aggregate claim bridge
    # ------------------------------------------------------------------

    def _get_verified_claims(self, request: StrategyImprovementRequest) -> list[Claim]:
        if self._aggregate_review_service is None:
            return []
        agg_request = AggregatedTradeReviewRequest(
            symbol=request.symbol,
            pattern=request.pattern,
            start_date=request.start_date,
            end_date=request.end_date,
            max_trades=request.max_trades,
            log_source=request.log_source,
        )
        agg_result = self._aggregate_review_service.aggregate(agg_request)
        if agg_result.verifier is None:
            return list(agg_result.claims)
        surviving: list[Claim] = []
        downgraded_ids = set(agg_result.verifier.downgraded_claim_ids)
        boundary_violation_ids = set(agg_result.verifier.boundary_violation_claim_ids)
        for claim in agg_result.claims:
            if claim.claim_id in boundary_violation_ids:
                continue
            if claim.claim_id in downgraded_ids:
                if claim.status == ClaimStatus.SUPPORTED:
                    surviving.append(claim)
            else:
                if claim.status in (ClaimStatus.SUPPORTED, ClaimStatus.OBSERVATION):
                    surviving.append(claim)
        return surviving

    # ------------------------------------------------------------------
    # Pattern extraction
    # ------------------------------------------------------------------

    def extract_patterns(self, diagnostics: list[TradeDiagnosticResult]) -> list[AggregatePattern]:
        if not diagnostics:
            return []
        total = len(diagnostics)
        patterns: list[AggregatePattern] = []

        field_extractors: list[tuple[str, str]] = [
            ("failure_reason", "primary_failure_reason"),
            ("action_type", "strategy_action_type"),
            ("avoid_point", "earliest_avoid_point"),
            ("improvement_direction", "improvement_direction"),
            ("compound_dominance", "compound_failure_dominance"),
        ]

        for pattern_type, attr_name in field_extractors:
            value_to_trade_ids: dict[str, list[str]] = {}
            for diag in diagnostics:
                raw_value = getattr(diag, attr_name, None)
                if raw_value is None:
                    continue
                value = str(raw_value)
                if value in ("no_failure", "no_change", "maintain_current"):
                    continue
                if value not in value_to_trade_ids:
                    value_to_trade_ids[value] = []
                value_to_trade_ids[value].append(diag.trade_result_id)

            for value, trade_ids in value_to_trade_ids.items():
                seen: set[str] = set()
                distinct_ids: list[str] = []
                for tid in trade_ids:
                    if tid not in seen:
                        seen.add(tid)
                        distinct_ids.append(tid)
                count = len(distinct_ids)
                if count < MIN_PATTERN_COUNT:
                    continue
                patterns.append(
                    AggregatePattern(
                        pattern_id=f"pattern_{pattern_type}_{value}",
                        pattern_type=pattern_type,
                        value=value,
                        count=count,
                        distinct_trade_ids=distinct_ids,
                        sample_size=count,
                        frequency_pct=count / total if total > 0 else 0.0,
                    )
                )

        return patterns

    # ------------------------------------------------------------------
    # Candidate generation
    # ------------------------------------------------------------------

    def generate_candidates(
        self,
        patterns: list[AggregatePattern],
        now: datetime | None = None,
        *,
        verified_claims: list[Claim] | None = None,
    ) -> list[StrategyActionCandidate]:
        if now is None:
            now = datetime.now()

        candidates: list[StrategyActionCandidate] = []
        seen_action_types: set[str] = set()

        actionable_patterns: list[AggregatePattern] = []
        for p in patterns:
            if p.pattern_type in ("failure_reason", "action_type"):
                actionable_patterns.append(p)

        for pattern in actionable_patterns:
            action_type = self._resolve_action_type(pattern)
            if action_type is None or action_type == StrategyActionType.NO_CHANGE:
                continue

            action_key = f"{action_type.value}_{pattern.pattern_id}"
            if action_key in seen_action_types:
                continue
            seen_action_types.add(action_key)

            sample_size = pattern.sample_size
            minimum_met = sample_size >= MIN_CANDIDATE_SAMPLE_SIZE

            matching_claim_ids = _find_matching_claim_ids(action_type, verified_claims or [])

            if sample_size >= MIN_VERIFIED_SAMPLE_SIZE and minimum_met:
                if matching_claim_ids or action_type in (StrategyActionType.COLLECT_MORE_SAMPLES, StrategyActionType.NO_CHANGE):
                    status = StrategyActionStatus.VERIFIED_CANDIDATE
                else:
                    status = StrategyActionStatus.NEEDS_MORE_SAMPLES
            elif sample_size >= MIN_CANDIDATE_SAMPLE_SIZE:
                status = StrategyActionStatus.PROPOSED
            else:
                status = StrategyActionStatus.NEEDS_MORE_SAMPLES

            trade_id_list: list[str] = list(pattern.distinct_trade_ids)
            rationale = f"Pattern `{pattern.value}` observed in {pattern.count} trade(s) (trade IDs: {', '.join(trade_id_list[:5])}). Suggests `{action_type.value}` action."

            candidates.append(
                StrategyActionCandidate(
                    action_id=f"candidate_{action_type.value}_{pattern.pattern_id}",
                    action_type=action_type,
                    rationale=rationale,
                    supported_by_pattern_ids=[pattern.pattern_id],
                    supported_by_trade_ids=trade_id_list,
                    supported_by_claim_ids=matching_claim_ids,
                    sample_size=sample_size,
                    minimum_sample_size_met=minimum_met,
                    status=status,
                    confidence=min(0.9, pattern.frequency_pct) if pattern.frequency_pct > 0 else None,
                    as_of=now,
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # Change record creation
    # ------------------------------------------------------------------

    def _create_change_records(
        self,
        candidates: list[StrategyActionCandidate],
        source_loop_result_id: str,
        source_trade_count: int,
        now: datetime,
    ) -> list[StrategyChangeRecord]:
        records: list[StrategyChangeRecord] = []
        for candidate in candidates:
            if candidate.status != StrategyActionStatus.VERIFIED_CANDIDATE:
                continue
            records.append(
                StrategyChangeRecord(
                    record_id=f"change_{candidate.action_id}",
                    candidate=candidate,
                    created_at=now,
                    source_loop_result_id=source_loop_result_id,
                    source_trade_count=source_trade_count,
                )
            )
        return records

    # ------------------------------------------------------------------
    # Loading saved reviews
    # ------------------------------------------------------------------

    def _load_reviews(self, request: StrategyImprovementRequest) -> list[dict[str, object]]:
        reviews: list[dict[str, object]] = []
        for filename in list_saved_results():
            data = load_saved_result(filename)
            if data is None:
                continue
            if data.get("workflow") != "trade_review":
                continue
            if not self._matches_filter(data, request):
                continue
            reviews.append(data)
        if request.max_trades is not None and len(reviews) > request.max_trades:
            reviews = reviews[: request.max_trades]
        return reviews

    def _matches_filter(self, data: dict[str, object], request: StrategyImprovementRequest) -> bool:
        if request.symbol:
            symbol = str(data.get("symbol", ""))
            if symbol.upper() != request.symbol.upper():
                return False
        if request.log_source:
            log_source = str(data.get("log_source", ""))
            if log_source != request.log_source:
                return False

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        if request.pattern:
            pattern = str(metadata.get("pattern", ""))
            if pattern != request.pattern:
                return False

        if request.start_date or request.end_date:
            td_raw = data.get("trading_date")
            if isinstance(td_raw, str) and td_raw:
                try:
                    td = date.fromisoformat(td_raw)
                except ValueError:
                    return False
                if request.start_date and td < request.start_date:
                    return False
                if request.end_date and td > request.end_date:
                    return False
            else:
                return False

        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_action_type(self, pattern: AggregatePattern) -> StrategyActionType | None:
        if pattern.pattern_type == "action_type":
            try:
                return StrategyActionType(pattern.value)
            except ValueError:
                return None
        if pattern.pattern_type == "failure_reason":
            return _FAILURE_REASON_TO_ACTION.get(pattern.value)
        return None


# ---------------------------------------------------------------------------
# Claim matching
# ---------------------------------------------------------------------------


def _find_matching_claim_ids(action_type: StrategyActionType, claims: list[Claim]) -> list[str]:
    if action_type in (StrategyActionType.COLLECT_MORE_SAMPLES, StrategyActionType.NO_CHANGE):
        return []
    prefix = _ACTION_TO_CLAIM_PREFIX.get(action_type.value)
    if prefix is not None:
        matching: list[str] = []
        for claim in claims:
            if claim.claim_id.startswith(prefix):
                matching.append(claim.claim_id)
        return matching
    if action_type == StrategyActionType.TIGHTEN_RISK_RULE:
        all_ids: list[str] = []
        for claim in claims:
            all_ids.append(claim.claim_id)
        return all_ids
    return []
