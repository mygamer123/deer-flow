# P0 Implementation Plan v2

## Scope Lock

This plan covers only the audit P0 items:

- P0.1 dedicated research-agent topology
- P0.2 claim/evidence model + evidence service
- P0.3 verifier layer
- P0.4 minimal setup research flow
- P0.5 structured, evidence-backed report generation

Out of scope unless a direct P0 dependency forces it:

- market regime agent
- catalyst/news agent as a separate runtime agent
- frontend work
- chat/channel work
- platform-wide DeerFlow refactors
- real trading execution
- broad generic research features beyond one narrow setup template

## Blunt Current-State Recheck

- The repo already has real finance trade-review logic in Python.
- The repo also has a generic `backend/src/community/research/` package, but it is not a safe P0 endpoint by itself because it is generic, not setup-scoped, and not evidence/verifier structured.
- The current runtime still centers on one generic `lead_agent` graph.

So the minimal real path is still:

1. keep existing finance truth-engine logic
2. add a narrow structured trading-research layer on top
3. make structured results, evidence registration, verifier checks, and Markdown rendering real first
4. add graph wrappers only after the core workflow works without them

## Core Design Decisions

### 1. Minimal real path beats architecture purity

Use adapters and wrappers.
Do not move or rename the existing finance package unless a tiny compatibility seam is required.

### 2. Core before graphs

The real P0 core is:

- services
- schemas
- verifier
- report pipeline
- CLI

LangGraph wrappers are last-mile orchestration, not the core. They should not block the P0 path.

### 3. Recommendations cannot float free

Every `Recommendation` must derive from verified claims.

Required contract:

- `supported_by_claim_ids: list[str]`

Rules:

- recommendations are generated only from claims that survive verifier checks
- if a claim is downgraded to unsupported, recommendations depending only on that claim must either be dropped or downgraded to low-confidence observations
- reports should show recommendation-to-claim linkage explicitly

### 4. Evidence and result persistence must not overlap

`evidence_service.py` responsibility:

- normalize deterministic provenance payloads into `EvidenceItem`
- generate stable `evidence_id`
- persist evidence records
- fetch evidence by ID

`store.py` responsibility:

- persist final structured workflow outputs (`ReviewResult`, `SetupResearchResult`)
- list/load saved workflow outputs
- never generate evidence IDs
- never persist standalone evidence records

Rule:

- evidence records live in the evidence store
- workflow outputs live in the result store
- result objects only reference evidence by ID

### 5. Deterministic verifier only

The verifier remains deterministic.
It does not pretend to semantically prove claims.

It will do only these checks:

- every claim has at least one `evidence_id`
- every referenced evidence ID exists in the evidence store
- every recommendation has at least one `supported_by_claim_ids` entry
- every referenced supporting claim exists in the result and is not `unsupported`
- if a claim is unsupported, recommendations depending on it cannot remain normal recommendations

## Implementation Priority Order

1. schemas
2. services and contracts
3. verifier
4. report pipeline
5. CLI/tool entrypoints
6. tests
7. LangGraph wrappers

That order is mandatory.

## Structured Schema Contract

Create pragmatic dataclass-style models in `backend/src/trading_research/models.py`.

### Required models

- `EvidenceItem`
- `Claim`
- `Finding`
- `Recommendation`
- `ReviewResult`
- `SetupResearchResult`
- `VerifierResult`
- `VerifierIssue`

### Required field rules

#### `EvidenceItem`
- `evidence_id: str`
- `evidence_type: str`
- `title: str`
- `content: str`
- `source_ref: str`
- `provenance: dict[str, object]`
- `as_of: datetime | None`
- `sample_size: int | None`
- `confidence: float | None`
- `limitations: list[str]`
- `schema_version: str`

#### `Claim`
- `claim_id: str`
- `statement: str`
- `status: supported | observation | unsupported`
- `evidence_ids: list[str]`
- `confidence: float | None`
- `sample_size: int | None`
- `limitations: list[str]`
- `as_of: datetime | None`

#### `Finding`
- `finding_id: str`
- `title: str`
- `detail: str`
- `evidence_ids: list[str]`
- `confidence: float | None`
- `sample_size: int | None`
- `limitations: list[str]`
- `as_of: datetime | None`

#### `Recommendation`
- `recommendation_id: str`
- `summary: str`
- `action: str`
- `supported_by_claim_ids: list[str]`
- `evidence_ids: list[str]`
- `confidence: float | None`
- `priority: high | medium | low`
- `limitations: list[str]`
- `as_of: datetime | None`

Rule:

- `evidence_ids` on recommendations should be derived from the claims they cite, not invented separately unless there is direct extra evidence

#### `ReviewResult`
- workflow metadata
- trade metadata
- `findings`
- `claims`
- `recommendations`
- `evidence_ids`
- `limitations`
- `verifier`

#### `SetupResearchResult`
- workflow metadata
- narrow setup-research input metadata
- `findings`
- `claims`
- `recommendations`
- `evidence_ids`
- `limitations`
- `verifier`

#### `VerifierResult`
- `passed: bool`
- `verified_at: datetime`
- `checked_claim_count: int`
- `checked_evidence_count: int`
- `downgraded_claim_ids: list[str]`
- `dropped_recommendation_ids: list[str]`
- `issues: list[VerifierIssue]`
- `summary: str`

## Stable Evidence ID Algorithm

Implement in `backend/src/trading_research/evidence_service.py`.

### Required algorithm

`evidence_id` must be derived from a normalized payload built from:

- `schema_version`
- `evidence_type`
- stable provenance fields
- stable source identity fields
- normalized content or normalized deterministic summary

### Required hash input rules

Include:

- `schema_version`
- `evidence_type`
- stable `source_ref`
- normalized provenance payload
- normalized evidence content or deterministic summary

Do not include:

- runtime-generated timestamps
- persistence time
- random UUIDs
- verifier time

`as_of` rule:

- `as_of` is metadata by default
- it should not be part of the hash unless it is semantically required to distinguish two otherwise identical evidence records

### Practical normalization rule

Normalize payload before hashing by:

- sorting dictionary keys
- trimming surrounding whitespace
- collapsing repeated whitespace in content fields
- using JSON with stable key ordering

### Hash output

- use SHA-1 or SHA-256 truncated to a practical length
- prefix with `ev_`

Example shape:

```text
ev_<hash>
```

## Minimal Deterministic Setup Research Contract

Do not implement open-ended generic research for P0.

### P0 input contract

One narrow setup template only:

- `symbol: str`
- `setup_type: str`
- `trade_date: date | None`

Allowed `setup_type` for P0:

- one fixed template, for example `intraday_breakout`

That means the service is not “research anything.”
It is “research this symbol for this one supported setup template.”

### P0-safe deterministic behavior

The setup research service should:

1. build a fixed query set from the input template
2. gather raw evidence from deterministic helpers / current research service
3. produce structured findings and claims about that one setup template only
4. attach limitations if evidence is thin
5. run verifier
6. render report only after verifier

### What it must NOT do

- no arbitrary open-ended topic research API
- no broad autonomous hypothesis expansion
- no unsupported setup taxonomy
- no fake quant scoring beyond what deterministic inputs support

## Implementation Phases

### Phase 1: Services and contracts first

Add the package `backend/src/trading_research/` with these target files:

- `models.py`
- `evidence_service.py`
- `verifier_service.py`
- `trade_review_service.py`
- `setup_research_service.py`
- `report_service.py`
- `store.py`
- `tools.py`
- `cli.py`

Do this before any LangGraph wrapper work.

### Phase 2: Schemas

Implement the structured models exactly enough to support the two P0 workflows.

### Phase 3: Verifier

Implement deterministic checks for:

- claim -> evidence linkage
- recommendation -> verified-claim linkage
- downgrade/drop behavior

### Phase 4: Trade review service

Wrap `backend/src/community/finance/decision_review_service.py`.

Requirements:

- preserve existing finance analysis logic
- translate finance outputs into `ReviewResult`
- register evidence through `evidence_service`
- derive recommendations from claims, not directly from prose
- run verifier before rendering

### Phase 5: Setup research service

Implement one narrow setup template path.

Requirements:

- fixed deterministic input contract
- fixed deterministic query builder
- structured `SetupResearchResult`
- evidence registration
- verifier run
- no open-ended generic research surface

### Phase 6: Report pipeline

`report_service.py` renders Markdown only from structured results.

Required output sections:

- Findings
- Claims
- Recommendations
- Evidence References
- Verifier Summary
- Limitations

Recommendations section must show support linkage to verified claims.

### Phase 7: CLI and tool entrypoints

Add minimal callable entrypoints only after the structured core works.

CLI preferred:

- `trade-review`
- `setup-research`

Tool wrappers may be added in the same phase, but they are not allowed to bypass the structured core.

### Phase 8: Golden end-to-end tests

Add at least two golden E2E-style tests.

Required tests:

1. trade review golden flow
2. setup research golden flow

Each must cover:

- input
- structured result creation
- evidence registration
- verifier pass
- markdown rendering

These are the minimum proof that the P0 pipeline is real.

### Phase 9: Graph wrappers last

Only after the core path passes tests:

- add `trade_review_agent` wrapper
- add `setup_research_agent` wrapper
- register them in `backend/langgraph.json`

If core services are working but graph wrappers are delayed, P0 core is still valid.

## File-by-File Change Plan

### `backend/src/trading_research/models.py`
- add all structured schemas
- include `Recommendation.supported_by_claim_ids`

### `backend/src/trading_research/evidence_service.py`
- stable evidence ID generation
- evidence-only persistence
- evidence lookup helpers
- no result persistence

### `backend/src/trading_research/store.py`
- persist final structured results only
- list/load saved results only
- no evidence ID generation

### `backend/src/trading_research/verifier_service.py`
- claim/evidence checks
- recommendation/claim checks
- downgrade/drop logic

### `backend/src/trading_research/trade_review_service.py`
- adapt finance `TradeReview` into `ReviewResult`
- derive claims from deterministic finance outputs
- derive recommendations from verified claims

### `backend/src/trading_research/setup_research_service.py`
- implement one narrow setup template path
- build fixed deterministic query set
- convert gathered evidence into structured outputs

### `backend/src/trading_research/report_service.py`
- render Markdown from structured results only
- show recommendation support linkage

### `backend/src/trading_research/tools.py`
- thin wrappers only
- must call structured services

### `backend/src/trading_research/cli.py`
- direct CLI entrypoints for both workflows

### `backend/tests/test_trading_research/`
- schema tests
- evidence service tests
- verifier tests
- report tests
- trade review service tests
- setup research service tests
- two golden E2E tests

### Graph/runtime files to touch only after core passes
- `backend/src/agents/trading_research_agents.py`
- `backend/langgraph.json`
- `config.yaml`
- `config.example.yaml`

## Dependencies and Order

1. `models.py`
2. `evidence_service.py`
3. `store.py`
4. `verifier_service.py`
5. `trade_review_service.py`
6. `setup_research_service.py`
7. `report_service.py`
8. `cli.py` + `tools.py`
9. golden tests
10. graph wrappers + config wiring
11. completion report

## Risks

### Risk 1: Existing finance outputs are not naturally evidence-shaped
- Mitigation: create deterministic evidence records from trade snapshot, module findings, metrics, and review summaries without changing finance internals.

### Risk 2: Setup research scope could drift back into generic web research
- Mitigation: lock the input contract to one setup template and reject unsupported setup types.

### Risk 3: Recommendations could become prose blobs again
- Mitigation: enforce `supported_by_claim_ids` in schema and verifier.

### Risk 4: Persistence responsibilities could overlap
- Mitigation: enforce a hard split between evidence storage and result storage.

## Non-Goals

- no generic multi-agent platform redesign
- no broad research marketplace
- no UI redesign
- no market regime / catalyst split in this pass
- no semantic fact-checking theater
- no unrelated cleanup

## Definition of Done

P0 is done only when all of these are true:

1. trade review produces a structured result object before Markdown
2. setup research produces a structured result object before Markdown
3. evidence records have stable deterministic IDs
4. evidence persistence and result persistence are separated cleanly
5. claims are verifier-checked against persisted evidence
6. recommendations reference verified claims through `supported_by_claim_ids`
7. final Markdown separates findings, claims, recommendations, evidence references, verifier summary, and limitations
8. CLI entrypoints work without LangGraph wrappers
9. two golden end-to-end tests pass
10. graph wrapper work, if added, is only thin orchestration on top of an already working core
