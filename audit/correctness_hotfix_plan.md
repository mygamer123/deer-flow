# Correctness Hotfix Plan

## Scope Lock

This pass fixes five end-to-end correctness bugs identified in a code review of the `trading_research` structured core. Each fix is minimal — no new features, no refactors, no loosening of verifier/sample-size/boundary invariants.

Fix order: 2, 1, 3, 4, 5 (by priority).

Out of scope:
- New features or workflows
- Verifier rule changes
- Diagnostic service refactoring
- UI / frontend / channels
- Prose or LLM-based analysis
- Repo-wide refactors

## Pre-conditions

- 90 tests pass (34 P0+P1 + 18 P2 + 38 P3+P3.1) — all must remain passing after hotfixes
- All P0/P1/P2/P3/P3.1 invariants preserved

---

## Issue 2 (Priority 1): Strategy loop aggregate bridge not wired by default

**File**: `strategy_improvement_service.py`

**Root cause**: `StrategyImprovementService.__init__()` stores `self._aggregate_review_service = aggregate_review_service` without defaulting to `AggregateReviewService()`. Default construction leaves it as `None`.

**Impact**: `_get_verified_claims()` (line 107) returns `[]` when `self._aggregate_review_service is None`. Candidates can never achieve `VERIFIED_CANDIDATE` status and no change records are emitted via the default CLI/tool path.

**Fix**: Change line 61 from:
```python
self._aggregate_review_service = aggregate_review_service
```
to:
```python
self._aggregate_review_service = aggregate_review_service or AggregateReviewService()
```

This mirrors the pattern already used for `_diagnostic_service` on line 60.

**Regression test**: Construct `StrategyImprovementService()` with no arguments and verify that `self._aggregate_review_service` is not `None`. In `test_strategy_improvement.py`.

---

## Issue 1 (Priority 2): Trade outcome not persisted in metadata

**File**: `trade_review_service.py`

**Root cause**: Lines 75-80 build the `metadata` dict with `quality_tier`, `overall_verdict`, `pattern`, `total_iterations` but **not** `outcome`. The trade outcome (`review.trade.outcome`) is a `TradeOutcome(str, Enum)` with values like `"tp_filled"`, `"manual_exit"`, etc.

**Impact**: Downstream consumers that read `metadata["outcome"]` — `DiagnosticService` (line 36) and `_parse_loaded_review` in `aggregate_review_service.py` (line 552) — both get `"unknown"` for reloaded reviews. This causes `_derive_extraction_quality()` to misclassify extraction quality for every reloaded trade.

**Fix**: Add `"outcome": review.trade.outcome.value` to the metadata dict at line 79 (before `"total_iterations"`).

The metadata dict becomes:
```python
metadata={
    "quality_tier": review.quality_tier.name,
    "overall_verdict": review.overall_verdict.value,
    "pattern": review.pattern.value,
    "outcome": review.trade.outcome.value,
    "total_iterations": review.total_iterations,
},
```

**Regression test**: In `test_trade_review_service.py`, assert that `result.metadata["outcome"]` equals `"tp_filled"` (the outcome set in `_make_trade_review()`).

---

## Issue 3 (Priority 3): Aggregate claims get wrong evidence IDs

**File**: `aggregate_review_service.py`

**Root cause**: Line 358:
```python
type_evidence_ids = [eid for eid in evidence_ids if f"{claim_type}_pattern" in eid]
```
This filters evidence IDs by checking if the string `"selection_pattern"` etc. appears in the evidence ID string. But evidence IDs are opaque hashed strings from `EvidenceService.register()` (e.g., `ev_abc123...`), so the substring check **never matches**.

**Impact**: `type_evidence_ids` is always empty. `claim_evidence` falls back to `evidence_ids[:1]` (generic cohort summary evidence). Selection/entry/exit claims never bind to their intended metric evidence items.

**Fix**: Track the mapping from `source_ref` to persisted evidence ID during `_build_evidence`, then use that mapping in `_build_claims` to find the correct evidence IDs for each claim type.

Implementation:
1. `_build_evidence` already builds evidence items with `source_ref=f"aggregate:{grouping_key}:{claim_type}_pattern"`. Return a `source_ref → evidence_id` mapping alongside the evidence items.
2. In `_build_claims`, look up the evidence ID by constructing the expected `source_ref` for each claim type:
   ```python
   expected_ref = f"aggregate:{grouping_key}:{claim_type}_pattern"
   type_evidence_ids = [evidence_ref_map[expected_ref]] if expected_ref in evidence_ref_map else []
   ```

**Regression test**: In `test_aggregate_review_service.py`, add a test that verifies selection/entry/exit claims have evidence IDs that differ from the cohort summary evidence ID (i.e., they get the correct type-specific evidence).

---

## Issue 4 (Priority 4): Historical setup evidence timestamped with fetch time

**File**: `setup_research_service.py`

**Root cause**: Lines 114, 117-119 use `source.fetched_at` for `as_of`, `observed_at`, `effective_start`, `effective_end`. For historical research (where `trade_date` is in the past), the boundary is set to `trade_date 23:59:59` (line 264). But evidence timestamps are `fetched_at` (current time), which is **after** the boundary. The verifier flags all evidence as boundary violations.

**Impact**: All claims from historical setup research become boundary violations — the path self-invalidates.

**Fix**: When `request.trade_date` is set and the derived boundary is before `source.fetched_at`, use the boundary time for the evidence timestamps instead of `fetched_at`. This is an honest approximation — we don't know the exact publication time, but we know the user is asking about a historical date.

Implementation in `_build_evidence_items`:
1. Accept `result_boundary: datetime` as a parameter.
2. For each evidence item, compute: `evidence_time = min(source.fetched_at, result_boundary)` when `source.fetched_at > result_boundary`. Otherwise use `source.fetched_at`.
3. Use `evidence_time` for `as_of`, `observed_at`, `effective_start`, `effective_end`.

Call site change: pass `result_boundary` (already computed on line 58) to `_build_evidence_items`.

**Regression test**: In `test_setup_research_service.py`, add a test with a historical `trade_date` and verify that evidence timestamps are clamped to the boundary.

---

## Issue 5 (Priority 5): Contradictory snippets classified as support first

**File**: `research_service.py` (in `src/community/research/`)

**Root cause**: Lines 95-98 in `verify_claim()`: `_snippet_supports()` is checked first. If a snippet both contains enough matching words (>40% threshold) AND contains contradiction markers with enough matching words (>30% threshold), it gets classified as support because the `if` branch runs first and the `elif` branch is skipped.

**Impact**: Snippets like "This claim is false: X" where X has high word overlap get classified as supporting evidence, potentially flipping contradicted claims to supported.

**Fix**: Check contradiction first since it has a lower bar (30% word overlap + contradiction marker) and is the more specific signal. Swap the order:

```python
if self._snippet_contradicts(snippet, statement_lower):
    claim.contradicting_evidence.append(evidence)
elif self._snippet_supports(snippet, statement_lower):
    claim.supporting_evidence.append(evidence)
```

**Regression test**: In the research test file or a new one, create a snippet that has >40% word overlap AND contradiction markers, and verify it gets classified as contradiction, not support.

---

## Test Plan

Each fix gets at least one regression test. All 90 existing tests must continue to pass. Tests will be added to the existing test files for each service.

## Files Modified

| File | Issue |
|------|-------|
| `backend/src/trading_research/strategy_improvement_service.py` | Issue 2 |
| `backend/src/trading_research/trade_review_service.py` | Issue 1 |
| `backend/src/trading_research/aggregate_review_service.py` | Issue 3 |
| `backend/src/trading_research/setup_research_service.py` | Issue 4 |
| `backend/src/community/research/research_service.py` | Issue 5 |
| `backend/tests/test_trading_research/test_strategy_improvement.py` | Issue 2 test |
| `backend/tests/test_trading_research/test_trade_review_service.py` | Issue 1 test |
| `backend/tests/test_trading_research/test_aggregate_review_service.py` | Issue 3 test |
| `backend/tests/test_trading_research/test_setup_research_service.py` | Issue 4 test |
| `backend/tests/test_trading_research/` or `backend/tests/test_community/` | Issue 5 test |
