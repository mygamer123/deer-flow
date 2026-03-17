from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from tavily.errors import InvalidAPIKeyError, MissingAPIKeyError

from src.community.research.research_service import ResearchService
from src.community.research.tools import research_topic_tool, verify_claim_tool


def test_research_service_search_raises_config_error_when_api_key_missing() -> None:
    service = ResearchService.__new__(ResearchService)
    service._client = MagicMock()
    service._client.search.side_effect = MissingAPIKeyError()

    with pytest.raises(Exception, match="Tavily web search is not configured"):
        service._search("test topic")


def test_research_service_search_raises_config_error_when_api_key_invalid() -> None:
    service = ResearchService.__new__(ResearchService)
    service._client = MagicMock()
    service._client.search.side_effect = InvalidAPIKeyError("Unauthorized: missing or invalid API key.")

    with pytest.raises(Exception, match="Tavily API key is invalid"):
        service._search("test topic")


def test_research_topic_tool_surfaces_tavily_config_errors() -> None:
    service = MagicMock()
    service.research_topic.side_effect = MissingAPIKeyError()

    with patch("src.community.research.tools._get_service", return_value=service):
        result = research_topic_tool.run({"topic": "intraday breakouts"})

    assert result == "Error: Tavily web search is not configured. Set `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."


def test_verify_claim_tool_surfaces_tavily_config_errors() -> None:
    service = MagicMock()
    service.verify_claim.side_effect = InvalidAPIKeyError("Unauthorized: missing or invalid API key.")

    with patch("src.community.research.tools._get_service", return_value=service):
        result = verify_claim_tool.run({"statement": "The setup is statistically significant"})

    assert result == "Error: Tavily API key is invalid. Update `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."
