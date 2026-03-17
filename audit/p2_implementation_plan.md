# P2 Implementation Plan

## Scope Lock

This pass implements one narrow capability:

**Multi-trade aggregation pipeline that produces recommendation-eligible claims.**

Specifically:
1. Aggregated trade review input contract
2. Aggregated review result model
3. Deterministic grouping and aggregate statistics from structured fields only
4. Sample-size semantics: `sample_size = distinct contributing trade count`
5. Recommendation gating: only from verified aggregate claims
6. Evidence model for aggregation (narrow extension of existing evidence system)
7. Report rendering for aggregate results
8. CLI entrypoint

Out of scope:
- New agents
- UI / frontend
- Slack / OpenClaw / channels
- Setup research changes
- Semantic fact-checking
- Repo-wide refactors
- Loosening P1 thresholds
- Prose-based or LLM-derived aggregation (all aggregation is from structured fields)

## Current State

After P1:
- Single-trade `ReviewResult` claims have `sample_size=1`
- All claims downgrade to `observation` (threshold is 2)
- All recommendations are suppressed (threshold is 3)
- `verifier.passed = False` for every single-trade review
- This is intentional and correct

The system has no path to produce claims with `sample_size ≥ 2`. P2 creates that path.

## Design

### What gets aggregated

The aggregation consumes **already-computed `ReviewResult` objects**, not raw `TradeReview` objects. This means:
- Each single-trade review has already run through evidence registration, claim building, and the verifier
- The aggregate layer reads structured fields from `ReviewResult` — it does not re-invoke the underlying `DecisionReviewService`
- The aggregate layer does NOT re-interpret prose or observations — it only uses structured fields

### Grouping strategy

Group by a deterministic key derived from structured fields:

Primary key: `setup_type` (derived from `result.metadata["pattern"]`)
Optional refinement: `symbol` (if filtering to a single symbol)

The grouping key is explicit in the output so the consumer knows exactly what was grouped.

### What aggregate metrics are derivable

From `ReviewResult.metadata` (all structured, set by `trade_review_service.py`):
- `quality_tier` → count by tier
- `overall_verdict` → count by verdict, win/loss classification
- `pattern` → the grouping key itself

From `ReviewResult.claims` (structured fields):
- Per claim type (selection, entry, exit, failure, overall): count how many reviews produced each claim type and what the claim statement distribution looks like
- Confidence values → mean/median confidence per claim type

From `ParsedTrade` properties exposed in evidence (structured):
- `pnl_pct` → derivable from entry/exit prices in evidence provenance
- `outcome` → from `metadata["overall_verdict"]` mapping

What is NOT available and will NOT be faked:
- MAE/MFE (not in current structured output)
- Hold duration (not in current structured output, though derivable from entry/exit timestamps if both exist)
- News impact (not structured)

### Sample-size semantics

Hard rule: `sample_size` for an aggregate claim = number of distinct `result_id` values contributing to that claim.

NOT:
- Number of evidence fragments (a single trade can produce multiple evidence items)
- Number of claim instances (each trade produces one claim per type)

The aggregate service tracks contributing `result_id` values per claim and sets `sample_size = len(contributing_result_ids)`.

### Recommendation rules

1. Aggregate recommendations are only produced when aggregate claims survive the verifier
2. The existing verifier runs unchanged — it checks sample_size ≥ 2 for supported claims, ≥ 3 for recommendation eligibility
3. Recommendation text references the aggregate pattern, not individual trade hindsight
4. If fewer than 3 trades contribute, the aggregate claims exist as observations but no recommendations are produced

### Evidence model for aggregation

New evidence types (narrow):
- `aggregate_metric` — structured summary statistic (e.g., "3/5 trades had verdict=good_trade")
- `cohort_summary` — overall cohort metadata (trade count, date range, grouping key)

These use the existing `EvidenceItem` model and `EvidenceService`. No new persistence layer.

Provenance for aggregate evidence includes:
- `contributing_result_ids: list[str]` — which trade reviews contributed
- `grouping_key: str` — e.g., `"strong_uptrending"` or `"AMPX:strong_uptrending"`
- `record_type: "aggregate_metric"` or `"cohort_summary"`

Evidence IDs are deterministic via the existing hash (content + provenance + source_ref).

### Boundary time for aggregate results

`boundary_time` = latest `boundary_time` across all contributing `ReviewResult` objects. This is the most conservative choice — the aggregate cannot be more recent than its newest input.

Claim-level `boundary_time` = same (latest contributing result boundary).

## Files to Change

### New file

**`backend/src/trading_research/aggregate_review_service.py`**
- Reason: Aggregation logic is a distinct responsibility from single-trade review. Putting it in `trade_review_service.py` would bloat that file and blur boundaries.
- Contains: `AggregateReviewService` class, `AggregatedTradeReviewRequest` dataclass, aggregation logic, aggregate claim/finding/recommendation builders
- Depends on: `models.py`, `evidence_service.py`, `verifier_service.py`, `store.py`
- Does NOT depend on: `trade_review_service.py` (it consumes `ReviewResult`, not `TradeReviewService`)

### Modified files

**`backend/src/trading_research/models.py`**
- Add `WorkflowKind.AGGREGATE_TRADE_REVIEW = "aggregate_trade_review"`
- Add `EvidenceSourceType.AGGREGATE_METRIC = "aggregate_metric"` and `EvidenceSourceType.COHORT_SUMMARY = "cohort_summary"`
- Add `AggregatedReviewResult(StructuredResult)` dataclass with:
  - `trade_count: int`
  - `contributing_result_ids: list[str]`
  - `grouping_key: str`
  - `date_range_start: date | None`
  - `date_range_end: date | None`
  - `symbol: str` (empty if multi-symbol)
  - `cohort_stats: dict[str, object]` (structured aggregate metrics)

**`backend/src/trading_research/report_service.py`**
- Add `build_aggregate_review_markdown(result, evidence_service)` function
- Renders: Cohort Summary, Findings, Claims, Recommendations, Evidence References, Verifier Summary, Limitations
- Cohort Summary section shows: trade count, grouping key, date range, contributing result IDs, cohort stats

**`backend/src/trading_research/store.py`**
- Add `AggregatedReviewResult` to the `_filename_for` function so it can be saved
- Import `AggregatedReviewResult` from models

**`backend/src/trading_research/cli.py`**
- Add `aggregate-trade-review` subcommand
- Arguments: `--symbol`, `--pattern`, `--start-date`, `--end-date`, `--max-trades`, `--log-source`
- Loads saved single-trade review results from the store, filters, aggregates, renders

**`backend/src/trading_research/tools.py`**
- Add `run_aggregate_trade_review` tool wrapper (small, consistent with existing tools)

**`backend/src/trading_research/__init__.py`**
- Export new model types

### Files NOT changed

- `evidence_service.py` — No changes. The existing `register()` handles the new evidence types via existing `EvidenceItem` model.
- `verifier_service.py` — No changes. The existing verifier already handles sample_size, boundary, and recommendation gating correctly. Aggregate results will produce claims with real sample_size values that the verifier checks with existing thresholds.
- `setup_research_service.py` — Out of scope.
- `trade_review_service.py` — Not modified. The aggregate service consumes `ReviewResult` objects, not `TradeReviewService`.

## AggregatedTradeReviewRequest Contract

```python
@dataclass
class AggregatedTradeReviewRequest:
    trade_result_ids: list[str] | None = None   # explicit result IDs to aggregate
    symbol: str | None = None                    # filter to single symbol
    pattern: str | None = None                   # filter to setup pattern (grouping key)
    start_date: date | None = None               # filter by trading date range
    end_date: date | None = None
    max_trades: int | None = None                # cap number of trades
    log_source: str | None = None                # filter by log source
    aggregation_mode: str = "by_pattern"         # "by_pattern" or "by_symbol_pattern"
```

When `trade_result_ids` is provided, those exact results are loaded.
When `trade_result_ids` is None, the service scans saved results in the store, filtered by the other fields.

## Aggregate Claim Types

For each unique claim type present in the contributing reviews:
- `agg_claim_verdict_{grouping_key}` — aggregate verdict distribution
- `agg_claim_selection_{grouping_key}` — aggregate selection pattern (how often should_trade was True)
- `agg_claim_entry_{grouping_key}` — aggregate entry quality pattern
- `agg_claim_exit_{grouping_key}` — aggregate exit policy pattern

Each aggregate claim:
- `sample_size` = number of distinct contributing trades
- `confidence` = mean confidence across contributing claims of that type
- `evidence_ids` = the aggregate evidence items created for this claim
- `boundary_time` = latest boundary from contributing results

## Recommendation Types

Only produced when aggregate claims survive verification:

- `agg_rec_selection_{key}` — "Based on N trades, tighten/keep selection filters for {pattern} setups"
- `agg_rec_entry_{key}` — "Based on N trades, entry timing is/isn't consistently suboptimal for {pattern} setups"
- `agg_rec_exit_{key}` — "Based on N trades, {policy} is the most frequently recommended exit policy for {pattern} setups"

Each recommendation:
- References aggregate claim IDs
- References aggregate evidence IDs
- Text explicitly states the sample size and pattern, not individual trade hindsight

## What Will NOT Be Changed

- P1 verifier thresholds (`MIN_SUPPORTED_CLAIM_SAMPLE_SIZE=2`, `MIN_RECOMMENDATION_SAMPLE_SIZE=3`, `SAMPLE_SIZE_CONFIDENCE_CAP=0.49`)
- P1 boundary enforcement
- Single-trade review behavior (still produces `sample_size=1`, still downgrades, still no recommendations)
- Evidence hash algorithm
- Evidence service internals
- Verifier service internals
- Setup research (out of scope)

## Risks / Compatibility Notes

### Risk 1: Store may have no saved results
- The aggregate service must handle the case where the store has zero or insufficient matching results
- Return an empty aggregate result with appropriate limitations, not a crash

### Risk 2: Aggregation of 2 trades produces claims but not recommendations
- With `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE=2`, claims survive as `supported`
- But `MIN_RECOMMENDATION_SAMPLE_SIZE=3`, so recommendations still get dropped
- This is correct and expected — 2 trades is enough for a supported claim but not for a recommendation
- The aggregate report will show supported claims without recommendations

### Risk 3: Store format is JSON dicts, not typed objects
- `load_saved_result()` returns `dict[str, object] | None`
- The aggregate service needs to deserialize these back into `ReviewResult` objects
- A narrow `_load_review_result(data: dict)` helper is needed

### Risk 4: Grouping key depends on metadata["pattern"]
- If a saved result has no `pattern` in metadata, it groups under `"unclassified"`
- This is honest, not a bug

### Risk 5: Existing golden tests must not break
- Single-trade review golden flows must remain exactly as they are
- New aggregate golden flow test will be added

## Execution Order

1. `models.py` — add workflow kind, evidence source types, `AggregatedReviewResult`
2. `aggregate_review_service.py` — new file with aggregation logic
3. `report_service.py` — add aggregate report rendering
4. `store.py` — add `AggregatedReviewResult` to filename generation
5. `cli.py` — add `aggregate-trade-review` subcommand
6. `tools.py` — add aggregate tool wrapper
7. `__init__.py` — export new types
8. Tests — new aggregate tests + verify existing tests still pass
9. `audit/p2_completion_report.md`

## Test Requirements

### A. Aggregation core
- Multiple `ReviewResult` objects can be aggregated deterministically
- Aggregate claim `sample_size` equals distinct contributing trade count
- Duplicate results from the same trade do not inflate sample_size (deduplicated by result_id)
- Empty input produces empty aggregate result with limitations

### B. Recommendation gating
- Aggregate with ≥ 3 trades produces recommendations (if claims survive verifier)
- Aggregate with 2 trades produces supported claims but no recommendations
- Aggregate with 1 trade behaves like single-trade review (claims downgraded)
- Single-trade review behavior is unchanged

### C. Report output
- Aggregate report includes cohort summary section
- Report shows trade count and grouping key
- Report distinguishes supported aggregate claims from downgraded observations

### D. Golden-path regression
- Existing single-trade review golden flow unchanged
- New aggregate-review golden path passes end-to-end

That is the entire plan.
