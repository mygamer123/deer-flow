# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging

from langchain.tools import tool
from tavily.errors import InvalidAPIKeyError, MissingAPIKeyError

from src.community.tavily.tools import _format_tavily_error
from .report_builder import build_claim_report, build_research_report
from .research_service import ResearchService, TavilyAuthError
from .research_store import list_saved_reports, save_research_report

logger = logging.getLogger(__name__)


def _get_service() -> ResearchService:
    return ResearchService()


def _render_tavily_error(error: Exception) -> str:
    if isinstance(error, TavilyAuthError):
        return str(error)
    return _format_tavily_error(error)


@tool("research_topic", parse_docstring=True)
def research_topic_tool(topic: str, depth: int = 2) -> str:
    """Research a topic by searching the web, fetching top sources, and extracting claims.

    Args:
        topic: The topic or question to research (e.g. 'effects of intermittent fasting on longevity').
        depth: How many search rounds and pages to fetch (1-3). Higher = more thorough but slower.
    """
    try:
        svc = _get_service()
        report = svc.research_topic(topic, depth=min(max(depth, 1), 3))
        save_research_report(report)
        return build_research_report(report)
    except (TavilyAuthError, MissingAPIKeyError, InvalidAPIKeyError) as error:
        return _render_tavily_error(error)
    except Exception:
        logger.exception("Failed to research topic: %s", topic)
        return f"Error: Failed to research '{topic}'. Check that TAVILY_API_KEY is set."


@tool("verify_claim", parse_docstring=True)
def verify_claim_tool(statement: str) -> str:
    """Verify a factual claim by searching for supporting and contradicting evidence.

    Args:
        statement: The claim to verify (e.g. 'The Great Wall of China is visible from space').
    """
    try:
        svc = _get_service()
        claim = svc.verify_claim(statement)
        return build_claim_report(claim)
    except (TavilyAuthError, MissingAPIKeyError, InvalidAPIKeyError) as error:
        return _render_tavily_error(error)
    except Exception:
        logger.exception("Failed to verify claim: %s", statement)
        return f"Error: Failed to verify claim '{statement}'. Check that TAVILY_API_KEY is set."


@tool("list_research_reports", parse_docstring=True)
def list_research_reports_tool() -> str:
    """List all previously saved research reports."""
    reports = list_saved_reports()
    if not reports:
        return "No research reports saved yet."
    lines = ["# Saved Research Reports", ""]
    for name in reports:
        lines.append(f"- {name}")
    return "\n".join(lines)
