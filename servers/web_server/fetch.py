"""Bounded webpage retrieval with SSRF protections and text extraction."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from security.url_policy import validate_public_url


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self._chunks.append(cleaned)

    def text(self) -> str:
        return "\n".join(self._chunks)


def extract_readable_text(body: bytes, content_type: str) -> str:
    encoding = "utf-8"
    for piece in content_type.split(";")[1:]:
        if piece.strip().lower().startswith("charset="):
            encoding = piece.split("=", 1)[1].strip().strip('"') or "utf-8"
    text = body.decode(encoding, errors="replace")
    if "html" not in content_type.casefold():
        return text.strip()
    parser = _ReadableHTMLParser()
    parser.feed(text)
    return parser.text()


async def read_bounded_body(response: httpx.Response, maximum: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = 0
        if declared_size > maximum:
            raise ValueError("Web response exceeds configured size limit")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > maximum:
            raise ValueError("Web response exceeds configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_webpage_data(
    url: str,
    *,
    timeout_seconds: int = 10,
    max_response_size: int = 2 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    current_url = validate_public_url(url)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        headers={"User-Agent": "LocalAssistant/0.1 (+privacy-first MCP client)"},
    )
    try:
        for _ in range(4):
            async with active_client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect response did not include a location")
                    current_url = validate_public_url(urljoin(current_url, location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "text/plain")
                media_type = content_type.split(";", 1)[0].strip().casefold()
                if media_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                    raise ValueError("Webpage response is not readable text or HTML")
                body = await read_bounded_body(response, max_response_size)
                text = extract_readable_text(body, content_type)
                return {
                    "url": str(response.url),
                    "content_type": media_type,
                    "text": text,
                    "bytes": len(body),
                }
        raise ValueError("Too many redirects")
    except httpx.TimeoutException as exc:
        raise TimeoutError("Webpage request timed out") from exc
    finally:
        if owns_client:
            await active_client.aclose()
