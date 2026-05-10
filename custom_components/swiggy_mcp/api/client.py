"""SwiggyApiClient — all HTTP/MCP calls to mcp.swiggy.com.

Auth knowledge is ZERO here. The client asks SwiggyAuthManager for a token
and uses it.  On 401 it forces one refresh and retries once; a second 401
raises ConfigEntryAuthFailed and HA will start a reauth flow.
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
    SWIGGY_FOOD_URL,
    SWIGGY_INSTAMART_URL,
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

    def __init__(self, hass, auth: SwiggyAuthManager) -> None:
        self._hass = hass
        self._auth = auth

    # ── Transport ─────────────────────────────────────────────────────────────

    async def _post(self, url: str, payload: dict, *, _retry: bool = True) -> dict:
        """POST a JSON-RPC payload; handles 401 with one forced refresh+retry."""
        token = await self._auth.async_get_access_token()
        session = async_get_clientsession(self._hass)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401:
                if _retry:
                    _LOGGER.warning("Got 401 — forcing token refresh and retrying once")
                    await self._auth._async_refresh()
                    return await self._post(url, payload, _retry=False)
                # Second 401 after refresh — auth is dead
                raise ConfigEntryAuthFailed(
                    "Authentication failed after token refresh — please re-authenticate"
                )

            if resp.status >= 500:
                raise UpdateFailed(f"Swiggy server error: HTTP {resp.status}")

            if resp.status not in (200, 201):
                raise UpdateFailed(f"Swiggy unexpected status: HTTP {resp.status}")

            return await resp.json()

    # ── Public MCP tool wrappers ──────────────────────────────────────────────

    async def get_addresses(self) -> list[dict]:
        """Fetch saved delivery addresses."""
        raw = await self._post(SWIGGY_FOOD_URL, _mcp_payload("get_addresses", {}))
        data = _parse_mcp_data(raw)
        return (data or {}).get("addresses", [])

    async def get_food_orders(self, address_id: str, count: int = 1) -> dict:
        """Fetch active/recent food orders."""
        raw = await self._post(
            SWIGGY_FOOD_URL,
            _mcp_payload("get_food_orders", {"addressId": address_id, "orderCount": count}),
        )
        return _parse_mcp_data(raw) or {}

    async def get_food_order_details(self, order_id: str) -> dict:
        """Fetch details for a specific food order."""
        raw = await self._post(
            SWIGGY_FOOD_URL,
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
        """Add an item to Food or Instamart cart."""
        url = SWIGGY_INSTAMART_URL if service == "instamart" else SWIGGY_FOOD_URL
        tool = "add_to_instamart_cart" if service == "instamart" else "add_to_food_cart"
        raw = await self._post(
            url,
            _mcp_payload(tool, {"item": item, "quantity": quantity, "addressId": address_id}),
        )
        return _parse_mcp_data(raw) or {}

    async def flush_cart(self, service: str, address_id: str) -> dict:
        """Clear Food or Instamart cart."""
        url = SWIGGY_INSTAMART_URL if service == "instamart" else SWIGGY_FOOD_URL
        raw = await self._post(
            url,
            _mcp_payload("flush_food_cart", {"addressId": address_id}),
        )
        return _parse_mcp_data(raw) or {}
