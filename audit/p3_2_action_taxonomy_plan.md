# P3.2 Action Taxonomy Refinement — Implementation Plan

## Problem Statement

The current `StrategyActionType` enum has 7 values. The most critical issue: **`TIGHTEN_RISK_RULE` is a catch-all** for every grade-E trade regardless of the specific failure mode. In the manual acceptance test, ALL four bad trades received `tighten_risk_rule` even though diagnostics showed distinct failures (bad entry timing, bad opportunity, poor extraction). This makes the strategy improvement pipeline's output non-actionable — a trader can't tell *what specifically to change*.

Secondary issue: `REFINE_ENTRY_RULE` conflates entry timing problems with entry sizing problems. `REFINE_EXIT_RULE` conflates premature exits with trailing-stop failures.

## Design Principles

1. **Extension over rewrite** — old values remain valid; new values refine them.
2. **Deterministic mapping only** — every new action type maps from existing structured fields, never from prose.
3. **No action type without evidence** — a refined type is only assigned when structured diagnostic fields distinguish it from the coarser parent.
4. **Backward compatibility** — old coarse values remain loadable and serializable. Old saved results can be deserialized without error.
5. **No new data collection** — we only use fields already present in `TradeDiagnosticResult`.

## Proposed Refined Taxonomy

### Current → Refined Mapping

| Current (7) | Refined (12) | When Used |
|---|---|---|
| `no_change` | `no_change` | Unchanged |
| `add_pretrade_filter` | `add_pretrade_filter` | Unchanged — opportunity invalid |
| `refine_entry_rule` | `refine_entry_timing` | Poor execution + earliest_avoid_point == "entry_timing" |
| `refine_entry_rule` | `refine_entry_rule` | Poor execution, no specific avoid point (fallback) |
| `refine_stop_rule` | `refine_stop_rule` | Unchanged — poor execution AND poor extraction |
| `refine_exit_rule` | `refine_exit_timing` | Poor extraction + earliest_minimize_loss_point == "exit_management" |
| `refine_exit_rule` | `refine_exit_rule` | Poor extraction, no specific minimize_loss_point (fallback) |
| `tighten_risk_rule` | `add_pretrade_filter` | Grade E + invalid opportunity |
| `tighten_risk_rule` | `refine_entry_timing` | Grade E + poor execution + avoid_point == "entry_timing" |
| `tighten_risk_rule` | `refine_entry_rule` | Grade E + poor execution (no specific avoid_point) |
| `tighten_risk_rule` | `refine_stop_rule` | Grade E + poor execution AND poor extraction |
| `tighten_risk_rule` | `refine_exit_timing` | Grade E + poor extraction + minimize_loss_point == "exit_management" |
| `tighten_risk_rule` | `refine_exit_rule` | Grade E + poor extraction (no specific minimize_loss_point) |
| `tighten_risk_rule` | `tighten_risk_rule` | Grade E, no distinguishable sub-failure (true compound/ambiguous failure) |
| `collect_more_samples` | `collect_more_samples` | Unchanged |

### New Enum Values

```python
class StrategyActionType(StrEnum):
    # Unchanged
    NO_CHANGE = "no_change"
    ADD_PRETRADE_FILTER = "add_pretrade_filter"
    REFINE_STOP_RULE = "refine_stop_rule"
    TIGHTEN_RISK_RULE = "tighten_risk_rule"
    COLLECT_MORE_SAMPLES = "collect_more_samples"

    # Refined from refine_entry_rule
    REFINE_ENTRY_RULE = "refine_entry_rule"          # kept as fallback
    REFINE_ENTRY_TIMING = "refine_entry_timing"      # NEW

    # Refined from refine_exit_rule
    REFINE_EXIT_RULE = "refine_exit_rule"             # kept as fallback
    REFINE_EXIT_TIMING = "refine_exit_timing"         # NEW
```

Total: 9 values (was 7, added 2). Conservative expansion. Each new value is backed by a structured field that already exists.

### Why Only 2 New Values

The structured diagnostic fields available for deterministic mapping are:
- `earliest_avoid_point`: `"pre_trade_selection"` | `"entry_timing"` | `None`
- `earliest_minimize_loss_point`: `"exit_management"` | `"entry_improvement"` | `None`

These provide exactly two further refinements:
1. **Entry timing specifically poor** (vs entry generally poor) — distinguished by `earliest_avoid_point == "entry_timing"`
2. **Exit timing specifically poor** (vs exit generally poor) — distinguished by `earliest_minimize_loss_point == "exit_management"`

Adding more types would require inventing distinctions not supported by existing structured data — violating principle #3.

## Backward Compatibility Strategy

### Enum Compatibility
Old values (`refine_entry_rule`, `refine_exit_rule`, `tighten_risk_rule`) remain in the enum. They are still valid values. Loading a saved result with `"tighten_risk_rule"` will deserialize to `StrategyActionType.TIGHTEN_RISK_RULE` without error.

### Old-to-New Upgrade Path
No automatic upgrade of old saved results. Old results retain their coarse action types. Only *new* diagnostic runs produce refined types. This is safe because:
- Old results still serialize/deserialize correctly
- The improvement loop reads action_type from diagnostics, not from stored results directly
- Pattern extraction already uses string matching on `strategy_action_type` values

### `_FAILURE_REASON_TO_ACTION` Compatibility
This mapping in `strategy_improvement_service.py` maps `PrimaryFailureReason` → `StrategyActionType`. Since `PrimaryFailureReason` doesn't have the granularity to distinguish timing from general failures, this mapping stays coarse. The refinement happens in `_derive_strategy_action_type` (diagnostic_service.py) where we have access to `earliest_avoid_point` and `earliest_minimize_loss_point`.

However, `_resolve_action_type` in the improvement service handles `action_type` patterns — these will now contain refined values like `refine_entry_timing`, and `StrategyActionType("refine_entry_timing")` will resolve correctly because it's in the enum.

### `_ACTION_TO_CLAIM_PREFIX` Extension
New action types map to claim prefixes:
```python
_ACTION_TO_CLAIM_PREFIX = {
    ADD_PRETRADE_FILTER: "agg_claim_selection_",
    REFINE_ENTRY_RULE: "agg_claim_entry_",
    REFINE_ENTRY_TIMING: "agg_claim_entry_",      # NEW — same claim domain
    REFINE_EXIT_RULE: "agg_claim_exit_",
    REFINE_EXIT_TIMING: "agg_claim_exit_",         # NEW — same claim domain
    REFINE_STOP_RULE: "agg_claim_exit_",
}
```

## Files to Change

### 1. `backend/src/trading_research/models.py`
**Changes**: Add `REFINE_ENTRY_TIMING` and `REFINE_EXIT_TIMING` to `StrategyActionType` enum.
**Lines affected**: 214-221 (enum definition)
**Risk**: Low — pure extension.

### 2. `backend/src/trading_research/diagnostic_service.py`
**Changes**: Rewrite `_derive_strategy_action_type` to:
- Accept additional parameters: `earliest_avoid_point` and `earliest_minimize_loss_point`
- For grade E: drill into sub-failures instead of blanket `TIGHTEN_RISK_RULE`
- For poor execution: check `earliest_avoid_point == "entry_timing"` → `REFINE_ENTRY_TIMING`
- For poor extraction: check `earliest_minimize_loss_point == "exit_management"` → `REFINE_EXIT_TIMING`
- Retain `TIGHTEN_RISK_RULE` as true fallback for ambiguous compound failures

**Also update**: The call site in `build_diagnostic_result` to pass the new parameters.
**Lines affected**: 294-312 (function), ~120 (call site)
**Risk**: Medium — this is the core logic change. Must preserve all non-E-grade behavior exactly.

### 3. `backend/src/trading_research/strategy_improvement_service.py`
**Changes**:
- Extend `_ACTION_TO_CLAIM_PREFIX` with new action type entries
- `_FAILURE_REASON_TO_ACTION` stays unchanged (operates at coarser level)
- `_find_matching_claim_ids`: add new action types to non-catch-all prefix matching (they already work via the prefix dict, but verify `TIGHTEN_RISK_RULE` catch-all still applies)
**Lines affected**: 31-36 (prefix dict), 356-371 (claim matching)
**Risk**: Low — additive changes to mappings.

### 4. `backend/src/trading_research/report_service.py`
**Changes**: No structural changes needed. The report already renders `action_type.value` as a string. New values will appear automatically. Optionally add human-friendly labels for new types.
**Risk**: Very low.

### 5. `backend/src/trading_research/__init__.py`
**Changes**: If new enum values need explicit re-export, add them. Check current exports.
**Risk**: Very low.

### Files NOT Changing
- `aggregate_review_service.py` — produces claims, not action types
- `store.py` — uses JSON serialization that handles any StrEnum value
- `cli.py` — passes through action types as strings, no type-specific logic

## Implementation Order

1. **models.py** — Add 2 new enum values
2. **diagnostic_service.py** — Refine `_derive_strategy_action_type` and its call site
3. **strategy_improvement_service.py** — Extend `_ACTION_TO_CLAIM_PREFIX`
4. **report_service.py** — Optional human labels
5. **Tests** — All 5 categories (A through E)

## Detailed Mapping Logic

### New `_derive_strategy_action_type` (pseudocode)

```python
def _derive_strategy_action_type(
    grade, opportunity, execution, extraction,
    earliest_avoid_point, earliest_minimize_loss_point,
):
    # Good trades — no change
    if grade in (A, B):
        return NO_CHANGE

    # Grade E — drill into specifics instead of blanket TIGHTEN_RISK_RULE
    if grade == E:
        return _derive_action_for_failure(
            opportunity, execution, extraction,
            earliest_avoid_point, earliest_minimize_loss_point,
        )

    # Non-E failures (grade C/D) — same logic but with refinements
    return _derive_action_for_failure(
        opportunity, execution, extraction,
        earliest_avoid_point, earliest_minimize_loss_point,
    )


def _derive_action_for_failure(
    opportunity, execution, extraction,
    earliest_avoid_point, earliest_minimize_loss_point,
):
    # Bad opportunity takes priority
    if opportunity == INVALID:
        return ADD_PRETRADE_FILTER

    # Both execution and extraction bad
    if execution == POOR and extraction == POORLY_EXTRACTED:
        return REFINE_STOP_RULE

    # Execution bad — refine entry
    if execution == POOR:
        if earliest_avoid_point == "entry_timing":
            return REFINE_ENTRY_TIMING
        return REFINE_ENTRY_RULE

    # Extraction bad — refine exit
    if extraction == POORLY_EXTRACTED:
        if earliest_minimize_loss_point == "exit_management":
            return REFINE_EXIT_TIMING
        return REFINE_EXIT_RULE

    # No specific failure identified — fallback
    # For grade E with no distinguishable sub-failure, this is TIGHTEN_RISK_RULE
    # For non-E grades, this is COLLECT_MORE_SAMPLES
    return COLLECT_MORE_SAMPLES
```

**Key behavioral change**: Grade E trades no longer *all* get `TIGHTEN_RISK_RULE`. They get the specific refined type matching their actual failure. Only grade E trades with no distinguishable sub-failure (opportunity valid, execution not poor, extraction not poorly_extracted) get `TIGHTEN_RISK_RULE` as a genuine catch-all.

Wait — for grade E with no distinguishable sub-failure, we need to preserve `TIGHTEN_RISK_RULE` specifically for grade E (since it means catastrophic failure), while non-E grades get `COLLECT_MORE_SAMPLES`. Revised:

```python
def _derive_strategy_action_type(
    grade, opportunity, execution, extraction,
    earliest_avoid_point, earliest_minimize_loss_point,
):
    if grade in (A, B):
        return NO_CHANGE

    # Shared sub-failure analysis for C/D/E
    specific = _derive_specific_action(
        opportunity, execution, extraction,
        earliest_avoid_point, earliest_minimize_loss_point,
    )
    if specific is not None:
        return specific

    # No specific failure found — grade-dependent fallback
    if grade == E:
        return TIGHTEN_RISK_RULE
    return COLLECT_MORE_SAMPLES


def _derive_specific_action(opportunity, execution, extraction,
                            earliest_avoid_point, earliest_minimize_loss_point):
    if opportunity == INVALID:
        return ADD_PRETRADE_FILTER
    if execution == POOR and extraction == POORLY_EXTRACTED:
        return REFINE_STOP_RULE
    if execution == POOR:
        if earliest_avoid_point == "entry_timing":
            return REFINE_ENTRY_TIMING
        return REFINE_ENTRY_RULE
    if extraction == POORLY_EXTRACTED:
        if earliest_minimize_loss_point == "exit_management":
            return REFINE_EXIT_TIMING
        return REFINE_EXIT_RULE
    return None
```

This preserves the original behavior that grade E without identifiable sub-failure gets `TIGHTEN_RISK_RULE` (genuine compound failure) while grade C/D without sub-failure gets `COLLECT_MORE_SAMPLES`.

## Required Tests

### A: Taxonomy Validity
- All 9 enum values serialize to their string values
- All 9 string values deserialize back to enum members
- Old values (`tighten_risk_rule`, `refine_entry_rule`, `refine_exit_rule`) still valid
- New values (`refine_entry_timing`, `refine_exit_timing`) valid

### B: Deterministic Mapping
- Grade A → `no_change` (unchanged)
- Grade B → `no_change` (unchanged)
- Grade E + invalid opportunity → `add_pretrade_filter` (was `tighten_risk_rule`)
- Grade E + poor execution + avoid_point="entry_timing" → `refine_entry_timing` (was `tighten_risk_rule`)
- Grade E + poor execution + no avoid_point → `refine_entry_rule` (was `tighten_risk_rule`)
- Grade E + poor execution + poor extraction → `refine_stop_rule` (was `tighten_risk_rule`)
- Grade E + poor extraction + minimize_loss="exit_management" → `refine_exit_timing` (was `tighten_risk_rule`)
- Grade E + poor extraction + no minimize_loss → `refine_exit_rule` (was `tighten_risk_rule`)
- Grade E + no specific sub-failure → `tighten_risk_rule` (unchanged — genuine catch-all)
- Grade C/D + invalid opportunity → `add_pretrade_filter` (unchanged)
- Grade C/D + poor execution → `refine_entry_rule` or `refine_entry_timing` (refined)
- Grade C/D + poor extraction → `refine_exit_rule` or `refine_exit_timing` (refined)
- Grade C/D + no specific failure → `collect_more_samples` (unchanged)

### C: Candidate Gating
- New action types (`refine_entry_timing`, `refine_exit_timing`) match claim prefixes correctly
- `TIGHTEN_RISK_RULE` still matches ALL claims (catch-all behavior preserved)
- Candidate generation with refined patterns produces candidates with refined action types
- Single-trade diagnostics cannot produce VERIFIED_CANDIDATE (unchanged)

### D: Report Usefulness
- Report output contains refined action type strings
- More specific than old coarse labels for the same input data

### E: Regression
- All existing 113 tests still pass
- Golden flow tests unchanged in behavior for grade A/B trades
- Aggregate review pipeline unchanged
- Store round-trip for results with old action types works

## What Will NOT Change

1. **Deterministic verifier** — no changes to verification logic
2. **Boundary/anti-future-leakage checks** — no changes
3. **Sample-size downgrade rules** — constants unchanged
4. **Claim-backed/pattern-backed gating** — `supported_by_claim_ids` and `supported_by_pattern_ids` remain required
5. **Aggregate support requirement** — MIN_CANDIDATE_SAMPLE_SIZE, MIN_VERIFIED_SAMPLE_SIZE unchanged
6. **Conservative single-trade review** — no single trade can create VERIFIED_CANDIDATE
7. **`PrimaryFailureReason` enum** — no changes
8. **`ImprovementDirection` enum** — no changes
9. **`aggregate_review_service.py`** — no changes
10. **`store.py`** — no changes
11. **Claim structure and claim IDs** — no changes
12. **`_FAILURE_REASON_TO_ACTION` mapping** — stays at coarse level (PrimaryFailureReason lacks timing info)

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Breaking existing tests | Run full suite after each file change |
| Old saved results fail to load | Old enum values preserved — no deserialization breakage |
| Pattern extraction breaks with new values | New values are valid StrEnum members; string matching works |
| Grade E behavior regresses | Explicit test for grade E + each sub-failure combination |
| `TIGHTEN_RISK_RULE` disappears | Preserved as genuine catch-all for ambiguous compound failures |

## Estimated Scope

- ~20 lines in models.py (2 new enum values)
- ~40 lines in diagnostic_service.py (refactored derivation function)
- ~5 lines in strategy_improvement_service.py (extended prefix dict)
- ~10 lines in report_service.py (optional labels)
- ~150 lines of new tests
- Total: ~225 lines of changes
