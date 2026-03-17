# P3 Completion Report

## Scope

Strategy improvement loop added to the structured trading research core. This creates a diagnostic-to-strategy-change path: single trades are decomposed into three independent quality dimensions, failure diagnostics are derived deterministically, aggregate patterns are extracted from structured fields, and gated strategy-change candidates are produced.

No new agents, no UI work, no repo-wide refactors. The P0 structured core, P1 invariants, and P2 aggregation pipeline remain intact.

## Completed Items

### 1. Models

- `WorkflowKind.STRATEGY_IMPROVEMENT = "strategy_improvement"` -- new workflow kind
- 8 new StrEnum classes:
  - `OpportunityQuality`: `valid`, `marginal`, `invalid`
  - `ExecutionQuality`: `excellent`, `acceptable`, `poor`
  - `ExtractionQuality`: `fully_extracted`, `partially_extracted`, `poorly_extracted`, `not_applicable`
  - `OverallGrade`: `A`, `B`, `C`, `D`, `E`
  - `PrimaryFailureReason`: `no_failure`, `bad_opportunity`, `poor_execution`, `poor_extraction`, `bad_opportunity_and_execution`, `multiple_failures`
  - `ImprovementDirection`: `improve_selection`, `improve_entry`, `improve_exit`, `improve_risk_management`, `maintain_current`, `insufficient_data`
  - `StrategyActionType`: `no_change`, `add_pretrade_filter`, `refine_entry_rule`, `refine_stop_rule`, `refine_exit_rule`, `tighten_risk_rule`, `collect_more_samples`
  - `StrategyActionStatus`: `proposed`, `needs_more_samples`, `verified_candidate`, `rejected`
- 4 new dataclasses:
  - `TradeDiagnosticResult` -- single-trade diagnostic with three quality dimensions + composite grade + failure analysis
  - `AggregatePattern` -- recurring value across diagnostics with distinct trade ID tracking
  - `StrategyActionCandidate` -- gated strategy change proposal with sample-size backing
  - `StrategyImprovementLoopResult` -- top-level result containing diagnostics, patterns, candidates, and limitations

### 2. Diagnostic Service

New file: `diagnostic_service.py` (323 lines).

Pure computation service that derives all diagnostic dimensions from saved `ReviewResult` dicts. Operates on `dict[str, object]` (same pattern as `_parse_loaded_review` in `aggregate_review_service.py`). No side effects, no evidence registration.

#### Derivation approach

Reads from saved ReviewResult JSON:
- `metadata["quality_tier"]` -> execution quality
- `metadata["overall_verdict"]` -> opportunity and extraction quality
- `metadata["outcome"]` -> extraction quality refinement
- Claim `statement` substrings ("should have been taken", "suboptimal", "favors") -> quality dimension refinements

Three quality dimensions are derived independently:
- **Opportunity quality**: `valid` / `marginal` / `invalid` from verdict and selection claims
- **Execution quality**: `excellent` / `acceptable` / `poor` from quality tier and entry claims
- **Extraction quality**: `fully_extracted` / `partially_extracted` / `poorly_extracted` / `not_applicable` from verdict, outcome, and exit claims

Composite grade (A-E), failure reason, avoid/minimize points, improvement direction, and strategy action type are all derived deterministically from the three dimensions.

#### Methods
- `diagnose_single(review_data: dict[str, object]) -> TradeDiagnosticResult | None`
- `diagnose_many(review_data_list: list[dict[str, object]]) -> list[TradeDiagnosticResult]`

### 3. Strategy Improvement Service

New file: `strategy_improvement_service.py` (258 lines).

Orchestration service with `run_loop()`, `extract_patterns()`, and `generate_candidates()`. Loads saved reviews from store, diagnoses them, extracts patterns, generates candidates.

#### Pipeline
1. **Load**: Reads saved trade review results from store (filtered by symbol, pattern, date range, max_trades, log_source)
2. **Diagnose**: Runs `DiagnosticService.diagnose_many()` on all loaded reviews
3. **Extract patterns**: Counts recurring values across structured diagnostic fields
4. **Generate candidates**: Maps patterns to strategy action candidates with sample-size gating
5. **Build result**: Assembles `StrategyImprovementLoopResult` with limitations

#### Pattern extraction
- Scans 4 diagnostic fields: `primary_failure_reason`, `strategy_action_type`, `earliest_avoid_point`, `improvement_direction`
- Groups by distinct values, tracking distinct trade IDs
- Only emits patterns with count >= `MIN_PATTERN_COUNT` (2)
- Pattern IDs are deterministic: `pattern_{field}_{value}`

#### Candidate generation
- Only processes patterns of type `failure_reason` or `action_type`
- Maps failure reasons to action types via `_FAILURE_REASON_TO_ACTION` dict
- Status gating:
  - `verified_candidate`: sample_size >= `MIN_VERIFIED_SAMPLE_SIZE` (3)
  - `proposed`: sample_size >= `MIN_CANDIDATE_SAMPLE_SIZE` (2)
  - `needs_more_samples`: sample_size < 2

### 4. Report Service

Added `build_strategy_improvement_markdown()`:
- **Trade Diagnostics** section: table of all diagnostics (symbol, date, opportunity, execution, extraction, grade, failure reason, action type)
- **Aggregate Patterns** section: table of extracted patterns (type, value, count, frequency, trade IDs)
- **Strategy Action Candidates** section: table of candidates (action ID, type, status, sample size, rationale)
- **Limitations** section
- Empty sections render gracefully with explanatory messages

### 5. Store

- Added `save_strategy_improvement_result()` function (separate from `save_result()` because `StrategyImprovementLoopResult` does not extend `StructuredResult`)
- Serialization handles dataclass nesting via `dataclasses.asdict()`, datetime via `.isoformat()`, and enum via `.value`
- Filename pattern: `strategy_improvement_{timestamp}.json`

### 6. CLI

- `diagnose-trade` subcommand: `<symbol> <trading_date> [--log-source]` -- runs single-trade diagnostic lookup and prints result
- `strategy-improvement-loop` subcommand: `[--symbol] [--pattern] [--start-date] [--end-date] [--max-trades] [--log-source]` -- loads reviews, runs full loop, prints markdown report and saves result

### 7. Tools

- `run_trade_diagnostic_tool` with `@tool` decorator and full docstring (required by LangChain's `parse_docstring=True`)
- `run_strategy_improvement_loop_tool` with `@tool` decorator and full docstring

### 8. Package exports

12 new exports added to `__init__.py`:
- `OpportunityQuality`, `ExecutionQuality`, `ExtractionQuality`, `OverallGrade`
- `PrimaryFailureReason`, `ImprovementDirection`, `StrategyActionType`, `StrategyActionStatus`
- `TradeDiagnosticResult`, `AggregatePattern`, `StrategyActionCandidate`, `StrategyImprovementLoopResult`

## Behavioral Consequences

### Diagnostic decomposition captures three independent quality dimensions
- A trade can be `invalid` opportunity but `excellent` execution (the trader executed well on a bad idea)
- A trade can be `valid` opportunity but `poorly_extracted` (good idea, left money on the table)
- Profitability alone does not determine any single dimension
- The composite grade (A-E) provides a single-value summary without hiding the decomposition

### Strategy candidates require aggregate backing
- A single trade's diagnostic suggests an action type but cannot produce a `minimum_sample_size_met=True` candidate
- 2 trades sharing a failure reason produce a `proposed` candidate
- 3+ trades sharing a failure reason produce a `verified_candidate`
- This mirrors P2's claim-to-recommendation gating: single observations inform, cohort patterns recommend

### Single-trade diagnostics are diagnostic-first, not prescriptive
- A single trade may diagnose problems (grade D or E, specific failure reasons)
- But a single trade cannot directly create a supported strategy recommendation
- This prevents knee-jerk strategy changes from one bad trade

### All existing behavior unchanged
- P0 structured core: claims, evidence, findings, recommendations, verification
- P1 invariants: boundary checks, sample-size rules, recommendation gating
- P2 aggregation: multi-trade review pipeline
- 52 existing tests pass without modification

## Files Changed

### Source files created
- `backend/src/trading_research/diagnostic_service.py` -- pure diagnostic computation (323 lines)
- `backend/src/trading_research/strategy_improvement_service.py` -- orchestration + pattern extraction + candidate generation (258 lines)

### Source files modified
- `backend/src/trading_research/models.py` -- `WorkflowKind`, 8 StrEnum classes, 4 dataclasses (287 lines total)
- `backend/src/trading_research/report_service.py` -- `build_strategy_improvement_markdown()`
- `backend/src/trading_research/store.py` -- `save_strategy_improvement_result()`
- `backend/src/trading_research/cli.py` -- `diagnose-trade` and `strategy-improvement-loop` subcommands
- `backend/src/trading_research/tools.py` -- `run_trade_diagnostic_tool` and `run_strategy_improvement_loop_tool`
- `backend/src/trading_research/__init__.py` -- 12 new exports

### Source files NOT modified (intentionally)
- `backend/src/trading_research/evidence_service.py` -- P3 diagnostic service is pure computation, no evidence registration needed
- `backend/src/trading_research/verifier_service.py` -- must NOT be modified; strategy action candidates use their own sample-size gating
- `backend/src/trading_research/aggregate_review_service.py` -- P3 does not modify existing aggregation
- `backend/src/trading_research/trade_review_service.py` -- single-trade review behavior unchanged
- `backend/src/trading_research/setup_research_service.py` -- out of scope

### Test files created
- `backend/tests/test_trading_research/test_strategy_improvement.py` -- 20 tests across 6 categories (692 lines)

### Audit
- `audit/p3_strategy_improvement_plan.md` -- the spec (unchanged)
- `audit/p3_strategy_improvement_completion_report.md` -- this file

## Tests

### New tests: strategy improvement (20)

**A. Single-trade diagnostic decomposition (6)**
- `test_good_trade_gets_high_grades` -- valid opportunity + excellent execution + fully extracted = grade A
- `test_dimensions_are_independent_invalid_but_profitable` -- invalid opportunity + excellent execution (independent dimensions)
- `test_valid_but_unprofitable` -- valid opportunity + poor execution + poorly extracted
- `test_missing_claims_produce_honest_defaults` -- missing claims produce marginal/acceptable defaults, not crashes
- `test_missing_result_id_returns_none` -- missing result_id returns None from diagnose_single
- `test_grade_computation_a_through_e` -- each grade level A through E is reachable

**B. Failure/improvement diagnostics (5)**
- `test_diagnose_many` -- batch diagnostic produces correct count
- `test_avoid_point_for_invalid_opportunity` -- earliest_avoid_point = "pre_trade_selection" for invalid opportunity
- `test_minimize_loss_point_for_poor_extraction` -- earliest_minimize_loss_point = "exit_management" for poor extraction
- `test_action_type_enum_enforcement` -- strategy_action_type is a valid StrategyActionType enum
- `test_failure_reason_matches_worst_dimensions` -- primary failure reason reflects worst quality dimensions

**C. Aggregate pattern extraction (3)**
- `test_repeated_failures_form_patterns` -- 3 trades with same failure reason produce a pattern
- `test_single_trade_does_not_produce_patterns` -- single trade cannot form a pattern (count < 2)
- `test_pattern_sample_size_is_distinct_trades` -- sample_size counts distinct trade IDs, not total occurrences

**D. Strategy action candidate gating (3)**
- `test_candidates_from_aggregate_patterns_only` -- candidates require aggregate pattern backing
- `test_single_trade_cannot_produce_min_met_candidate` -- single trade diagnostic cannot produce minimum_sample_size_met=True
- `test_verified_candidate_requires_three_trades` -- verified_candidate status requires sample_size >= 3
- `test_proposed_status_for_two_trades` -- proposed status for sample_size == 2

**E. Report output (2)**
- `test_report_renders_all_sections` -- diagnostics, patterns, candidates sections all present
- `test_report_renders_empty_sections_gracefully` -- empty diagnostics/patterns/candidates render explanatory messages

**F. End-to-end flow (2)**
- `test_end_to_end_loop` -- full pipeline: saved reviews -> diagnostics -> patterns -> candidates -> report
- `test_end_to_end_loop_with_filters` -- filtering by symbol produces correct subset

### Existing tests unchanged
- All 52 P0+P1+P2 tests continue to pass without modification

## Verification Run

```
$ cd backend && uv run pytest tests/test_trading_research/ -v
74 passed in 0.73s
```

Zero failures. Zero skips. 52 original + 22 new = 74 total.

## Bug Found and Fixed During Testing

The two end-to-end tests (`test_end_to_end_loop`, `test_end_to_end_loop_with_filters`) initially patched `src.trading_research.strategy_improvement_service._RESULTS_DIR` to redirect the store directory. However, `strategy_improvement_service.py` does not have a `_RESULTS_DIR` attribute -- it calls `list_saved_results()` and `load_saved_result()` from `store.py`, which owns `_RESULTS_DIR`.

**Fix**: Removed the non-existent patch on `strategy_improvement_service._RESULTS_DIR` and kept only the `store._RESULTS_DIR` patch. Both tests now pass.

## Invariants Preserved

| Invariant | Status | Notes |
|---|---|---|
| Boundary checks on evidence timing | Preserved | P3 does not register evidence; diagnostic service is pure computation |
| Sample-size downgrade rules | Preserved | Verifier service not modified |
| `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2` | Preserved | Strategy candidates reference same threshold conceptually |
| `MIN_RECOMMENDATION_SAMPLE_SIZE = 3` | Preserved | `MIN_VERIFIED_SAMPLE_SIZE = 3` mirrors this for candidates |
| `SAMPLE_SIZE_CONFIDENCE_CAP = 0.49` | Preserved | Not applicable to P3 (candidates have their own confidence) |
| Recommendation requires surviving `supported` claim | Preserved | P3 candidates use their own gating, not the claim-recommendation path |
| Single-trade review produces `verifier.passed=False` | Preserved | No changes to single-trade path |
| Deterministic verifier | Preserved | `verifier_service.py` not modified |
| Single-trade diagnostic cannot produce strategy recommendation | Enforced | New invariant: candidates require aggregate pattern backing |

## Known Limitations

- Diagnostic decomposition depends on saved ReviewResult metadata fields (`quality_tier`, `overall_verdict`, `outcome`). Older results missing these fields produce honest defaults (`marginal`, `acceptable`, `poorly_extracted`), not crashes.
- Pattern extraction operates only on structured enum fields. No prose re-interpretation or semantic analysis is performed.
- Strategy action candidates are computed fresh each time. No persistent version history or manual status transitions in P3.
- The `StrategyImprovementLoopResult` does not extend `StructuredResult`, so it uses a separate `save_strategy_improvement_result()` function rather than the generic `save_result()`.
- basedpyright emits `Unknown` type warnings for `dict[str, object]` `.get()` calls in `diagnostic_service.py`. This is the same pattern as in `aggregate_review_service.py` and does not affect runtime behavior.
- With fewer than 2 trades sharing any diagnostic value, no patterns are extracted and no candidates are generated. The report shows diagnostics only, which is correct behavior.

## What Still Remains Beyond P3

- Semantic verification or human review checkpoints
- Broader agent topology (market regime agent, catalyst/news agent)
- Cross-result consistency checks
- Frontend integration for strategy improvement results
- Persistent strategy version history and manual status transitions
- Automated strategy improvement scheduling
- Integration with actual trading system rule updates

## Honest Verdict

The P3 strategy improvement loop is real and functional:

1. **Diagnostic decomposition captures independent quality dimensions.** A trade is not just "good" or "bad" -- it has separate opportunity, execution, and extraction qualities. An invalid-but-well-executed trade is representable. A valid-but-poorly-extracted trade is representable. The composite grade summarizes without hiding the decomposition.

2. **Strategy candidates require aggregate backing.** A single bad trade suggests where to look (diagnostic) but cannot prescribe a strategy change (candidate). Only when multiple trades show the same failure pattern does a candidate emerge. This prevents reactive over-fitting to individual trades.

3. **All P0/P1/P2 invariants are preserved.** The verifier was not modified. Boundary checks, sample-size rules, and recommendation gating apply to the existing claim pipeline exactly as before. The strategy improvement loop operates as a parallel analysis path, not a replacement.

4. **No services were weakened.** `evidence_service.py`, `verifier_service.py`, `trade_review_service.py`, `aggregate_review_service.py`, and `setup_research_service.py` were not touched. The diagnostic and strategy improvement services are pure extensions.
