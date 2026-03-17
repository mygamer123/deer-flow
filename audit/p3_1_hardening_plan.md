# P3.1 Implementation Plan: Strategy Improvement Loop Hardening

## Scope Lock

This pass hardens three structural weaknesses in the existing P3 strategy-improvement loop **without rewriting P3**:

1. **Claim-backed strategy action candidates** — candidates must be tied to verified aggregate claims that survived the verifier, not just pattern IDs/trade IDs
2. **Reduce heuristic/substring dependence in diagnostics** — prefer structured metadata fields over substring matching in claim statements
3. **Lightweight strategy change records** — persist strategy candidates as `StrategyChangeRecord` objects, not just transient report objects

Plus report hardening (show the full chain: diagnostics → patterns → verified claims → candidates → change records) and minimal CLI additions.

Out of scope:
- Real order execution
- UI / frontend
- Slack / OpenClaw / channels
- Setup research changes
- Semantic fact-checking
- Repo-wide refactors
- Loosening P1 thresholds
- Modifying `verifier_service.py`
- Prose-based or LLM-derived aggregation
- Building a second parallel truth system

## Current State

After P3:
- 74 tests pass (34 P0+P1 + 18 P2 + 22 P3)
- `StrategyActionCandidate` has `supported_by_pattern_ids` and `supported_by_trade_ids` but **no claim linkage**
- Candidates are gated purely by pattern sample size, disconnected from whether any aggregate claims survived the verifier
- `DiagnosticService` uses substring matching on claim statements for two of three quality dimensions (opportunity: `"should have been taken" in statement`, execution: `"suboptimal" in statement`)
- Extraction quality already uses structured fields (`outcome`, `overall_verdict`) — no substring matching there
- `StrategyImprovementLoopResult` does NOT extend `StructuredResult` — it has its own `save_strategy_improvement_result()` in `store.py`
- P3's `StrategyImprovementService` never calls `AggregateReviewService` or checks whether aggregate claims exist/survived

## Design

### H1: Claim-backed strategy action candidates

**Problem**: `StrategyActionCandidate` has `supported_by_pattern_ids` and `supported_by_trade_ids` but no connection to verified aggregate claims. A candidate could be emitted even though no aggregate claim on the same topic survived the verifier.

**Solution**: Add `supported_by_claim_ids: list[str]` to `StrategyActionCandidate`. Bridge the P3 service to P2 aggregate claims by:

1. After running diagnostics and extracting patterns, the `StrategyImprovementService` calls `AggregateReviewService.aggregate()` on the same set of trade reviews
2. The aggregated result contains verified claims (`agg_claim_verdict_*`, `agg_claim_selection_*`, `agg_claim_entry_*`, `agg_claim_exit_*`) that have been through the verifier
3. The service collects surviving claim IDs (claims with `status == supported` after the verifier ran)
4. When generating candidates, each candidate checks whether a related aggregate claim exists and survived:
   - `add_pretrade_filter` → needs a surviving `agg_claim_selection_*` claim
   - `refine_entry_rule` → needs a surviving `agg_claim_entry_*` claim
   - `refine_exit_rule` / `refine_stop_rule` → needs a surviving `agg_claim_exit_*` claim
   - `tighten_risk_rule` → needs any surviving aggregate claim
   - `collect_more_samples` → no claim required (explicitly about insufficient data)
5. If a candidate's required claim did not survive, the candidate is **downgraded** to `NEEDS_MORE_SAMPLES` status (not rejected — it may need more data, not necessarily wrong)
6. `supported_by_claim_ids` is populated with the matching surviving claim IDs

**Backward compatibility**: The new field defaults to `field(default_factory=list)`. Existing candidates without claim backing still work — they just have empty `supported_by_claim_ids`. The aggregate bridge is optional: if no aggregate result is available (e.g., no trade reviews match), candidates proceed with pattern-only backing but cannot achieve `VERIFIED_CANDIDATE` status.

**What will NOT change**: The verifier itself is not modified. The aggregate service is used as-is. Pattern extraction logic is unchanged. The diagnostic service decomposition is unchanged.

### H2: Reduce heuristic/substring dependence in diagnostics

**Problem**: Two derivation functions rely on substring matching in claim statements:
- `_derive_opportunity_quality` (line 109): `"should have been taken" in statement`
- `_derive_execution_quality` (line 123): `"suboptimal" in statement`

This is fragile — if claim statement wording changes, diagnostics silently degrade.

**Solution**: Add structured metadata fields to the derivation inputs, with substring matching as a fallback:

1. **Opportunity quality**: Check claim `metadata.get("should_trade")` first (a boolean set during trade review). If metadata field exists, use it directly. If not present, fall back to existing substring matching. This is a graceful migration — old saved reviews use substrings, new ones use structured fields.

2. **Execution quality**: Check claim `metadata.get("execution_rating")` first (a string like "optimal", "suboptimal", "poor" set during trade review). If metadata field exists, use it directly. If not present, fall back to existing substring matching.

**Implementation approach**: The `_derive_opportunity_quality` and `_derive_execution_quality` functions gain a metadata-first path with existing substring logic as fallback. No existing test expectations change because the test data either has or doesn't have the metadata fields — both paths produce the same results.

**What will NOT change**: Extraction quality derivation (already uses structured fields). The claim format itself. The metadata fields are checked with `.get()` — missing fields gracefully fall through to existing behavior.

### H3: Lightweight strategy change records

**Problem**: Strategy candidates are transient objects inside `StrategyImprovementLoopResult`. There is no way to track which candidates were emitted across multiple loop runs, compare them, or see which persisted.

**Solution**: Add a `StrategyChangeRecord` dataclass that wraps a `StrategyActionCandidate` snapshot with persistence metadata:

```
StrategyChangeRecord:
    record_id: str
    candidate: StrategyActionCandidate  # snapshot of the candidate at creation time
    created_at: datetime
    source_loop_result_id: str  # links back to the StrategyImprovementLoopResult
    source_trade_count: int
    notes: str  # optional human-readable context
```

Persistence:
- Change records are saved to the same `_RESULTS_DIR` as other results, with filename pattern `strategy_change_{record_id}_{timestamp}.json`
- A `save_strategy_change_records()` function saves a list of records from a single loop run
- A `list_strategy_change_records()` function lists saved records
- A `load_strategy_change_record()` function loads a single record

The `StrategyImprovementService.run_loop()` method creates `StrategyChangeRecord` objects for all candidates with `status == VERIFIED_CANDIDATE` and returns them in the result. The result dataclass gains a `change_records: list[StrategyChangeRecord]` field.

**What will NOT change**: Existing `save_strategy_improvement_result()` continues to work. The `StrategyImprovementLoopResult` already persists as a JSON file — change records are a new addition, not a replacement.

### H4: Report hardening

**Problem**: The current strategy improvement report shows diagnostics → patterns → candidates but does not show verified claims or change records. The chain is incomplete.

**Solution**: Add two new sections to `build_strategy_improvement_markdown()`:

1. **Verified Aggregate Claims** (between Patterns and Candidates):
   - Table of surviving aggregate claims (claim_id, statement, status, sample_size, confidence)
   - Shows which claims backed which candidates
   - If no aggregate result was produced: "No aggregate claims were produced (insufficient data for aggregation)."

2. **Strategy Change Records** (after Candidates):
   - Table of change records (record_id, action_type, status, source trades, created_at)
   - If no change records: "No strategy change records were produced."

The result must carry the aggregate claims for the report to render them. Add `verified_claims: list[Claim]` to `StrategyImprovementLoopResult` (default empty).

### H5: Minimal CLI additions

Add a `list-strategy-changes` subcommand that lists saved strategy change records from the store.

## Files to Change

### Modified files

**`backend/src/trading_research/models.py`**
- Add `supported_by_claim_ids: list[str] = field(default_factory=list)` to `StrategyActionCandidate`
- Add `StrategyChangeRecord` dataclass
- Add `change_records: list[StrategyChangeRecord] = field(default_factory=list)` to `StrategyImprovementLoopResult`
- Add `verified_claims: list[Claim] = field(default_factory=list)` to `StrategyImprovementLoopResult`

**`backend/src/trading_research/diagnostic_service.py`**
- Modify `_derive_opportunity_quality()`: check claim `metadata.get("should_trade")` first, fall back to substring
- Modify `_derive_execution_quality()`: check claim `metadata.get("execution_rating")` first, fall back to substring
- No changes to `_derive_extraction_quality()` (already structured)

**`backend/src/trading_research/strategy_improvement_service.py`**
- Add optional `AggregateReviewService` dependency injection to `__init__`
- In `run_loop()`: after extracting patterns, call aggregate service to get verified claims
- In `generate_candidates()`: accept optional verified claims, populate `supported_by_claim_ids`, downgrade candidates without claim backing
- In `run_loop()`: create `StrategyChangeRecord` objects for verified candidates
- Populate `verified_claims` and `change_records` on the result

**`backend/src/trading_research/report_service.py`**
- Add "Verified Aggregate Claims" section to `build_strategy_improvement_markdown()`
- Add "Strategy Change Records" section to `build_strategy_improvement_markdown()`

**`backend/src/trading_research/store.py`**
- Add `save_strategy_change_records()` function
- Add `list_strategy_change_records()` function
- Add `load_strategy_change_record()` function

**`backend/src/trading_research/cli.py`**
- Add `list-strategy-changes` subcommand

**`backend/src/trading_research/__init__.py`**
- Export `StrategyChangeRecord`

### Files NOT changed

- `verifier_service.py` — must NOT be modified
- `evidence_service.py` — change records don't register evidence
- `aggregate_review_service.py` — used as-is, not modified
- `trade_review_service.py` — single-trade review behavior unchanged
- `setup_research_service.py` — out of scope
- `tools.py` — no new tool wrappers in this pass

## Diagnostic Derivation Changes

### Opportunity quality — metadata-first derivation

Current (substring only):
```python
should_trade = "should have been taken" in statement
```

New (metadata-first with fallback):
```python
metadata = selection_claim.get("metadata", {})
should_trade_field = metadata.get("should_trade") if isinstance(metadata, dict) else None

if should_trade_field is not None:
    should_trade = bool(should_trade_field)
else:
    should_trade = "should have been taken" in statement
```

### Execution quality — metadata-first derivation

Current (substring only):
```python
should_have_waited = "suboptimal" in statement
```

New (metadata-first with fallback):
```python
metadata = entry_claim.get("metadata", {})
execution_rating = metadata.get("execution_rating") if isinstance(metadata, dict) else None

if execution_rating is not None:
    should_have_waited = execution_rating in ("suboptimal", "poor")
else:
    should_have_waited = "suboptimal" in statement
```

## Candidate-to-Claim Mapping

| Candidate action_type | Required aggregate claim prefix | Fallback behavior (no claim) |
|---|---|---|
| `add_pretrade_filter` | `agg_claim_selection_` | Downgrade to `NEEDS_MORE_SAMPLES` |
| `refine_entry_rule` | `agg_claim_entry_` | Downgrade to `NEEDS_MORE_SAMPLES` |
| `refine_exit_rule` | `agg_claim_exit_` | Downgrade to `NEEDS_MORE_SAMPLES` |
| `refine_stop_rule` | `agg_claim_exit_` | Downgrade to `NEEDS_MORE_SAMPLES` |
| `tighten_risk_rule` | any surviving claim | Downgrade to `NEEDS_MORE_SAMPLES` |
| `collect_more_samples` | none required | No downgrade (explicitly about needing more data) |
| `no_change` | none required | No downgrade (no action needed) |

## Risks / Compatibility Notes

### Risk 1: Aggregate service has side effects (evidence registration)
- `AggregateReviewService.aggregate()` registers evidence items via `EvidenceService`
- P3.1 calls this same service, which will register duplicate evidence if aggregate was already run
- Mitigation: `EvidenceService.register()` is idempotent by evidence_id. The aggregate service generates deterministic evidence IDs from grouping_key. Re-registration overwrites with the same data.

### Risk 2: Aggregate service needs matching reviews
- P3's `StrategyImprovementService` and P2's `AggregateReviewService` both load reviews from the store. They use different filter structures (`StrategyImprovementRequest` vs `AggregatedTradeReviewRequest`).
- Mitigation: P3.1 constructs an `AggregatedTradeReviewRequest` from the `StrategyImprovementRequest` fields. Both have the same filter parameters (symbol, pattern, start_date, end_date, max_trades, log_source).

### Risk 3: Existing P3 tests rely on `generate_candidates()` signature
- Adding verified claims as a parameter changes the signature
- Mitigation: Use `verified_claims: list[Claim] | None = None` as optional parameter with default None. Existing calls without claims still work — candidates just won't have claim backing and won't be downgraded.

### Risk 4: `StrategyImprovementLoopResult` gains new fields
- Adding `verified_claims` and `change_records` with `field(default_factory=list)` is backward compatible
- Existing code that constructs `StrategyImprovementLoopResult` without these fields continues to work
- Existing saved JSON files can be loaded (missing fields get defaults)

### Risk 5: 74 existing tests must not break
- All model changes are additive (new fields with defaults)
- All service changes add optional parameters or new code paths
- Diagnostic changes add metadata-first path with existing substring fallback
- No existing behavior is removed

## Test Requirements

### G. Claim-backed candidates (new tests)
- Candidates with surviving aggregate claims get `supported_by_claim_ids` populated
- Candidates without matching claims are downgraded to `NEEDS_MORE_SAMPLES`
- `collect_more_samples` candidates are not downgraded even without claims
- End-to-end: reviews → diagnostics → patterns → aggregate claims → claim-backed candidates

### H. Metadata-first diagnostics (new tests)
- Opportunity quality uses `metadata.should_trade` when present
- Opportunity quality falls back to substring when metadata absent
- Execution quality uses `metadata.execution_rating` when present
- Execution quality falls back to substring when metadata absent
- Both paths produce correct results

### I. Strategy change records (new tests)
- Change records are created for `VERIFIED_CANDIDATE` status candidates only
- Change records contain correct snapshot data
- Change records can be saved to and loaded from the store
- `list-strategy-changes` CLI subcommand works

### J. Report hardening (new tests)
- Report includes "Verified Aggregate Claims" section
- Report includes "Strategy Change Records" section
- Both sections render correctly when empty

### K. Golden regression
- All 74 existing tests pass unchanged
- New tests bring the total to approximately 84-90 tests

## Execution Order

1. `models.py` — add `supported_by_claim_ids` to `StrategyActionCandidate`, add `StrategyChangeRecord`, extend `StrategyImprovementLoopResult`
2. `diagnostic_service.py` — metadata-first derivation with substring fallback
3. `strategy_improvement_service.py` — aggregate bridge, claim-backed candidates, change record creation
4. `report_service.py` — verified claims section, change records section
5. `store.py` — change record persistence functions
6. `cli.py` — `list-strategy-changes` subcommand
7. `__init__.py` — export `StrategyChangeRecord`
8. Tests — new P3.1 tests + verify all 74 existing tests pass
9. `audit/p3_1_hardening_completion_report.md`

That is the entire plan.
