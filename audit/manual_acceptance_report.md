# Manual Acceptance Report: trading_research Structured Core

**Date**: 2026-03-14
**Scope**: 5 acceptance scenarios exercising DiagnosticService, AggregateReviewService, StrategyImprovementService, SetupResearchService, EvidenceService, VerifierService, and ReportService
**Prior work**: P0-P3.1 complete, 5 correctness hotfixes applied, 113/113 tests passing

---

## 1. Executive Verdict

**PASS WITH CAVEATS**

The structured core produces plausible, internally consistent, and mechanically sound outputs across all 5 acceptance scenarios. No acceptance blockers were found. Three caveats are noted in Section 7 — none require code changes before shipping, but all affect real-world usefulness if left unaddressed in future iterations.

---

## 2. Dataset / Sample Used

Five representative synthetic trade reviews modeled after production data shapes:

| Trade | Symbol | Pattern | Verdict | Outcome | Quality |
|-------|--------|---------|---------|---------|---------|
| TRADE_1 | AMPX | strong_uptrending | good_trade | tp_filled | GOOD |
| TRADE_2 | TSLA | pullback_breakout | bad_trade | stopped_out | BAD |
| TRADE_3 | NVDA | strong_uptrending | bad_trade | stopped_out | BAD |
| TRADE_4 | AMD | strong_uptrending | marginal | manual_exit | FAIR |
| TRADE_5 | COIN | strong_uptrending | should_skip | stopped_out | BAD |

Scenario A: all 5 trades. Scenario B: 4 bad trades filtered to 3 by `pattern=strong_uptrending`. Scenario C: mocked ResearchReport with 3 sources and boundary-clamped timestamps. Scenario D: all 5 trades filtered to 4 by pattern. Scenario E: judgment on Scenario B.

---

## 3. Scenario A: Single-Trade Diagnostic Sanity

### Results

| Trade | Grade | Opportunity | Execution | Extraction | Failure Reason | Action Type |
|-------|-------|-------------|-----------|------------|----------------|-------------|
| AMPX (good) | A | valid | excellent | fully_extracted | no_failure | no_change |
| TSLA (bad) | E | marginal | poor | poorly_extracted | multiple_failures | tighten_risk_rule |
| NVDA (bad) | E | valid | poor | poorly_extracted | multiple_failures | tighten_risk_rule |
| AMD (marginal) | E | marginal | poor | poorly_extracted | multiple_failures | tighten_risk_rule |
| COIN (should_skip) | E | invalid | poor | poorly_extracted | bad_opportunity_and_execution | tighten_risk_rule |

### Assessment: PASS

Every diagnostic is plausible and internally consistent:

- **AMPX (good trade)**: Grade A, valid opportunity, excellent execution, fully extracted. No failure, no action needed. Correct.
- **TSLA (bad, stopped out)**: Grade E, marginal opportunity (marginal signal score), poor execution ("suboptimal" in statement), poorly extracted (stopped_out + BAD quality). Multiple failures, tighten risk. Correct.
- **NVDA (bad, stopped out)**: Grade E, valid opportunity (strong signal 8.9 but weak context — "should have been taken" triggers valid), poor execution ("suboptimal" in statement), poorly extracted. Correct.
- **AMD (marginal, manual_exit)**: Grade E, marginal opportunity (moderate signal), poor execution ("suboptimal"), poorly extracted (manual_exit + FAIR quality maps to poorly_extracted). This is the one borderline case — "poorly_extracted" for a FAIR/manual_exit trade feels slightly harsh. However, the derivation logic (`manual_exit` + quality_tier != `GOOD` → `POORLY_EXTRACTED`) is consistent with the code. Not a bug; at most a tuning question.
- **COIN (should_skip)**: Grade E, invalid opportunity ("should not have been taken" + confidence 0.7 >= 0.5), poor execution, poorly extracted, bad_opportunity_and_execution. Correct — COIN shouldn't have been taken, and the system correctly identifies both opportunity and execution as failures.

**No contradictions. No obviously broken outputs.** The grade distribution (one A, four E) is stark but defensible — these are intentionally bad trades except AMPX.

---

## 4. Scenario B: Aggregate Bad-Trade Cohort

### Aggregate Review Results

- **Trade count**: 3 (TSLA correctly excluded — `pullback_breakout` != `strong_uptrending`)
- **Contributing IDs**: NVDA, AMD, COIN
- **Grouping key**: `strong_uptrending`
- **Verifier**: PASS (all claims reference persisted evidence)

**Cohort Stats**:
- Outcome: manual_exit=1, stopped_out=2
- Quality: BAD=2, FAIR=1
- Verdict: bad_trade=1, marginal=1, should_skip=1

**Claims (4)**:
1. "0% received a good_trade or acceptable verdict" — status: supported, confidence: 0%, sample_size: 3. **Correct.** 0% is accurate (0/3).
2. "2/3 selection claims indicated the trade should have been taken" — status: supported, confidence: 62%, sample_size: 3. **Correct.** NVDA and AMD have "should have been taken"; COIN has "should not have been taken". 2/3 = 67%, confidence is 62% (average of individual claim confidences).
3. "3/3 entry claims indicated suboptimal entry timing" — status: supported, confidence: 55%, sample_size: 3. **Correct.** All three have "suboptimal" in their entry statements.
4. "Most frequently recommended exit policy is `fixed_tp_sl`" — status: supported, confidence: 62%, sample_size: 3. **Correct.** NVDA and COIN favor `fixed_tp_sl`, AMD favors `trailing_stop`. 2/3 majority.

**Recommendations (3)**: All medium priority, each backed by a specific claim. Selection, entry, and exit recommendations are present. All evidence IDs are claim-type-specific (not generic cohort-summary fallback).

### Strategy Improvement Results

- **Trades diagnosed**: 3
- **Patterns extracted**: 3 (failure_reason=multiple_failures at 67%, action_type=tighten_risk_rule at 100%, improvement_direction=improve_entry at 67%)
- **Candidates**: 2
  - `proposed` (n=2, failure_reason pattern) — below MIN_VERIFIED_SAMPLE_SIZE of 3, correctly stays at `proposed`
  - `verified_candidate` (n=3, action_type pattern) — meets sample size, correctly promoted to `verified_candidate`
- **Change records**: 1 — only the verified candidate gets a change record. Correct.
- **Verified claims**: 4 — all aggregate claims pass through to strategy improvement. Correct.

### Assessment: PASS

- Sample sizes are correct (3 distinct trades, not double-counted).
- Grouping is explicit and pattern-filtered correctly.
- Cohort summary is coherent with the input data.
- Claims survive verification with correct evidence linkage.
- Strategy candidates are emitted only when pattern support exists.
- Candidate status progression (`proposed` vs `verified_candidate`) respects sample-size thresholds.
- Change record persistence works — only the verified candidate generates a record.
- Report markdown is well-structured and readable.

---

## 5. Scenario C: Historical Setup Research

### Results

- **Topic**: AMPX intraday breakout setup research
- **Boundary time**: 2026-03-05 23:59:59
- **Evidence timing**: All evidence clamped to boundary. `evidence_timing_ok = True`. Correct.
- **Verifier**: FAIL (boundary: passed, 2 claims downgraded, 1 recommendation dropped)

**Claims (3)**:
1. "Strong relative volume and price momentum" — status: supported, confidence: 0.70, evidence: 2 items. **Correct.** Two sources support it, sample_size=2 >= MIN_SUPPORTED_CLAIM_SAMPLE_SIZE of 2.
2. "Day-2 catalyst continuation setups have historically elevated win rate" — status: **observation** (downgraded from supported), confidence: 0.40, evidence: 1 item. **Correct.** Original was `INSUFFICIENT` status with sample_size=1, correctly downgraded by verifier.
3. "Low float creates elevated reversal risk" — status: **observation** (downgraded from supported), confidence: 0.49, evidence: 1 item. **Correct.** Originally `SUPPORTED` but sample_size=1 < MIN_SUPPORTED_CLAIM_SAMPLE_SIZE of 2, so verifier downgraded and capped confidence at 0.49.

**Recommendations**: 0 (the single recommendation was dropped because all supporting claims had sample_size < MIN_RECOMMENDATION_SAMPLE_SIZE of 3). **Correct.**

**Verifier FAIL**: The verifier reports `passed=False` because the recommendation drop is an `error`-severity issue. This is correct behavior — the verifier is correctly flagging that the recommendation was insufficiently supported. The boundary check passed separately. The result is still interpretable; the FAIL means "verifier had to intervene", not "output is garbage."

### Assessment: PASS

- Verifier does NOT collapse into all boundary violations (boundary_status=passed, 0 violations).
- Evidence timing is honest — clamped to boundary, verified as correct.
- Approximation/limitations are surfaced clearly in the output.
- Result is interpretable — supported claim is identified, weak claims are downgraded with clear rationale.
- Recommendation absence is valid — correctly dropped due to insufficient support.
- The confidence cap (0.49) and status downgrade (supported → observation) are working as designed.

---

## 6. Scenario D: Claim-to-Evidence Trace

### Traced Claim

- **Claim ID**: `agg_claim_entry_strong_uptrending`
- **Statement**: "Across 4 trades in `strong_uptrending`, 3/4 entry claims indicated suboptimal entry timing."
- **Status**: supported, confidence: 55%, sample_size: 4

(Note: Scenario D used all 5 trades, so 4 matched `strong_uptrending`. The claim correctly reflects 3/4 suboptimal entries — AMPX has acceptable entry timing.)

### Evidence Trace

- **Evidence ID**: `ev_276914c8dea2`
- **Source ref**: `aggregate:strong_uptrending:entry_pattern` — **claim-type-specific** (not generic cohort-summary)
- **Sample size**: 4
- **Content preview**: Entry claims from 4 trades with specific statements from each

### Verification

- **Claim appears in report markdown**: Yes
- **Evidence is claim-specific**: Yes — source_ref contains `entry_pattern`, not `cohort_summary`

### Assessment: PASS

The evidence chain is intact: claim → evidence_id → evidence metadata → report section. The evidence is specific to the entry claim type (not a generic cohort summary fallback). The source_ref accurately describes what the evidence contains. The report markdown includes the claim statement and evidence references.

---

## 7. Scenario E: End-User Usefulness Judgment

### Would a trader learn something actionable from the Scenario B outputs?

**Yes, but with important caveats.**

The aggregate review correctly identifies:
1. **Entry timing is the dominant failure mode** (3/3 trades had suboptimal entry). A trader would see this and know to focus on entry execution.
2. **The exit policy recommendation** (`fixed_tp_sl` over `trailing_stop`) gives a specific, testable parameter change.
3. **The selection signal** (2/3 "should have been taken") correctly flags that the issue isn't stock selection but execution.

The strategy improvement loop adds:
4. **A verified candidate** (`tighten_risk_rule`) with a change record, which is the first step toward automated strategy adjustment.

### Is the recommended action too vague or too hindsight-driven?

**Partially hindsight-driven, but not uselessly so.** The `tighten_risk_rule` action type is generic — it doesn't specify *which* rule to tighten or by how much. However, the evidence backing (entry timing patterns, exit policy patterns) gives enough context for a trader to derive specific parameter changes. The system correctly avoids over-specifying actions it can't back with evidence.

The aggregate claims are grounded in structured data, not prose re-interpretation, which limits hindsight bias. The confidence values (55%-62%) and sample sizes (3) are honestly low, and the system surfaces this in limitations.

### What is the single most important weakness?

**The `tighten_risk_rule` action type is too coarse to be directly actionable.** Every bad trade gets the same diagnosis: `tighten_risk_rule`. When the failure modes are different (bad entry timing vs. bad stock selection vs. bad exit policy), collapsing them all into one action type loses the diagnostic specificity the system already has. The system *knows* the entry is the problem (3/3 suboptimal), but the strategy candidate says "tighten risk rule" rather than "improve entry timing protocol."

This is a P1-level improvement, not a blocker. The evidence and claims are specific enough that a human trader can interpret them correctly. But the strategy action type taxonomy would benefit from finer granularity (e.g., `improve_entry_timing`, `narrow_stop_loss`, `skip_low_score_setups`).

### Assessment: PASS WITH CAVEATS

---

## 8. Remaining Weaknesses (Top 3)

### 1. Strategy action type taxonomy is too coarse
**Severity**: Medium
**Impact**: Reduces actionability of strategy improvement candidates
**Detail**: `tighten_risk_rule` covers too many distinct failure modes. When entry timing is the clear problem, the action type should be more specific. The diagnostic *improvement_direction* field (`improve_entry`) is more useful than the action type.
**Recommendation**: Expand `StrategyActionType` enum to include `improve_entry_timing`, `narrow_stop_loss`, `raise_signal_threshold`, etc. Use `improvement_direction` to select the action type.

### 2. Extraction quality derivation is harsh for marginal trades
**Severity**: Low
**Impact**: AMD (FAIR quality, manual_exit) gets `poorly_extracted`, which feels slightly punitive for a marginal trade that was manually exited (not stopped out).
**Detail**: The derivation maps `manual_exit` + quality_tier != `GOOD` → `POORLY_EXTRACTED`. A FAIR-quality manual exit arguably should be `PARTIALLY_EXTRACTED`.
**Recommendation**: Consider a tier-aware mapping: FAIR + manual_exit → PARTIALLY_EXTRACTED.

### 3. No cross-pattern comparison capability
**Severity**: Low
**Impact**: A trader can only analyze one pattern at a time. If `pullback_breakout` trades also have entry timing issues, the system can't surface that commonality.
**Detail**: The aggregation is strictly pattern-filtered. Cross-pattern analysis would require a different aggregation mode or a meta-analysis layer.
**Recommendation**: Future P2+ work. Not a blocker.

---

## 9. Final Acceptance Decision

### PASS WITH CAVEATS

**Rationale**: All 5 acceptance scenarios produce correct, plausible, and internally consistent outputs. The evidence chain is intact from claims through evidence to reports. The verifier correctly enforces sample-size, boundary, and recommendation-support invariants. The diagnostic, aggregation, strategy improvement, and setup research services all work as designed with representative (non-trivially-synthetic) data.

**No acceptance blockers found.** No code changes required.

**Caveats** (none are blockers):
1. Strategy action type taxonomy should be expanded for real-world actionability
2. Extraction quality derivation could be more nuanced for marginal trades
3. Cross-pattern analysis is not yet supported

**Test coverage**: 113/113 tests passing (90 original + 8 regression + 15 verification).

**Services verified end-to-end**:
- DiagnosticService
- AggregateReviewService
- StrategyImprovementService
- SetupResearchService
- EvidenceService
- VerifierService
- ReportService (all 3 markdown generators)
