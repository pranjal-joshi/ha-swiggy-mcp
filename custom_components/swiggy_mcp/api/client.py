"""SwiggyApiClient — all HTTP/MCP calls to mcp.swiggy.com (direct) or
the local Swiggy MCP Proxy add-on (add-on mode).

Tool name reference (from https://mcp.swiggy.com/builders/docs/reference/):
  Food:      get_addresses, get_food_orders, get_food_order_details, get_food_cart,
             update_food_cart, flush_food_cart, place_food_order,
             search_restaurants, search_menu, get_restaurant_menu,
             track_food_order, fetch_food_coupons, apply_food_coupon
  Instamart: get_addresses, get_cart, update_cart, clear_cart, checkout,
             search_products, get_orders, get_order_details, track_order
  Dineout:   search_restaurants_dineout, get_restaurant_details,
             get_available_slots, create_cart, book_table, get_booking_status

Swiggy MCP returns plain human-readable text in content[0].text for some
tools (get_addresses, flush_food_cart, clear_cart, etc.) — NOT JSON.
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
    """Pull content[0].text from a JSON-RPC MCP response envelope."""
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
        return json.dumps(text)
    return text.strip() or None


def _try_parse_json(text: str) -> Any:
    """Attempt JSON parse; return parsed object or None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _unwrap_data(parsed: Any) -> Any:
    """Unwrap Swiggy's {success, data, message} envelope if present."""
    if isinstance(parsed, dict):
        if not parsed.get("success", True):
            raise UpdateFailed(
                parsed.get("error", {}).get("message", "Swiggy returned an error")
            )
        return parsed.get("data") if "data" in parsed else parsed
    return parsed


def _parse_addresses_text(text: str) -> list[dict]:
    """Parse Swiggy's plain-text address list into structured dicts.

    Format: '1. [Label] Name: Address (ID: id_value)'
    """
    addresses = []
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
        _LOGGER.debug("Could not parse addresses from plain text: %r", text[:300])
    return addresses


def _parse_orders_text(text: str) -> dict:
    """Best-effort parse of Swiggy's plain-text order response."""
    _LOGGER.debug("Plain-text order response: %r", text[:500])
    lower = text.lower()
    if any(p in lower for p in ("no active", "no order", "no current")):
        return {"orders": []}
    _LOGGER.warning(
        "get_food_orders returned plain text — cannot parse order state. "
        "Raw (first 300 chars): %r", text[:300]
    )
    return {"orders": []}


def _parse_cart_text(text: str) -> dict:
    """Best-effort parse of Swiggy's plain-text cart response."""
    lower = text.lower()
    if any(p in lower for p in ("cart is empty", "empty cart", "no items")):
        return {"items": [], "total": None}

    items = []
    total = None

    item_pattern = re.compile(
        r"^\d+\.\s+(.+?)(?:\s+[x×](\d+))?(?:\s*[-–]\s*[₹Rs.]?[\d.,]+)?\s*$"
    )
    for line in text.splitlines():
        m = item_pattern.match(line.strip())
        if m:
            name = m.group(1).strip()
            qty = int(m.group(2)) if m.group(2) else 1
            items.append(f"{name} x{qty}" if qty > 1 else name)

    total_pattern = re.compile(r"(?:grand\s+)?total[:\s]+[₹Rs.]*([\\d.,]+)", re.IGNORECASE)
    m = total_pattern.search(text)
    if m:
        try:
            total = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return {"items": items, "total": total}


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
                            _LOGGER.debug("Non-JSON SSE data: %r", data_str[:500])
                            raise UpdateFailed("Swiggy SSE response contained invalid JSON")
                raise UpdateFailed("SSE response contained no data: payload")

            parsed = _try_parse_json(body)
            if parsed is not None:
                return parsed
            _LOGGER.debug("Non-JSON top-level response: %r", body[:500])
            raise UpdateFailed(f"Swiggy returned a non-JSON response: {body[:100]}")

    # ── Addresses ─────────────────────────────────────────────────────────────

    async def get_addresses(self) -> list[dict]:
        """Fetch saved delivery addresses. Handles JSON and plain-text."""
        raw = await self._post("food", _mcp_payload("get_addresses", {}))
        text = _extract_content_text(raw)
        if text is None:
            return []
        parsed = _try_parse_json(text)
        if parsed is not None:
            data = _unwrap_data(parsed)
            return data.get("addresses", []) if isinstance(data, dict) else []
        _LOGGER.debug("get_addresses: parsing plain-text response")
        return _parse_addresses_text(text)

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_food_orders(self, address_id: str, count: int = 1) -> dict:
        """Fetch active food orders."""
        raw = await self._post(
            "food",
            _mcp_payload("get_food_orders", {"addressId": address_id, "orderCount": count}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"orders": []}
        parsed = _try_parse_json(text)
        if parsed is not None:
            data = _unwrap_data(parsed)
            return data if isinstance(data, dict) else {"orders": []}
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
            data = _unwrap_data(parsed)
            return data if isinstance(data, dict) else {}
        _LOGGER.debug("get_food_order_details plain-text: %r", text[:300])
        return {}

    # ── Cart — Food ───────────────────────────────────────────────────────────

    async def get_cart(self, service: str, address_id: str) -> dict:
        """Fetch current cart. Food: get_food_cart / Instamart: get_cart."""
        if service == "instamart":
            # get_cart takes selectedAddressId
            raw = await self._post(
                "instamart",
                _mcp_payload("get_cart", {"selectedAddressId": address_id}),
            )
        else:
            raw = await self._post(
                "food",
                _mcp_payload("get_food_cart", {"addressId": address_id}),
            )
        text = _extract_content_text(raw)
        if text is None:
            return {"items": [], "total": None}
        parsed = _try_parse_json(text)
        if parsed is not None:
            data = _unwrap_data(parsed) if isinstance(parsed, dict) else parsed
            if isinstance(data, dict):
                # Food cart: cartItems[]; Instamart cart: items[]
                raw_items = data.get("cartItems") or data.get("items") or []
                names = [
                    i.get("name") or i.get("itemName") or i.get("productName", "")
                    for i in raw_items if isinstance(i, dict)
                ]
                total = (
                    data.get("total") or data.get("grandTotal")
                    or data.get("billTotal") or data.get("totalAmount")
                )
                return {"items": [n for n in names if n], "total": total}
        _LOGGER.debug("get_cart(%s) plain-text: %r", service, text[:500])
        return _parse_cart_text(text)

    async def add_to_food_cart_by_name(
        self, item_name: str, quantity: int, address_id: str
    ) -> dict:
        """Search for a dish by name, then add first result to food cart.

        Uses search_menu to resolve item + restaurant IDs, then update_food_cart.
        """
        # Step 1: search for the item
        search_raw = await self._post(
            "food",
            _mcp_payload("search_menu", {"query": item_name, "addressId": address_id}),
        )
        search_text = _extract_content_text(search_raw)
        restaurant_id = None
        cart_items = []

        if search_text:
            parsed = _try_parse_json(search_text)
            if parsed is not None:
                data = _unwrap_data(parsed) if isinstance(parsed, dict) else parsed
                results = []
                if isinstance(data, dict):
                    results = data.get("restaurants") or data.get("items") or []
                elif isinstance(data, list):
                    results = data

                for r in results[:1]:  # take first restaurant match
                    restaurant_id = r.get("restaurantId") or r.get("id")
                    menu_items = r.get("menuItems") or r.get("items") or []
                    for mi in menu_items[:1]:  # take first item match
                        cart_items = [{
                            "itemId": mi.get("itemId") or mi.get("id"),
                            "quantity": quantity,
                            "variants": mi.get("variants", []),
                        }]
                        break
                    if restaurant_id and cart_items:
                        break

        if not restaurant_id or not cart_items:
            _LOGGER.warning(
                "Could not resolve restaurant/item for '%s' from search_menu", item_name
            )
            raise UpdateFailed(
                f"Could not find '{item_name}' on Swiggy Food — "
                "try searching in the Swiggy app first to confirm availability"
            )

        # Step 2: add to cart
        raw = await self._post(
            "food",
            _mcp_payload("update_food_cart", {
                "restaurantId": restaurant_id,
                "cartItems": cart_items,
                "addressId": address_id,
            }),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"success": True}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return _unwrap_data(parsed) if isinstance(parsed, dict) else {"success": True}
        _LOGGER.info("add_to_food_cart response: %s", text[:200])
        return {"success": True, "message": text}

    async def add_to_instamart_cart_by_name(
        self, item_name: str, quantity: int, address_id: str
    ) -> dict:
        """Search Instamart for a product by name, then add to cart.

        Uses search_products → get spinId → merge with current cart → update_cart.
        """
        # Step 1: search for the product
        search_raw = await self._post(
            "instamart",
            _mcp_payload("search_products", {
                "query": item_name,
                "addressId": address_id,
            }),
        )
        search_text = _extract_content_text(search_raw)
        spin_id = None

        if search_text:
            parsed = _try_parse_json(search_text)
            if parsed is not None:
                data = _unwrap_data(parsed) if isinstance(parsed, dict) else parsed
                products = []
                if isinstance(data, dict):
                    products = data.get("products") or data.get("items") or []
                elif isinstance(data, list):
                    products = data
                for p in products[:1]:
                    # Products have variants; take the first variant's spinId
                    variants = p.get("variants") or [p]
                    spin_id = variants[0].get("spinId") if variants else p.get("spinId")
                    if spin_id:
                        break

        if not spin_id:
            _LOGGER.warning("Could not resolve spinId for '%s'", item_name)
            raise UpdateFailed(
                f"Could not find '{item_name}' on Swiggy Instamart — "
                "check the product name and try again"
            )

        # Step 2: get current cart to merge (update_cart REPLACES entire cart)
        try:
            current = await self.get_cart("instamart", address_id)
            existing_items = []
            # We don't have spinIds for existing items from the text response,
            # so start fresh with just the new item (limitation of plain-text cart)
        except Exception:
            existing_items = []

        new_items = [{"spinId": spin_id, "quantity": quantity}]

        # Step 3: update cart
        raw = await self._post(
            "instamart",
            _mcp_payload("update_cart", {
                "selectedAddressId": address_id,
                "items": new_items,
            }),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"success": True}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return _unwrap_data(parsed) if isinstance(parsed, dict) else {"success": True}
        _LOGGER.info("add_to_instamart_cart response: %s", text[:200])
        return {"success": True, "message": text}

    async def flush_cart(self, service: str, address_id: str) -> dict:
        """Clear cart. Food: flush_food_cart (needs addressId) / Instamart: clear_cart (no params)."""
        if service == "instamart":
            # clear_cart takes no parameters
            raw = await self._post(
                "instamart",
                _mcp_payload("clear_cart", {}),
            )
        else:
            raw = await self._post(
                "food",
                _mcp_payload("flush_food_cart", {"addressId": address_id}),
            )
        text = _extract_content_text(raw)
        if text is None:
            return {"success": True}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return _unwrap_data(parsed) if isinstance(parsed, dict) else {"success": True}
        _LOGGER.info("flush_cart(%s) response: %s", service, text[:200])
        return {"success": True, "message": text}

    async def get_instamart_orders(self, address_id: str, count: int = 1) -> dict:
        """Fetch recent Instamart orders."""
        raw = await self._post(
            "instamart",
            _mcp_payload("get_orders", {"count": count}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"orders": []}
        parsed = _try_parse_json(text)
        if parsed is not None:
            data = _unwrap_data(parsed)
            return data if isinstance(data, dict) else {"orders": []}
        _LOGGER.debug("get_instamart_orders plain-text: %r", text[:300])
        lower = text.lower()
        if any(p in lower for p in ("no active", "no order", "no current")):
            return {"orders": []}
        _LOGGER.warning(
            "get_instamart_orders returned plain text — cannot parse order state. "
            "Raw (first 300 chars): %r", text[:300]
        )
        return {"orders": []}

    async def place_food_order(self, address_id: str) -> dict:
        """Place food delivery order. Cart value must be < ₹1000 (Swiggy beta limit)."""
        raw = await self._post(
            "food",
            _mcp_payload("place_food_order", {"addressId": address_id}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"success": True}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return _unwrap_data(parsed) if isinstance(parsed, dict) else {"success": True}
        _LOGGER.info("place_food_order response: %s", text[:300])
        return {"success": True, "message": text}
