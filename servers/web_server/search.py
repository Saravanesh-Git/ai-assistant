"""SearXNG JSON search adapter."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from servers.web_server.fetch import read_bounded_body


class SearchUnavailableError(RuntimeError):
    """Raised when the configured SearXNG service cannot be used."""


def _search_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("SEARXNG_URL must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed in SEARXNG_URL")
    path = parsed.path.rstrip("/") + "/search"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


async def search_web_data(
    query: str,
    *,
    base_url: str,
    max_results: int = 5,
    timeout_seconds: int = 10,
    max_response_size: int = 2 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("Search query cannot be empty")
    if len(normalized) > 500:
        raise ValueError("Search query is too long")
    limit = max(1, min(int(max_results), 10))
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
    try:
        async with active_client.stream(
            "GET",
            _search_endpoint(base_url),
            params={"q": normalized, "format": "json", "pageno": 1},
            headers={"Accept": "application/json", "User-Agent": "LocalAssistant/0.1"},
        ) as response:
            response.raise_for_status()
            body = await read_bounded_body(response, max_response_size)
        payload = json.loads(body)
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("Malformed SearXNG response")
        results = []
        for item in raw_results[:limit]:
            if not isinstance(item, dict):
                continue
            result_url = str(item.get("url", ""))
            title = str(item.get("title", "Untitled"))
            if not result_url:
                continue
            results.append(
                {
                    "title": title[:500],
                    "url": result_url[:2048],
                    "snippet": str(item.get("content", ""))[:2000],
                    "engine": str(item.get("engine", "unknown"))[:100],
                }
            )
        return {"query": normalized, "results": results}
    except (httpx.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        raise SearchUnavailableError("Web search is unavailable") from exc
    finally:
        if owns_client:
            await active_client.aclose()
