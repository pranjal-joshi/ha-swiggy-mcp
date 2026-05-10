"""SwiggyApiClient — all HTTP/MCP calls to mcp.swiggy.com (direct) or
the local Swiggy MCP Proxy add-on (add-on mode).

Add-on mode: reads use_addon + addon_url from the config entry. No token
injection needed — the add-on handles auth and forwards calls to Swiggy.

Direct mode: asks SwiggyAuthManager for a token and uses it. On 401 it
forces one refresh and retries once; a second 401 raises ConfigEntryAuthFailed.
"""
from __future__ import annotations

import json
import logging
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


def _parse_mcp_data(raw: dict) -> Any:
    """Extract .data from a successful MCP response envelope."""
    result = raw.get("result", {})
    content = result.get("content", [])
    if not content:
        return None
    text = content[0].get("text", "{}")
    parsed = json.loads(text) if isinstance(text, str) else text
    if not parsed.get("success", True):
        raise UpdateFailed(parsed.get("error", {}).get("message", "Swiggy error"))
    return parsed.get("data")


class SwiggyApiClient:
    """Thin async HTTP client for Swiggy MCP endpoints."""

    def __init__(self, hass, auth: SwiggyAuthManager | None, entry_data: dict) -> None:
        self._hass = hass
        self._auth = auth
        self._use_addon: bool = entry_data.get(CONF_USE_ADDON, False)
        self._addon_url: str = entry_data.get(CONF_ADDON_URL, "").rstrip("/")

    def _resolve_url(self, service: str) -> str:
        """Return the correct endpoint URL for the given service."""
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
        """POST a JSON-RPC payload; handles 401 with one forced refresh+retry.
        Handles both plain JSON and SSE (text/event-stream) responses.
        """
        url = self._resolve_url(service)
        session = async_get_clientsession(self._hass)

        # MCP Streamable HTTP transport requires both MIME types in Accept.
        # Without text/event-stream the server returns HTTP 406.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if not self._use_addon and self._auth:
            token = await self._auth.async_get_access_token()
            headers["Authorization"] = f"Bearer {token}"

        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401:
                if self._use_addon:
                    raise UpdateFailed(
                        "Add-on returned 401 — open the Swiggy MCP Proxy add-on UI and re-authenticate"
                    )
                if _retry and self._auth:
                    _LOGGER.warning("Got 401 — forcing token refresh and retrying once")
                    await self._auth._async_refresh()
                    return await self._post(service, payload, _retry=False)
                raise ConfigEntryAuthFailed(
                    "Authentication failed after token refresh — please re-authenticate"
                )

            if resp.status >= 500:
                raise UpdateFailed(f"Swiggy server error: HTTP {resp.status}")

            if resp.status not in (200, 201):
                raise UpdateFailed(f"Swiggy unexpected status: HTTP {resp.status}")

            content_type = resp.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                # SSE response — extract first data: line
                raw = await resp.text()
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("data:"):
                        payload_str = line[5:].strip()
                        if payload_str and payload_str != "[DONE]":
                            return json.loads(payload_str)
                raise UpdateFailed("SSE response contained no data: payload")

            return await resp.json()

    # ── Public MCP tool wrappers ──────────────────────────────────────────────

    async def get_addresses(self) -> list[dict]:
        raw = await self._post("food", _mcp_payload("get_addresses", {}))
        data = _parse_mcp_data(raw)
        return (data or {}).get("addresses", [])

    async def get_food_orders(self, address_id: str, count: int = 1) -> dict:
        raw = await self._post(
            "food",
            _mcp_payload("get_food_orders", {"addressId": address_id, "orderCount": count}),
        )
        return _parse_mcp_data(raw) or {}

    async def get_food_order_details(self, order_id: str) -> dict:
        raw = await self._post(
            "food",
            _mcp_payload("get_food_order_details", {"orderId": order_id}),
        )
        return _parse_mcp_data(raw) or {}

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
        return _parse_mcp_data(raw) or {}

    async def flush_cart(self, service: str, address_id: str) -> dict:
        svc = "instamart" if service == "instamart" else "food"
        raw = await self._post(
            svc,
            _mcp_payload("flush_food_cart", {"addressId": address_id}),
        )
        return _parse_mcp_data(raw) or {}
