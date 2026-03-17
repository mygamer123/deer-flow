# P1 Completion Report

## Scope

Two P1 controls implemented inside the existing structured core:

1. **Anti-future-leakage controls** — explicit boundary/timing metadata on evidence and claims, with deterministic verifier enforcement
2. **Enforced sample-size downgrade rules** — hard thresholds that downgrade low-sample claims and suppress weak recommendations

No new agents, no UI work, no repo-wide refactors. The P0 structured core remains intact.

## Completed Items

### 1. Anti-Future-Leakage Controls

#### Evidence timing metadata
- `EvidenceItem` now carries `observed_at`, `effective_start`, `effective_end` (all `datetime | None`)
- These fields are metadata-only — they do NOT participate in the evidence ID hash
- `evidence_service.py` persists and restores these three fields

#### Claim and result boundary times
- `Claim.boundary_time: datetime | None` — the latest moment evidence should represent
- `StructuredResult.boundary_time: datetime | None` — the result-level boundary

#### Trade review timing assignments
- Snapshot evidence: `observed_at = signal_timestamp`
- Summary evidence: `observed_at = as_of`, `effective_start = effective_end = as_of`
- Lens evidence: `observed_at = module_boundary_time` (mapped per module)
- Claim boundary times: selection → signal timestamp, entry → entry timestamp, exit → exit timestamp, failure/overall → as_of
- `_module_boundary_time()` helper maps module names to appropriate timestamps

#### Setup research timing assignments
- Evidence: `observed_at = effective_start = effective_end = source.fetched_at`
- Result boundary: `trade_date 23:59:59` if trade_date provided, else `report.created_at`
- `_derive_boundary_time()` helper

#### Verifier boundary enforcement
- `_check_claim_boundary()` compares each claim's `boundary_time` against supporting evidence `observed_at`, `effective_start`, `effective_end`
- Evidence observed/effective after claim boundary → claim downgraded to `unsupported`, boundary violation recorded
- Evidence with no timing metadata → claim status `observation`, boundary status `limited`
- Claim with no boundary_time → boundary check skipped (honest handling)

#### Verifier output fields
- `VerifierResult.boundary_status: str` — `"passed"`, `"failed"`, or `"limited"`
- `VerifierResult.boundary_violation_claim_ids: list[str]`
- `_merge_boundary_status()` helper computes overall status from per-claim outcomes

#### Report rendering
- Verifier summary now shows: `Boundary status: {status}`
- When violations exist: `Boundary violations: {claim_ids}`

### 2. Enforced Sample-Size Downgrade Rules

#### Hard thresholds (module-level constants)
- `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2` — claims below this are downgraded to `observation`
- `MIN_RECOMMENDATION_SAMPLE_SIZE = 3` — recommendations whose claims are all below this are dropped
- `SAMPLE_SIZE_CONFIDENCE_CAP = 0.49` — confidence ceiling for sample-size-downgraded claims

#### Claim downgrade logic
- `_check_sample_size()` runs on every claim
- `sample_size is None` or `sample_size < MIN_SUPPORTED_CLAIM_SAMPLE_SIZE` → status becomes `observation`, confidence capped at `SAMPLE_SIZE_CONFIDENCE_CAP`
- Confidence is only lowered, never raised

#### Recommendation suppression
- Recommendations are dropped if ALL supporting claims have `sample_size < MIN_RECOMMENDATION_SAMPLE_SIZE`
- Recommendations are also dropped if no supporting claim survived verification as `supported`

#### Verifier output fields
- `VerifierResult.sample_size_downgraded_claim_ids: list[str]`

#### Report rendering
- Verifier summary now shows: `Sample-size downgraded claims: {claim_ids}` (when present)

## Behavioral Consequences

### Trade review outputs are now more conservative
- All trade review claims have `sample_size=1` (single-trade reviews)
- With `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2`, all these claims downgrade to `observation`
- Since all claims downgrade, recommendations that depend on them are dropped
- `verifier.passed` becomes `False` for single-trade reviews
- **This is expected behavior per the plan (Risk 1), not a bug** — single observations should not drive recommendations

### Setup research with few sources
- Claims with `sample_size = len(evidence_ids)` — claims backed by only 1 source get `sample_size=1` and downgrade
- Same downstream effect: recommendations drop if all supporting claims are low-sample
- **This is also expected** — weak evidence should not produce strong recommendations

## Files Changed

### Source files modified
- `backend/src/trading_research/models.py` — added timing and boundary fields to `EvidenceItem`, `Claim`, `StructuredResult`, `VerifierResult`
- `backend/src/trading_research/evidence_service.py` — persistence for `observed_at`, `effective_start`, `effective_end`
- `backend/src/trading_research/verifier_service.py` — complete rewrite with boundary enforcement + sample-size rules
- `backend/src/trading_research/trade_review_service.py` — evidence timing metadata, claim boundary times, `_module_boundary_time()`, `_build_claims()` signature change
- `backend/src/trading_research/setup_research_service.py` — evidence timing, `_derive_boundary_time()`, `_build_claims()` signature change
- `backend/src/trading_research/report_service.py` — boundary status + sample-size downgrade rendering in verifier summary

### Source files NOT modified (intentionally)
- `backend/src/trading_research/store.py` — result-only persistence, no boundary/sample-size responsibility
- `backend/src/trading_research/cli.py` — no changes needed
- `backend/src/trading_research/tools.py` — no changes needed
- `backend/src/trading_research/__init__.py` — no changes needed

### Test files created
- `backend/tests/test_trading_research/test_boundary_controls.py` — 7 tests
- `backend/tests/test_trading_research/test_sample_size_rules.py` — 9 tests (+ 1 threshold constant test = 10 total functions)

### Test files updated
- `backend/tests/test_trading_research/test_verifier_service.py` — expectations updated for sample-size downgrades
- `backend/tests/test_trading_research/test_trade_review_service.py` — expects `verifier.passed=False`, `recommendations=[]`
- `backend/tests/test_trading_research/test_setup_research_service.py` — expects `verifier.passed=False`, `recommendations=[]`
- `backend/tests/test_trading_research/test_report_service.py` — asserts `"Boundary status: passed"` in output
- `backend/tests/test_trading_research/test_golden_flows.py` — both flows expect `verifier.passed=False`, sample-size downgrades, `recommendations=[]`

### Audit
- `audit/p1_implementation_plan.md` — the spec (unchanged)
- `audit/p1_completion_report.md` — this file

## Tests

### New tests: boundary controls (7)
- `test_boundary_violation_when_evidence_observed_after_claim_boundary`
- `test_boundary_violation_when_effective_end_after_boundary`
- `test_boundary_violation_when_effective_start_after_boundary`
- `test_boundary_limited_when_evidence_has_no_timing`
- `test_boundary_passes_when_all_evidence_within_boundary`
- `test_boundary_not_checked_when_claim_has_no_boundary_time`
- `test_boundary_violation_drops_recommendation`

### New tests: sample-size rules (10)
- `test_claim_below_min_sample_size_downgraded_to_observation`
- `test_claim_with_none_sample_size_downgraded`
- `test_confidence_capped_on_sample_size_downgrade`
- `test_confidence_preserved_when_already_below_cap`
- `test_claim_at_threshold_passes_sample_size_check`
- `test_recommendation_dropped_when_all_claims_below_rec_threshold`
- `test_recommendation_kept_when_supporting_claim_meets_rec_threshold`
- `test_recommendation_dropped_when_claim_downgraded_by_sample_size`
- `test_thresholds_have_expected_values`

### Updated existing tests (5 files)
- All updated to match new enforcement behavior
- No tests deleted — only expectations changed

## Verification Run

```
$ cd backend && .venv/bin/python -m pytest tests/test_trading_research/ -v
34 passed in 1.05s
```

Zero failures. Zero skips.

## Invariants Now Enforced (Hard, Not Best-Effort)

| Invariant | Enforcement Point | Consequence |
|---|---|---|
| Evidence observed after claim boundary → violation | `verifier_service._check_claim_boundary()` | Claim becomes `unsupported`, boundary status `failed` |
| Evidence effective range extends past boundary → violation | `verifier_service._check_claim_boundary()` | Same |
| Evidence with no timing metadata → honest degradation | `verifier_service._check_claim_boundary()` | Claim becomes `observation`, boundary status `limited` |
| Claim `sample_size < 2` → downgraded | `verifier_service._check_sample_size()` | Claim becomes `observation`, confidence capped at 0.49 |
| Claim `sample_size is None` → downgraded | `verifier_service._check_sample_size()` | Same |
| All supporting claims `sample_size < 3` → recommendation dropped | `verifier_service.verify()` | Recommendation removed from output |
| No surviving `supported` claim for recommendation → dropped | `verifier_service.verify()` | Recommendation removed from output |

## Known Limitations

- Boundary checks rely on services setting `observed_at`/`effective_start`/`effective_end` correctly. If a service sets bogus timestamps, the verifier will happily accept them. The invariant is structural, not semantic.
- `boundary_status = "limited"` (evidence has no timing) is honest but does not actively prevent leakage — it only signals that boundary verification could not run.
- Trade reviews will always produce `verifier.passed=False` until trade reviews accumulate multi-trade evidence (sample_size ≥ 2). This is intentional conservatism, not a bug.
- The thresholds (`MIN_SUPPORTED_CLAIM_SAMPLE_SIZE=2`, `MIN_RECOMMENDATION_SAMPLE_SIZE=3`, `SAMPLE_SIZE_CONFIDENCE_CAP=0.49`) are hard-coded constants. Changing them requires a code change and test update, which is the correct level of friction.
- No semantic fact-checking was added. The verifier remains deterministic and structural.

## What Still Remains Beyond P1

- Semantic verification or human review checkpoints
- Multi-trade aggregation pipelines that produce claims with `sample_size ≥ 2`
- Broader agent topology (market regime agent, catalyst/news agent)
- Cross-result consistency checks (comparing claims across multiple research runs)
- Frontend integration for boundary/sample-size status display
- Documentation for the structured trading research workflow

## Honest Verdict

The two P1 controls are real and enforced:

1. **Boundary checks are hard invariants.** Evidence observed or effective after a claim's boundary time causes the claim to be downgraded and flagged. Missing timing is reported honestly as `limited`, not silently passed.

2. **Sample-size rules are hard invariants.** Low-sample claims cannot be `supported`. Low-sample recommendations are dropped. The system is now intentionally conservative — single observations cannot drive recommendations.

The P0 structured core remains intact. The P1 controls live entirely inside the existing service/verifier/report architecture. No new orchestration layers, no prompt-based enforcement, no semantic theater.
