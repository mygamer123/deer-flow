# P3.3 Completion Report

## Scope

Compound-failure refinement for the strategy improvement loop. When both entry-side and exit-side failures are present (POOR execution + POORLY_EXTRACTED extraction), classify the failure dominance as `entry_dominant`, `exit_dominant`, or `mixed` using structured signals, then route to the appropriate existing action type instead of always falling back to `REFINE_STOP_RULE`.

No new `StrategyActionType` values. No new data collection. No UI work.

## Problem

In P3.2, compound failures (both entry and exit sub-failures present) always received `REFINE_STOP_RULE` because `_derive_specific_action()` checked the compound case first (priority 2) and short-circuited before examining which side was dominant. This meant trades where the exit side was clearly at fault still got a generic stop-rule recommendation rather than the more specific `REFINE_EXIT_TIMING`.

## Tightened Dominance Rules (User-Mandated)

1. OpportunityQuality alone CANNOT determine dominance — requires at least one structured side-signal (`earliest_avoid_point == "entry_timing"` or `earliest_minimize_loss_point == "exit_management"`)
2. If both side-signals are absent, result is always `MIXED` regardless of opportunity quality
3. OpportunityQuality is a weak tiebreaker only when side evidence already exists — effectively unused since exactly-one-signal cases don't need a tiebreaker
4. Test F required: regression check that refined dominance does not artificially inflate the number of verified candidates compared with the P3.2 conservative fallback path

## Derivation Logic

Function `_derive_compound_failure_dominance(opp, avoid_point, minimize_point)` uses exactly two signals:
- `has_entry_signal = avoid_point == "entry_timing"`
- `has_exit_signal = minimize_point == "exit_management"`

| entry_signal | exit_signal | Result |
|-------------|-------------|--------|
| No | No | MIXED |
| Yes | Yes | MIXED |
| Yes | No | ENTRY_DOMINANT |
| No | Yes | EXIT_DOMINANT |

Action routing in `_derive_specific_action()`:
- `ENTRY_DOMINANT` → `REFINE_ENTRY_TIMING`
- `EXIT_DOMINANT` → `REFINE_EXIT_TIMING`
- `MIXED` → `REFINE_STOP_RULE` (unchanged from P3.2)

## Completed Items

### 1. Models (`models.py`)

New enum `CompoundFailureDominance` with three values: `ENTRY_DOMINANT`, `EXIT_DOMINANT`, `MIXED`.

New optional field on `TradeDiagnosticResult`: `compound_failure_dominance: CompoundFailureDominance | None = None`. Set only when both `execution == POOR` and `extraction == POORLY_EXTRACTED`.

### 2. Diagnostic Service (`diagnostic_service.py`)

New function `_derive_compound_failure_dominance(opp, avoid_point, minimize_point)` implementing the derivation table above.

Modified `_derive_specific_action()` compound-failure branch (priority 2): instead of unconditionally returning `REFINE_STOP_RULE`, now calls `_derive_compound_failure_dominance` and routes based on dominance.

Modified `diagnose_trade()`: computes and stores `compound_failure_dominance` on the diagnostic result whenever both entry and exit sub-failures are present.

### 3. Pattern Extraction (`strategy_improvement_service.py`)

Added `("compound_dominance", "compound_failure_dominance")` to `field_extractors` so compound dominance values are extracted into aggregate patterns.

### 4. Report (`report_service.py`)

Added "Dominance" column to the per-trade diagnostics table in `build_strategy_improvement_markdown`. Shows the dominance value for compound failures and `-` for non-compound trades.

### 5. P3.2 Test Updates (`test_p32_acceptance.py`)

- `test_trade3_nvda`: assertion changed from `REFINE_STOP_RULE` to `REFINE_EXIT_TIMING` (NVDA has VALID opp + exit_claim → EXIT_DOMINANT)
- Cohort specificity test: updated to expect 3 distinct action types including `REFINE_EXIT_TIMING`

### 6. Pre-existing P3.2 Test Fix (`test_strategy_improvement.py`)

- `test_p32_both_poor_gets_stop_rule` renamed to `test_p32_both_poor_valid_opp_gets_exit_timing` with assertion updated from `REFINE_STOP_RULE` to `REFINE_EXIT_TIMING`. The test constructs VALID opp (confidence=0.8, should_trade=True) + POOR exec + exit_claim → EXIT_DOMINANT → `REFINE_EXIT_TIMING`.

### 7. P3.3 Acceptance Tests (`test_p33_acceptance.py`)

599 lines, 19 test cases across 6 test classes:

| Class | Tests | What It Covers |
|-------|-------|----------------|
| TestA: CompoundFailureAttribution | 6 | All dominance derivation branches, non-compound returns None, opp-quality-alone cannot determine dominance |
| TestB: AggregateCompoundPatterns | 3 | Patterns extracted with correct sample sizes, mixed dominance below threshold produces no pattern |
| TestC: CandidateRefinement | 5 | Exit-dominant → exit_timing candidate, entry-dominant → entry_timing candidate, mixed → stop_rule, gating still requires min sample size, compound_dominance patterns don't generate candidates |
| TestD: ReportDominanceColumn | 2 | Dominance column present in markdown, dash for non-compound |
| TestE: RegressionOriginalCohort | 2 | Original 5-trade cohort action types match P3.3 expectations, dominance values match derivation |
| TestF: CandidateInflationRegression | 3 | Homogeneous compound cohort, mixed cohort, and original cohort all produce at most P3.2-equivalent verified candidates |

## Impact on Original 5-Trade Cohort

| Trade | Opp | avoid_point | minimize_point | Dominance | Old Action | New Action |
|-------|-----|-------------|----------------|-----------|------------|------------|
| TRADE_1_AMPX | VALID | — | — | — | COLLECT_MORE_SAMPLES | COLLECT_MORE_SAMPLES |
| TRADE_2_TSLA | MARGINAL | entry_timing | exit_management | MIXED | REFINE_STOP_RULE | REFINE_STOP_RULE |
| TRADE_3_NVDA | VALID | — | exit_management | EXIT_DOMINANT | REFINE_STOP_RULE | **REFINE_EXIT_TIMING** |
| TRADE_4_AMD | MARGINAL | entry_timing | exit_management | MIXED | REFINE_STOP_RULE | REFINE_STOP_RULE |
| TRADE_5_COIN | INVALID | pre_trade_selection | exit_management | EXIT_DOMINANT | ADD_PRETRADE_FILTER | ADD_PRETRADE_FILTER |

Only TRADE_3_NVDA changes action type. TRADE_5_COIN gets dominance computed but its action type is determined by priority 1 (INVALID opp → ADD_PRETRADE_FILTER).

## Invariants Preserved

- Deterministic verifier: no changes
- Boundary checks: no changes
- Sample-size downgrade rules: no changes
- Claim-backed/pattern-backed gating: no changes
- Aggregate support requirements: no changes
- Conservative single-trade behavior: no changes
- No new `StrategyActionType` values

## Test Results

168 tests collected, 168 passed, 0 failed (0.96s).
