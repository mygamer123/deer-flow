import json

from langchain.tools import tool
from tavily import TavilyClient
from tavily.errors import BadRequestError, ForbiddenError, InvalidAPIKeyError, MissingAPIKeyError, TimeoutError, UsageLimitExceededError

from src.config import get_app_config


def _get_tavily_client() -> TavilyClient:
    config = get_app_config().get_tool_config("web_search")
    api_key = None
    if config is not None:
        model_extra = config.model_extra or {}
        if "api_key" in model_extra:
            api_key = model_extra.get("api_key")
    return TavilyClient(api_key=api_key)


def _format_tavily_error(error: Exception) -> str:
    if isinstance(error, MissingAPIKeyError):
        return "Error: Tavily web search is not configured. Set `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."
    if isinstance(error, InvalidAPIKeyError):
        return "Error: Tavily API key is invalid. Update `TAVILY_API_KEY` or `tools.web_search.api_key` in `config.yaml`."
    if isinstance(error, UsageLimitExceededError):
        return f"Error: Tavily usage limit exceeded. {error}"
    if isinstance(error, (BadRequestError, ForbiddenError, TimeoutError)):
        return f"Error: Tavily request failed. {error}"
    return f"Error: Tavily request failed. {error}"


def _get_max_results() -> int:
    config = get_app_config().get_tool_config("web_search")
    if config is None:
        return 5

    model_extra = config.model_extra or {}
    configured_max_results = model_extra.get("max_results")
    return configured_max_results if isinstance(configured_max_results, int) else 5


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    client = _get_tavily_client()
    try:
        res = client.search(query, max_results=_get_max_results())
    except Exception as error:
        return _format_tavily_error(error)

    normalized_results = [
        {
            "title": result["title"],
            "url": result["url"],
            "snippet": result["content"],
        }
        for result in res["results"]
    ]
    json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
    return json_results


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    client = _get_tavily_client()
    try:
        res = client.extract([url])
    except Exception as error:
        return _format_tavily_error(error)

    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        return f"# {result['title']}\n\n{result['raw_content'][:4096]}"
    else:
        return "Error: No results found"
