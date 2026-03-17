# Post-P3.2 Acceptance Report

**Date**: 2026-03-14
**Scope**: Manual acceptance rerun to verify P3.2 action taxonomy refinement produces more specific, more actionable strategy outputs without weakening existing invariants
**Prior work**: P0–P3.2 complete, 129 tests passing pre-acceptance. 18 new acceptance tests added (all passing).
**Test file**: `backend/tests/test_trading_research/test_p32_acceptance.py`

---

## 1. Executive Verdict

**PASS**

The refined action taxonomy produces strictly more specific outputs for the original 5-trade acceptance cohort. All existing invariants (deterministic verifier, boundary checks, sample-size downgrade rules, claim-backed gating, aggregate support requirements, conservative single-trade behavior) remain intact. The two new action types (`REFINE_ENTRY_TIMING`, `REFINE_EXIT_TIMING`) fire correctly for single-dimension failures and integrate cleanly into the strategy improvement pipeline. No code changes were required beyond a single test assertion correction.

---

## 2. Sample Used

### Original 5-Trade Cohort (from `audit/manual_acceptance_report.md`)

| Trade | Symbol | Pattern | Verdict | Outcome | Quality |
|-------|--------|---------|---------|---------|---------|
| TRADE_1 | AMPX | strong_uptrending | good_trade | tp_filled | GOOD |
| TRADE_2 | TSLA | pullback_breakout | bad_trade | stopped_out | BAD |
| TRADE_3 | NVDA | strong_uptrending | bad_trade | stopped_out | BAD |
| TRADE_4 | AMD | strong_uptrending | marginal | manual_exit | BAD |
| TRADE_5 | COIN | strong_uptrending | should_skip | stopped_out | BAD |

### 3 Additional Trades (constructed to exercise new refined action types)

| Trade | Symbol | Pattern | Opp | Exec | Extract | Target Action |
|-------|--------|---------|-----|------|---------|---------------|
| TRADE_ENTRY_TIMING | META | strong_uptrending | MARGINAL | POOR | PARTIALLY_EXTRACTED | REFINE_ENTRY_TIMING |
| TRADE_EXIT_TIMING | GOOG | strong_uptrending | VALID | EXCELLENT | POORLY_EXTRACTED | REFINE_EXIT_TIMING |
| TRADE_EXIT_RULE | MSFT | strong_uptrending | VALID | EXCELLENT | POORLY_EXTRACTED | REFINE_EXIT_RULE |

### Rationale for Additional Trades

The original cohort's bad trades ALL have compound failures (both poor execution AND poor extraction), which routes them to `REFINE_STOP_RULE`. The two new P3.2 types (`REFINE_ENTRY_TIMING`, `REFINE_EXIT_TIMING`) only fire for single-dimension failures — poor execution without poor extraction, or vice versa. Additional trades were needed to confirm these paths work correctly.

---

## 3. Scenario A: Prior Bad-Trade Cohort Rerun

### Specificity Comparison

| Trade | Symbol | Old Action (pre-P3.2) | New Action (post-P3.2) | Change |
|-------|--------|-----------------------|------------------------|--------|
| TRADE_1 | AMPX | no_change | **NO_CHANGE** | Unchanged |
| TRADE_2 | TSLA | tighten_risk_rule | **REFINE_STOP_RULE** | More specific |
| TRADE_3 | NVDA | tighten_risk_rule | **REFINE_STOP_RULE** | More specific |
| TRADE_4 | AMD | tighten_risk_rule | **REFINE_STOP_RULE** | More specific |
| TRADE_5 | COIN | tighten_risk_rule | **ADD_PRETRADE_FILTER** | More specific |

**Before P3.2**: All 4 bad trades received the same action: `tighten_risk_rule`.
**After P3.2**: 3 trades → `refine_stop_rule`, 1 trade → `add_pretrade_filter`. **2 distinct action types instead of 1.**

### Why REFINE_STOP_RULE (not REFINE_ENTRY_TIMING or REFINE_EXIT_TIMING)?

TSLA, NVDA, and AMD all have **both** `execution == POOR` and `extraction == POORLY_EXTRACTED`. The `_derive_specific_action` routing rule (priority 2) maps compound failure → `REFINE_STOP_RULE`. This is correct — when both entry and exit failed, the issue is the overall risk/stop configuration, not just entry timing or exit timing.

### Why ADD_PRETRADE_FILTER for COIN?

COIN's selection claim has `should_trade=False` with confidence ≥ 0.5, making `opportunity_quality == INVALID`. Invalid opportunity takes precedence (priority 1 in `_derive_specific_action`) → `ADD_PRETRADE_FILTER`. This is more specific than the old `tighten_risk_rule` and directly actionable: add a filter to skip this type of trade.

### Gating Verification

Each original trade was individually run through `extract_patterns` and `generate_candidates`. **All 5 produced zero patterns and zero candidates.** Single-trade diagnostics cannot become strategy change candidates — the minimum pattern count (≥ 2) and minimum verified sample size (≥ 3) gates hold.

### Assessment: PASS

Specificity improved (2 distinct types from 1). Gating intact. No false positives.

**Tests**: `TestScenarioACohortRerun` — 7/7 passing.

---

## 4. Scenario B: Single-Trade Diagnostic Sanity

### 3 Reviewed Trades

| Trade | Opp | Exec | Extract | Avoid Point | Minimize Point | Action Type |
|-------|-----|------|---------|-------------|----------------|-------------|
| TRADE_ENTRY_TIMING (META) | MARGINAL | POOR | PARTIALLY_EXTRACTED | entry_timing | — | **REFINE_ENTRY_TIMING** |
| TRADE_EXIT_TIMING (GOOG) | VALID | EXCELLENT | POORLY_EXTRACTED | — | exit_management | **REFINE_EXIT_TIMING** |
| TRADE_EXIT_RULE (MSFT) | VALID | EXCELLENT | POORLY_EXTRACTED | — | None | **REFINE_EXIT_RULE** |

### Why These Route Correctly

1. **META (REFINE_ENTRY_TIMING)**: Execution is POOR but extraction is NOT POORLY_EXTRACTED (manual_exit + POOR quality → PARTIALLY_EXTRACTED). Since only execution failed, and `earliest_avoid_point == "entry_timing"`, the routing selects `REFINE_ENTRY_TIMING`.

2. **GOOG (REFINE_EXIT_TIMING)**: Execution is EXCELLENT (optimal rating + GOOD quality) but extraction is POORLY_EXTRACTED (stopped_out). Since only extraction failed, and `earliest_minimize_loss_point == "exit_management"` (exit claim present), the routing selects `REFINE_EXIT_TIMING`.

3. **MSFT (REFINE_EXIT_RULE)**: Same as GOOG but with no exit claim. Without an exit claim, `earliest_minimize_loss_point` is None, so the routing falls through to the generic `REFINE_EXIT_RULE`.

### Single-Trade Candidate Gating

All three trades were individually run through `extract_patterns` → `generate_candidates`. **All produced zero patterns and zero candidates.** Confirmed: single-trade reviews expose refined action types diagnostically but cannot become strategy change candidates.

### Assessment: PASS

All 3 refined types fire correctly for their specific sub-failure patterns. Single-trade gating holds.

**Tests**: `TestScenarioBSingleTradeDiagnostic` — 4/4 passing.

---

## 5. Scenario C: Aggregate Candidate Sanity

### REFINE_EXIT_TIMING Candidate (3 GOOG trades)

- **Input**: 3 identical GOOG trades with VALID opportunity, EXCELLENT execution, POORLY_EXTRACTED, exit claims present
- **Diagnostics**: All 3 diagnosed as `REFINE_EXIT_TIMING`
- **Patterns extracted**: `action_type=refine_exit_timing` with count=3, sample_size=3
- **Verified claims provided**: `agg_claim_exit_strong_uptrending` (SUPPORTED, sample_size=3, confidence=0.8)
- **Candidate result**:
  - Action type: `REFINE_EXIT_TIMING`
  - Status: `VERIFIED_CANDIDATE`
  - Sample size: 3
  - Pattern backing: ✅ (`pattern_action_type_refine_exit_timing` in `supported_by_pattern_ids`)
  - Claim backing: ✅ (`agg_claim_exit_strong_uptrending` in `supported_by_claim_ids`)

### REFINE_ENTRY_TIMING Candidate (3 META trades)

- **Input**: 3 identical META trades with MARGINAL opportunity, POOR execution, PARTIALLY_EXTRACTED
- **Diagnostics**: All 3 diagnosed as `REFINE_ENTRY_TIMING`
- **Patterns extracted**: `action_type=refine_entry_timing` with count=3
- **Verified claims provided**: `agg_claim_entry_strong_uptrending` (SUPPORTED, sample_size=3, confidence=0.8)
- **Candidate result**:
  - Action type: `REFINE_ENTRY_TIMING`
  - Status: `VERIFIED_CANDIDATE`
  - Claim backing: ✅ (`agg_claim_entry_strong_uptrending` in `supported_by_claim_ids`)

### Claim Prefix Mapping

`REFINE_ENTRY_TIMING` maps to `agg_claim_entry_` prefix — same domain as `REFINE_ENTRY_RULE`. `REFINE_EXIT_TIMING` maps to `agg_claim_exit_` prefix — same domain as `REFINE_EXIT_RULE`. This is correct: refined and coarse types share the same claim domain because they address the same aspect (entry or exit) at different specificity levels.

### Assessment: PASS

Aggregate candidates with refined action types are properly claim-backed and pattern-backed, reaching `VERIFIED_CANDIDATE` status when evidence thresholds are met.

**Tests**: `TestScenarioCAggregateCandidateSanity` — 2/2 passing.

---

## 6. Scenario D: Fallback Sanity

### Case 1: COLLECT_MORE_SAMPLES (no sub-failure)

- **Input**: Trade with VALID opportunity, acceptable execution, PARTIALLY_EXTRACTED (AVERAGE quality, manual_exit)
- **Result**: `COLLECT_MORE_SAMPLES`
- **Why**: No dimension is in worst tier → `_derive_specific_action` returns None → non-E grade fallback → `COLLECT_MORE_SAMPLES`
- **Assessment**: Correct. When evidence is ambiguous, the system conservatively asks for more data.

### Case 2: TIGHTEN_RISK_RULE (via failure_reason pattern)

- **Input**: 3 pattern instances of `failure_reason=bad_opportunity_and_execution` with matching claims
- **Result**: Candidates with `TIGHTEN_RISK_RULE` action type at `VERIFIED_CANDIDATE` status
- **Why**: The `_FAILURE_REASON_TO_ACTION` mapping in `strategy_improvement_service.py` maps `bad_opportunity_and_execution` → `TIGHTEN_RISK_RULE`. This path remains functional even though the grade-E direct fallback in `_derive_strategy_action_type` is effectively dead code.
- **Assessment**: Correct. `TIGHTEN_RISK_RULE` still surfaces through aggregate pattern resolution.

### Case 3: COLLECT_MORE_SAMPLES bypasses claim-backing

- **Input**: 3-count pattern for `collect_more_samples` with NO verified claims
- **Result**: `VERIFIED_CANDIDATE` status despite no claim backing
- **Why**: `COLLECT_MORE_SAMPLES` is explicitly exempted from claim-backing requirements — it's a meta-action ("collect more data") that doesn't need evidence support.
- **Assessment**: Correct. The exemption is intentional and prevents circular logic (can't require evidence to recommend gathering evidence).

### Case 4: Claim-requiring candidates without claims get downgraded

- **Input**: 3-count pattern for `refine_exit_timing` with NO verified claims
- **Result**: `NEEDS_MORE_SAMPLES` status
- **Why**: `REFINE_EXIT_TIMING` requires claim backing. Without matching claims, the candidate cannot reach `VERIFIED_CANDIDATE`.
- **Assessment**: Correct. This confirms that refined action types don't get special treatment — they must earn their verification through evidence.

### Assessment: PASS

Fallback paths work correctly. Coarse actions surface when evidence is weak. Claim-backing requirements are enforced for refined types. Meta-actions bypass claim requirements appropriately.

**Tests**: `TestScenarioDFallbackSanity` — 4/4 passing.

---

## 7. Remaining Weaknesses (Top 3)

### 1. TIGHTEN_RISK_RULE grade-E fallback is effectively dead code in `_derive_strategy_action_type`

**Severity**: Low
**Impact**: No runtime impact; defensive-only code path
**Detail**: The fallback at line 316 of `diagnostic_service.py` (grade E + `_derive_specific_action` returns None → `TIGHTEN_RISK_RULE`) cannot fire under normal conditions. Grade E requires `worst_count >= 2`, and any combination of 2+ worst-tier dimensions always matches a specific action rule in `_derive_specific_action`. The action type still surfaces correctly through `_FAILURE_REASON_TO_ACTION` in aggregate pattern resolution.
**Recommendation**: Leave as defensive code. Add a comment noting it's a safety net. No action needed.

### 2. New refined types require rare single-dimension failure patterns

**Severity**: Medium
**Impact**: Reduces frequency of the most specific action types in real data
**Detail**: `REFINE_ENTRY_TIMING` requires poor execution WITHOUT poor extraction. `REFINE_EXIT_TIMING` requires poor extraction WITHOUT poor execution. In practice, bad trades tend to fail on multiple dimensions simultaneously (as the original cohort demonstrates — all 4 bad trades have compound failures). The refined types may rarely fire in production data.
**Recommendation**: Monitor production diagnostic distributions. If refined types fire < 5% of the time, consider whether the compound-failure routing (→ `REFINE_STOP_RULE`) should be decomposed further to identify the *primary* failure dimension.

### 3. No compound-refinement path for simultaneous entry and exit failures

**Severity**: Low
**Impact**: Loses some diagnostic specificity for compound failures
**Detail**: When both execution and extraction fail, the system always routes to `REFINE_STOP_RULE` regardless of whether the entry or exit was the more impactful failure. A trade where entry was catastrophic but exit was only slightly poor gets the same action type as one where both were equally bad.
**Recommendation**: Future work could add a severity comparison (e.g., entry_severity > exit_severity → `REFINE_STOP_RULE_ENTRY_BIASED`), but this requires structured severity data not currently available in diagnostic fields. Not a blocker.

---

## 8. Final Acceptance Decision

### PASS

**Rationale**: All 4 acceptance scenarios satisfied:

| Scenario | Result | Evidence |
|----------|--------|----------|
| A: Prior Bad-Trade Cohort Rerun | PASS | 2 distinct action types (from 1); gating intact |
| B: Single-Trade Diagnostic Sanity | PASS | 3 refined types fire correctly; single trades cannot become candidates |
| C: Aggregate Candidate Sanity | PASS | Refined candidates reach VERIFIED_CANDIDATE with proper claim/pattern backing |
| D: Fallback Sanity | PASS | Coarse actions fire when evidence is weak; claim requirements enforced |

**Invariants verified intact**:
- Deterministic verifier: not modified
- Boundary/anti-future-leakage checks: not modified
- Sample-size downgrade rules: enforced (MIN_SUPPORTED_CLAIM_SAMPLE_SIZE=2, MIN_RECOMMENDATION_SAMPLE_SIZE=3)
- Claim-backed/pattern-backed gating: enforced for all non-meta action types
- Aggregate support requirements: MIN_CANDIDATE_SAMPLE_SIZE, MIN_VERIFIED_SAMPLE_SIZE unchanged
- Conservative single-trade review: confirmed — zero candidates from any single trade
- Change record creation: only for VERIFIED_CANDIDATE status

**Code changes during acceptance**: None to production code. One test assertion corrected (`ExecutionQuality.ACCEPTABLE` → `ExecutionQuality.EXCELLENT` for AMPX good-trade test — the trade's quality_tier="GOOD" + no suboptimal entry metadata correctly produces EXCELLENT, not ACCEPTABLE).

**Test coverage**: 147 tests passing (129 pre-existing + 18 new acceptance tests).

**Upgrade from prior acceptance**: The original manual acceptance report (`audit/manual_acceptance_report.md`) gave **PASS WITH CAVEATS**, with Caveat #1 being "Strategy action type taxonomy is too coarse." P3.2 directly addresses this caveat. This acceptance report upgrades to **PASS** — the taxonomy is no longer too coarse for the failure modes observable in structured diagnostic data.
