# P3.3 Compound-Failure Refinement — Implementation Plan

**Date**: 2026-03-14
**Status**: PLAN (no code changes until approved)
**Prior work**: P0–P3.2 complete, 147 tests passing (129 pre-P3.2 + 18 P3.2 acceptance)
**Goal**: Differentiate compound failures (execution == POOR AND extraction == POORLY_EXTRACTED) by primary-side attribution instead of always mapping to `REFINE_STOP_RULE`

---

## 1. Problem Statement

In `_derive_specific_action` (diagnostic_service.py, line 329–330), all compound failures take this path:

```python
if execution == ExecutionQuality.POOR and extraction == ExtractionQuality.POORLY_EXTRACTED:
    return StrategyActionType.REFINE_STOP_RULE
```

This fires at priority 2 (after INVALID opportunity check) and before the single-dimension entry/exit paths. Every compound failure gets the same action regardless of which side dominated the failure. In the original 5-trade cohort, TSLA/NVDA/AMD all collapse to `REFINE_STOP_RULE` with no differentiation.

**What P3.3 adds**: Classify compound failures as `entry_dominant`, `exit_dominant`, or `mixed`, then route to the more justified action type when structured evidence supports a primary side.

---

## 2. Available Structured Signals

These signals already exist on every `TradeDiagnosticResult` and can determine dominance without adding new data:

| Signal | Entry-dominant indicator | Exit-dominant indicator |
|--------|--------------------------|-------------------------|
| `earliest_avoid_point` | `"entry_timing"` present | absent |
| `earliest_minimize_loss_point` | absent or `"entry_improvement"` | `"exit_management"` present |
| `improvement_direction` | `IMPROVE_ENTRY` | `IMPROVE_EXIT` |
| `opportunity_quality` | `MARGINAL` (marginal + poor entry) | `VALID` (good setup, poor extraction) |

### Current derivation behavior for compound failures

When `execution == POOR` and `extraction == POORLY_EXTRACTED`:

- `_derive_earliest_avoid_point`: returns `"entry_timing"` only if `opportunity == MARGINAL`, else `None`
- `_derive_earliest_minimize_loss_point`: returns `"exit_management"` if exit_claim is present; else returns `"entry_improvement"` (because `execution == POOR`)
- `_derive_improvement_direction`: returns `IMPROVE_ENTRY` (because `execution == POOR` is checked first)

**Key insight**: `improvement_direction` alone always says `IMPROVE_ENTRY` for compound failures because the entry check fires first. It cannot distinguish dominance. We need to combine signals.

---

## 3. Compound-Failure Attribution Model

### 3.1 New model: `CompoundFailureDominance` (StrEnum)

```python
class CompoundFailureDominance(StrEnum):
    ENTRY_DOMINANT = "entry_dominant"
    EXIT_DOMINANT = "exit_dominant"
    MIXED = "mixed"
```

Added to `models.py`. This is an **internal attribution field** — it does NOT expand the public `StrategyActionType` taxonomy.

### 3.2 New field on `TradeDiagnosticResult`

```python
compound_failure_dominance: CompoundFailureDominance | None = None
```

Set only when both `execution == POOR` and `extraction == POORLY_EXTRACTED`. Otherwise `None`.

### 3.3 Attribution rules (deterministic, no prose)

A new function `_derive_compound_failure_dominance` in `diagnostic_service.py`:

```python
def _derive_compound_failure_dominance(
    opportunity: OpportunityQuality,
    earliest_avoid_point: str | None,
    earliest_minimize_loss_point: str | None,
) -> CompoundFailureDominance:
    has_entry_signal = earliest_avoid_point == "entry_timing"
    has_exit_signal = earliest_minimize_loss_point == "exit_management"

    # Rule 1: At least one structured side-signal required for non-MIXED.
    # If neither side-signal is present, no amount of OpportunityQuality
    # alone can justify attributing dominance to one side.
    if not has_entry_signal and not has_exit_signal:
        return CompoundFailureDominance.MIXED

    # Rule 2: Both side-signals present → both sides have structured
    # evidence of failure → conservative MIXED.
    if has_entry_signal and has_exit_signal:
        return CompoundFailureDominance.MIXED

    # Rule 3: Exactly one side-signal present.
    # OpportunityQuality may strengthen the signal but never overrides it.
    if has_entry_signal:
        # Entry signal present, no exit signal.
        # OpportunityQuality == MARGINAL would reinforce, but even without
        # it the entry signal alone is sufficient.
        return CompoundFailureDominance.ENTRY_DOMINANT
    # has_exit_signal is True (only remaining case).
    return CompoundFailureDominance.EXIT_DOMINANT
```

**Rationale for each branch**:

- Neither side-signal present → no structured evidence supports either side → **mixed** (conservative). OpportunityQuality alone is never a standalone dominance source (constraint 1–3).
- Both side-signals present → both sides have structured evidence of failure → **mixed** (conservative).
- `entry_timing` present + no `exit_management` → the structured avoid-point identifies entry as the earliest correctable mistake → **entry-dominant**. OpportunityQuality == MARGINAL would reinforce this but is not required.
- `exit_management` present + no `entry_timing` → the structured minimize-loss-point identifies exit as the key correctable mistake → **exit-dominant**. OpportunityQuality == VALID would reinforce this but is not required.

### 3.4 What is NOT used for attribution

- PnL magnitude alone
- Hindsight-only maximum excursion
- Prose similarity or LLM re-interpretation
- Free-form rationale text
- **OpportunityQuality as a standalone dominance source** — it may only reinforce an existing side-signal, never determine dominance on its own. When both side-signals are absent, result is always MIXED regardless of opportunity quality.

---

## 4. Primary-Side Decision Rules

### 4.1 Modified `_derive_specific_action`

Replace the single compound-failure line (line 329–330) with dominance-aware routing:

```python
def _derive_specific_action(
    opportunity: OpportunityQuality,
    execution: ExecutionQuality,
    extraction: ExtractionQuality,
    earliest_avoid_point: str | None,
    earliest_minimize_loss_point: str | None,
) -> StrategyActionType | None:
    # Priority 1: invalid opportunity (unchanged)
    if opportunity == OpportunityQuality.INVALID:
        return StrategyActionType.ADD_PRETRADE_FILTER

    # Priority 2: compound failure — now dominance-aware
    if execution == ExecutionQuality.POOR and extraction == ExtractionQuality.POORLY_EXTRACTED:
        dominance = _derive_compound_failure_dominance(
            opportunity, earliest_avoid_point, earliest_minimize_loss_point,
        )
        if dominance == CompoundFailureDominance.ENTRY_DOMINANT:
            if earliest_avoid_point == "entry_timing":
                return StrategyActionType.REFINE_ENTRY_TIMING
            return StrategyActionType.REFINE_ENTRY_RULE
        if dominance == CompoundFailureDominance.EXIT_DOMINANT:
            if earliest_minimize_loss_point == "exit_management":
                return StrategyActionType.REFINE_EXIT_TIMING
            return StrategyActionType.REFINE_EXIT_RULE
        # MIXED: conservative fallback — unchanged from P3.2
        return StrategyActionType.REFINE_STOP_RULE

    # Priority 3: entry-only failure (unchanged)
    if execution == ExecutionQuality.POOR:
        if earliest_avoid_point == "entry_timing":
            return StrategyActionType.REFINE_ENTRY_TIMING
        return StrategyActionType.REFINE_ENTRY_RULE

    # Priority 4: exit-only failure (unchanged)
    if extraction == ExtractionQuality.POORLY_EXTRACTED:
        if earliest_minimize_loss_point == "exit_management":
            return StrategyActionType.REFINE_EXIT_TIMING
        return StrategyActionType.REFINE_EXIT_RULE

    return None
```

### 4.2 Action routing summary for compound failures

| Dominance | Condition | Action Type |
|-----------|-----------|-------------|
| entry_dominant | `earliest_avoid_point == "entry_timing"` (only side-signal) | `REFINE_ENTRY_TIMING` |
| exit_dominant | `earliest_minimize_loss_point == "exit_management"` (only side-signal) | `REFINE_EXIT_TIMING` |
| mixed | Both side-signals present | `REFINE_STOP_RULE` |
| mixed | Neither side-signal present (regardless of opportunity) | `REFINE_STOP_RULE` |

**Note**: Entry-dominant always implies `earliest_avoid_point == "entry_timing"` (it is the only entry side-signal), so the action is always `REFINE_ENTRY_TIMING`. Exit-dominant always implies `earliest_minimize_loss_point == "exit_management"`, so the action is always `REFINE_EXIT_TIMING`. The `REFINE_ENTRY_RULE` / `REFINE_EXIT_RULE` branches in section 4.1 are retained for defensive completeness but should not fire under current derivation rules.

### 4.3 What changes for the original 5-trade cohort

| Trade | Symbol | Opp | Avoid | Minimize | Old Action | Dominance | New Action |
|-------|--------|-----|-------|----------|------------|-----------|------------|
| TRADE_1 | AMPX | VALID | — | — | NO_CHANGE | n/a | **NO_CHANGE** |
| TRADE_2 | TSLA | ? | ? | ? | REFINE_STOP_RULE | (depends on signals) | (depends) |
| TRADE_3 | NVDA | ? | ? | ? | REFINE_STOP_RULE | (depends on signals) | (depends) |
| TRADE_4 | AMD | ? | ? | ? | REFINE_STOP_RULE | (depends on signals) | (depends) |
| TRADE_5 | COIN | INVALID | — | — | ADD_PRETRADE_FILTER | n/a | **ADD_PRETRADE_FILTER** |

TRADE_1 and TRADE_5 are unaffected (grade A/B and invalid opportunity, respectively). TRADE_2/3/4 will be differentiated based on their actual structured signals. If all three have `opportunity == VALID` and no `entry_timing` avoid point, they'll route to exit-dominant actions. If their signals are uniform, they may still share an action type — but it will be the *correct* action type for their dominant failure side rather than a generic fallback.

**Key constraint**: If structured signals don't clearly indicate a side, the trade gets `MIXED` → `REFINE_STOP_RULE`, same as P3.2. P3.3 does not invent dominance where evidence is absent.

---

## 5. Aggregate Compound-Pattern Extraction

### 5.1 New pattern type: `compound_dominance`

Add to the `field_extractors` list in `extract_patterns()`:

```python
field_extractors: list[tuple[str, str]] = [
    ("failure_reason", "primary_failure_reason"),
    ("action_type", "strategy_action_type"),
    ("avoid_point", "earliest_avoid_point"),
    ("improvement_direction", "improvement_direction"),
    ("compound_dominance", "compound_failure_dominance"),  # NEW
]
```

This extracts patterns like:
- `pattern_compound_dominance_entry_dominant` (count=N)
- `pattern_compound_dominance_exit_dominant` (count=N)
- `pattern_compound_dominance_mixed` (count=N)

Existing `MIN_PATTERN_COUNT = 2` and dedup-by-trade-ID logic apply unchanged.

### 5.2 Pattern filtering

The skip-values list in `extract_patterns` filters out no-information values. Add `None`-skipping (already implicit since `getattr` returns `None` which is skipped). No additional skip values needed — all three dominance values (`entry_dominant`, `exit_dominant`, `mixed`) are informative.

### 5.3 Sample size invariant

`sample_size` = number of distinct trade IDs contributing. This is already enforced by the dedup logic and remains unchanged.

---

## 6. Strategy Candidate Refinement

### 6.1 No new action types

P3.3 does NOT add new `StrategyActionType` values. Compound failures now route to existing entry-side or exit-side actions when dominance is clear. The `compound_dominance` pattern type provides aggregate visibility but candidates still map to existing action types.

### 6.2 `_resolve_action_type` change

The `compound_dominance` pattern type is NOT an `action_type` or `failure_reason` pattern, so `_resolve_action_type` does not need to handle it directly. Compound dominance patterns are informational for reports but do not generate separate candidates — the differentiated `action_type` patterns already capture the correct actions.

**Alternatively**: If `compound_dominance` patterns should influence candidates, add a handler:

```python
if pattern.pattern_type == "compound_dominance":
    if pattern.value == "entry_dominant":
        return StrategyActionType.REFINE_ENTRY_RULE
    if pattern.value == "exit_dominant":
        return StrategyActionType.REFINE_EXIT_RULE
    return StrategyActionType.REFINE_STOP_RULE
```

**Decision**: Do NOT add this handler. The `action_type` patterns already carry the correct per-trade action, so compound-dominance patterns would produce duplicate candidates for the same trades. Include `compound_dominance` patterns in reports only.

### 6.3 Claim matching

`_ACTION_TO_CLAIM_PREFIX` already maps entry-side and exit-side actions correctly:
- `REFINE_ENTRY_RULE` → `agg_claim_entry_`
- `REFINE_ENTRY_TIMING` → `agg_claim_entry_`
- `REFINE_EXIT_RULE` → `agg_claim_exit_`
- `REFINE_EXIT_TIMING` → `agg_claim_exit_`
- `REFINE_STOP_RULE` → `agg_claim_exit_`

No changes needed. Compound failures that route to entry-side actions will now match entry-side claims; compound failures that route to exit-side actions will match exit-side claims. Mixed fallback (`REFINE_STOP_RULE`) continues matching exit-side claims.

### 6.4 Gating invariants (unchanged)

- `MIN_PATTERN_COUNT = 2`: patterns need ≥ 2 distinct trades
- `MIN_CANDIDATE_SAMPLE_SIZE = 2`: candidates need ≥ 2 sample size
- `MIN_VERIFIED_SAMPLE_SIZE = 3`: verified candidates need ≥ 3 trades + matching claims
- Claim-backed gating: verified status requires matching aggregate claims
- Single-trade reviews cannot produce patterns or candidates

---

## 7. Report Improvements

### 7.1 Diagnostics table: add compound dominance column

In `build_strategy_improvement_markdown`, extend the diagnostics table:

```
| Symbol | Date | Grade | Opportunity | Execution | Extraction | Failure | Dominance | Action |
```

The "Dominance" column shows `compound_failure_dominance` value when non-None, else `"—"`.

### 7.2 Compound-dominance patterns in aggregate section

The existing patterns table already renders all pattern types. `compound_dominance` patterns will appear automatically with pattern type, value, count, frequency, and sample size.

### 7.3 No new report sections

The existing sections (diagnostics, patterns, claims, candidates, change records, limitations) are sufficient. Adding a separate "Compound Failure Analysis" section would duplicate information already visible in the diagnostics and patterns tables.

---

## 8. Files to Change

| File | Change | Lines (approx) |
|------|--------|-----------------|
| `models.py` | Add `CompoundFailureDominance` enum, add `compound_failure_dominance` field to `TradeDiagnosticResult` | +10 |
| `diagnostic_service.py` | Add `_derive_compound_failure_dominance` function, modify `_derive_specific_action` compound-failure branch, set `compound_failure_dominance` in `diagnose_one` | +25, ~10 modified |
| `strategy_improvement_service.py` | Add `("compound_dominance", "compound_failure_dominance")` to `field_extractors` | +1 |
| `report_service.py` | Add "Dominance" column to diagnostics table in `build_strategy_improvement_markdown` | ~5 modified |
| Test file (new) | `test_p33_acceptance.py` with tests A–E | +300–400 (estimated) |

### Files NOT changed

| File | Why not |
|------|---------|
| `aggregate_review_service.py` | Compound dominance is a per-trade diagnostic field; aggregate review operates on claims/evidence, not diagnostic fields |
| `evidence_service.py` | No new evidence types |
| `store.py` | No storage format changes |
| Existing test files | Regression verified by running existing 147 tests; no modifications needed |
| Frontend/UI files | Out of scope |
| Slack/OpenClaw integration | Out of scope |

---

## 9. Implementation Order

1. **Models** (`models.py`)
   - Add `CompoundFailureDominance` enum
   - Add `compound_failure_dominance: CompoundFailureDominance | None = None` to `TradeDiagnosticResult`

2. **Diagnostic service** (`diagnostic_service.py`)
   - Add `_derive_compound_failure_dominance()` function
   - Modify `_derive_specific_action()` to call it for compound failures
   - Set `compound_failure_dominance` in `diagnose_one()` result construction

3. **Pattern extraction** (`strategy_improvement_service.py`)
   - Add `("compound_dominance", "compound_failure_dominance")` to `field_extractors`

4. **Report** (`report_service.py`)
   - Add "Dominance" column to diagnostics table

5. **Tests** (`test_p33_acceptance.py`)
   - Test A: Compound-failure attribution correctness
   - Test B: Aggregate compound patterns
   - Test C: Candidate refinement with dominance
   - Test D: Report output includes dominance
   - Test E: Regression (all 147 existing tests still pass)
   - Test F: Candidate-inflation regression — same cohort must not produce more verified candidates than the P3.2 conservative fallback path would have

---

## 10. What Will NOT Change

- **No new public `StrategyActionType` values** — compound failures route to existing entry/exit action types
- **No weakening of existing invariants**: deterministic verifier, boundary checks, sample-size downgrade, claim-backed gating, aggregate support requirements, conservative single-trade behavior
- **No changes to `_derive_earliest_avoid_point` or `_derive_earliest_minimize_loss_point`** — these functions already produce the signals P3.3 consumes
- **No changes to `_derive_improvement_direction`** — it remains entry-biased for compound failures; P3.3 adds a separate, more nuanced attribution
- **No changes to `_derive_primary_failure_reason`** — `MULTIPLE_FAILURES` and `BAD_OPPORTUNITY_AND_EXECUTION` remain as-is
- **No prose-based attribution or LLM re-interpretation**
- **No UI/frontend/Slack/OpenClaw changes**
- **No broad refactors or taxonomy explosion**

---

## 11. Backward Compatibility

### Serialization

`compound_failure_dominance` defaults to `None`. Existing saved results without this field will deserialize normally (dataclass default). No migration needed.

### Pattern extraction

New `compound_dominance` patterns only appear for trades diagnosed with P3.3 logic. Old diagnostics (re-loaded from disk) won't have the field, so `getattr(..., None)` skips them — no spurious patterns.

### Action type changes

Trades previously receiving `REFINE_STOP_RULE` may now receive entry-side or exit-side actions. This is the intended improvement. The change is:
- **Narrowing**: fewer actions fall into the generic `REFINE_STOP_RULE` bucket
- **Non-breaking**: all output actions are values that already exist in `StrategyActionType`
- **Deterministic**: same inputs → same outputs (no randomness or LLM calls)

### Existing tests

All 147 existing tests should pass unchanged. The only tests that assert `REFINE_STOP_RULE` for compound failures are in `test_p32_acceptance.py`. These tests construct specific metadata; if any need updating, it will be because the test's constructed metadata now triggers a non-mixed dominance. Any such updates will be documented explicitly.

---

## 12. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Existing tests break due to action type change | Medium | Run all 147 tests before any code change. Update test assertions only for tests whose constructed metadata legitimately triggers non-mixed dominance. Document each change. |
| Attribution assigns dominance without sufficient evidence | Very low | Tightened: dominance requires at least one structured side-signal. No side-signals → MIXED regardless of OpportunityQuality. |
| Refined dominance inflates verified candidate count | Low | Regression test F (see §13) verifies that the same cohort does not produce more verified candidates than the P3.2 conservative path would have. |
| New patterns duplicate existing action_type patterns | Low | `compound_dominance` patterns are informational only — they don't generate candidates. |
| `compound_failure_dominance` field breaks serialization | Very low | Defaults to `None`, dataclass handles missing fields gracefully. |

---

## 13. Acceptance Criteria

P3.3 is complete when:

1. **Attribution works**: Compound failures with exactly one structured side-signal → dominant for that side; both or neither side-signals → mixed. OpportunityQuality alone never determines dominance.
2. **Action routing works**: Entry-dominant → entry-side action; exit-dominant → exit-side action; mixed → `REFINE_STOP_RULE`
3. **Aggregate patterns extracted**: `compound_dominance` patterns appear with correct sample sizes (distinct trades, no inflation)
4. **Candidates use correct gating**: Entry/exit-dominant candidates match correct claim prefixes; mixed candidates match exit-side claims; all gating thresholds unchanged
5. **Reports show attribution**: Diagnostics table includes dominance column
6. **Regression passes**: All 147 existing tests pass (with documented assertion updates if needed)
7. **No invariant violations**: Deterministic verifier, boundary checks, sample-size rules, claim-backed gating, aggregate support requirements all intact
8. **No candidate inflation**: Refined dominance routing does not produce more verified candidates for the same cohort than the P3.2 conservative fallback would have (Test F)
