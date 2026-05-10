"""MCP proxy — forwards requests to mcp.swiggy.com with stored Bearer token.

Swiggy MCP uses the Streamable HTTP transport spec. Responses may be:
  - Content-Type: application/json  → plain JSON, pass through directly
  - Content-Type: text/event-stream → SSE stream, extract data: lines and
    return the first non-empty JSON payload as application/json
"""
import logging
import time

import aiohttp

from storage import load_tokens, save_tokens
from oauth import refresh_access_token

_LOGGER = logging.getLogger(__name__)

SWIGGY_ENDPOINTS = {
    "food": "https://mcp.swiggy.com/food",
    "instamart": "https://mcp.swiggy.com/im",
    "im": "https://mcp.swiggy.com/im",
    "dineout": "https://mcp.swiggy.com/dineout",
}


def _extract_from_sse(raw_bytes: bytes) -> bytes:
    """Parse SSE body and return the first data: payload as plain bytes.

    SSE format:
        data: {"jsonrpc":"2.0","result":{...},"id":1}\n\n

    We extract all data: lines, concatenate them (for multi-chunk events),
    and return the result so the HA integration can JSON-parse it normally.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    collected = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                collected.append(payload)
    if collected:
        # Most MCP responses fit in a single data: line
        return collected[0].encode("utf-8")
    _LOGGER.warning("SSE response contained no data: lines; raw: %r", text[:200])
    return b"{}"


async def _read_mcp_response(resp: aiohttp.ClientResponse) -> bytes:
    """Read an MCP HTTP response, normalising SSE to plain JSON bytes."""
    content_type = resp.headers.get("Content-Type", "")
    raw = await resp.read()
    if "text/event-stream" in content_type:
        _LOGGER.debug("SSE response detected, extracting data: payload")
        return _extract_from_sse(raw)
    return raw


async def _get_valid_token(session: aiohttp.ClientSession):
    tokens = load_tokens()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    client_id = tokens.get("client_id")
    expires_at = tokens.get("expires_at", 0)

    if not access_token:
        return None

    # Refresh if expiring within 5 minutes
    if refresh_token and client_id and time.time() > (expires_at - 300):
        try:
            _LOGGER.info("Refreshing Swiggy access token")
            data = await refresh_access_token(session, refresh_token, client_id)
            tokens["access_token"] = data["access_token"]
            tokens["expires_at"] = time.time() + int(data.get("expires_in", 3600))
            if "refresh_token" in data:
                tokens["refresh_token"] = data["refresh_token"]
            save_tokens(tokens)
            return tokens["access_token"]
        except Exception as e:
            _LOGGER.warning("Token refresh failed: %s", e)

    return access_token


async def proxy_request(
    service: str,
    request_body: bytes,
    request_headers: dict,
    session: aiohttp.ClientSession,
):
    """Proxy an MCP request to Swiggy. Returns (status, headers, body)."""
    target_url = SWIGGY_ENDPOINTS.get(service)
    if not target_url:
        return 404, {}, b'{"error": "unknown service"}'

    access_token = await _get_valid_token(session)
    if not access_token:
        return 401, {}, b'{"error": "not authenticated - complete OAuth in add-on UI"}'

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        # MCP Streamable HTTP transport requires both types in Accept.
        # Without text/event-stream Swiggy returns HTTP 406.
        "Accept": "application/json, text/event-stream",
    }

    async with session.post(target_url, data=request_body, headers=headers) as resp:
        status = resp.status
        body = await _read_mcp_response(resp)
        # Always return application/json — HA integration expects JSON
        resp_headers = {"Content-Type": "application/json"}

        if status == 401:
            tokens = load_tokens()
            tokens.pop("access_token", None)
            save_tokens(tokens)
            _LOGGER.warning("Swiggy rejected token — reauth required")

        return status, resp_headers, body
