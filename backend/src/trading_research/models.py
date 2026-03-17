from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class WorkflowKind(StrEnum):
    TRADE_REVIEW = "trade_review"
    SETUP_RESEARCH = "setup_research"
    AGGREGATE_TRADE_REVIEW = "aggregate_trade_review"
    STRATEGY_IMPROVEMENT = "strategy_improvement"


class EvidenceSourceType(StrEnum):
    TRADE_METRIC = "trade_metric"
    REVIEW_LENS = "review_lens"
    REVIEW_SUMMARY = "review_summary"
    WEB_SOURCE = "web_source"
    WEB_FETCH = "web_fetch"
    AGGREGATE_METRIC = "aggregate_metric"
    COHORT_SUMMARY = "cohort_summary"


class SetupType(StrEnum):
    INTRADAY_BREAKOUT = "intraday_breakout"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    OBSERVATION = "observation"
    UNSUPPORTED = "unsupported"


class RecommendationPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EvidenceItem:
    evidence_id: str = ""
    evidence_type: str = "generic_evidence"
    title: str = ""
    content: str = ""
    source_type: EvidenceSourceType = EvidenceSourceType.REVIEW_SUMMARY
    source_ref: str = ""
    provenance: dict[str, object] = field(default_factory=dict)
    as_of: datetime | None = None
    confidence: float | None = None
    sample_size: int | None = None
    limitations: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    schema_version: str = "v1"
    # P1: timing metadata for boundary enforcement
    observed_at: datetime | None = None
    effective_start: datetime | None = None
    effective_end: datetime | None = None


@dataclass
class Finding:
    finding_id: str
    title: str
    detail: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    sample_size: int | None = None
    limitations: list[str] = field(default_factory=list)
    as_of: datetime | None = None


@dataclass
class Claim:
    claim_id: str
    statement: str
    status: ClaimStatus = ClaimStatus.OBSERVATION
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    sample_size: int | None = None
    limitations: list[str] = field(default_factory=list)
    as_of: datetime | None = None
    boundary_time: datetime | None = None


@dataclass
class Recommendation:
    recommendation_id: str
    summary: str
    action: str
    supported_by_claim_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    priority: RecommendationPriority = RecommendationPriority.MEDIUM
    limitations: list[str] = field(default_factory=list)
    as_of: datetime | None = None


@dataclass
class VerifierIssue:
    code: str
    message: str
    severity: str = "warning"
    claim_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class VerifierResult:
    passed: bool
    verified_at: datetime
    checked_claim_count: int
    checked_evidence_count: int
    downgraded_claim_ids: list[str] = field(default_factory=list)
    dropped_recommendation_ids: list[str] = field(default_factory=list)
    issues: list[VerifierIssue] = field(default_factory=list)
    summary: str = ""
    boundary_status: str = "passed"
    boundary_violation_claim_ids: list[str] = field(default_factory=list)
    sample_size_downgraded_claim_ids: list[str] = field(default_factory=list)


@dataclass
class StructuredResult:
    result_id: str
    workflow: WorkflowKind
    title: str
    subject: str
    as_of: datetime
    findings: list[Finding] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    verifier: VerifierResult | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    boundary_time: datetime | None = None


@dataclass
class ReviewResult(StructuredResult):
    trading_date: date | None = None
    symbol: str = ""
    log_source: str | None = None


@dataclass
class SetupResearchResult(StructuredResult):
    topic: str = ""
    symbol: str = ""
    setup_type: SetupType = SetupType.INTRADAY_BREAKOUT
    trade_date: date | None = None
    search_queries: list[str] = field(default_factory=list)
    pages_fetched: int = 0


@dataclass
class AggregatedReviewResult(StructuredResult):
    trade_count: int = 0
    contributing_result_ids: list[str] = field(default_factory=list)
    grouping_key: str = ""
    date_range_start: date | None = None
    date_range_end: date | None = None
    symbol: str = ""
    cohort_stats: dict[str, object] = field(default_factory=dict)


class OpportunityQuality(StrEnum):
    VALID = "valid"
    MARGINAL = "marginal"
    INVALID = "invalid"


class ExecutionQuality(StrEnum):
    EXCELLENT = "excellent"
    ACCEPTABLE = "acceptable"
    POOR = "poor"


class ExtractionQuality(StrEnum):
    FULLY_EXTRACTED = "fully_extracted"
    PARTIALLY_EXTRACTED = "partially_extracted"
    POORLY_EXTRACTED = "poorly_extracted"
    NOT_APPLICABLE = "not_applicable"


class OverallGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class PrimaryFailureReason(StrEnum):
    NO_FAILURE = "no_failure"
    BAD_OPPORTUNITY = "bad_opportunity"
    POOR_EXECUTION = "poor_execution"
    POOR_EXTRACTION = "poor_extraction"
    BAD_OPPORTUNITY_AND_EXECUTION = "bad_opportunity_and_execution"
    MULTIPLE_FAILURES = "multiple_failures"


class ImprovementDirection(StrEnum):
    IMPROVE_SELECTION = "improve_selection"
    IMPROVE_ENTRY = "improve_entry"
    IMPROVE_EXIT = "improve_exit"
    IMPROVE_RISK_MANAGEMENT = "improve_risk_management"
    MAINTAIN_CURRENT = "maintain_current"
    INSUFFICIENT_DATA = "insufficient_data"


class CompoundFailureDominance(StrEnum):
    ENTRY_DOMINANT = "entry_dominant"
    EXIT_DOMINANT = "exit_dominant"
    MIXED = "mixed"


class StrategyActionType(StrEnum):
    NO_CHANGE = "no_change"
    ADD_PRETRADE_FILTER = "add_pretrade_filter"
    REFINE_ENTRY_RULE = "refine_entry_rule"
    REFINE_ENTRY_TIMING = "refine_entry_timing"
    REFINE_STOP_RULE = "refine_stop_rule"
    REFINE_EXIT_RULE = "refine_exit_rule"
    REFINE_EXIT_TIMING = "refine_exit_timing"
    TIGHTEN_RISK_RULE = "tighten_risk_rule"
    COLLECT_MORE_SAMPLES = "collect_more_samples"


class StrategyActionStatus(StrEnum):
    PROPOSED = "proposed"
    NEEDS_MORE_SAMPLES = "needs_more_samples"
    VERIFIED_CANDIDATE = "verified_candidate"
    REJECTED = "rejected"


@dataclass
class TradeDiagnosticResult:
    result_id: str
    trade_result_id: str
    symbol: str
    trading_date: date | None
    pattern: str
    opportunity_quality: OpportunityQuality
    execution_quality: ExecutionQuality
    extraction_quality: ExtractionQuality
    overall_grade: OverallGrade
    primary_failure_reason: PrimaryFailureReason
    earliest_avoid_point: str | None
    earliest_minimize_loss_point: str | None
    improvement_direction: ImprovementDirection
    strategy_action_type: StrategyActionType
    as_of: datetime
    compound_failure_dominance: CompoundFailureDominance | None = None


@dataclass
class AggregatePattern:
    pattern_id: str
    pattern_type: str
    value: str
    count: int
    distinct_trade_ids: list[str] = field(default_factory=list)
    sample_size: int = 0
    frequency_pct: float = 0.0


@dataclass
class StrategyActionCandidate:
    action_id: str
    action_type: StrategyActionType
    rationale: str
    supported_by_pattern_ids: list[str] = field(default_factory=list)
    supported_by_trade_ids: list[str] = field(default_factory=list)
    supported_by_claim_ids: list[str] = field(default_factory=list)
    sample_size: int = 0
    minimum_sample_size_met: bool = False
    status: StrategyActionStatus = StrategyActionStatus.PROPOSED
    confidence: float | None = None
    as_of: datetime | None = None


@dataclass
class StrategyChangeRecord:
    record_id: str
    candidate: StrategyActionCandidate
    created_at: datetime
    source_loop_result_id: str
    source_trade_count: int
    notes: str = ""


@dataclass
class StrategyImprovementLoopResult:
    result_id: str
    workflow: WorkflowKind
    title: str
    as_of: datetime
    diagnostics: list[TradeDiagnosticResult] = field(default_factory=list)
    patterns: list[AggregatePattern] = field(default_factory=list)
    candidates: list[StrategyActionCandidate] = field(default_factory=list)
    verified_claims: list[Claim] = field(default_factory=list)
    change_records: list[StrategyChangeRecord] = field(default_factory=list)
    trade_count: int = 0
    pattern_count: int = 0
    candidate_count: int = 0
    limitations: list[str] = field(default_factory=list)
