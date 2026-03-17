from __future__ import annotations

from datetime import date, datetime

from .models import (
    CompoundFailureDominance,
    ExecutionQuality,
    ExtractionQuality,
    ImprovementDirection,
    OpportunityQuality,
    OverallGrade,
    PrimaryFailureReason,
    StrategyActionType,
    TradeDiagnosticResult,
)


class DiagnosticService:
    def diagnose_trade(self, review_data: dict[str, object]) -> TradeDiagnosticResult | None:
        result_id = str(review_data.get("result_id", ""))
        if not result_id:
            return None
        metadata = review_data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        symbol = str(review_data.get("symbol", ""))
        trading_date = _parse_date(review_data.get("trading_date"))
        pattern = str(metadata.get("pattern", "unclassified"))

        claims = review_data.get("claims", [])
        if not isinstance(claims, list):
            claims = []

        quality_tier = str(metadata.get("quality_tier", "unknown"))
        overall_verdict = str(metadata.get("overall_verdict", "unknown"))
        outcome = str(metadata.get("outcome", "unknown"))

        selection_claim = _find_claim(claims, "claim_selection_")
        entry_claim = _find_claim(claims, "claim_entry_")
        exit_claim = _find_claim(claims, "claim_exit_")

        opportunity = _derive_opportunity_quality(selection_claim)
        execution = _derive_execution_quality(entry_claim, quality_tier)
        extraction = _derive_extraction_quality(exit_claim, overall_verdict, outcome)
        grade = _compute_grade(opportunity, execution, extraction)
        failure_reason = _derive_failure_reason(opportunity, execution, extraction)
        avoid_point = _derive_earliest_avoid_point(opportunity, execution)
        minimize_point = _derive_earliest_minimize_loss_point(execution, extraction, exit_claim)
        direction = _derive_improvement_direction(opportunity, execution, extraction)
        action_type = _derive_strategy_action_type(grade, opportunity, execution, extraction, avoid_point, minimize_point)

        compound_dominance: CompoundFailureDominance | None = None
        if execution == ExecutionQuality.POOR and extraction == ExtractionQuality.POORLY_EXTRACTED:
            compound_dominance = _derive_compound_failure_dominance(opportunity, avoid_point, minimize_point)

        boundary_raw = review_data.get("boundary_time")
        as_of_raw = review_data.get("as_of")
        as_of = _parse_datetime(as_of_raw) or _parse_datetime(boundary_raw) or datetime.now()

        return TradeDiagnosticResult(
            result_id=f"diag_{result_id}",
            trade_result_id=result_id,
            symbol=symbol,
            trading_date=trading_date,
            pattern=pattern,
            opportunity_quality=opportunity,
            execution_quality=execution,
            extraction_quality=extraction,
            overall_grade=grade,
            primary_failure_reason=failure_reason,
            earliest_avoid_point=avoid_point,
            earliest_minimize_loss_point=minimize_point,
            improvement_direction=direction,
            strategy_action_type=action_type,
            as_of=as_of,
            compound_failure_dominance=compound_dominance,
        )

    def diagnose_many(self, review_data_list: list[dict[str, object]]) -> list[TradeDiagnosticResult]:
        results: list[TradeDiagnosticResult] = []
        for data in review_data_list:
            diag = self.diagnose_trade(data)
            if diag is not None:
                results.append(diag)
        return results


# ---------------------------------------------------------------------------
# Claim lookup
# ---------------------------------------------------------------------------


def _find_claim(claims: list[object], prefix: str) -> dict[str, object] | None:
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id", "")
        if isinstance(claim_id, str) and claim_id.startswith(prefix):
            return claim
    return None


# ---------------------------------------------------------------------------
# Quality dimension derivation
# ---------------------------------------------------------------------------


def _derive_opportunity_quality(selection_claim: dict[str, object] | None) -> OpportunityQuality:
    if selection_claim is None:
        return OpportunityQuality.MARGINAL
    confidence_raw = selection_claim.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.5

    claim_metadata = selection_claim.get("metadata")
    should_trade_field = claim_metadata.get("should_trade") if isinstance(claim_metadata, dict) else None

    if should_trade_field is not None:
        should_trade = bool(should_trade_field)
    else:
        statement = str(selection_claim.get("statement", ""))
        should_trade = "should have been taken" in statement

    if should_trade:
        if confidence >= 0.6:
            return OpportunityQuality.VALID
        return OpportunityQuality.MARGINAL
    if confidence >= 0.5:
        return OpportunityQuality.INVALID
    return OpportunityQuality.MARGINAL


def _derive_execution_quality(entry_claim: dict[str, object] | None, quality_tier: str) -> ExecutionQuality:
    if entry_claim is None:
        return ExecutionQuality.POOR

    claim_metadata = entry_claim.get("metadata")
    execution_rating = claim_metadata.get("execution_rating") if isinstance(claim_metadata, dict) else None

    if execution_rating is not None:
        should_have_waited = str(execution_rating) in ("suboptimal", "poor")
    else:
        statement = str(entry_claim.get("statement", ""))
        should_have_waited = "suboptimal" in statement

    top_tiers = {"EXCELLENT", "GOOD"}
    if not should_have_waited:
        if quality_tier.upper() in top_tiers:
            return ExecutionQuality.EXCELLENT
        return ExecutionQuality.ACCEPTABLE
    if quality_tier.upper() in top_tiers:
        return ExecutionQuality.ACCEPTABLE
    return ExecutionQuality.POOR


def _derive_extraction_quality(
    exit_claim: dict[str, object] | None,
    overall_verdict: str,
    outcome: str,
) -> ExtractionQuality:
    if outcome in ("open", "stranded") and exit_claim is None:
        return ExtractionQuality.NOT_APPLICABLE
    if outcome == "tp_filled" and overall_verdict in ("good_trade", "acceptable"):
        return ExtractionQuality.FULLY_EXTRACTED
    if outcome == "manual_exit" and overall_verdict in ("good_trade", "acceptable"):
        return ExtractionQuality.PARTIALLY_EXTRACTED
    if outcome == "manual_exit" and overall_verdict not in ("good_trade", "acceptable"):
        return ExtractionQuality.POORLY_EXTRACTED
    if outcome == "stopped_out":
        return ExtractionQuality.POORLY_EXTRACTED
    if overall_verdict == "good_trade":
        return ExtractionQuality.FULLY_EXTRACTED
    if overall_verdict == "acceptable":
        return ExtractionQuality.PARTIALLY_EXTRACTED
    if overall_verdict in ("marginal", "should_skip", "bad_trade"):
        return ExtractionQuality.POORLY_EXTRACTED
    return ExtractionQuality.POORLY_EXTRACTED


# ---------------------------------------------------------------------------
# Composite grade
# ---------------------------------------------------------------------------


_BEST_TIERS = {
    OpportunityQuality.VALID,
    ExecutionQuality.EXCELLENT,
    ExtractionQuality.FULLY_EXTRACTED,
}

_WORST_TIERS: set[OpportunityQuality | ExecutionQuality | ExtractionQuality] = {
    OpportunityQuality.INVALID,
    ExecutionQuality.POOR,
    ExtractionQuality.POORLY_EXTRACTED,
}


def _compute_grade(
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
) -> OverallGrade:
    dims: tuple[OpportunityQuality | ExecutionQuality | ExtractionQuality, ...] = (opportunity, execution, extraction)
    best_count = sum(1 for d in dims if d in _BEST_TIERS)
    worst_count = sum(1 for d in dims if d in _WORST_TIERS)

    if best_count == 3:
        return OverallGrade.A
    if worst_count == 0 and best_count >= 2:
        return OverallGrade.B
    if worst_count == 0:
        return OverallGrade.C
    if worst_count == 1:
        return OverallGrade.D
    return OverallGrade.E


# ---------------------------------------------------------------------------
# Failure reason
# ---------------------------------------------------------------------------


def _derive_failure_reason(
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
) -> PrimaryFailureReason:
    opp_worst = opportunity == OpportunityQuality.INVALID
    exec_worst = execution == ExecutionQuality.POOR
    ext_worst = extraction == ExtractionQuality.POORLY_EXTRACTED

    worst_count = sum([opp_worst, exec_worst, ext_worst])
    if worst_count == 0:
        return PrimaryFailureReason.NO_FAILURE
    if worst_count >= 2 and opp_worst and exec_worst:
        return PrimaryFailureReason.BAD_OPPORTUNITY_AND_EXECUTION
    if worst_count >= 2:
        return PrimaryFailureReason.MULTIPLE_FAILURES
    if opp_worst:
        return PrimaryFailureReason.BAD_OPPORTUNITY
    if exec_worst:
        return PrimaryFailureReason.POOR_EXECUTION
    return PrimaryFailureReason.POOR_EXTRACTION


# ---------------------------------------------------------------------------
# Avoid / minimize points
# ---------------------------------------------------------------------------


def _derive_earliest_avoid_point(
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
) -> str | None:
    if opportunity == OpportunityQuality.INVALID:
        return "pre_trade_selection"
    if opportunity == OpportunityQuality.MARGINAL and execution == ExecutionQuality.POOR:
        return "entry_timing"
    return None


def _derive_earliest_minimize_loss_point(
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
    exit_claim: dict[str, object] | None,
) -> str | None:
    if extraction == ExtractionQuality.POORLY_EXTRACTED and exit_claim is not None:
        return "exit_management"
    if execution == ExecutionQuality.POOR:
        return "entry_improvement"
    return None


# ---------------------------------------------------------------------------
# Improvement direction
# ---------------------------------------------------------------------------


def _derive_improvement_direction(
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
) -> ImprovementDirection:
    if opportunity == OpportunityQuality.INVALID:
        return ImprovementDirection.IMPROVE_SELECTION
    if execution == ExecutionQuality.POOR:
        return ImprovementDirection.IMPROVE_ENTRY
    if extraction == ExtractionQuality.POORLY_EXTRACTED:
        return ImprovementDirection.IMPROVE_EXIT
    if opportunity == OpportunityQuality.VALID and extraction != ExtractionQuality.NOT_APPLICABLE:
        return ImprovementDirection.MAINTAIN_CURRENT
    return ImprovementDirection.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Strategy action type
# ---------------------------------------------------------------------------


def _derive_strategy_action_type(
    grade: OverallGrade,
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
    earliest_avoid_point: str | None = None,
    earliest_minimize_loss_point: str | None = None,
) -> StrategyActionType:
    if grade in (OverallGrade.A, OverallGrade.B):
        return StrategyActionType.NO_CHANGE

    specific = _derive_specific_action(
        opportunity,
        execution,
        extraction,
        earliest_avoid_point,
        earliest_minimize_loss_point,
    )
    if specific is not None:
        return specific

    if grade == OverallGrade.E:
        return StrategyActionType.TIGHTEN_RISK_RULE
    return StrategyActionType.COLLECT_MORE_SAMPLES


def _derive_specific_action(
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
    earliest_avoid_point: str | None,
    earliest_minimize_loss_point: str | None,
) -> StrategyActionType | None:
    # Priority 1: invalid opportunity
    if opportunity == OpportunityQuality.INVALID:
        return StrategyActionType.ADD_PRETRADE_FILTER

    # Priority 2: compound failure — dominance-aware
    if execution == ExecutionQuality.POOR and extraction == ExtractionQuality.POORLY_EXTRACTED:
        dominance = _derive_compound_failure_dominance(
            opportunity,
            earliest_avoid_point,
            earliest_minimize_loss_point,
        )
        if dominance == CompoundFailureDominance.ENTRY_DOMINANT:
            if earliest_avoid_point == "entry_timing":
                return StrategyActionType.REFINE_ENTRY_TIMING
            return StrategyActionType.REFINE_ENTRY_RULE
        if dominance == CompoundFailureDominance.EXIT_DOMINANT:
            if earliest_minimize_loss_point == "exit_management":
                return StrategyActionType.REFINE_EXIT_TIMING
            return StrategyActionType.REFINE_EXIT_RULE
        # MIXED: conservative fallback
        return StrategyActionType.REFINE_STOP_RULE

    # Priority 3: entry-only failure
    if execution == ExecutionQuality.POOR:
        if earliest_avoid_point == "entry_timing":
            return StrategyActionType.REFINE_ENTRY_TIMING
        return StrategyActionType.REFINE_ENTRY_RULE

    # Priority 4: exit-only failure
    if extraction == ExtractionQuality.POORLY_EXTRACTED:
        if earliest_minimize_loss_point == "exit_management":
            return StrategyActionType.REFINE_EXIT_TIMING
        return StrategyActionType.REFINE_EXIT_RULE

    return None


# ---------------------------------------------------------------------------
# Compound-failure dominance
# ---------------------------------------------------------------------------


def _derive_compound_failure_dominance(
    opportunity: OpportunityQuality,
    earliest_avoid_point: str | None,
    earliest_minimize_loss_point: str | None,
) -> CompoundFailureDominance:
    has_entry_signal = earliest_avoid_point == "entry_timing"
    has_exit_signal = earliest_minimize_loss_point == "exit_management"

    # No structured side-signals → MIXED regardless of opportunity quality.
    if not has_entry_signal and not has_exit_signal:
        return CompoundFailureDominance.MIXED

    # Both side-signals present → conservative MIXED.
    if has_entry_signal and has_exit_signal:
        return CompoundFailureDominance.MIXED

    # Exactly one side-signal present.
    if has_entry_signal:
        return CompoundFailureDominance.ENTRY_DOMINANT
    return CompoundFailureDominance.EXIT_DOMINANT


# ---------------------------------------------------------------------------
# Date/time parsing
# ---------------------------------------------------------------------------


def _parse_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
