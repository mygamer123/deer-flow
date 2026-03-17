# P0 Implementation Plan

## Scope Lock

This plan implements only the audit P0 items:

- P0.1 dedicated research-agent topology
- P0.2 claim/evidence model + evidence service
- P0.3 verifier layer
- P0.4 minimal setup research flow
- P0.5 structured, evidence-backed report generation

Everything else stays out of scope unless it is a direct dependency for the above.

## Blunt Current-State Recheck

- The repo already has a real finance trade-review package.
- The repo also now has a generic `backend/src/community/research/` module, but it is not sufficient for the target P0 architecture:
  - it has no `evidence_id` contract
  - it has no verifier gate
  - it renders Markdown directly
  - it is generic web research, not a narrow setup-research workflow
- The current runtime still only has one real LangGraph graph registered in `backend/langgraph.json`.

So the minimal real path is not to replace DeerFlow or rewrite finance. It is to add a thin structured trading-research layer on top of the existing finance/research modules and then expose that layer through narrow entrypoints.

## Architecture Decision

### Chosen approach

Use adapter/wrapper services, not a repo-wide refactor.

Concretely:

1. Keep existing finance internals as the truth-engine base.
2. Reuse the current `community/research` module only as a raw topic-research helper where useful.
3. Add a new narrow package for structured P0 workflows.
4. Make reports render from structured result objects only.
5. Add a deterministic verifier gate before report rendering.
6. Add minimal callable entrypoints.

### What counts as the P0 "agent topology"

Minimal, code-tracked topology for P0 will be:

- existing `lead_agent`
- new `trade_review_agent` graph wrapper
- new `setup_research_agent` graph wrapper

The verifier will be implemented as a deterministic service gate, not an LLM-heavy fake agent. That is the smallest honest implementation.

### What will NOT be done in P0

- No market regime agent
- No catalyst/news agent as a separate runtime agent
- No frontend rewrite
- No channel/chat integration work
- No platform-wide prompt redesign
- No generic clean-architecture reorg of the whole repo
- No database migration or heavy persistence layer
- No real trading execution

## Implementation Order

### Phase 1: Structured schemas

Add first-class structured models for:

- `EvidenceItem`
- `Claim`
- `Finding`
- `Recommendation`
- `ReviewResult`
- `SetupResearchResult`
- `VerifierResult`

Rules baked into schema shape:

- important claims carry `evidence_ids: list[str]`
- claims/findings include `confidence` where meaningful
- include `sample_size` where meaningful
- include `limitations: list[str]`
- include `as_of` timestamps
- include explicit separation between findings, claims, and recommendations

### Phase 2: Evidence service

Add a minimal file-backed evidence service that:

- assigns stable evidence IDs from deterministic provenance data
- persists evidence JSON records
- supports lookup by ID
- supports batch registration from both trade review and setup research flows

### Phase 3: Verifier service

Add a deterministic verifier that:

- checks every claim references existing evidence IDs
- downgrades claims with missing evidence
- records issues/warnings in a structured verifier result
- gates final Markdown rendering

No fake semantic verification.

### Phase 4: Trade review structured service

Wrap the existing finance `DecisionReviewService` in a new structured `trade_review_service` adapter that:

- runs the current finance review logic unchanged as much as possible
- converts `TradeReview` / `DayReview` into structured `ReviewResult`
- registers evidence
- runs verifier
- returns structured output first

### Phase 5: Setup research structured service

Add a narrow `setup_research_service` that:

- takes a simple deterministic topic/setup input
- uses current research helpers and/or direct web search results as raw inputs
- emits structured findings/claims/recommendations
- registers evidence
- runs verifier
- returns structured output first

### Phase 6: Report service

Add one report renderer that consumes only structured results and outputs Markdown with explicit sections:

- Findings
- Claims
- Recommendations
- Evidence references
- Verifier summary
- Limitations

### Phase 7: Minimal entrypoints

Add:

- CLI entrypoint for trade review
- CLI entrypoint for setup research
- narrow tool wrappers for the new structured flows
- minimal LangGraph graph wrappers for `trade_review_agent` and `setup_research_agent`

### Phase 8: Tests

Add focused tests only for the P0 path:

- schema tests
- evidence service tests
- verifier tests
- trade review structured-output tests
- setup research structured-output tests
- report rendering tests

## File-by-File Plan

### New package: `backend/src/trading_research/`

Create this new package instead of stuffing more logic into `community/finance`.

#### `backend/src/trading_research/__init__.py`
- Package exports for P0 workflow services and schema entrypoints.

#### `backend/src/trading_research/models.py`
- Add the new structured P0 schemas.
- Keep them pragmatic dataclasses to match the existing finance style.

#### `backend/src/trading_research/evidence_service.py`
- Stable evidence ID generation
- evidence persistence
- evidence lookup helpers

#### `backend/src/trading_research/verifier_service.py`
- deterministic verification logic
- downgrade unsupported claims
- build `VerifierResult`

#### `backend/src/trading_research/report_service.py`
- render Markdown from `ReviewResult` and `SetupResearchResult`
- optionally provide JSON serialization helper if useful for CLI tests

#### `backend/src/trading_research/store.py`
- persist structured results for traceability
- file-backed, no DB

#### `backend/src/trading_research/trade_review_service.py`
- adapter around `backend/src/community/finance/decision_review_service.py`
- translate finance outputs to structured results
- register evidence
- run verifier

#### `backend/src/trading_research/setup_research_service.py`
- narrow setup-research flow
- reuse the current `community/research/research_service.py` where it helps
- convert raw research output into structured result + evidence + verifier pass

#### `backend/src/trading_research/tools.py`
- add narrow tool wrappers for:
  - `run_trade_review`
  - `run_setup_research`
- these should call the new structured services, not the old string-first renderers

#### `backend/src/trading_research/cli.py`
- argparse-based minimal CLI
- subcommands:
  - `trade-review`
  - `setup-research`

### Agent topology

#### `backend/src/agents/trading_research_agents.py`
- add minimal graph factory wrappers:
  - `make_trade_review_agent`
  - `make_setup_research_agent`
- reuse DeerFlow agent construction patterns
- keep tool surface narrow by using only the new workflow tool group
- append short domain-specific prompt instructions instead of rewriting DeerFlow core prompts

#### `backend/langgraph.json`
- register the new graphs alongside `lead_agent`

### Config wiring

#### `config.yaml`
- add a new tool group for the structured P0 workflow tools
- register the new tool wrappers
- add minimal research config only if truly needed for defaults

#### `config.example.yaml`
- mirror the new tool group + tool entries

### Existing code to adapt, not rewrite

#### `backend/src/community/finance/decision_review_service.py`
- leave core analysis logic intact
- only touch if a small helper/export is needed by the new adapter

#### `backend/src/community/finance/models.py`
- do not replace existing finance dataclasses
- only extend if a tiny compatibility hook is needed

#### `backend/src/community/research/research_service.py`
- preserve current raw research behavior unless a small adapter hook is needed
- do not count it as the final P0 schema/verifier layer

### Tests

#### New tests under `backend/tests/test_trading_research/`

- `test_models.py`
- `test_evidence_service.py`
- `test_verifier_service.py`
- `test_trade_review_service.py`
- `test_setup_research_service.py`
- `test_report_service.py`

## Dependencies / Execution Sequence

1. `models.py`
2. `evidence_service.py`
3. `verifier_service.py`
4. `trade_review_service.py`
5. `setup_research_service.py`
6. `report_service.py`
7. `tools.py` and `cli.py`
8. graph wrappers + `langgraph.json`
9. config updates
10. tests
11. `audit/p0_completion_report.md`

## Risks

### Risk 1: Existing finance outputs are not naturally evidence-shaped
- Mitigation: register evidence from deterministic observations, metrics, hypotheses, and source/provenance fields without rewriting finance internals.

### Risk 2: The current `community/research` module is generic and weakly structured
- Mitigation: treat it as an input collector only. The new structured setup-research service owns final result shape, verifier pass, and report generation.

### Risk 3: Agent-topology work could balloon into platform refactor
- Mitigation: add only two minimal graph wrappers for P0. No generalized multi-agent framework changes.

### Risk 4: Verifier overreach
- Mitigation: verifier will only do deterministic checks: existence of evidence IDs, missing evidence, empty evidence, unsupported claims, and explicit downgrade behavior.

## Non-Goals

- no attempt to build a full quant research platform
- no broker execution
- no autonomous strategy mutation
- no market-regime / catalyst agent split in this pass
- no UI redesign
- no cleanup of unrelated DeerFlow docs/platform issues

## Definition of Done for This P0 Pass

The P0 pass is done only when all of the following are true:

1. Trade review produces a structured result object before Markdown.
2. Setup research produces a structured result object before Markdown.
3. Both flows register evidence with stable IDs.
4. Both flows run through a deterministic verifier.
5. Final Markdown clearly separates findings, claims, recommendations, evidence references, verifier summary, and limitations.
6. Minimal CLI entrypoints work.
7. New tests cover the new structured path.
8. `audit/p0_completion_report.md` documents what is complete and what remains.
