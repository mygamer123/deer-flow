from __future__ import annotations

from typing import Any, cast

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig

from src.agents.lead_agent.agent import _build_middlewares
from src.agents.lead_agent.prompt import apply_prompt_template
from src.agents.thread_state import ThreadState
from src.config.app_config import get_app_config
from src.models import create_chat_model
from src.tools import get_available_tools


_MARKET_DATA_RULE = """
**MARKET DATA RULE (overrides clarification_system for this agent):**
NEVER ask the user for prices, quotes, OHLCV bars, volume, technical indicators, or any market/price data.
All required market data is fetched automatically from Polygon API by the trade-review tools.
If Polygon returns partial data or the latest bar is delayed, use the most recent available bar as the current price.
Proceed with the available data rather than pausing to ask the user.
"""


def make_trade_review_agent(config: RunnableConfig):
    return _make_specialized_agent(
        config,
        role_instructions=(
            "You are the Trade Review Agent. Use the structured trade-review workflow tool for the task. Do not improvise broad research or generic coding work when the trade-review workflow can answer the request." + _MARKET_DATA_RULE
        ),
    )


def make_setup_research_agent(config: RunnableConfig):
    return _make_specialized_agent(
        config,
        role_instructions=("You are the Setup Research Agent. Use the structured setup-research workflow tool for the task. Keep outputs evidence-backed and narrow to the requested setup or research topic." + _MARKET_DATA_RULE),
    )


def _make_specialized_agent(config: RunnableConfig, *, role_instructions: str):
    cfg = config.get("configurable", {})
    app_config = get_app_config()
    if not app_config.models:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")

    model_name = cfg.get("model_name") or app_config.models[0].name
    thinking_enabled = cfg.get("thinking_enabled", False)
    system_prompt = apply_prompt_template(subagent_enabled=False) + "\n\n<specific_role>\n" + role_instructions + "\n</specific_role>"

    agent_factory = cast(Any, create_agent)
    return agent_factory(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
        tools=get_available_tools(groups=["trading-research"], model_name=model_name, subagent_enabled=False),
        middleware=_build_middlewares(config, model_name=model_name),
        system_prompt=system_prompt,
        state_schema=ThreadState,
    )
