# Correctness Hotfix Completion Report

## Summary

All five correctness bugs identified in the code review have been fixed. 98 tests pass (90 original + 8 new regression tests). No existing tests broken. No verifier/sample-size/boundary invariants changed.

## Results

| Issue | Priority | Status | Root Cause | Fix |
|-------|----------|--------|------------|-----|
| 2 | 1 (highest) | Fixed | `StrategyImprovementService.__init__()` stored `None` for `_aggregate_review_service` when no arg provided | Default to `AggregateReviewService()` (mirrors `_diagnostic_service` pattern) |
| 1 | 2 | Fixed | `trade_review_service.py` metadata dict omitted `outcome` | Added `"outcome": review.trade.outcome.value` to metadata |
| 3 | 3 | Fixed | Aggregate claims filtered evidence IDs by substring match on opaque hashes (never matches) | Built `source_ref → evidence_id` mapping; lookup by constructed `source_ref` key |
| 4 | 4 | Fixed | `setup_research_service.py` used `source.fetched_at` for evidence timestamps; for historical research, fetch time exceeds boundary | Clamp `evidence_time` to `result_boundary` when `fetched_at > result_boundary`; guard for `None` |
| 5 | 5 (lowest) | Fixed | `research_service.py` checked `_snippet_supports()` before `_snippet_contradicts()`; snippets matching both get classified as support | Swapped order: contradiction checked first (more specific signal) |

## Files Changed

| File | Change |
|------|--------|
| `backend/src/trading_research/strategy_improvement_service.py` | Line 61: `aggregate_review_service or AggregateReviewService()` |
| `backend/src/trading_research/trade_review_service.py` | Line 79: added `"outcome": review.trade.outcome.value` to metadata dict |
| `backend/src/trading_research/aggregate_review_service.py` | Lines 78-80: build `evidence_ref_map` from `zip(evidence_items, persisted_evidence)`; line 83: pass `evidence_ref_map` to `_build_claims`; line 324: new param; lines 362-363: lookup by `expected_ref` |
| `backend/src/trading_research/setup_research_service.py` | Line 97: accept `result_boundary` param; lines 102-104: clamp `evidence_time` when `> result_boundary` with `None` guard; line 60: pass `result_boundary` at call site |
| `backend/src/community/research/research_service.py` | Lines 95-98: swapped `_snippet_contradicts` / `_snippet_supports` check order |
| `backend/tests/test_trading_research/test_correctness_hotfix_regressions.py` | New file: 8 regression tests covering all 5 fixes |

## Regression Tests Added

| Test | Issue | What It Verifies |
|------|-------|------------------|
| `test_issue1_outcome_persisted_in_metadata` | 1 | `result.metadata["outcome"]` equals `"stopped_out"` for a stopped-out trade |
| `test_issue1_all_outcome_values_round_trip` | 1 | Every `TradeOutcome` variant survives the metadata round-trip |
| `test_issue2_aggregate_review_service_wired_by_default` | 2 | Default-constructed `StrategyImprovementService` has a non-None `AggregateReviewService` |
| `test_issue3_evidence_correctly_mapped_to_claims` | 3 | Per-type aggregate claims reference valid evidence IDs from the result's evidence index |
| `test_issue4_future_evidence_clamped_to_boundary` | 4 | Evidence with `fetched_at` after boundary gets clamped; `result.boundary_time <= boundary` |
| `test_issue4_none_fetched_at_not_clamped` | 4 | Evidence with `fetched_at=None` does not crash; evidence IDs are still produced |
| `test_issue5_contradiction_wins_over_support` | 5 | A snippet matching both contradiction markers and support threshold is classified as contradicting |
| `test_issue5_pure_support_still_works` | 5 | A snippet that only supports (no contradiction markers) is still classified as supporting |

## Test Suite

- **Before**: 90 tests passing
- **After**: 98 tests passing (90 original + 8 new)
- **Broken**: 0

## Remaining Known Limitations

1. **Issue 5 overlap zone**: Snippets that match contradiction markers but have very high word overlap (>40%) could theoretically be "strong support with coincidental contradiction words." The fix prioritizes contradiction as the more specific signal, which is correct for the general case but could misclassify edge cases. The `_snippet_contradicts` method already requires both a contradiction marker AND >30% word overlap, making false positives unlikely.

2. **Issue 4 timestamp approximation**: Clamping `fetched_at` to `result_boundary` for historical research is an honest approximation. The true publication date of the source is unknown. This is better than the prior behavior (boundary violation for all historical evidence) but still an approximation.

3. **Pre-existing LSP errors**: `registry.py`, `agents_config.py`, `debug.py`, `memory/prompt.py`, `memory_middleware.py` have type errors unrelated to this hotfix. Not addressed.
