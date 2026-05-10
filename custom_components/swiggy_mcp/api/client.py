"""SwiggyApiClient — all HTTP/MCP calls to mcp.swiggy.com (direct) or
the local Swiggy MCP Proxy add-on (add-on mode).

Swiggy's MCP server returns plain human-readable text in content[0].text
for some tools (get_addresses, flush_food_cart, etc.), NOT JSON.
Each method handles its response format explicitly.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from ..auth.manager import SwiggyAuthManager
from ..const import (
    CONF_ADDON_URL,
    CONF_USE_ADDON,
    SWIGGY_FOOD_URL,
    SWIGGY_INSTAMART_URL,
    SWIGGY_DINEOUT_URL,
)

_LOGGER = logging.getLogger(__name__)


def _mcp_payload(name: str, arguments: dict, req_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
        "id": req_id,
    }


def _extract_content_text(raw: dict) -> str | None:
    """Pull content[0].text from a JSON-RPC MCP response envelope.

    Returns the raw text string (may be JSON or plain text) or None.
    """
    _LOGGER.debug("Raw MCP envelope: %r", str(raw)[:1000])
    result = raw.get("result") or {}
    content = result.get("content") or []
    if not content:
        _LOGGER.debug("MCP response had empty content; result keys: %s", list(result.keys()))
        return None
    text = content[0].get("text")
    if text is None:
        return None
    if not isinstance(text, str):
        # Already a dict/list — serialise back so callers handle uniformly
        return json.dumps(text)
    return text.strip() or None


def _try_parse_json(text: str) -> Any:
    """Attempt JSON parse; return parsed object or None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_addresses_text(text: str) -> list[dict]:
    """Parse Swiggy's plain-text address list into structured dicts.

    Format (example):
        Found 5 saved addresses:
        1. [Home] Pranjal Joshi: C-304, Marigold Avenue, ... (ID: 11535454)
        2. [Work] Name: Address ... (ID: abc123)
    """
    addresses = []
    # Match: N. [Label] Name: Address (ID: id_value)
    pattern = re.compile(
        r"^\d+\.\s+\[([^\]]+)\]\s+([^:]+):\s+(.+?)\s+\(ID:\s*([^)]+)\)\s*$"
    )
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            addresses.append({
                "id": m.group(4).strip(),
                "label": m.group(1).strip(),
                "name": m.group(2).strip(),
                "address": m.group(3).strip(),
            })
    if not addresses:
        _LOGGER.debug("Could not parse any addresses from plain text: %r", text[:300])
    return addresses


def _parse_orders_text(text: str) -> dict:
    """Best-effort parse of Swiggy's plain-text order response.

    Returns a dict with an 'orders' key. If we can't extract structured
    data, returns empty orders so the coordinator shows unknown state
    rather than crashing.
    """
    _LOGGER.debug("Plain-text order response: %r", text[:500])
    # Swiggy might return "No active orders" or similar
    lower = text.lower()
    if any(phrase in lower for phrase in ("no active", "no order", "no current")):
        return {"orders": []}
    # We can't reliably parse rich order data from plain text yet.
    # Return empty and let sensors show unknown until we see the format.
    _LOGGER.warning(
        "get_food_orders returned plain text (not JSON) — cannot parse order state. "
        "Raw (first 300 chars): %r", text[:300]
    )
    return {"orders": []}


class SwiggyApiClient:
    """Thin async HTTP client for Swiggy MCP endpoints."""

    def __init__(self, hass, auth: SwiggyAuthManager | None, entry_data: dict) -> None:
        self._hass = hass
        self._auth = auth
        self._use_addon: bool = entry_data.get(CONF_USE_ADDON, False)
        self._addon_url: str = entry_data.get(CONF_ADDON_URL, "").rstrip("/")

    def _resolve_url(self, service: str) -> str:
        if self._use_addon:
            return f"{self._addon_url}/{service}"
        mapping = {
            "food": SWIGGY_FOOD_URL,
            "instamart": SWIGGY_INSTAMART_URL,
            "im": SWIGGY_INSTAMART_URL,
            "dineout": SWIGGY_DINEOUT_URL,
        }
        return mapping.get(service, SWIGGY_FOOD_URL)

    # ── Transport ─────────────────────────────────────────────────────────────

    async def _post(self, service: str, payload: dict, *, _retry: bool = True) -> dict:
        """POST a JSON-RPC payload. Handles JSON and SSE responses."""
        url = self._resolve_url(service)
        session = async_get_clientsession(self._hass)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if not self._use_addon and self._auth:
            token = await self._auth.async_get_access_token()
            headers["Authorization"] = f"Bearer {token}"

        async with session.post(url, json=payload, headers=headers) as resp:
            body = await resp.text()

            if resp.status == 401:
                _LOGGER.debug("Swiggy 401 body: %r", body[:200])
                if self._use_addon:
                    raise UpdateFailed(
                        "Add-on returned 401 - open the add-on UI and re-authenticate"
                    )
                if _retry and self._auth:
                    _LOGGER.warning("Got 401 - forcing token refresh and retrying once")
                    await self._auth._async_refresh()
                    return await self._post(service, payload, _retry=False)
                raise ConfigEntryAuthFailed(
                    "Authentication failed after token refresh - please re-authenticate"
                )

            if resp.status not in (200, 201):
                _LOGGER.warning("Swiggy HTTP %s body: %r", resp.status, body[:500])
                raise UpdateFailed(
                    f"Swiggy unexpected status: HTTP {resp.status} - {body[:200]}"
                )

            content_type = resp.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                for line in body.splitlines():
                    line = line.strip()
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str and data_str != "[DONE]":
                            parsed = _try_parse_json(data_str)
                            if parsed is not None:
                                return parsed
                            _LOGGER.debug("Non-JSON SSE data line: %r", data_str[:500])
                            raise UpdateFailed("Swiggy SSE response contained invalid JSON")
                raise UpdateFailed("SSE response contained no data: payload")

            parsed = _try_parse_json(body)
            if parsed is not None:
                return parsed
            _LOGGER.debug("Non-JSON top-level response: %r", body[:500])
            raise UpdateFailed(f"Swiggy returned a non-JSON response: {body[:100]}")

    # ── Public MCP tool wrappers ──────────────────────────────────────────────

    async def get_addresses(self) -> list[dict]:
        """Fetch saved delivery addresses. Handles both JSON and plain-text responses."""
        raw = await self._post("food", _mcp_payload("get_addresses", {}))
        text = _extract_content_text(raw)
        if text is None:
            return []

        parsed = _try_parse_json(text)
        if parsed is not None:
            # JSON response — extract addresses list from data envelope
            if isinstance(parsed, dict):
                data = parsed.get("data") or parsed
                return data.get("addresses", []) if isinstance(data, dict) else []
            return []

        # Plain-text response — parse the human-readable address list
        _LOGGER.debug("get_addresses: parsing plain-text response")
        return _parse_addresses_text(text)

    async def get_food_orders(self, address_id: str, count: int = 1) -> dict:
        """Fetch active food orders. Handles both JSON and plain-text responses."""
        raw = await self._post(
            "food",
            _mcp_payload("get_food_orders", {"addressId": address_id, "orderCount": count}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"orders": []}

        parsed = _try_parse_json(text)
        if parsed is not None:
            if isinstance(parsed, dict):
                return parsed.get("data") or parsed
            return {"orders": []}

        # Plain-text — best-effort parse
        return _parse_orders_text(text)

    async def get_food_order_details(self, order_id: str) -> dict:
        raw = await self._post(
            "food",
            _mcp_payload("get_food_order_details", {"orderId": order_id}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return (parsed.get("data") or parsed) if isinstance(parsed, dict) else {}
        _LOGGER.debug("get_food_order_details plain-text response: %r", text[:300])
        return {}

    async def add_to_cart(
        self,
        service: str,
        item: str,
        quantity: int,
        address_id: str,
    ) -> dict:
        svc = "instamart" if service == "instamart" else "food"
        tool = "add_to_instamart_cart" if service == "instamart" else "add_to_food_cart"
        raw = await self._post(
            svc,
            _mcp_payload(tool, {"item": item, "quantity": quantity, "addressId": address_id}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return (parsed.get("data") or parsed) if isinstance(parsed, dict) else {}
        # Plain text like "Added Maggi to cart" — treat as success
        _LOGGER.info("add_to_cart response: %s", text[:200])
        return {"success": True, "message": text}

    async def flush_cart(self, service: str, address_id: str) -> dict:
        svc = "instamart" if service == "instamart" else "food"
        tool = "flush_instamart_cart" if service == "instamart" else "flush_food_cart"
        raw = await self._post(
            svc,
            _mcp_payload(tool, {"addressId": address_id}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return (parsed.get("data") or parsed) if isinstance(parsed, dict) else {}
        # Plain text like "Flushed Food cart successfully" — treat as success
        _LOGGER.info("flush_cart response: %s", text[:200])
        return {"success": True, "message": text}
