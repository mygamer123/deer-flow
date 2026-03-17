# P1 Implementation Plan

## Scope Lock

This pass implements only two P1 items:

1. explicit anti-future-leakage controls
2. enforced sample-size downgrade rules

Everything else stays out of scope unless it is a strict dependency of these two controls.

Out of scope:

- new agents
- UI work
- Slack / OpenClaw / channel work
- broader research expansion
- semantic fact-checking
- repo-wide refactors
- changing DeerFlow core orchestration patterns

## Blunt Current-State Recheck

- The structured P0 core is real and should stay intact.
- The missing P1 controls belong inside the existing structured core, not in new orchestration layers.
- The current gap is not data access; it is enforcement.
- Right now the system records `as_of` and `sample_size`, but it does not enforce claim-boundary timing rules or hard sample-size downgrades.

## Narrow Design

### Anti-future-leakage

The minimum honest implementation is:

- attach explicit timing metadata to evidence
- attach explicit claim boundary metadata to claims/results
- make the verifier compare claim boundaries against evidence timing windows
- expose boundary outcomes in the verifier output and final report

No fake semantic leakage detection.

### Sample-size downgrade

The minimum honest implementation is:

- define hard thresholds in verifier logic
- downgrade low-sample claims to `observation`
- suppress recommendations supported only by low-sample or unsupported claims
- expose downgrade/suppression in verifier output and final report

No LLM judgment.

## Exact Files To Change

### 1. `backend/src/trading_research/models.py`

Why:
- this is where explicit timing and rule-enforcement fields belong

Planned changes:
- add boundary/timing fields to `EvidenceItem`
- add boundary fields to `Claim`
- add result-level boundary field to `StructuredResult` / `ReviewResult` / `SetupResearchResult`
- extend `VerifierResult` with explicit boundary/sample-size outcome fields

Planned new fields:

- `EvidenceItem.observed_at: datetime | None`
- `EvidenceItem.effective_start: datetime | None`
- `EvidenceItem.effective_end: datetime | None`
- `Claim.boundary_time: datetime | None`
- `StructuredResult.boundary_time: datetime | None`
- `VerifierResult.boundary_status: str` with values like `passed`, `failed`, `limited`
- `VerifierResult.boundary_violation_claim_ids: list[str]`
- `VerifierResult.sample_size_downgraded_claim_ids: list[str]`

Notes:
- keep `as_of` as metadata; do not overload it as the only timing field
- keep existing `supported_by_claim_ids` unchanged

### 2. `backend/src/trading_research/evidence_service.py`

Why:
- this is the right place to normalize and persist timing-aware evidence metadata

Planned changes:
- keep evidence-only persistence responsibility
- preserve the current stable ID algorithm, but make the timing rules explicit in code/comments/tests
- optionally accept/store timing metadata without making it part of the default hash
- add helper logic for normalized timing-aware persistence

Invariants:
- `evidence_service.py` persists evidence only
- it does not persist workflow outputs
- it does not run verifier logic
- runtime-generated timestamps are not part of the hash by default

Hash invariant:
- hash input stays based on normalized provenance payload + evidence type + schema/version + stable source identity + normalized content
- `observed_at`, `effective_start`, `effective_end`, and `as_of` remain metadata unless a caller explicitly needs them in provenance

### 3. `backend/src/trading_research/verifier_service.py`

Why:
- this is the correct enforcement point for both P1 controls

Planned changes:

#### Anti-future-leakage enforcement
- for each claim, compare `claim.boundary_time` against all referenced evidence items
- deterministic rules:
  - if evidence has `observed_at` after `claim.boundary_time`, flag boundary violation
  - if evidence has `effective_start` after `claim.boundary_time`, flag boundary violation
  - if evidence has `effective_end` after `claim.boundary_time`, flag boundary violation because the evidence window extends past the allowed claim boundary
  - if timing metadata is missing for referenced evidence, flag boundary-limited status
- consequence:
  - hard boundary violation -> claim downgraded to `unsupported`
  - incomplete timing metadata -> claim downgraded to `observation` unless already weaker

#### Sample-size enforcement
- define deterministic module-level defaults inside verifier service, not config-driven for this pass
- proposed defaults:
  - `MIN_SUPPORTED_CLAIM_SAMPLE_SIZE = 2`
  - `MIN_RECOMMENDATION_SAMPLE_SIZE = 3`
- rules:
  - if `claim.sample_size` is `None` or `< MIN_SUPPORTED_CLAIM_SAMPLE_SIZE`, downgrade claim to `observation`
  - cap downgraded claim confidence to a deterministic ceiling, e.g. `min(existing_confidence, 0.49)`
  - recommendation is dropped if any `supported_by_claim_ids` claim is not `supported`
  - recommendation is also dropped if every supporting claim has `sample_size < MIN_RECOMMENDATION_SAMPLE_SIZE`

Verifier output invariants:
- explicit boundary status must be set on every run
- explicit downgraded claim IDs must be recorded
- explicit dropped recommendation IDs must be recorded
- reasons must be emitted as deterministic issue codes

### 4. `backend/src/trading_research/trade_review_service.py`

Why:
- trade review must attach claim boundaries and evidence timing explicitly instead of relying on implicit finance semantics

Planned changes:
- annotate evidence timing per evidence type
- annotate claim boundaries per claim type

Planned trade-review boundary model:

- `selection` claim boundary -> signal timestamp if present, else entry timestamp
- `entry` claim boundary -> entry timestamp
- `exit` claim boundary -> exit timestamp if present, else result `as_of`
- `failure` claim boundary -> result `as_of`
- `overall` claim boundary -> result `as_of`

Planned evidence timing model:

- trade snapshot evidence -> `observed_at` and `effective_end` at signal timestamp when it describes the signal
- overall summary evidence -> `observed_at` and `effective_end` at review `as_of`
- module evidence:
  - selection evidence -> capped at selection boundary
  - entry evidence -> capped at entry boundary
  - exit evidence -> capped at exit boundary
  - failure evidence -> capped at review `as_of`

Compatibility note:
- no finance module logic rewrite
- only add explicit timing/boundary mapping in the structured adapter layer

### 5. `backend/src/trading_research/setup_research_service.py`

Why:
- setup research currently has no explicit leakage guard against researching a past setup with present-day fetched evidence

Planned changes:
- derive one explicit result boundary for every setup research run:
  - if `trade_date` is provided -> boundary is end-of-day for that date
  - otherwise -> boundary is report creation time
- set result `boundary_time`
- set claim `boundary_time` to the result boundary
- set evidence timing from raw research sources:
  - `observed_at = source.fetched_at`
  - `effective_start = source.fetched_at`
  - `effective_end = source.fetched_at`

Expected deterministic consequence:
- if the user asks for past-date setup research using newly fetched evidence, the verifier will flag or fail those claims instead of silently accepting them

Compatibility note:
- keep the setup contract narrow: `symbol`, `setup_type`, `trade_date`
- do not expand into generic topic research

### 6. `backend/src/trading_research/report_service.py`

Why:
- the report must make both new controls visible

Planned changes:
- extend verifier summary rendering to show:
  - boundary status (`passed` / `failed` / `limited`)
  - boundary-violating claim IDs
  - sample-size downgraded claim IDs
  - dropped recommendation IDs
- make claim output clearly distinguish:
  - `supported`
  - `observation`
  - `unsupported`
- make recommendation section clearly show when no recommendations remain because support was suppressed

Report invariants:
- boundary outcomes must be visible
- downgrade outcomes must be visible
- recommendations must still show `supported_by_claim_ids`

### 7. Tests under `backend/tests/test_trading_research/`

Why:
- these two P1 controls are only real if they are enforced in tests

Planned test work:

#### Update existing tests
- `test_verifier_service.py`
- `test_trade_review_service.py`
- `test_setup_research_service.py`
- `test_report_service.py`
- `test_golden_flows.py`

#### Add focused new tests
- `test_boundary_controls.py`
- `test_sample_size_rules.py`

Required coverage:

##### A. Anti-future-leakage
- evidence with post-boundary timestamps gets flagged or causes claim downgrade
- verifier catches claim-level boundary violations
- incomplete timing metadata produces `limited` boundary status
- report includes boundary-check summary

##### B. Sample-size downgrade
- low-sample claims are downgraded deterministically to `observation`
- low-sample claims have confidence capped deterministically
- recommendations backed only by low-sample claims are suppressed
- report distinguishes supported claims from downgraded observations

##### C. Golden-path regression
- trade review golden flow still works with the new verifier behavior
- setup research golden flow still works with the new verifier behavior
- update expectations if P1 rules legitimately reduce claims to observations or suppress recommendations

## Invariants To Enforce

### Boundary invariants
- every structured result has a clear boundary time
- every claim has a clear boundary time
- every evidence item used for a claim is either:
  - within boundary, or
  - explicitly flagged as limited, or
  - explicitly flagged as violating boundary
- no claim remains `supported` if it relies on boundary-violating evidence

### Sample-size invariants
- no claim remains `supported` below the claim threshold
- no recommendation survives if its supporting claims fail recommendation eligibility
- downgrade behavior is fully deterministic and testable

### Persistence invariants
- `evidence_service.py` still handles evidence persistence only
- `store.py` still handles result persistence only

## What Will NOT Be Changed

- no graph-wrapper work in this phase
- no new agents
- no config.yaml expansion unless a strict bug forces it
- no finance algorithm rewrite
- no UI work
- no semantic fact verification layer
- no setup research contract expansion beyond the current narrow template

## Risks / Compatibility Notes

### Risk 1: Trade-review outputs may become more conservative
- With hard sample-size rules, many current trade-review claims may downgrade to `observation` and some recommendations may disappear.
- This is expected behavior, not a bug.

### Risk 2: Past-dated setup research may fail more often
- If setup research is requested for a historical date using present-day fetched evidence, the verifier should flag it.
- This is the intended anti-leakage behavior.

### Risk 3: Timing metadata for some evidence may be incomplete
- The plan handles this honestly with `boundary_status = limited` rather than pretending the evidence is safe.

### Risk 4: Existing golden tests will need expectation updates
- They should still pass, but some expected statuses or recommendations may change because P1 is intentionally stricter.

## Execution Order

1. `models.py`
2. `evidence_service.py`
3. `verifier_service.py`
4. `trade_review_service.py`
5. `setup_research_service.py`
6. `report_service.py`
7. tests
8. `audit/p1_completion_report.md`

That is the entire plan.
