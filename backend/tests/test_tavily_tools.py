from unittest.mock import MagicMock, patch

from tavily.errors import InvalidAPIKeyError, MissingAPIKeyError

from src.community.tavily import tools


class TestTavilyTools:
    @patch("src.community.tavily.tools._get_tavily_client")
    def test_web_search_tool_normalizes_results(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "content": "Snippet",
                }
            ]
        }
        mock_get_client.return_value = mock_client

        result = tools.web_search_tool.run("test query")

        assert '"title": "Example"' in result
        assert '"url": "https://example.com"' in result
        assert '"snippet": "Snippet"' in result
        mock_client.search.assert_called_once_with("test query", max_results=5)

    @patch("src.community.tavily.tools._get_tavily_client")
    def test_web_search_tool_returns_config_error_when_api_key_missing(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.side_effect = MissingAPIKeyError()
        mock_get_client.return_value = mock_client

        result = tools.web_search_tool.run("test query")

        assert result == "Error: Tavily web search is not configured. Set `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."

    @patch("src.community.tavily.tools._get_tavily_client")
    def test_web_fetch_tool_returns_config_error_when_api_key_invalid(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.extract.side_effect = InvalidAPIKeyError("Unauthorized: missing or invalid API key.")
        mock_get_client.return_value = mock_client

        result = tools.web_fetch_tool.run("https://example.com")

        assert result == "Error: Tavily API key is invalid. Update `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."
