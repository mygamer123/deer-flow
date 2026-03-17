# P3 Implementation Plan: Strategy Improvement Loop

## Scope Lock

This pass implements one capability:

**A strategy-improvement loop that decomposes single trades into diagnostic dimensions, extracts aggregate patterns from structured fields, and produces gated strategy-change candidates.**

Specifically:
1. Single-trade diagnostic decomposition (opportunity/execution/extraction quality + composite grade)
2. Failure/improvement diagnostics (primary failure reason, avoid/minimize points, improvement direction, action type)
3. New structured models (TradeDiagnosticResult, StrategyActionCandidate, AggregatePattern, StrategyImprovementLoopResult)
4. Aggregate recurring-pattern extraction from structured diagnostic fields
5. Strategy action candidates gated by aggregate backing only
6. Closed-loop strategy improvement report
7. Lightweight strategy versioning (candidate tracking with statuses)
8. CLI and tool entry points

Out of scope:
- Real order execution
- UI / frontend
- Slack / OpenClaw / channels
- Setup research changes
- Semantic fact-checking
- Repo-wide refactors
- Loosening P1 thresholds
- Modifying verifier_service.py
- Prose-based or LLM-derived aggregation

## Current State

After P2:
- Single-trade `ReviewResult` has claims with `sample_size=1`, all downgraded by verifier
- `AggregatedReviewResult` can aggregate multiple trade reviews, producing claims with real sample sizes
- Recommendations require `sample_size >= 3` to survive the verifier
- 52 tests pass (34 P0+P1, 18 P2)
- The system has no diagnostic decomposition, no failure analysis beyond the binary `should_exit_now`, and no structured path from trade diagnostics to strategy changes

P3 creates the diagnostic-to-strategy-change path.

## Design

### P3.1 Single-trade diagnostic decomposition

Three independent quality dimensions derived from existing `TradeReview` structured fields:

**Opportunity quality** (`valid` / `marginal` / `invalid`):
- Derived from `review.selection.should_trade` and `review.selection.confidence`
- `valid`: `should_trade=True` and `confidence >= 0.6`
- `marginal`: `should_trade=True` and `confidence < 0.6`, OR `should_trade=False` and `confidence < 0.5`
- `invalid`: `should_trade=False` and `confidence >= 0.5`
- If `selection` is None: `marginal` (insufficient data)

**Execution quality** (`excellent` / `acceptable` / `poor`):
- Derived from `review.entry.should_have_waited`, `review.entry.actual_vs_optimal_slippage_pct`, and `review.quality_tier`
- `excellent`: `should_have_waited=False` and `quality_tier in (EXCELLENT, GOOD)`
- `acceptable`: `should_have_waited=False` and `quality_tier not in (EXCELLENT, GOOD)`, OR `should_have_waited=True` and `|slippage| < 0.5%`
- `poor`: `should_have_waited=True` and `|slippage| >= 0.5%`, OR entry is None
- If `entry` is None: `poor` (no entry data to evaluate)

**Extraction quality** (`fully_extracted` / `partially_extracted` / `poorly_extracted` / `not_applicable`):
- Derived from `review.exit`, `review.trade.outcome`, `review.exit.max_favorable_excursion_pct`, `review.trade.pnl_pct`
- `not_applicable`: trade has no exit (still open/stranded with no exit price)
- `fully_extracted`: `pnl_pct is not None` and `mfe is not None` and `pnl_pct / mfe >= 0.7`
- `partially_extracted`: `pnl_pct is not None` and `mfe is not None` and `0.3 <= pnl_pct / mfe < 0.7`
- `poorly_extracted`: everything else (including negative pnl with positive mfe, or mfe unavailable)

**Composite overall_grade** (A through E):
- A: all three are best tier (valid + excellent + fully_extracted)
- B: no dimension is worst tier and at least two are best tier
- C: no dimension is worst tier (the "acceptable" middle)
- D: exactly one dimension is worst tier
- E: two or more dimensions are worst tier

Key invariant: **opportunity, execution, and extraction are independent**. A trade can be `invalid` opportunity but `excellent` execution (the trader executed well on a bad idea). A trade can be `valid` opportunity but `poorly_extracted` (good idea, left money on the table). Profitability alone does not determine any single dimension.

### P3.2 Failure/improvement diagnostics

Added to `TradeDiagnosticResult` alongside the quality dimensions:

**`primary_failure_reason`** (string enum):
- `no_failure` — grade A or B, no dominant failure
- `bad_opportunity` — opportunity was invalid
- `poor_execution` — execution was poor
- `poor_extraction` — extraction was poor
- `bad_opportunity_and_execution` — both invalid opportunity and poor execution
- `multiple_failures` — two or more worst-tier dimensions (grade E)

Derivation: deterministic from the three quality dimensions.

**`earliest_avoid_point`** (string, nullable):
- If opportunity is `invalid`: `"pre_trade_selection"` — should have been filtered before entry
- If opportunity is `marginal` and execution is `poor`: `"entry_timing"` — could have avoided by not entering
- Otherwise: None (trade was worth taking)

**`earliest_minimize_loss_point`** (string, nullable):
- If extraction is `poorly_extracted` and exit data exists: `"exit_management"` — better exit timing would have reduced loss
- If execution is `poor` and entry data exists: `"entry_improvement"` — waiting for better fill would have minimized adverse excursion
- Otherwise: None

**`improvement_direction`** (string):
- One of: `"improve_selection"`, `"improve_entry"`, `"improve_exit"`, `"improve_risk_management"`, `"maintain_current"`, `"insufficient_data"`
- Derived from the worst-performing dimension. If multiple are worst, priority order: selection > entry > exit.

**`strategy_action_type`** (string enum):
- `no_change` — grade A or B
- `add_pretrade_filter` — opportunity was invalid
- `refine_entry_rule` — execution was poor
- `refine_exit_rule` — extraction was poor
- `refine_stop_rule` — execution poor and extraction poor
- `tighten_risk_rule` — grade E (multiple failures)
- `collect_more_samples` — grade C or D with low confidence

All derivations are deterministic from structured fields. No LLM calls.

### P3.3 Structured models

**`OpportunityQuality`** (StrEnum): `valid`, `marginal`, `invalid`

**`ExecutionQuality`** (StrEnum): `excellent`, `acceptable`, `poor`

**`ExtractionQuality`** (StrEnum): `fully_extracted`, `partially_extracted`, `poorly_extracted`, `not_applicable`

**`OverallGrade`** (StrEnum): `A`, `B`, `C`, `D`, `E`

**`PrimaryFailureReason`** (StrEnum): `no_failure`, `bad_opportunity`, `poor_execution`, `poor_extraction`, `bad_opportunity_and_execution`, `multiple_failures`

**`ImprovementDirection`** (StrEnum): `improve_selection`, `improve_entry`, `improve_exit`, `improve_risk_management`, `maintain_current`, `insufficient_data`

**`StrategyActionType`** (StrEnum): `no_change`, `add_pretrade_filter`, `refine_entry_rule`, `refine_stop_rule`, `refine_exit_rule`, `tighten_risk_rule`, `collect_more_samples`

**`StrategyActionStatus`** (StrEnum): `proposed`, `needs_more_samples`, `verified_candidate`, `rejected`

**`TradeDiagnosticResult`** (dataclass):
```
result_id: str
trade_result_id: str  # links back to the ReviewResult
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
```

**`AggregatePattern`** (dataclass):
```
pattern_id: str
pattern_type: str  # e.g. "failure_reason", "action_type", "avoid_point"
value: str  # the repeated value
count: int
distinct_trade_ids: list[str]
sample_size: int  # == len(distinct_trade_ids)
frequency_pct: float  # count / total trades
```

**`StrategyActionCandidate`** (dataclass):
```
action_id: str
action_type: StrategyActionType
rationale: str
supported_by_pattern_ids: list[str]
supported_by_trade_ids: list[str]
sample_size: int
minimum_sample_size_met: bool
status: StrategyActionStatus
confidence: float | None
as_of: datetime
```

**`StrategyImprovementLoopResult`** (dataclass):
```
result_id: str
workflow: WorkflowKind  # STRATEGY_IMPROVEMENT
title: str
as_of: datetime
diagnostics: list[TradeDiagnosticResult]
patterns: list[AggregatePattern]
candidates: list[StrategyActionCandidate]
trade_count: int
pattern_count: int
candidate_count: int
limitations: list[str]
```

### P3.4 Aggregate recurring-pattern extraction

The pattern extractor operates on a list of `TradeDiagnosticResult` objects and produces `AggregatePattern` objects.

For each structured field (`primary_failure_reason`, `strategy_action_type`, `earliest_avoid_point`, `improvement_direction`):
1. Count occurrences of each distinct value
2. Track distinct `trade_result_id` values per value (no dedup inflation)
3. Compute `frequency_pct = count / total_diagnostics`
4. Only emit a pattern if `count >= 2` (at least two trades share the same value)

Pattern IDs are deterministic: `pattern_{field}_{value}` (e.g. `pattern_failure_reason_bad_opportunity`).

This is pure counting on structured enum fields. No semantic analysis.

### P3.5 Strategy action candidates from aggregate patterns only

Candidate generation rules:

1. A candidate is created when an `AggregatePattern` of type `action_type` or `failure_reason` has `sample_size >= 2`
2. The candidate's `action_type` is derived from the pattern value (failure_reason maps to action_type via the same mapping used in P3.2)
3. `minimum_sample_size_met` = `sample_size >= MIN_SUPPORTED_CLAIM_SAMPLE_SIZE` (2, from verifier constants)
4. `status`:
   - `proposed` if `sample_size >= 2` but `< 3`
   - `needs_more_samples` if `sample_size < 2`
   - `verified_candidate` if `sample_size >= 3` and `minimum_sample_size_met`
   - `rejected` is never set automatically (manual/future use)
5. `rationale` is a deterministic template string referencing the pattern count and trade IDs

**Critical invariant**: A single trade's diagnostic can suggest an action_type but CANNOT directly create a StrategyActionCandidate with `minimum_sample_size_met=True`. Only aggregate patterns with multiple distinct trades can produce actionable candidates.

### P3.6 Closed-loop strategy improvement report

Markdown report with three sections:
1. **Trade Diagnostics**: table of all diagnostics (symbol, date, grades, failure reason, action type)
2. **Aggregate Patterns**: table of extracted patterns (type, value, count, frequency)
3. **Strategy Action Candidates**: table of candidates (action_id, type, status, sample_size, rationale)

Plus limitations section.

### P3.7 Minimal strategy versioning

`StrategyActionCandidate` has a `status` field with values `proposed`, `needs_more_samples`, `verified_candidate`, `rejected`. This is set deterministically by the service based on sample size thresholds. No manual workflow or persistence of version history in P3 — candidates are computed fresh from current diagnostics each time.

The `StrategyImprovementLoopResult` is saved to the store for reference.

### P3.8 Entry points

CLI:
- `diagnose-trade <symbol> <trading_date>` — runs single-trade diagnostic, prints diagnostic result
- `strategy-improvement-loop` — loads saved reviews, runs diagnostics + patterns + candidates, prints full report

Tool:
- `run_trade_diagnostic` — wraps diagnose-trade
- `run_strategy_improvement_loop` — wraps the full loop

## Files to Change

### New files

**`backend/src/trading_research/diagnostic_service.py`**
- `DiagnosticService` class
- `diagnose_trade(review_result: ReviewResult) -> TradeDiagnosticResult` — derives all quality dimensions and failure diagnostics from a ReviewResult's metadata and structured fields
- `diagnose_many(review_results: list[ReviewResult]) -> list[TradeDiagnosticResult]`
- Pure computation, no side effects, no evidence registration
- Depends on: `models.py` only

**`backend/src/trading_research/strategy_improvement_service.py`**
- `StrategyImprovementService` class
- `run_loop(request) -> StrategyImprovementLoopResult`
- Orchestrates: load reviews → diagnose → extract patterns → generate candidates → build result
- `extract_patterns(diagnostics: list[TradeDiagnosticResult]) -> list[AggregatePattern]`
- `generate_candidates(patterns: list[AggregatePattern]) -> list[StrategyActionCandidate]`
- Depends on: `models.py`, `diagnostic_service.py`, `store.py`

### Modified files

**`backend/src/trading_research/models.py`**
- Add `WorkflowKind.STRATEGY_IMPROVEMENT = "strategy_improvement"`
- Add 8 new StrEnum classes (OpportunityQuality, ExecutionQuality, ExtractionQuality, OverallGrade, PrimaryFailureReason, ImprovementDirection, StrategyActionType, StrategyActionStatus)
- Add 4 new dataclasses (TradeDiagnosticResult, AggregatePattern, StrategyActionCandidate, StrategyImprovementLoopResult)

**`backend/src/trading_research/report_service.py`**
- Add `build_strategy_improvement_markdown(result: StrategyImprovementLoopResult) -> str`
- Three-section report: diagnostics table, patterns table, candidates table

**`backend/src/trading_research/store.py`**
- Add `StrategyImprovementLoopResult` to `_filename_for` dispatch
- Import new type

**`backend/src/trading_research/cli.py`**
- Add `diagnose-trade` subcommand (symbol, trading_date, --log-source)
- Add `strategy-improvement-loop` subcommand (--symbol, --pattern, --start-date, --end-date, --max-trades, --log-source)

**`backend/src/trading_research/tools.py`**
- Add `run_trade_diagnostic` tool wrapper
- Add `run_strategy_improvement_loop` tool wrapper

**`backend/src/trading_research/__init__.py`**
- Export new model types and enums

### Files NOT changed

- `evidence_service.py` — P3 diagnostic service is pure computation, no evidence registration needed
- `verifier_service.py` — must NOT be modified. Strategy action candidates use their own sample-size gating (referencing the same constants but not running through the verifier)
- `aggregate_review_service.py` — P3 does not modify existing aggregation. The strategy improvement service loads reviews independently
- `trade_review_service.py` — single-trade review behavior is unchanged
- `setup_research_service.py` — out of scope

## Diagnostic Derivation Mapping

Source: `ReviewResult.metadata` and `TradeReview` fields (accessed via saved result dicts)

| Diagnostic field | Source field(s) | Logic |
|---|---|---|
| opportunity_quality | metadata["overall_verdict"], selection claim statement | `should have been taken` → valid/marginal, `should have been skipped` → invalid |
| execution_quality | metadata["quality_tier"], entry claim statement | EXCELLENT/GOOD tier + acceptable entry → excellent, poor tier or suboptimal entry → poor |
| extraction_quality | metadata["overall_verdict"], metadata["outcome"], exit claim | verdict=good_trade + tp_filled → fully_extracted, manual_exit → partially, stopped_out → poorly |
| overall_grade | computed from above three | deterministic composite |

Because `DiagnosticService` operates on saved `ReviewResult` dicts (like `AggregateReviewService`), it reads `metadata`, `claims`, and structured fields without needing the original `TradeReview` object.

Specifically, from saved ReviewResult:
- `metadata["quality_tier"]` → string, one of QualityTier names
- `metadata["overall_verdict"]` → string, one of ReviewVerdict values
- `metadata["pattern"]` → string, one of PatternType values
- `metadata["outcome"]` → string, one of TradeOutcome values (if present)
- `claims` → list of claim dicts with `claim_id` and `statement` strings
- `symbol`, `trading_date`, `boundary_time` → top-level fields

## Risks / Compatibility Notes

### Risk 1: Saved ReviewResults may lack metadata fields
- Some older saved results may not have `outcome` in metadata
- Mitigation: default to `"unknown"` and classify extraction as `poorly_extracted` when data is missing
- This is honest degradation, not a crash

### Risk 2: Diagnostic decomposition adds complexity to what was a simple verdict
- The three-dimensional decomposition is more nuanced than the existing single verdict
- Mitigation: the composite `overall_grade` provides a single-value summary for users who don't need the decomposition
- The existing single-trade review behavior is completely unchanged

### Risk 3: Pattern extraction on small sample sets
- With fewer than 2 trades sharing a failure reason, no pattern is extracted
- This is correct — patterns require repetition
- The report will show diagnostics even when no patterns emerge

### Risk 4: Strategy action candidates may all be `proposed` (not `verified_candidate`)
- With sample_size < 3, candidates exist as `proposed` but not `verified_candidate`
- This mirrors P2's behavior where claims survive but recommendations don't
- The report clearly shows the status and sample_size

### Risk 5: basedpyright type-narrowing compatibility
- Use `isinstance` guards and accumulator loops, not generator expressions
- Apply the same patterns used successfully in P2

### Risk 6: Existing 52 tests must not break
- P3 adds new models and services but does not modify existing service behavior
- All existing tests must continue to pass unchanged

## Test Requirements

### A. Single-trade diagnostic decomposition
- Opportunity, execution, and extraction are computed independently
- An invalid-but-profitable trade is representable (invalid opportunity + excellent execution + fully_extracted)
- A valid-but-unprofitable trade is representable (valid opportunity + poor execution + poorly_extracted)
- Missing selection/entry/exit data produces honest defaults, not crashes
- Grade computation matches the A-E rules exactly

### B. Failure/improvement diagnostics
- `earliest_avoid_point` is set for invalid opportunity
- `earliest_minimize_loss_point` is set for poor extraction with exit data
- `strategy_action_type` enum is enforced (only valid enum values)
- `primary_failure_reason` matches the worst dimensions

### C. Aggregate pattern extraction
- Repeated failure reasons across trades form patterns
- `sample_size` = count of distinct trade IDs (no dedup inflation)
- Patterns require count >= 2
- Single-trade diagnostics do not produce patterns

### D. Strategy action candidate gating
- Candidates are only produced from aggregate patterns with sample_size >= 2
- A single trade's diagnostic cannot produce a candidate with `minimum_sample_size_met=True`
- `verified_candidate` status requires sample_size >= 3
- `proposed` status for sample_size 2

### E. Report output
- Diagnostics table renders all diagnostic fields
- Patterns table renders pattern type, value, count, frequency
- Candidates table renders action_id, type, status, sample_size
- Empty patterns/candidates sections render gracefully

### F. Golden regression
- All 52 existing tests pass unchanged
- New end-to-end path: ReviewResults → diagnostics → patterns → candidates → report

## Execution Order

1. `models.py` — add WorkflowKind, 8 enums, 4 dataclasses
2. `diagnostic_service.py` — new file, pure diagnostic computation
3. `strategy_improvement_service.py` — new file, orchestration + pattern extraction + candidate generation
4. `report_service.py` — add strategy improvement report renderer
5. `store.py` — add StrategyImprovementLoopResult to filename dispatch
6. `cli.py` — add diagnose-trade and strategy-improvement-loop subcommands
7. `tools.py` — add tool wrappers
8. `__init__.py` — export new types
9. Tests — new P3 tests + verify all 52 existing tests pass
10. `audit/p3_strategy_improvement_completion_report.md`

That is the entire plan.
