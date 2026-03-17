# P2 Completion Report

## Scope

Multi-trade aggregation pipeline added to the structured trading research core. This creates a valid path to recommendation-eligible claims (sample_size ≥ 2) without weakening the P0/P1 invariants that intentionally suppress single-trade recommendations.

No new agents, no UI work, no repo-wide refactors. The P0 structured core and P1 invariants remain intact.

## Completed Items

### 1. Models

- `WorkflowKind.AGGREGATE_TRADE_REVIEW = "aggregate_trade_review"` — new workflow kind
- `EvidenceSourceType.AGGREGATE_METRIC = "aggregate_metric"` — for distribution/pattern evidence
- `EvidenceSourceType.COHORT_SUMMARY = "cohort_summary"` — for cohort overview evidence
- `AggregatedReviewResult(StructuredResult)` — new result type with: `trade_count`, `contributing_result_ids`, `grouping_key`, `date_range_start`, `date_range_end`, `symbol`, `cohort_stats`

### 2. Aggregate Review Service

New file: `aggregate_review_service.py` (632 lines).

#### Request model
- `AggregatedTradeReviewRequest` with: `trade_result_ids`, `symbol`, `pattern`, `start_date`, `end_date`, `max_trades`, `log_source`, `aggregation_mode`

#### Pipeline
1. **Load**: Reads saved trade review results from store (by explicit IDs or filtered scan)
2. **Dedup**: By `result_id` to prevent double-counting
3. **Cap**: Optional `max_trades` limit
4. **Group**: By `pattern` (default) or `symbol:pattern`
5. **Cohort stats**: Verdict, pattern, quality, and outcome distributions
6. **Evidence**: Registers `cohort_summary` + `verdict_distribution` + per-claim-type pattern evidence via existing `EvidenceService`
7. **Findings**: Cohort overview finding with evidence linkage
8. **Claims**: Verdict claim + per-type (selection, entry, exit) claims with `sample_size` = distinct trade count
9. **Recommendations**: Pattern-level action text referencing sample size
10. **Verify**: Runs through existing `VerifierService` — boundary checks, sample-size rules, recommendation gating all apply

#### Key design decisions
- `sample_size` = number of distinct `result_id` values contributing (not evidence fragment count)
- `boundary_time` = latest `boundary_time` across all contributing ReviewResults (most conservative)
- Evidence timestamps (`observed_at`, `effective_start`, `effective_end`) = `result_boundary` (not `datetime.now()`), ensuring aggregate evidence stays within the temporal scope of the contributing reviews and passes boundary verification
- Only structured fields are aggregated — no prose re-interpretation
- Internal `_LoadedReview` dataclass handles deserialization from `dict[str, object]` store format
- `isinstance` guards + accumulator loops used instead of generator expressions for basedpyright type-narrowing compatibility

### 3. Report Service

Added `build_aggregate_review_markdown()`:
- Cohort Summary section: trade count, grouping key, symbol, date range, contributing result IDs, cohort stats
- Reuses `_append_common_sections()` for Findings, Claims, Recommendations, Evidence, Verifier, Limitations

### 4. Store

- `AggregatedReviewResult` added to imports
- `_filename_for()` generates filenames like `aggregate_trade_review_{key}_{timestamp}.json`

### 5. CLI

- `aggregate-trade-review` subcommand with arguments: `--symbol`, `--pattern`, `--start-date`, `--end-date`, `--max-trades`, `--log-source`, `--mode`

### 6. Tools

- `run_aggregate_trade_review_tool` with `@tool` decorator and full docstring (required by LangChain's `parse_docstring=True`)

### 7. Package exports

- `AggregatedReviewResult` added to `__init__.py` imports and `__all__`

## Behavioral Consequences

### Multi-trade aggregation now produces recommendation-eligible results
- 3+ trades → claims have `sample_size ≥ 3` → claims stay `supported` → recommendations survive verifier
- 2 trades → claims have `sample_size = 2` → claims stay `supported` → recommendations dropped (below `MIN_RECOMMENDATION_SAMPLE_SIZE`)
- 1 trade → claims have `sample_size = 1` → claims downgraded to `observation` → recommendations dropped

### Single-trade review behavior unchanged
- All single-trade claims still have `sample_size=1` and downgrade — this is correct P1 behavior
- The aggregate pipeline is the intended path to stronger claims, not a loosening of single-trade rules

### P1 invariants preserved
- Boundary checks: aggregate evidence uses `result_boundary` timestamps, passing boundary verification
- Sample-size rules: aggregate claims carry real `sample_size` from distinct trade count
- Recommendation gating: verifier still drops recommendations when supporting claims are weak
- Deterministic verifier: no changes to `verifier_service.py`

## Files Changed

### Source files created
- `backend/src/trading_research/aggregate_review_service.py` — aggregation pipeline (632 lines)

### Source files modified
- `backend/src/trading_research/models.py` — `WorkflowKind`, `EvidenceSourceType`, `AggregatedReviewResult`
- `backend/src/trading_research/report_service.py` — `build_aggregate_review_markdown()`
- `backend/src/trading_research/store.py` — `AggregatedReviewResult` in imports and `_filename_for()`
- `backend/src/trading_research/cli.py` — `aggregate-trade-review` subcommand
- `backend/src/trading_research/tools.py` — `run_aggregate_trade_review_tool`
- `backend/src/trading_research/__init__.py` — `AggregatedReviewResult` export

### Source files NOT modified (intentionally)
- `backend/src/trading_research/evidence_service.py` — existing `register()` and `register_many()` handle new evidence types without changes
- `backend/src/trading_research/verifier_service.py` — existing thresholds and boundary checks work correctly for aggregate results
- `backend/src/trading_research/trade_review_service.py` — single-trade behavior unchanged
- `backend/src/trading_research/setup_research_service.py` — out of scope

### Test files created
- `backend/tests/test_trading_research/test_aggregate_review_service.py` — 13 tests across 6 categories

### Test files modified
- `backend/tests/test_trading_research/test_golden_flows.py` — added `test_aggregate_review_golden_flow`
- `backend/tests/test_trading_research/test_cli.py` — added `test_cli_aggregate_trade_review_path_executes`
- `backend/tests/test_trading_research/test_tools.py` — added `test_run_aggregate_trade_review_tool_returns_rendered_markdown`
- `backend/tests/test_trading_research/test_store.py` — added `test_store_saves_aggregate_review_result`
- `backend/tests/test_trading_research/test_report_service.py` — added `test_aggregate_report_renders_cohort_summary`

### Audit
- `audit/p2_implementation_plan.md` — the spec (unchanged)
- `audit/p2_completion_report.md` — this file

## Tests

### New tests: aggregate review service (13)

**A. Aggregation core (4)**
- `test_deterministic_aggregation_with_three_trades`
- `test_sample_size_equals_distinct_trade_count`
- `test_dedup_by_result_id`
- `test_empty_input_produces_empty_result`

**B. Recommendation gating (3)**
- `test_three_trades_can_produce_recommendations`
- `test_two_trades_produce_supported_claims_but_no_recommendations`
- `test_one_trade_downgrades_all_claims`

**C. Filtering (3)**
- `test_symbol_filter`
- `test_max_trades_cap`
- `test_explicit_result_ids`

**D. Cohort stats (1)**
- `test_cohort_stats_contain_distributions`

**E. Boundary time (1)**
- `test_aggregate_boundary_is_latest_contributing`

**F. Grouping modes (1)**
- `test_by_symbol_pattern_grouping_key`

### New tests: integration (5)
- `test_aggregate_review_golden_flow` (golden flows)
- `test_cli_aggregate_trade_review_path_executes` (CLI)
- `test_run_aggregate_trade_review_tool_returns_rendered_markdown` (tools)
- `test_store_saves_aggregate_review_result` (store)
- `test_aggregate_report_renders_cohort_summary` (report service)

### Existing tests unchanged
- All 34 P0+P1 tests continue to pass without modification

## Verification Run

```
$ cd backend && uv run pytest tests/test_trading_research/ -v
52 passed in 1.54s
```

Zero failures. Zero skips. 34 original + 18 new = 52 total.

## Bug Found and Fixed During Testing

Evidence timestamps were initially set to `datetime.now()` (the time of aggregation), but claim `boundary_time` was set to the latest contributing review's boundary (which could be days earlier). The verifier correctly flagged this as a boundary violation — evidence observed "after" the claim boundary.

**Fix**: Evidence `observed_at`, `effective_start`, `effective_end` now use `result_boundary` (the latest contributing boundary time) instead of `datetime.now()`. This is semantically correct — aggregate evidence is derived from the contributing reviews, so its temporal scope should match theirs.

## Invariants Preserved

| Invariant | Status | Notes |
|---|---|---|
| Boundary checks on evidence timing | Preserved | Aggregate evidence uses `result_boundary` timestamps |
| Sample-size downgrade rules | Preserved | Aggregate claims carry real `sample_size` from distinct trade count |
| `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2` | Preserved | 1-trade aggregates still downgrade |
| `MIN_RECOMMENDATION_SAMPLE_SIZE = 3` | Preserved | 2-trade aggregates lose recommendations |
| `SAMPLE_SIZE_CONFIDENCE_CAP = 0.49` | Preserved | Downgraded claims still get capped |
| Recommendation requires surviving `supported` claim | Preserved | Verifier still enforces this |
| Single-trade review produces `verifier.passed=False` | Preserved | No changes to single-trade path |
| Deterministic verifier | Preserved | `verifier_service.py` not modified |

## Known Limitations

- Aggregate results depend on saved trade review results in the store. If trade reviews are not persisted, there is nothing to aggregate.
- Grouping is by `pattern` (or `symbol:pattern`). More sophisticated grouping (e.g., by time period, by quality tier) is possible but not implemented.
- The aggregate pipeline only uses structured fields from saved results. If a trade review's metadata lacks `pattern`, `overall_verdict`, `quality_tier`, or `outcome`, those fields default to `"unclassified"` / `"unknown"`.
- Evidence deduplication in the aggregate pipeline is by `result_id`, not by content hash. Running the same aggregation twice creates new evidence items (the evidence service deduplicates by provenance hash, but the aggregate service's provenance includes the grouping key which is deterministic, so repeated runs with the same inputs produce the same evidence IDs).
- No semantic fact-checking was added. The verifier remains deterministic and structural.
- basedpyright emits warnings about `dict[str, object]` type narrowing in the aggregate service. These are pre-existing patterns from the store's `load_saved_result()` return type and do not affect runtime behavior.

## What Still Remains Beyond P2

- Semantic verification or human review checkpoints
- Broader agent topology (market regime agent, catalyst/news agent)
- Cross-result consistency checks (comparing claims across multiple research runs)
- Frontend integration for aggregate results display
- Time-series trend analysis across aggregated cohorts
- Automated aggregation scheduling (e.g., nightly cohort summaries)
- Documentation for the structured trading research workflow

## Honest Verdict

The P2 multi-trade aggregation pipeline is real and functional:

1. **The aggregate path produces recommendation-eligible results.** Three or more trades in a cohort produce claims with `sample_size ≥ 3` that survive the verifier and keep their recommendations. This is the intended design — single observations inform, cohort patterns recommend.

2. **P1 invariants are preserved unconditionally.** The verifier was not modified. Boundary checks, sample-size rules, and recommendation gating apply identically to aggregate results. The only difference is that aggregate claims have real sample sizes, so they pass thresholds that single-trade claims cannot.

3. **No services were weakened.** `evidence_service.py`, `verifier_service.py`, `trade_review_service.py`, and `setup_research_service.py` were not touched. The aggregate pipeline is a pure extension that adds a new workflow kind, new evidence source types, and a new result type — all consumed by the existing verification infrastructure.
