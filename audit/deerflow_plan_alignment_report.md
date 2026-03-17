# DeerFlow Plan Alignment Audit

## 1. Executive Summary

- Blunt assessment: this repo is still primarily a general-purpose DeerFlow super-agent harness with a meaningful but narrow finance trade-review package added on top.
- Overall alignment estimate: about 30% of the target plan is real, implemented, wired, and callable today.
- Major strengths:
  - A real Lead Agent runtime exists and is wired through LangGraph (`backend/langgraph.json:7`, `backend/src/agents/lead_agent/agent.py:255`).
  - There is actual Python truth-engine-style work in the finance package: market data access, trade-log parsing, review orchestration, structured review objects, report building, persistence, and signal-source comparison (`backend/src/community/finance/market_data_service.py:259`, `backend/src/community/finance/decision_review_service.py:30`, `backend/src/community/finance/models.py:375`, `backend/src/community/finance/report_builder.py:12`, `backend/src/community/finance/review_store.py:79`, `backend/src/community/finance/signal_compare.py:69`).
  - Test coverage is real for the finance package and for the underlying DeerFlow platform (`backend/tests/test_finance/`, `backend/tests/test_client.py:1`, `backend/tests/test_client_live.py:1`).
- Major missing pieces:
  - No dedicated research agent stack beyond one Lead Agent.
  - No evidence service, no claim schema, no evidence schema, no verifier layer, and no evidence-linked reporting.
  - No separate setup-research pipeline or service.
  - No dedicated trading research CLI trigger.
- Biggest architectural risks:
  - DeerFlow is still being used as a broad super-agent shell instead of a narrow research orchestrator.
  - Finance verdicts are generated without a traceable claim/evidence contract.
  - Prompt and doc intent is ahead of implementation in several places.
  - Scope is drifting outward into channels, custom agents, and generic platform features instead of tightening around v0.1 research OS goals.

## 2. Current State Snapshot

### Orchestration

- One LangGraph graph is registered: `lead_agent` only (`backend/langgraph.json:7`).
- The lead agent is a generic super-agent with middleware, tools, and optional subagent delegation (`backend/src/agents/lead_agent/agent.py:255`, `backend/src/agents/lead_agent/prompt.py:150`).
- Subagents exist, but only as generic helpers: `general-purpose` and `bash` (`backend/src/subagents/builtins/__init__.py:11`).
- There is no dedicated workflow layer or domain-specific orchestration graph for market regime, catalyst, setup research, trade review, or verification.

### Agents

- Implemented: Lead Agent (`backend/src/agents/lead_agent/agent.py:255`).
- Implemented only as generic helper subagents: `general-purpose`, `bash` (`backend/src/subagents/builtins/__init__.py:12`).
- Not implemented as real agents: Market Regime Agent, Catalyst/News Agent, Setup Research Agent, Trade Review Agent, Verifier Agent.
- There is a CRUD API for custom agents, but that is platform scaffolding, not the target research architecture (`backend/src/gateway/routers/agents.py:1`).

### Tools / Services

- Generic DeerFlow tool surface is broad and open-ended: sandbox tools, built-ins, community tools, MCP tools (`backend/src/tools/tools.py:22`).
- Finance package contains the only clear domain-specific truth-engine-style modules:
  - `market_data_service.py`
  - `decision_review_service.py`
  - `selection_review.py`, `entry_review.py`, `exit_review.py`, `failure_review.py`
  - `trade_log_parser.py`
  - `signal_compare.py`
  - `report_builder.py`
  - `review_store.py`
- There is no dedicated `feature_service`, `setup_research_service`, `evidence_service`, or `report_service` boundary as described in the target plan.

### Memory / Context

- DeerFlow has a generic long-term memory system, including memory extraction, injection, caching, and async queueing (`backend/src/agents/memory/updater.py:19`, `backend/src/agents/memory/prompt.py:14`, `backend/src/agents/middlewares/memory_middleware.py:86`).
- Thread-scoped workspace/uploads/outputs state is implemented in `ThreadState` (`backend/src/agents/thread_state.py:48`).
- This memory system is generic user-context memory, not evidence memory for research claims.

### Evidence / Reporting

- Trade review outputs are structured as Python dataclasses (`backend/src/community/finance/models.py:375`).
- Reports are generated as Markdown strings only (`backend/src/community/finance/report_builder.py:12`).
- Review persistence exists as JSON files in `~/.deer-flow/finance/reviews` (`backend/src/community/finance/review_store.py:79`).
- Hypotheses can collect `evidence_for` and `evidence_against`, but these are plain strings, not normalized evidence records with IDs (`backend/src/community/finance/models.py:317`, `backend/src/community/finance/hypothesis.py:24`).
- No claim schema, no evidence schema, no evidence IDs, no evidence-linking in reports.

### Verifier / Guardrails

- Generic clarification guardrails exist in the lead-agent prompt (`backend/src/agents/lead_agent/prompt.py:167`).
- Finance modules use rule-based synthesis and confidence scores (`backend/src/community/finance/selection_review.py:196`, `backend/src/community/finance/entry_review.py:179`, `backend/src/community/finance/exit_review.py:184`, `backend/src/community/finance/failure_review.py:176`).
- Data-gap objects exist but are not meaningfully enforced as a report gate (`backend/src/community/finance/models.py:267`, `backend/src/community/finance/hypothesis.py:64`).
- No verifier agent, no verifier service, no hard "no evidence -> no conclusion" enforcement.

### CLI / UI Entry Points

- App start/stop is handled by `Makefile` and `scripts/start.sh` (`Makefile:153`, `scripts/start.sh:77`).
- There is a generic embedded Python client, `DeerFlowClient`, for programmatic calls (`backend/src/client.py:65`).
- There is a debug REPL-style script for the lead agent (`backend/debug.py:36`).
- Frontend is a generic DeerFlow chat/workspace UI, not a trading research UI (`frontend/package.json:6`, `frontend/src/` directory structure).
- No dedicated CLI command exists for trade review, setup research, evidence report generation, or verifier execution.

### Tests

- The repo has substantial backend unit coverage and some live integration coverage (`backend/tests/`).
- Finance package tests are real and fairly broad: parser, models, review modules, report builder, market data, persistence, and signal compare (`backend/tests/test_finance/`).
- There is at least one frontend test, but frontend coverage is minimal (`frontend/src/core/api/stream-mode.test.ts:1`).
- There is no trading research OS end-to-end test layer and no verifier-specific test layer.

### Docs

- Docs are extensive for generic DeerFlow backend/platform concerns (`backend/docs/ARCHITECTURE.md:1`, `backend/docs/API.md:1`, `backend/docs/CONFIGURATION.md:1`).
- There is one stock-research evaluation note framing DeerFlow as a research layer (`docs/deerflow-stock-research-evaluation.md:1`).
- There is no concrete PRD, service contract set, or architecture doc for the target trading research OS.
- Some docs are stale or overclaim relative to code.

### Config System

- Generic config is one of the strongest parts of the codebase: models, tools, sandbox, skills, memory, channels, subagents, title, summarization (`config.yaml`, `backend/src/config/app_config.py:23`).
- Finance now has named log-source config under `finance.log_sources` (`config.yaml:137`).
- There is still no dedicated config layer for research policies, evidence rules, or risk rules.

## 3. Plan Alignment Matrix

| Capability | Status | Evidence | Why it does or does not meet the target |
|---|---|---|---|
| Lead Agent | FULLY PRESENT | `backend/langgraph.json:7`, `backend/src/agents/lead_agent/agent.py:255` | A real lead agent exists, is wired into LangGraph, and is callable. |
| Market Regime Agent | MISSING | `backend/src/agents/` only contains `lead_agent/`; no matches for `market_regime` in `backend/src` | No dedicated market-regime agent, graph, or service exists. |
| Catalyst / News Agent | MISSING | `backend/src/community/finance/themes/intraday.py:29` has a `news_sentiment` lens, but there is no agent module or service boundary | News exists only as one analytic input, not as a dedicated catalyst/news agent. |
| Setup Research Agent | MISSING | No `setup_research` files or service names in `backend/src`; no matching graph in `backend/langgraph.json` | The codebase has no implemented setup-research agent path. |
| Trade Review Agent | PRESENT BUT MISALIGNED | `backend/src/community/finance/tools.py:44`, `backend/src/community/finance/decision_review_service.py:30`, `backend/langgraph.json:7` | Trade review functionality exists, but only as finance tools/services under the generic lead agent, not as a distinct agent layer. |
| Verifier Agent | MISSING | No `verifier` module, agent, graph, or router matches in `backend/src` | No verifier implementation exists. |
| `market_data_service` | FULLY PRESENT | `backend/src/community/finance/market_data_service.py:259` | A real service-like module exists with Polygon and DuckDB data access. |
| `feature_service` | PRESENT BUT MISALIGNED | Feature computation is spread across `selection_review.py`, `entry_review.py`, `exit_review.py`, `failure_review.py` | Feature logic exists, but not behind a dedicated service boundary. |
| `setup_research_service` | MISSING | No matching module/service name under `backend/src` | Setup research service does not exist. |
| `trade_review_service` | PRESENT BUT MISALIGNED | `backend/src/community/finance/decision_review_service.py:30` | There is real trade-review orchestration logic, but it is named differently and sits in `community/finance` rather than a clearer service layer. |
| `evidence_service` | MISSING | No matching module/service name; no evidence IDs in code search | There is no normalized evidence service. |
| `report_service` | PRESENT BUT MISALIGNED | `backend/src/community/finance/report_builder.py:12`, `backend/src/community/finance/review_store.py:79` | Report generation and persistence exist, but as builder/store helpers, not as an evidence-aware report service. |
| Claim schema | MISSING | No `Claim` model or equivalent in `backend/src/community/finance/models.py` | Important claims are not represented as first-class structured objects. |
| Evidence schema | MISSING | `backend/src/community/finance/models.py:317` only has string lists `evidence_for` / `evidence_against` | Evidence is unstructured text, not typed evidence objects with IDs. |
| Review output schema | FULLY PRESENT | `backend/src/community/finance/models.py:331`, `backend/src/community/finance/models.py:375` | Structured verdict and review dataclasses exist for trade-review output. |
| CLI trigger | PARTIALLY PRESENT | `Makefile:153`, `scripts/start.sh:77`, `backend/src/client.py:65`, `backend/debug.py:36` | Generic startup and Python/debug entrypoints exist, but no dedicated trading research CLI entrypoint exists. |
| Evidence-backed report output | PRESENT BUT MISALIGNED | `backend/src/community/finance/report_builder.py:12`, `backend/src/community/finance/review_store.py:79` | Reports and persisted JSON exist, but they are not evidence-linked and do not carry `evidence_ids`. |
| Anti-future-leakage safeguards | PARTIALLY PRESENT | `backend/src/community/finance/selection_review.py:79`, `backend/src/community/finance/entry_review.py:219`, `backend/src/community/finance/market_data_service.py:371` | Some functions use entry-time or date-bounded slices, but there is no explicit leakage-control layer or dedicated tests enforcing causal-only research logic. |
| Configs | PARTIALLY PRESENT | `config.yaml:125`, `config.yaml:137`, `backend/src/config/app_config.py:23` | Generic config is strong, and finance log-source config exists, but there is no research/risk/evidence rule config layer. |
| Tests | PARTIALLY PRESENT | `backend/tests/`, `backend/tests/test_finance/`, `backend/tests/test_client_live.py:1`, `frontend/src/core/api/stream-mode.test.ts:1` | Unit tests are substantial, but there is no targeted research-OS e2e flow or verifier-oriented test suite. |
| Docs | PARTIALLY PRESENT | `README.md:316`, `backend/docs/ARCHITECTURE.md:1`, `docs/deerflow-stock-research-evaluation.md:1` | Docs are extensive but mostly generic DeerFlow docs; the target trading research OS lacks its own architecture/PRD/tool-contract documentation. |

## 4. File-Level Evidence

- `README.md` - Root product framing. It describes DeerFlow as a general-purpose super-agent harness rather than a dedicated research OS.
- `docs/deerflow-stock-research-evaluation.md` - High-level stock-research suitability note. It correctly argues for DeerFlow as a research layer, but this is design intent, not implementation.
- `config.yaml` - Active config. Shows generic tool/model groups plus the finance log-source additions and finance tool entries.
- `backend/langgraph.json` - Definitive runtime graph registration. Only `lead_agent` is registered.
- `backend/src/agents/lead_agent/agent.py` - Core orchestration entrypoint, middleware chain, and model/tool assembly.
- `backend/src/agents/lead_agent/prompt.py` - Generic super-agent prompt. Strong evidence that the current orchestration layer is still broad-purpose, not research-specific.
- `backend/src/subagents/builtins/__init__.py` - Only `general-purpose` and `bash` subagents are implemented.
- `backend/src/tools/tools.py` - Tool assembly. Shows a wide, generic tool surface instead of a narrow research-specific boundary.
- `backend/src/client.py` - Embedded Python client. Real callable runtime entrypoint, but generic rather than trading-specific.
- `backend/debug.py` - Interactive debug REPL for the lead agent. Useful for development, but not a productized research CLI.
- `backend/src/community/finance/market_data_service.py` - Real market-data access layer using Polygon and DuckDB.
- `backend/src/community/finance/trade_log_parser.py` - Production log parser for trade review and signal comparison.
- `backend/src/community/finance/decision_review_service.py` - Trade-review orchestration service. The strongest domain-specific service currently present.
- `backend/src/community/finance/selection_review.py` - Selection heuristics and synthesis.
- `backend/src/community/finance/entry_review.py` - Entry heuristics and simulations.
- `backend/src/community/finance/exit_review.py` - Exit heuristics and simulations.
- `backend/src/community/finance/failure_review.py` - Failure/stranded-position heuristics.
- `backend/src/community/finance/models.py` - Structured review dataclasses; useful output schema exists here.
- `backend/src/community/finance/hypothesis.py` - Hypothesis tracker with weak, string-based evidence lists.
- `backend/src/community/finance/report_builder.py` - Markdown report generation only.
- `backend/src/community/finance/review_store.py` - JSON persistence for reviews.
- `backend/src/community/finance/signal_compare.py` - New prod/dev comparison flow with heuristic suggestions.
- `backend/src/community/finance/themes/intraday.py` - Trade-review theme registry and lens ordering.
- `backend/src/gateway/app.py` - Generic DeerFlow API gateway, not a trading-research API surface.
- `backend/src/gateway/routers/agents.py` - Generic custom-agent scaffolding.
- `backend/src/channels/service.py` and `backend/src/gateway/routers/channels.py` - Broad chat integrations beyond target v0.1 scope.
- `backend/src/agents/memory/*` and `backend/src/agents/middlewares/memory_middleware.py` - Generic memory/context system.
- `backend/tests/test_finance/*` - Real unit coverage for the finance package.
- `backend/tests/test_client_live.py` - Live client integration beginnings, but generic and not research-OS specific.
- `backend/docs/ARCHITECTURE.md`, `backend/docs/API.md`, `backend/docs/CONFIGURATION.md`, `backend/docs/TODO.md` - Solid generic platform docs, but not target-plan docs.
- `frontend/package.json` and `frontend/src/` - Generic Next.js chat workspace, not a dedicated research workstation UI.

## 5. Gap Analysis

### P0 = Blocks Target Architecture

#### P0.1 No dedicated research-agent topology
- Why it matters: the target architecture depends on explicit role separation across Lead, Market Regime, Catalyst/News, Setup Research, Trade Review, and Verifier agents.
- Concrete evidence: `backend/langgraph.json:7` registers only `lead_agent`; `backend/src/agents/` contains only `lead_agent/`; built-in subagents are only `general-purpose` and `bash` (`backend/src/subagents/builtins/__init__.py:11`).
- Recommended fix direction: define real domain agents/workflows with clear contracts and routing, even if v0.1 only wires Lead + Trade Review + Verifier first.
- Estimated effort: L

#### P0.2 No claim/evidence model or evidence service
- Why it matters: the target plan explicitly requires evidence-backed outputs, evidence IDs, and traceable claims.
- Concrete evidence: `backend/src/community/finance/models.py` defines `TradeReview`, `DayReview`, and `Hypothesis`, but no `Claim`, `Evidence`, or `evidence_id`; `backend/src/community/finance/report_builder.py:12` emits plain Markdown; `backend/src/community/finance/review_store.py:79` persists review JSON but not normalized evidence graphs.
- Recommended fix direction: create first-class `EvidenceItem`, `Claim`, `Finding`, and `Recommendation` schemas plus an `evidence_service` that assigns IDs and records provenance.
- Estimated effort: L

#### P0.3 No verifier layer
- Why it matters: the target plan requires a basic verifier in v0.1 and explicit anti-hallucination boundaries.
- Concrete evidence: no verifier module/agent/service exists under `backend/src`; no verifier graph exists in `backend/langgraph.json`; the lead-agent prompt contains clarification/citation guidance but no verification gate (`backend/src/agents/lead_agent/prompt.py:259`).
- Recommended fix direction: add a verifier service/agent that checks generated claims against collected evidence before final report emission.
- Estimated effort: M-L

#### P0.4 No setup-research implementation
- Why it matters: v0.1 scope includes a single research task, not just trade review.
- Concrete evidence: there is no `setup_research_service`, no setup-research agent, and no setup-research schema in `backend/src`; the only meaningful domain package is `backend/src/community/finance/`.
- Recommended fix direction: define a minimal setup-research path that takes one setup/ticker/task input, gathers evidence, and emits a structured report.
- Estimated effort: L

#### P0.5 Reports are not evidence-backed and do not separate findings from recommendations cleanly
- Why it matters: the target requires evidence-linked claims and explicit separation between findings and recommendations.
- Concrete evidence: `backend/src/community/finance/report_builder.py:80`-`143` mixes verdicts, recommendations, simulations, and reasons into one narrative block with no evidence IDs or section-level claim contract.
- Recommended fix direction: introduce an intermediate structured output with separate `findings[]`, `claims[]`, `recommendations[]`, and `evidence_ids[]`, then render Markdown/JSON from that object.
- Estimated effort: M-L

### P1 = Important but Not Blocking

#### P1.1 Trade-review truth engine exists but is mis-layered
- Why it matters: the target architecture wants clean truth-engine services; current finance logic is real but still looks like an add-on package inside DeerFlow community tools.
- Concrete evidence: `backend/src/community/finance/decision_review_service.py:30`, `backend/src/community/finance/market_data_service.py:259`, `backend/src/community/finance/report_builder.py:12`, `backend/src/community/finance/review_store.py:79`.
- Recommended fix direction: promote the finance package into a clearer service layer with stable interfaces and narrow orchestration touchpoints.
- Estimated effort: M

#### P1.2 Feature computation exists, but there is no `feature_service`
- Why it matters: target service boundaries expect reusable feature computation instead of logic scattered across review modules.
- Concrete evidence: feature logic is embedded in `selection_review.py`, `entry_review.py`, `exit_review.py`, and `failure_review.py`, with dispatch handled directly by `IterativeAnalyzer` (`backend/src/community/finance/iterative_analyzer.py:27`).
- Recommended fix direction: pull shared computations and feature extraction into a dedicated service that feeds both research and review flows.
- Estimated effort: M

#### P1.3 Prompt/doc intent overstates what is wired
- Why it matters: the audit should count only wired functionality.
- Concrete evidence:
  - `backend/src/community/finance/themes/intraday.py:31` says `final_synthesis` is where an LLM combines evidence.
  - `backend/src/community/finance/iterative_analyzer.py:72`-`74` explicitly skips `final_synthesis`.
  - `backend/src/community/finance/decision_review_service.py:99`-`107` calls rule-based synthesis functions directly.
  - `backend/docs/ARCHITECTURE.md:56` describes robust multi-agent orchestration, but runtime still registers one graph.
- Recommended fix direction: either implement the missing synthesis/verifier wiring or strip docs/prompt claims back to what the system really does.
- Estimated effort: S-M

#### P1.4 Anti-future-leakage controls are only implicit
- Why it matters: the target requires explicit leakage prevention for research/backtests.
- Concrete evidence:
  - Some causal slicing is present: `_find_bar_at` in `selection_review.py:255`, `_compute_vwap_at` in `entry_review.py:219`, and date-bounded news in `market_data_service.py:371`.
  - But there is no dedicated leakage guardrail module, no policy object, and no explicit leakage tests under `backend/tests/test_finance`.
- Recommended fix direction: add a research-guardrail layer and tests that distinguish review-time post-trade analysis from pre-trade research features.
- Estimated effort: M

#### P1.5 No low-sample-size downgrade logic
- Why it matters: the target explicitly says low sample size must be treated as observation, not rule.
- Concrete evidence: no sample-size policy exists in finance services or schemas; verdict synthesis in `selection_review.py:196`, `exit_review.py:184`, and `failure_review.py:176` does not gate conclusions on sample size.
- Recommended fix direction: introduce sample-size metadata and downgrade thresholds in claim generation and verifier logic.
- Estimated effort: M

#### P1.6 Tool boundaries are too loose for a research OS
- Why it matters: the target wants DeerFlow to orchestrate deterministic services, not to operate as an unrestricted general shell.
- Concrete evidence: `backend/src/tools/tools.py:22` returns configured tools + built-ins + MCP; `backend/src/agents/lead_agent/prompt.py:150` defines the role as an open-source super agent; root README frames the product as a general harness (`README.md:316`).
- Recommended fix direction: create narrower tool groups per domain agent and make the research workflow prefer service calls over ad hoc generic tool use.
- Estimated effort: M

#### P1.7 v0.1 scope is diluted by non-essential platform breadth
- Why it matters: the target intentionally excludes broad chat integrations and other platform concerns from v0.1 priority.
- Concrete evidence: channels are implemented for Telegram, Slack, and Feishu (`backend/src/channels/service.py:15`); channels are exposed via gateway (`backend/src/gateway/routers/channels.py:12`); root README has a large IM channels section (`README.md:207`).
- Recommended fix direction: keep these features, but stop treating them as core to the research OS milestone; isolate or de-emphasize them in planning and docs.
- Estimated effort: S-M

#### P1.8 No dedicated trading research CLI
- Why it matters: target v0.1 includes a CLI trigger.
- Concrete evidence: the repo has startup scripts (`Makefile:153`, `scripts/start.sh:77`), a generic embedded client (`backend/src/client.py:65`), and a debug REPL (`backend/debug.py:36`), but no purpose-built CLI for trade review or setup research.
- Recommended fix direction: add a Typer/argparse command that calls the truth-engine services directly.
- Estimated effort: S

### P2 = Polish / Structure / Naming / Cleanup

#### P2.1 Directory layout does not reflect the target architecture
- Why it matters: the target plan expects obvious layers like `agents/`, `services/`, `schemas/`, `configs/`, `artifacts/`, and potentially `apps/`.
- Concrete evidence: root contains `backend/`, `frontend/`, `skills/`, and generic DeerFlow folders; there is no `services/` directory, no `apps/` directory, and no `schemas/` package outside ad hoc dataclasses (`/Users/mathiswan/Documents/github/deer-flow` root listing, `backend/src/` listing).
- Recommended fix direction: reorganize the trading-research implementation into explicit architecture-aligned packages or, at minimum, create a well-named subpackage for the research OS.
- Estimated effort: M-L

#### P2.2 Output layer lacks HTML, charts, and artifact generation
- Why it matters: the target output layer expects report/artifact flexibility.
- Concrete evidence: finance output code is limited to Markdown report strings and JSON persistence (`backend/src/community/finance/report_builder.py:12`, `backend/src/community/finance/review_store.py:79`); no chart or HTML generation files were found in the finance package.
- Recommended fix direction: add a report service that can emit JSON first, then Markdown/HTML, and optionally write chart artifacts.
- Estimated effort: M

#### P2.3 Documentation is broad but not target-specific
- Why it matters: the target expects architecture docs, PRD, and tool contracts for the research OS.
- Concrete evidence: root docs contain only `deerflow-stock-research-evaluation.md` plus generic change notes; backend docs are generic DeerFlow docs; no research-OS PRD or service contract docs were found.
- Recommended fix direction: write one concise target-architecture doc, one PRD, and one tool/service contract doc for the trading research stack.
- Estimated effort: S-M

#### P2.4 Some docs are stale relative to implementation
- Why it matters: stale docs lower auditability and make architecture claims less trustworthy.
- Concrete evidence: `backend/docs/ARCHITECTURE.md:69`-`75` shows an outdated `agent` config snippet instead of the current `graphs` config; `README.md:252`-`264` still references `mobile_agent` and `vip_agent` even though only `lead_agent` is registered in `backend/langgraph.json:7`.
- Recommended fix direction: treat docs as versioned contracts and update them alongside runtime changes.
- Estimated effort: S

## 6. Architectural Misalignments

### 6.1 DeerFlow is still acting like a broad super-agent shell

The project goal says DeerFlow should be the orchestration harness on top of Python truth services. In practice, the current lead agent is still configured as a generic super agent with broad tools, generic skills, open-ended subagent delegation, memory, channels, and file sandboxing.

- Evidence: `backend/src/agents/lead_agent/prompt.py:150`, `backend/src/tools/tools.py:22`, `README.md:316`.
- Why this matters: it weakens the anti-hallucination boundary and makes the system harder to reason about as a research OS.

### 6.2 The only real domain implementation is trade review, not a research OS

The finance package is real and non-trivial, but it is a trade-review subsystem, not the full architecture in the target plan.

- Evidence: `backend/src/community/finance/` contains trade-review parsing, scoring, and reporting; there is no corresponding setup-research subsystem.
- Why this matters: current progress should not be mistaken for full target-architecture progress.

### 6.3 Business logic is partly in Python services, but orchestration boundaries are still unclear

This is the most positive sign in the repo: the finance package does place meaningful logic in Python instead of prompts. But those services are not exposed or organized as explicit truth-engine boundaries yet.

- Evidence: `market_data_service.py`, `decision_review_service.py`, `report_builder.py`, `review_store.py`.
- Why this matters: the repo is moving in the right direction at the module level, but not yet at the system-architecture level.

### 6.4 The repo hints at evidence-based synthesis, but the evidence contract is not real

Terms like "evidence" and "final_synthesis" exist, but the implementation stops at string lists and heuristic reasons.

- Evidence: `backend/src/community/finance/models.py:317`, `backend/src/community/finance/themes/intraday.py:31`, `backend/src/community/finance/iterative_analyzer.py:72`, `backend/src/community/finance/decision_review_service.py:99`.
- Why this matters: this is exactly the kind of prompt/docs-only progress the audit should discount.

### 6.5 Findings and recommendations are still collapsed together

Trade-review output is one combined narrative instead of a structured pipeline from evidence -> findings -> claims -> recommendations.

- Evidence: `backend/src/community/finance/report_builder.py:63`-`145`.
- Why this matters: verifier wiring becomes much harder later if the intermediate objects are not explicit now.

### 6.6 Scope is broader than the target v0.1 requires

Channels, custom agent CRUD, generic skills marketplace docs, and broad platform features all exist in parallel with the partially built trading layer.

- Evidence: `backend/src/channels/service.py:15`, `backend/src/gateway/routers/agents.py:1`, `backend/docs/TODO.md:17`, `README.md:207`.
- Why this matters: the project risks optimizing DeerFlow-as-platform instead of landing DeerFlow-as-research-OS.

## 7. Top 10 Next Actions

1. Define core typed schemas for `EvidenceItem`, `Claim`, `Finding`, `Recommendation`, `ReviewResult`, and `VerifierResult`.
2. Build an `evidence_service` that records provenance from tool/service outputs and assigns stable `evidence_id`s.
3. Build a minimal `verifier_service` or `Verifier Agent` that refuses unsupported claims.
4. Promote the existing finance trade-review stack into a clearer truth-engine layer: keep `market_data_service`, rename/wrap `decision_review_service` as `trade_review_service`, and treat `report_builder`/`review_store` as implementation details.
5. Add a real `setup_research_service` with a narrow v0.1 contract: one research task in, evidence-backed structured output out.
6. Add a dedicated `Trade Review Agent` and `Setup Research Agent` that call those services instead of relying on the generic lead agent to improvise.
7. Narrow tool access per agent so the research stack prefers deterministic service calls over open-ended generic shell behavior.
8. Implement explicit anti-leakage and sample-size guardrails, with tests that prove causal-only research behavior and downgrade low-sample conclusions.
9. Add a dedicated CLI entrypoint for v0.1 flows such as `review-trade` and `research-setup`.
10. Write target-specific docs: architecture, PRD, service/tool contracts, and a minimal e2e test plan.

## 8. Honest Final Verdict

- Is this codebase already on the right path?
  - Partly. The finance package is moving in the right direction because it puts real logic in Python modules instead of prompts.

- Is it still mostly scaffold/demo?
  - Yes, relative to the target plan. The DeerFlow platform itself is real, but the trading research OS is still mostly unbuilt.

- What percentage of the target plan is real today?
  - Roughly 30%.

- What should be built next before anything else?
  - Before any more UI, prompts, or scope expansion, build the evidence/claim/verifier layer and formalize the service boundaries for trade review and setup research.
