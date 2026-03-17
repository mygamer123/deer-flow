# DeerFlow Integration Blockers

Generated: 2026-03-14

Two blockers prevent full end-to-end integration today. Neither involves broken logic.

---

## Blocker 1 — Stale LangGraph Server (Operational)

**Severity:** Blocks runtime access to `trade_review_agent` and `setup_research_agent`

**What happens:** Requesting `trade_review_agent` via the LangGraph API returns:
```json
{"detail":"Graph 'trade_review_agent' not found. Expected one of: ['lead_agent']"}
```

**Root cause:** The running LangGraph server (PID 27942) was started on Thu Mar 12 midnight with `--no-reload`. `langgraph.json` was modified on Mar 13 22:07 (adding `trade_review_agent` and `setup_research_agent`). The server loaded the pre-modification version of `langgraph.json` and never reloaded it.

**Proof:**
```
ps aux | grep langgraph
-> uv run langgraph dev --no-browser --allow-blocking --no-reload   [Thu12AM]

GET /info -> version 0.7.65, knows only: ['lead_agent']
```

**Fix:** Restart the server.
```bash
make stop && make dev
```

After restart, `trade_review_agent` and `setup_research_agent` will be accessible.

**Files to change:** None. `langgraph.json` already contains the correct registrations.

---

## Blocker 2 — Three P3 Tools Missing from Config (Code Gap)

**Severity:** Three tools permanently invisible to all DeerFlow agents

**What is missing:**

| Tool name | Defined in | Missing from |
|-----------|-----------|--------------|
| `run_aggregate_trade_review` | `src/trading_research/tools.py` line 75 | `config.yaml`, `config.example.yaml` |
| `run_trade_diagnostic` | `src/trading_research/tools.py` line 116 | `config.yaml`, `config.example.yaml` |
| `run_strategy_improvement_loop` | `src/trading_research/tools.py` line 170 | `config.yaml`, `config.example.yaml` |

**Root cause:** These tools were implemented as part of P3 (aggregate review, single-trade diagnostics, strategy improvement loop) but were never added to the config files that the `get_available_tools()` loader reads from.

**Impact:** Even after server restart, `trade_review_agent` and `lead_agent` will not have access to these tools. The strategy improvement loop and trade diagnostic flows are only accessible via the CLI (`python -m src.trading_research diagnose-trade ...`).

**Fix:** Add the following three entries to both `config.yaml` and `config.example.yaml`, in the `tools:` section, alongside the existing `run_trade_review` and `run_setup_research` entries:

```yaml
  - name: run_aggregate_trade_review
    group: trading-research
    use: src.trading_research.tools:run_aggregate_trade_review_tool

  - name: run_trade_diagnostic
    group: trading-research
    use: src.trading_research.tools:run_trade_diagnostic_tool

  - name: run_strategy_improvement_loop
    group: trading-research
    use: src.trading_research.tools:run_strategy_improvement_loop_tool
```

**Verification:** After adding, confirm:
```bash
cd backend && uv run python -c "
from src.tools import get_available_tools
tools = get_available_tools(groups=['trading-research'], model_name=None, subagent_enabled=False)
names = [t.name for t in tools if t.name.startswith('run_')]
print(names)
# Expected: ['run_trade_review', 'run_setup_research', 'run_aggregate_trade_review', 'run_trade_diagnostic', 'run_strategy_improvement_loop']
"
```
