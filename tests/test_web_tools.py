import json

import httpx
import pytest

from security.url_policy import URLPolicyError
from servers.web_server.fetch import fetch_webpage_data
from servers.web_server.search import search_web_data


PUBLIC_URL = "http://93.184.216.34/page"


@pytest.mark.asyncio
async def test_fetch_strips_scripts_and_handles_malformed_html() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body><h1>Hello</h1><script>steal()</script><p>World",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_webpage_data(PUBLIC_URL, client=client)
    assert "Hello" in result["text"]
    assert "World" in result["text"]
    assert "steal" not in result["text"]


@pytest.mark.asyncio
async def test_fetch_rejects_private_redirect() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(URLPolicyError):
            await fetch_webpage_data(PUBLIC_URL, client=client)


@pytest.mark.asyncio
async def test_fetch_rejects_oversized_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 11, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="size limit"):
            await fetch_webpage_data(PUBLIC_URL, max_response_size=10, client=client)


@pytest.mark.asyncio
async def test_fetch_timeout_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError):
            await fetch_webpage_data(PUBLIC_URL, client=client)


@pytest.mark.asyncio
async def test_fetch_rejects_invalid_scheme() -> None:
    with pytest.raises(URLPolicyError):
        await fetch_webpage_data("file:///etc/passwd")


@pytest.mark.asyncio
async def test_search_normalizes_and_limits_results() -> None:
    seen_request = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        payload = {
            "results": [
                {"title": f"Result {index}", "url": f"https://example.com/{index}", "content": "Text", "engine": "test"}
                for index in range(12)
            ]
        }
        return httpx.Response(200, content=json.dumps(payload), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await search_web_data(
            "  Python   MCP  ", base_url="http://localhost:8080", max_results=99, client=client
        )
    assert result["query"] == "Python MCP"
    assert len(result["results"]) == 10
    assert seen_request.url.params["q"] == "Python MCP"
    assert seen_request.url.params["format"] == "json"


@pytest.mark.asyncio
async def test_search_rejects_malformed_json_shape() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": "not-a-list"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Malformed"):
            await search_web_data("test", base_url="http://localhost:8080", client=client)
