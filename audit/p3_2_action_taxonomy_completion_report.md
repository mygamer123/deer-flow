# P3.2 Completion Report

## Scope

Action taxonomy refinement for the strategy improvement loop. One structural weakness addressed without rewriting P3:

1. **Refined action types** — grade-E trades (and C/D trades with identifiable sub-failures) now receive specific action types instead of blanket `tighten_risk_rule` or coarse `refine_entry_rule`/`refine_exit_rule`

Two new enum values added. Deterministic mapping from existing structured diagnostic fields. No new data collection, no new agents, no UI work.

## Problem

In the manual acceptance test (see `audit/manual_acceptance_report.md`), all four bad trades received `tighten_risk_rule` despite having distinct failure modes: bad entry timing, bad opportunity selection, poor exit extraction. The strategy improvement pipeline's output was non-actionable — a trader couldn't tell *what specifically to change*.

The root cause: `_derive_strategy_action_type` hardcoded grade E → `TIGHTEN_RISK_RULE` regardless of available sub-failure information in `earliest_avoid_point` and `earliest_minimize_loss_point`.

## Completed Items

### 1. Models (`models.py`)

Two new `StrategyActionType` enum values:
- `REFINE_ENTRY_TIMING = "refine_entry_timing"` — when poor execution is specifically an entry timing problem (`earliest_avoid_point == "entry_timing"`)
- `REFINE_EXIT_TIMING = "refine_exit_timing"` — when poor extraction is specifically an exit timing problem (`earliest_minimize_loss_point == "exit_management"`)

Total enum size: 9 values (was 7). Old values unchanged and still valid.

### 2. Diagnostic Service (`diagnostic_service.py`)

**`_derive_strategy_action_type`** — accepts two new optional parameters:
- `earliest_avoid_point: str | None = None`
- `earliest_minimize_loss_point: str | None = None`

Defaults preserve backward compatibility for any caller not passing these fields.

**New helper `_derive_specific_action()`** — shared sub-failure analysis for grades C/D/E:
1. `opportunity == INVALID` → `ADD_PRETRADE_FILTER`
2. `execution == POOR` and `extraction == POORLY_EXTRACTED` → `REFINE_STOP_RULE`
3. `execution == POOR` + `earliest_avoid_point == "entry_timing"` → `REFINE_ENTRY_TIMING` (NEW)
4. `execution == POOR` (no specific avoid point) → `REFINE_ENTRY_RULE`
5. `extraction == POORLY_EXTRACTED` + `earliest_minimize_loss_point == "exit_management"` → `REFINE_EXIT_TIMING` (NEW)
6. `extraction == POORLY_EXTRACTED` (no specific minimize point) → `REFINE_EXIT_RULE`
7. No sub-failure found → `None` (caller applies grade-dependent fallback)

Grade-dependent fallback: grade E → `TIGHTEN_RISK_RULE`; non-E → `COLLECT_MORE_SAMPLES`.

**Call site updated** (line 50): passes `avoid_point` and `minimize_point` from the diagnostic context.

### 3. Strategy Improvement Service (`strategy_improvement_service.py`)

`_ACTION_TO_CLAIM_PREFIX` extended:
- `REFINE_ENTRY_TIMING` → `"agg_claim_entry_"` (same claim domain as `REFINE_ENTRY_RULE`)
- `REFINE_EXIT_TIMING` → `"agg_claim_exit_"` (same claim domain as `REFINE_EXIT_RULE`)

`TIGHTEN_RISK_RULE` catch-all behavior preserved — matches any surviving claim.

### 4. Report Service (`report_service.py`)

No changes needed. Reports already render `action_type.value` as a string. New refined values appear automatically.

### 5. Other Files NOT Modified

- `aggregate_review_service.py` — produces claims, not action types
- `store.py` — uses JSON serialization that handles any StrEnum value
- `cli.py` — passes through action types as strings
- `verifier_service.py` — unchanged
- `evidence_service.py` — unchanged
- `__init__.py` — no new exports needed (enum values, not new classes)

## Test Results

**129 tests pass** across all 14 test files in `test_trading_research/`.

13 new P3.2 tests added to `test_strategy_improvement.py` (file total: 54 tests, all passing):

### Taxonomy validity (3 tests)

- `test_p32_taxonomy_all_values_serialize` — all 9 enum values serialize to their string values
- `test_p32_taxonomy_old_values_still_loadable` — original 7 values deserialize correctly
- `test_p32_taxonomy_new_values_loadable` — `refine_entry_timing` and `refine_exit_timing` deserialize correctly

### Deterministic mapping (7 tests)

- `test_p32_grade_e_poor_execution_with_entry_timing_avoid_point` — grade E + poor execution + `earliest_avoid_point="entry_timing"` → `REFINE_ENTRY_TIMING` (was `TIGHTEN_RISK_RULE`)
- `test_p32_poor_execution_without_entry_timing_gets_entry_rule` — grade E + poor execution + no avoid point → `REFINE_ENTRY_RULE` (was `TIGHTEN_RISK_RULE`)
- `test_p32_poor_extraction_with_exit_management_gets_exit_timing` — grade E + poor extraction + `earliest_minimize_loss_point="exit_management"` → `REFINE_EXIT_TIMING` (was `TIGHTEN_RISK_RULE`)
- `test_p32_poor_extraction_without_exit_claim_gets_exit_rule` — grade E + poor extraction + no exit claim → `REFINE_EXIT_RULE` (was `TIGHTEN_RISK_RULE`)
- `test_p32_invalid_opportunity_gets_pretrade_filter` — grade E + invalid opportunity → `ADD_PRETRADE_FILTER` (was `TIGHTEN_RISK_RULE`)
- `test_p32_both_poor_gets_stop_rule` — grade E + poor execution + poor extraction → `REFINE_STOP_RULE` (was `TIGHTEN_RISK_RULE`)
- `test_p32_no_sub_failure_fallback` — grade E + no identifiable sub-failure → `TIGHTEN_RISK_RULE` (unchanged; genuine catch-all)

### Backward compatibility (1 test)

- `test_p32_grade_ab_unchanged` — grade A and B trades still return `NO_CHANGE`

### Candidate gating (2 tests)

- `test_p32_claim_prefix_new_entry_timing` — `REFINE_ENTRY_TIMING` maps to `agg_claim_entry_` prefix and finds matching claims
- `test_p32_claim_prefix_new_exit_timing` — `REFINE_EXIT_TIMING` maps to `agg_claim_exit_` prefix and finds matching claims
- `test_p32_tighten_risk_still_catches_all_claims` — `TIGHTEN_RISK_RULE` catch-all matches any surviving claim regardless of prefix
- `test_p32_candidate_generation_with_refined_pattern` — candidates with refined action types are generated correctly with proper claim backing

### Report usefulness (1 test)

- `test_p32_report_shows_refined_action_types` — report output contains refined action type strings (e.g., `refine_entry_timing` instead of `tighten_risk_rule`)

## Behavioral Changes

### Before P3.2

| Trade Failure | Action Type Assigned |
|---|---|
| Grade E, bad entry timing | `tighten_risk_rule` |
| Grade E, bad opportunity | `tighten_risk_rule` |
| Grade E, bad exit extraction | `tighten_risk_rule` |
| Grade E, bad entry + bad exit | `tighten_risk_rule` |
| Grade E, ambiguous failure | `tighten_risk_rule` |

### After P3.2

| Trade Failure | Action Type Assigned |
|---|---|
| Grade E, bad entry timing (avoid_point = entry_timing) | `refine_entry_timing` |
| Grade E, bad entry (no specific avoid point) | `refine_entry_rule` |
| Grade E, bad opportunity | `add_pretrade_filter` |
| Grade E, bad exit (minimize_point = exit_management) | `refine_exit_timing` |
| Grade E, bad exit (no specific minimize point) | `refine_exit_rule` |
| Grade E, bad entry + bad exit | `refine_stop_rule` |
| Grade E, ambiguous / no sub-failure | `tighten_risk_rule` |

Grade C/D trades see the same refinement; their no-sub-failure fallback remains `collect_more_samples`.

## Invariants Preserved

All P0/P1/P2/P3/P3.1 invariants remain intact:

- **Deterministic verifier** — not modified
- **Boundary/anti-future-leakage checks** — not modified
- **Sample-size downgrade rules** — `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2`, `MIN_RECOMMENDATION_SAMPLE_SIZE = 3`, `SAMPLE_SIZE_CONFIDENCE_CAP = 0.49` enforced by verifier
- **Claim-backed/pattern-backed gating** — `supported_by_claim_ids` and `supported_by_pattern_ids` still required for `VERIFIED_CANDIDATE` status
- **Aggregate support requirement** — `MIN_CANDIDATE_SAMPLE_SIZE`, `MIN_VERIFIED_SAMPLE_SIZE` unchanged
- **Conservative single-trade review** — single trades cannot produce `VERIFIED_CANDIDATE`
- **Change record creation** — only for `VERIFIED_CANDIDATE` status (P3.1 behavior intact)
- **Metadata-first derivation** — P3.1 metadata paths unchanged

## Design Decisions

### Why only 2 new enum values (not 5 or 12)?

The structured diagnostic fields available for deterministic refinement are limited:
- `earliest_avoid_point`: `"pre_trade_selection"` | `"entry_timing"` | `None`
- `earliest_minimize_loss_point`: `"exit_management"` | `"entry_improvement"` | `None`

Only `"entry_timing"` and `"exit_management"` produce refinements that differ from existing coarse types. Adding more types would require inventing distinctions not supported by existing structured data — violating the "no action type without evidence" principle.

### Why shared sub-failure analysis for C/D/E instead of E-only?

Grades C and D can also have identifiable sub-failures. The old code already routed these through specific action types, but using a shared helper ensures consistent refinement across all failing grades while preserving the grade-dependent fallback (E → `TIGHTEN_RISK_RULE`, non-E → `COLLECT_MORE_SAMPLES`).

### Why same claim prefixes for refined and coarse types?

`REFINE_ENTRY_TIMING` and `REFINE_ENTRY_RULE` both relate to entry-domain claims. Using the same `agg_claim_entry_` prefix ensures refined candidates can find backing from the same pool of aggregate claims. Creating separate claim domains would require changes to the aggregate review pipeline — out of scope and unnecessary.

### Why keep `TIGHTEN_RISK_RULE` at all?

Not every grade-E trade has a cleanly identifiable sub-failure. When opportunity is valid, execution is not poor, and extraction is not poorly extracted, but the overall grade is still E (via other worst-tier combinations), `TIGHTEN_RISK_RULE` correctly signals "something is fundamentally wrong, but no single dimension explains it." Removing it would lose that legitimate signal.

## Files Modified

| File | Lines Changed | Change |
|---|---|---|
| `models.py` | +2 | Two new `StrategyActionType` enum values |
| `diagnostic_service.py` | +30 | Refactored `_derive_strategy_action_type`, new `_derive_specific_action` helper, updated call site |
| `strategy_improvement_service.py` | +2 | Extended `_ACTION_TO_CLAIM_PREFIX` with new action types |
| `test_strategy_improvement.py` | +195 | 13 new P3.2 tests |

## What Comes Next

Potential future work (not in scope for P3.2):

- **Additional diagnostic fields**: If trade review agents add more structured metadata (e.g., `position_sizing_quality`, `market_regime`), the taxonomy could be further refined with more action types
- **Action type aggregation across loops**: Track which refined action types recur across multiple loop runs to identify persistent strategy weaknesses
- **Human-friendly labels**: Add display names for new action types in report headers (currently uses raw enum values which are readable but not polished)
- **Manual acceptance re-run**: Re-run the manual acceptance test from `audit/manual_acceptance_report.md` to verify that the four bad trades now receive distinct, specific action types instead of blanket `tighten_risk_rule`
