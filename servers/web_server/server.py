"""Local stdio MCP server exposing bounded web capabilities."""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server import MCPServer

from app.core.config import load_settings
from servers.web_server.fetch import fetch_webpage_data
from servers.web_server.search import SearchUnavailableError, search_web_data
from servers.stdio_transport import run_server_stdio

settings = load_settings()
mcp = MCPServer(
    "local-assistant-web",
    instructions="SearXNG search and SSRF-protected, size-bounded webpage retrieval.",
)


@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web through the configured SearXNG service (maximum 10 results)."""
    try:
        return await search_web_data(
            query,
            base_url=settings.searxng_url,
            max_results=max_results,
            timeout_seconds=settings.web_timeout_seconds,
            max_response_size=settings.max_web_response_size,
        )
    except SearchUnavailableError:
        return {"query": " ".join(query.split()), "results": [], "unavailable": True}


@mcp.tool()
async def fetch_webpage(url: str) -> dict[str, Any]:
    """Fetch readable text from one public HTTP(S) webpage with SSRF protection."""
    return await fetch_webpage_data(
        url,
        timeout_seconds=settings.web_timeout_seconds,
        max_response_size=settings.max_web_response_size,
    )


def main() -> None:
    anyio.run(run_server_stdio, mcp)


if __name__ == "__main__":
    main()
