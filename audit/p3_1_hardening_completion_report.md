# P3.1 Completion Report

## Scope

Hardening pass on the P3 strategy improvement loop. Three structural weaknesses addressed without rewriting P3:

1. **Claim-backed strategy action candidates** — candidates now link to verified aggregate claims that survived the verifier, not just pattern IDs/trade IDs
2. **Reduced heuristic/substring dependence in diagnostics** — structured metadata fields checked first, substring matching retained as fallback
3. **Lightweight strategy change records** — verified candidates persisted as `StrategyChangeRecord` objects with provenance metadata

Plus report hardening (full chain: diagnostics -> patterns -> verified claims -> candidates -> change records) and a new CLI subcommand.

No new agents, no UI work, no repo-wide refactors. The P0 structured core, P1 invariants, P2 aggregation pipeline, and P3 loop remain intact.

## Completed Items

### 1. Models (`models.py`)

- `StrategyActionCandidate.supported_by_claim_ids: list[str]` — new field linking candidates to verified aggregate claims. Defaults to empty list for backward compatibility.
- `StrategyChangeRecord` — new dataclass:
  - `record_id: str`
  - `candidate: StrategyActionCandidate` (snapshot at creation time)
  - `created_at: datetime`
  - `source_loop_result_id: str` (links back to the loop result)
  - `source_trade_count: int`
  - `notes: str` (optional human-readable context)
- `StrategyImprovementLoopResult.verified_claims: list[Claim]` — stores the aggregate claims that survived the verifier
- `StrategyImprovementLoopResult.change_records: list[StrategyChangeRecord]` — stores change records created from verified candidates

### 2. Diagnostic Service (`diagnostic_service.py`)

Two derivation functions hardened with metadata-first paths and substring fallback:

**`_derive_opportunity_quality`**:
- Now checks `claim.metadata.get("should_trade")` first (boolean field set during trade review)
- If metadata field is absent, falls back to existing substring matching (`"should have been taken" in statement`)
- Same output for both paths; graceful migration from old to new review format

**`_derive_execution_quality`**:
- Now checks `claim.metadata.get("execution_rating")` first (string like `"suboptimal"`, `"poor"`)
- If metadata field is absent, falls back to existing substring matching (`"suboptimal" in statement`)
- Same output for both paths

Extraction quality derivation was already metadata-based (uses `outcome` and `overall_verdict`) — no changes needed.

### 3. Strategy Improvement Service (`strategy_improvement_service.py`)

**Aggregate bridge**: New `_get_verified_claims()` method:
- Accepts an `AggregateReviewService` instance and raw trade review dicts
- Calls `AggregateReviewService.aggregate()` on the same reviews
- Collects surviving claims (status == `SUPPORTED`) from the aggregated result
- Returns list of verified `Claim` objects

**Claim-backed candidate generation**: `generate_candidates()` gains optional `verified_claims` parameter:
- New `_ACTION_TO_CLAIM_PREFIX` mapping: `add_pretrade_filter` -> `agg_claim_selection_`, `refine_entry_rule` -> `agg_claim_entry_`, `refine_exit_rule`/`refine_stop_rule` -> `agg_claim_exit_`
- `tighten_risk_rule` matches any surviving claim
- `collect_more_samples` / `no_change` require no claim backing
- Module-level `_find_matching_claim_ids()` function performs the prefix-based lookup
- Candidates with claim backing and sufficient sample size achieve `VERIFIED_CANDIDATE` status
- Candidates without claim backing are downgraded to `NEEDS_MORE_SAMPLES` (not rejected)
- `supported_by_claim_ids` populated on each candidate

**Change record creation**: New `_create_change_records()` method:
- Creates `StrategyChangeRecord` for each `VERIFIED_CANDIDATE` candidate
- Records include `source_loop_result_id`, `source_trade_count`, and auto-generated notes
- Returns list of change records

**`run_loop()` integration**: Updated to:
1. Call `_get_verified_claims()` via the aggregate bridge
2. Pass `verified_claims` to `generate_candidates()`
3. Call `_create_change_records()` on the resulting candidates
4. Populate `verified_claims` and `change_records` on the result

### 4. Report Service (`report_service.py`)

Three new sections added to the strategy improvement report:

1. **Verified Aggregate Claims** — table between Patterns and Candidates showing claim ID, statement, status, sample size, and confidence for each surviving claim
2. **Strategy Action Candidates** — existing table updated with a "Claim IDs" column showing which aggregate claims back each candidate
3. **Strategy Change Records** — new section after Candidates showing record ID, action type, status, source loop result, trade count, and creation time

### 5. Store (`store.py`)

Three new functions for change record persistence:

- `save_strategy_change_records(records)` — saves a list of `StrategyChangeRecord` objects to JSON files with pattern `strategy_change_{record_id}_{timestamp}.json`
- `list_strategy_change_records()` — scans results directory for change record files, returns list of `(record_id, path)` tuples
- `load_strategy_change_record(record_id)` — loads a single change record by ID, reconstructing `StrategyChangeRecord` and nested `StrategyActionCandidate` from JSON

### 6. CLI (`cli.py`)

New `list-strategy-changes` subcommand:
- Lists all saved strategy change records
- Displays record ID, action type, status, source loop result, trade count, and creation time
- Handles empty results gracefully

### 7. Package Exports (`__init__.py`)

`StrategyChangeRecord` added to imports and `__all__`.

## Test Results

**90 tests pass** (34 P0+P1 + 18 P2 + 38 P3+P3.1).

16 new P3.1 tests added across 4 sections:

### Section G: Diagnostic metadata-first derivation (4 tests)

- `test_opportunity_quality_from_metadata_should_trade` — verifies metadata `should_trade=False` produces INVALID without substring matching
- `test_opportunity_quality_falls_back_to_substring` — verifies substring fallback when metadata absent
- `test_execution_quality_from_metadata_rating` — verifies metadata `execution_rating="suboptimal"` produces POOR without substring matching
- `test_execution_quality_falls_back_to_substring` — verifies substring fallback when metadata absent

### Section H: Claim-backed candidates (4 tests)

- `test_candidates_with_claims_get_claim_ids_populated` — candidates backed by surviving claims get `supported_by_claim_ids` populated
- `test_candidates_without_claims_downgraded` — candidates without matching claims are not `VERIFIED_CANDIDATE`
- `test_collect_more_samples_not_downgraded_without_claims` — `collect_more_samples` action type exempted from claim requirement
- `test_tighten_risk_uses_any_surviving_claim` — `tighten_risk_rule` matches any surviving claim regardless of prefix

### Section I: Change records (4 tests)

- `test_change_records_created_for_verified_candidates` — change records created only for `VERIFIED_CANDIDATE` status candidates
- `test_change_records_not_created_for_non_verified` — non-verified candidates produce no change records
- `test_change_record_fields_populated` — all change record fields correctly populated from candidate and context
- `test_change_records_empty_when_no_verified` — empty candidate list or all non-verified produces empty change records

### Section J: Store persistence (4 tests)

- `test_save_and_list_strategy_change_records` — round-trip save and list
- `test_load_strategy_change_record` — round-trip save and load with field verification
- `test_load_nonexistent_change_record` — returns None for missing records
- `test_save_empty_change_records` — saving empty list creates no files

### Existing test updated (1)

- `test_verified_candidate_requires_three_trades` — updated to supply `verified_claims` parameter. Under P3.1, candidates without claim backing cannot achieve `VERIFIED_CANDIDATE` status even with sufficient sample size. This is an intentional behavior change from the hardening.

## Invariants Preserved

All P0/P1/P2/P3 invariants remain intact:

- **Deterministic verifier** — not modified
- **Boundary/anti-future-leakage checks** — not modified
- **Sample-size downgrade rules** — `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2`, `MIN_RECOMMENDATION_SAMPLE_SIZE = 3`, `SAMPLE_SIZE_CONFIDENCE_CAP = 0.49` enforced by verifier
- **Recommendation support linkage** — recommendations still require claims with evidence
- **Single-trade conservatism** — single trades cannot produce supported claims or actionable candidates
- **Aggregate requirement for actionable candidates** — strengthened: candidates now require surviving aggregate claims for `VERIFIED_CANDIDATE` status

## Design Decisions

### Why metadata-first with substring fallback (not metadata-only)?

Existing saved trade reviews do not have `metadata.should_trade` or `metadata.execution_rating` fields. Removing substring matching would silently degrade diagnostics for all historical data. The fallback ensures backward compatibility while new reviews benefit from structured fields.

### Why downgrade instead of reject candidates without claims?

A candidate without a matching aggregate claim may simply need more data (the claim could survive with a larger sample). Downgrading to `NEEDS_MORE_SAMPLES` preserves the signal without overstating confidence.

### Why create change records only for VERIFIED_CANDIDATE?

Change records represent strategy actions with sufficient backing. Proposed or needs-more-samples candidates are not ready for tracking — they are still hypotheses. Recording only verified candidates prevents noise in the change history.

### Why TIGHTEN_RISK_RULE matches any surviving claim?

Risk tightening is a defensive action that can be justified by any form of systematic failure across trades. Requiring a specific claim prefix would be artificially restrictive for what is essentially a "something is consistently wrong" signal.

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| `models.py` | +22 | `supported_by_claim_ids` field, `StrategyChangeRecord` dataclass, `verified_claims`/`change_records` on result |
| `diagnostic_service.py` | +12 | Metadata-first derivation paths for opportunity and execution quality |
| `strategy_improvement_service.py` | +76 | Aggregate bridge, claim matching, change record creation, updated `run_loop` |
| `report_service.py` | +38 | Verified claims section, claim IDs column, change records section |
| `store.py` | +62 | Save/list/load strategy change records |
| `cli.py` | +26 | `list-strategy-changes` subcommand |
| `__init__.py` | +2 | Export `StrategyChangeRecord` |
| `test_strategy_improvement.py` | +225 | 16 new tests, 1 updated test |

## Files NOT Modified

- `verifier_service.py` — unchanged (design constraint)
- `aggregate_review_service.py` — used as-is (no modifications)
- `evidence_service.py` — unchanged
- `trade_review_service.py` — unchanged
- `setup_research_service.py` — unchanged
- `tools.py` — unchanged

## What Comes Next

Potential future work (not in scope for P3.1):

- **Strategy change application**: Use change records to modify actual strategy parameters (currently records are informational)
- **Cross-loop comparison**: Compare change records across multiple loop runs to find recurring recommendations
- **Metadata population**: Ensure trade review agents emit `metadata.should_trade` and `metadata.execution_rating` fields so the metadata-first path is exercised in production
- **Change record expiry**: Age-based or sample-count-based expiry for old change records
