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


def _parse_search_menu_items(text: str) -> list[dict]:
    """Parse a plain-text search_menu response into a list of structured items.

    Each returned dict has keys: name (str), restaurant_id (str), item_id (str).
    Handles the following known plain-text formats emitted by Swiggy's MCP server:

    Format A — numbered list with separate label lines:
        1. Butter Chicken (₹349) - Non-veg
           Restaurant: Punjab Grill (ID: 12345)
           Item ID: 67890

    Format B — pipe-separated single line:
        Butter Chicken | Restaurant ID: 12345 | Item ID: 67890

    Format C — inline JSON-like key-value fragments:
        "restaurantId": "12345"  ...  "itemId": "67890"  ...  "name": "Butter Chicken"

    Format D — restaurant header followed by indented items:
        Punjab Grill (ID: 12345)
          - Butter Chicken (Item ID: 67890, ₹349)

    Returns an empty list if no items can be parsed.
    """
    items: list[dict] = []

    # ── Format A: numbered list ───────────────────────────────────────────────
    # Match blocks: first line is the item name/price, subsequent indented lines
    # give Restaurant ID and Item ID.
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Numbered item line: "1. Some Dish Name (₹XX) - ..."
        name_m = re.match(r"^\d+\.\s+(.+?)(?:\s*[\(（][₹Rs.\d,]+[\)）].*)?$", line)
        if name_m:
            name = re.sub(r"\s*[\(（][₹Rs.\d,]+[\)）].*$", "", name_m.group(1)).strip()
            rid: str | None = None
            iid: str | None = None
            # Scan the next few lines for IDs
            for j in range(i + 1, min(i + 6, len(lines))):
                sub = lines[j].strip()
                if not sub or re.match(r"^\d+\.", sub):
                    break
                if not rid:
                    rm = re.search(
                        r"[Rr]estaurant\b[^(]*\(ID:\s*([A-Za-z0-9_@.-]+)\)"
                        r"|[Rr]estaurant\s+(?:ID|Id|id)\s*[=:]\s*\"?([A-Za-z0-9_@.-]+)\"?",
                        sub,
                    )
                    if rm:
                        rid = (rm.group(1) or rm.group(2) or "").strip()
                if not iid:
                    im = re.search(
                        r"[Ii]tem\s+(?:ID|Id|id)\s*[=:]\s*\"?([A-Za-z0-9_@.-]+)\"?",
                        sub,
                    )
                    if im:
                        iid = im.group(1).strip()
            if rid and iid and name:
                items.append({"name": name, "restaurant_id": rid, "item_id": iid})
        i += 1

    if items:
        _LOGGER.debug("_parse_search_menu_items (Format A): found %d items", len(items))
        return items

    # ── Format B: pipe-separated ──────────────────────────────────────────────
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            name = parts[0]
            rid = iid = None
            for part in parts[1:]:
                rm = re.search(r"[Rr]estaurant\s+(?:ID|Id|id)\s*[=:]\s*([A-Za-z0-9_@.-]+)", part)
                if rm:
                    rid = rm.group(1).strip()
                im = re.search(r"[Ii]tem\s+(?:ID|Id|id)\s*[=:]\s*([A-Za-z0-9_@.-]+)", part)
                if im:
                    iid = im.group(1).strip()
            if rid and iid and name:
                items.append({"name": name, "restaurant_id": rid, "item_id": iid})

    if items:
        _LOGGER.debug("_parse_search_menu_items (Format B): found %d items", len(items))
        return items

    # ── Format C: JSON-like fragments in multi-line text ─────────────────────
    # Scan entire text for all restaurantId/itemId/name occurrences and zip them.
    rids = re.findall(r'"?restaurantId"?\s*[=:]\s*"([A-Za-z0-9_@.-]+)"', text)
    iids = re.findall(r'"itemId"\s*[=:]\s*"([A-Za-z0-9_@.-]+)"', text)
    names_c = re.findall(r'"name"\s*:\s*"([^"]+)"', text)
    for idx in range(min(len(rids), len(iids))):
        name = names_c[idx] if idx < len(names_c) else f"Item {idx + 1}"
        items.append({"name": name, "restaurant_id": rids[idx], "item_id": iids[idx]})

    if items:
        _LOGGER.debug("_parse_search_menu_items (Format C): found %d items", len(items))
        return items

    # ── Format D: restaurant header + indented item lines ─────────────────────
    current_rid: str | None = None
    for line in lines:
        stripped = line.strip()
        # Restaurant header: "Punjab Grill (ID: 12345)"
        rh = re.match(r"^(.+?)\s+\(ID:\s*([A-Za-z0-9_@.-]+)\)\s*$", stripped)
        if rh:
            current_rid = rh.group(2).strip()
            continue
        if current_rid:
            # Item line: "- Butter Chicken (Item ID: 67890, ₹349)"
            il = re.match(r"^[-*]\s+(.+?)\s+\([Ii]tem\s+ID:\s*([A-Za-z0-9_@.-]+)", stripped)
            if il:
                items.append({
                    "name": il.group(1).strip(),
                    "restaurant_id": current_rid,
                    "item_id": il.group(2).strip(),
                })

    if items:
        _LOGGER.debug("_parse_search_menu_items (Format D): found %d items", len(items))
        return items

    # ── Format E: get_restaurant_menu output ──────────────────────────────────
    # Header: "Menu for Bikkgane Biryani (ID: 1230155)"
    # Items:  "  - Chicken Dum Biryani Bowl - 500ml — ₹339 | Non-veg (ID: 184897574)"
    #
    # Also handles search_restaurants output:
    # "1. Bikkgane Biryani (Ad) — ... (ID: 1230155)"
    # followed by search_menu output that contains same (ID: ...) inline.
    menu_rid: str | None = None
    # Try to find restaurant ID from a header line (first ~5 lines)
    for line in lines[:5]:
        hm = re.search(r"\(ID:\s*([A-Za-z0-9_@.-]+)\)", line)
        if hm:
            menu_rid = hm.group(1).strip()
            break

    if menu_rid:
        for line in lines:
            stripped = line.strip()
            # "  - Item Name — ₹Price | Tags, has addons (ID: 184897574)"
            im = re.match(
                r"^[-*]\s+(.+?)\s+[—–-]+\s*[₹Rs.\d,]+.*\(ID:\s*([A-Za-z0-9_@.-]+)\)",
                stripped,
            )
            if im:
                items.append({
                    "name": im.group(1).strip(),
                    "restaurant_id": menu_rid,
                    "item_id": im.group(2).strip(),
                })

    if items:
        _LOGGER.debug("_parse_search_menu_items (Format E): found %d items from restaurant %s", len(items), menu_rid)
        return items

    _LOGGER.warning(
        "_parse_search_menu_items: could not extract any items from text "
        "(first 600 chars): %r", text[:600]
    )
    return []


def _fuzzy_pick_item(query: str, items: list[dict], threshold: int = 45) -> dict | None:
    """Return the best fuzzy match from a parsed item list using thefuzz.

    Uses token_set_ratio which handles:
    - Extra words: "butter chicken" matches "Butter Chicken Boneless (Half)"
    - Word order: "chicken butter" matches "Butter Chicken"
    - Case differences

    Returns None if best score < threshold.
    """
    try:
        from thefuzz import fuzz  # type: ignore[import]
    except ImportError:
        _LOGGER.warning(
            "_fuzzy_pick_item: thefuzz not installed; falling back to difflib"
        )
        import difflib
        names = [it["name"].lower() for it in items]
        matches = difflib.get_close_matches(query.lower(), names, n=1, cutoff=threshold / 100)
        if matches:
            idx = names.index(matches[0])
            _LOGGER.debug("_fuzzy_pick_item (difflib): matched %r → %r", query, items[idx]["name"])
            return items[idx]
        return None

    best_score = 0
    best_item: dict | None = None
    q = query.lower()
    for item in items:
        score = fuzz.token_set_ratio(q, item["name"].lower())
        if score > best_score:
            best_score = score
            best_item = item

    if best_item and best_score >= threshold:
        _LOGGER.debug(
            "_fuzzy_pick_item: matched %r → %r (score=%d)",
            query, best_item["name"], best_score,
        )
        return best_item

    _LOGGER.debug(
        "_fuzzy_pick_item: no match above threshold %d for %r (best=%d on %r)",
        threshold, query, best_score, best_item["name"] if best_item else "—",
    )
    return None


# Keep for backward compat — wraps _parse_search_menu_items and returns single (rid, iid)
def _parse_search_menu_text(text: str) -> tuple[str | None, str | None]:
    """Extract restaurantId and itemId from plain-text. Returns first found pair."""
    items = _parse_search_menu_items(text)
    if items:
        return items[0]["restaurant_id"], items[0]["item_id"]
    return None, None


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


async def _resolve_with_ai_task(hass, text: str, item_name: str) -> tuple[str | None, str | None]:
    """Use ai_task.generate_data to extract restaurantId + itemId from raw text.

    This is the third-tier fallback (after JSON parse and regex) for
    search_menu responses that are too free-form for regex patterns.

    Returns (restaurant_id, item_id) — both None on failure or if ai_task
    is unavailable.

    HA 2025.7+ API:
        result = await ai_task.async_generate_data(
            hass,
            task_name="...",
            instructions="...",
            structure=voluptuous_schema,
        )
        restaurant_id = result.data["restaurant_id"]
        item_id       = result.data["item_id"]
    """
    try:
        import voluptuous as vol
        from homeassistant.components import ai_task as _ai_task

        schema = vol.Schema({
            vol.Required("restaurant_id"): str,
            vol.Required("item_id"): str,
        })
        instructions = (
            f"You are a JSON extractor. From the following Swiggy search_menu response "
            f"(searching for '{item_name}'), extract the restaurant ID and menu item ID "
            f"for the best matching result.\n\n"
            f"Response text:\n{text[:2000]}\n\n"
            f"Return ONLY a JSON object with keys 'restaurant_id' and 'item_id'. "
            f"If you cannot find them, return empty strings."
        )
        result = await _ai_task.async_generate_data(
            hass,
            task_name=f"swiggy_mcp_resolve_menu_item_{item_name[:30]}",
            instructions=instructions,
            structure=schema,
        )
        rid = (result.data or {}).get("restaurant_id", "").strip()
        iid = (result.data or {}).get("item_id", "").strip()
        if rid and iid:
            _LOGGER.info(
                "_resolve_with_ai_task: extracted restaurant=%r item=%r for '%s'",
                rid, iid, item_name,
            )
            return rid, iid
        _LOGGER.warning(
            "_resolve_with_ai_task: ai_task returned empty IDs for '%s'", item_name
        )
        return None, None
    except AttributeError:
        # ai_task.async_generate_data not available in this HA version
        _LOGGER.debug("ai_task.async_generate_data not available; skipping LLM fallback")
        return None, None
    except Exception as err:
        _LOGGER.warning("_resolve_with_ai_task failed for '%s': %s", item_name, err)
        return None, None


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
        """Fetch current cart. Returns {items, total, raw_items}.

        Food:      get_food_cart — requires addressId
        Instamart: get_cart     — takes NO parameters (per Swiggy docs)

        raw_items is included for Instamart merge use:
          [{"spinId": ..., "quantity": ...}, ...]
        """
        if service == "instamart":
            raw = await self._post(
                "instamart",
                _mcp_payload("get_cart", {}),
            )
        else:
            raw = await self._post(
                "food",
                _mcp_payload("get_food_cart", {"addressId": address_id}),
            )
        text = _extract_content_text(raw)
        if text is None:
            return {"items": [], "total": None, "raw_items": []}
        parsed = _try_parse_json(text)
        if parsed is not None:
            data = _unwrap_data(parsed) if isinstance(parsed, dict) else parsed
            if isinstance(data, dict):
                # Food cart: cartItems[]; Instamart cart: items[] or cartItems[]
                # Instamart multi-store: stores[i].items[]
                raw_items: list = (
                    data.get("cartItems") or data.get("items") or []
                )
                # Also check multi-store shape: data.stores[i].items[]
                if not raw_items:
                    for store in (data.get("stores") or []):
                        if isinstance(store, dict):
                            raw_items.extend(store.get("items") or store.get("cartItems") or [])

                names = [
                    i.get("name") or i.get("itemName") or i.get("productName", "")
                    for i in raw_items if isinstance(i, dict)
                ]

                # ── Total resolution — many possible field names / nesting ──
                # Swiggy uses inconsistent keys AND mixes numeric/string values
                # e.g. cartTotalAmount="₹195", toPay={"value":"₹195"}, grandTotal=195.0

                def _strip_currency(val: Any) -> float | None:
                    """Parse numeric or currency-string value to float.
                    Handles: 195, 195.0, "195", "₹195", "Rs. 1,200.50"
                    """
                    if isinstance(val, (int, float)):
                        return float(val)
                    if isinstance(val, str):
                        cleaned = re.sub(r"[₹RsA-Za-z\s,]", "", val).strip(".")
                        try:
                            return float(cleaned) if cleaned else None
                        except ValueError:
                            return None
                    return None

                def _find_total(d: dict) -> float | None:
                    # Direct keys — includes cartTotalAmount (Instamart uses this)
                    for key in (
                        "totalToPay", "grandTotal", "total", "billTotal",
                        "totalAmount", "itemTotal", "cartTotal", "orderTotal",
                        "cartTotalAmount",
                    ):
                        result = _strip_currency(d.get(key))
                        if result is not None:
                            return result
                    # Nested {value: "₹195"} / {amount: 195} shape
                    # e.g. toPay: {label: "To Pay", value: "₹195"}
                    for key in ("toPay", "totalToPay", "grandTotal", "total"):
                        nested = d.get(key)
                        if isinstance(nested, dict):
                            result = _strip_currency(
                                nested.get("value") or nested.get("amount")
                            )
                            if result is not None:
                                return result
                    return None

                total: float | None = _find_total(data)

                if total is None:
                    # Sub-objects: billBreakdown (Instamart) + billBreakup + others
                    for sub_key in (
                        "billBreakdown", "billBreakup", "charges", "bill", "pricing"
                    ):
                        sub = data.get(sub_key)
                        if isinstance(sub, dict):
                            total = _find_total(sub)
                            if total is not None:
                                _LOGGER.debug(
                                    "get_cart(%s) total from sub-object %r = %s",
                                    service, sub_key, total,
                                )
                                break
                            # lineItems scan: look for "To Pay" / "Grand Total" label
                            for li in (sub.get("lineItems") or []):
                                if not isinstance(li, dict):
                                    continue
                                label = (li.get("label") or "").lower()
                                if any(k in label for k in ("to pay", "grand total", "total")):
                                    result = _strip_currency(li.get("value"))
                                    if result is not None:
                                        total = result
                                        _LOGGER.debug(
                                            "get_cart(%s) total from lineItems label=%r = %s",
                                            service, li.get("label"), total,
                                        )
                                        break
                            if total is not None:
                                break

                if total is None:
                    # Multi-store: stores[0].billBreakup / billBreakdown
                    for store in (data.get("stores") or []):
                        if isinstance(store, dict):
                            total = _find_total(store)
                            if total is None:
                                for sub_key in (
                                    "billBreakdown", "billBreakup", "charges", "bill"
                                ):
                                    sub = store.get(sub_key)
                                    if isinstance(sub, dict):
                                        total = _find_total(sub)
                                        break
                            if total is not None:
                                break

                if total is None:
                    # Last resort: scan all top-level keys containing "total" or "pay"
                    for k, v in data.items():
                        if any(kw in k.lower() for kw in ("total", "topay", "to_pay")):
                            result = _strip_currency(v)
                            if result is not None:
                                total = result
                                _LOGGER.debug(
                                    "get_cart(%s) total from fallback key %r = %s",
                                    service, k, total,
                                )
                                break

                # For Instamart, preserve spinId+quantity for cart merge
                im_raw = []
                if service == "instamart":
                    for i in raw_items:
                        if isinstance(i, dict) and i.get("spinId"):
                            im_raw.append({
                                "spinId": i["spinId"],
                                "quantity": i.get("quantity", 1),
                            })
                _LOGGER.debug("get_cart(%s) parsed total=%s items=%d keys=%s", service, total, len(names), list(data.keys())[:10])
                return {"items": [n for n in names if n], "total": total, "raw_items": im_raw}
        _LOGGER.debug("get_cart(%s) plain-text: %r", service, text[:500])
        result = _parse_cart_text(text)
        result["raw_items"] = []
        return result

    async def add_to_food_cart_by_name(
        self, item_name: str, quantity: int, address_id: str
    ) -> dict:
        """Search for a dish by name, then add first result to food cart.

        Uses search_menu to resolve item + restaurant IDs, then update_food_cart.
        Handles all known response shapes defensively:
          - Shape A: data.items[i]               { id, restaurantId, name, variants/variantsV2, ... }
          - Shape B: data.restaurants[i].menuItems[j]                        ← legacy
          - Shape C: data is a list of items directly
          - Shape D: top-level list of restaurant objects
          - Plain-text fallback: parse IDs from text using regex
        """
        # Step 1: search for the item
        search_raw = await self._post(
            "food",
            _mcp_payload("search_menu", {"query": item_name, "addressId": address_id}),
        )
        search_text = _extract_content_text(search_raw)
        restaurant_id = None
        cart_items = []

        _LOGGER.debug("search_menu raw response for '%s': %r", item_name, (search_text or "")[:1200])

        def _build_cart_item(iid: str, item: dict) -> dict:
            """Build a cartItems entry for update_food_cart.

            For a headless HA service the user hasn't chosen a variant, so we
            pass empty arrays. Swiggy will apply defaults for items that don't
            require a mandatory variant selection. We deliberately do NOT copy
            the full variants/variantsV2 array from search results — that list
            contains ALL possible options and sending it wholesale causes API
            errors.
            """
            entry: dict = {"itemId": iid, "quantity": quantity}
            if "variantsV2" in item:
                entry["variantsV2"] = []
            else:
                entry["variants"] = []
            return entry

        def _try_extract_from_list(item_list: list) -> tuple[str | None, list]:
            """Scan a flat list of menu item dicts and return (restaurantId, cartItems)."""
            for item in item_list:
                if not isinstance(item, dict):
                    continue
                rid = (
                    item.get("restaurantId") or item.get("restaurant_id")
                    or item.get("restId")
                )
                iid = (
                    item.get("id") or item.get("itemId") or item.get("dishId")
                    or item.get("menuItemId")
                )
                if rid and iid:
                    _LOGGER.debug("search_menu flat-item match: restaurant=%s item=%s", rid, iid)
                    return rid, [_build_cart_item(str(iid), item)]
            return None, []

        if search_text:
            parsed = _try_parse_json(search_text)
            if parsed is not None:
                data = _unwrap_data(parsed) if isinstance(parsed, dict) else parsed

                if not data:
                    _LOGGER.warning(
                        "search_menu returned success but empty data for '%s'", item_name
                    )
                else:
                    # ── Shape A: data = { items: [...] } or { menuItems: [...] } ──
                    flat_items: list = []
                    if isinstance(data, dict):
                        flat_items = (
                            data.get("items") or data.get("menuItems")
                            or data.get("dishes") or data.get("results") or []
                        )
                    elif isinstance(data, list):
                        # Shape C: bare list — could be items OR restaurants
                        first = data[0] if data else {}
                        if isinstance(first, dict) and (
                            first.get("items") or first.get("menuItems")
                        ):
                            # Shape D: list of restaurant objects
                            for r in data[:3]:
                                rid = r.get("restaurantId") or r.get("id")
                                mi_list = r.get("menuItems") or r.get("items") or []
                                rid2, ci = _try_extract_from_list(mi_list)
                                if rid2 and ci:
                                    restaurant_id, cart_items = rid2, ci
                                    break
                                elif rid:
                                    rid2, ci = _try_extract_from_list(mi_list)
                                    if ci:
                                        restaurant_id, cart_items = rid, ci
                                        break
                        else:
                            flat_items = data

                    if not restaurant_id:
                        restaurant_id, cart_items = _try_extract_from_list(flat_items)

                    # ── Shape B: data.restaurants[].menuItems[] ─────────────────
                    if not restaurant_id and isinstance(data, dict):
                        nested = data.get("restaurants") or data.get("restaurantList") or []
                        for r in nested[:3]:
                            rid = r.get("restaurantId") or r.get("id")
                            mi_list = r.get("menuItems") or r.get("items") or r.get("dishes") or []
                            rid2, ci = _try_extract_from_list(mi_list)
                            if rid2 and ci:
                                restaurant_id, cart_items = rid2, ci
                                break
                            elif rid and ci:
                                restaurant_id, cart_items = rid, ci
                                break

            else:
                # JSON parse failed — content[0].text is plain human-readable text.
                # Tier 2a: parse text into a list of {name, restaurant_id, item_id}
                # Tier 2b: fuzzy-match user's query against parsed names (thefuzz)
                _LOGGER.warning(
                    "search_menu returned non-JSON for '%s'; attempting fuzzy text parse. "
                    "Raw (first 800 chars): %r",
                    item_name, search_text[:800],
                )
                parsed_items = _parse_search_menu_items(search_text)
                if parsed_items:
                    best = _fuzzy_pick_item(item_name, parsed_items)
                    if best:
                        restaurant_id = best["restaurant_id"]
                        cart_items = [{"itemId": best["item_id"], "quantity": quantity, "variants": []}]
                    else:
                        _LOGGER.warning(
                            "Fuzzy match found no item above threshold for '%s' "
                            "among %d parsed candidates: %s",
                            item_name, len(parsed_items),
                            [it["name"] for it in parsed_items[:5]],
                        )
                else:
                    # Tier 3: ai_task LLM extraction (last resort)
                    _LOGGER.warning(
                        "Text parse found no items for '%s'; trying ai_task LLM fallback.",
                        item_name,
                    )
                    rid, iid = await _resolve_with_ai_task(self._hass, search_text, item_name)
                    if rid and iid:
                        restaurant_id = rid
                        cart_items = [{"itemId": iid, "quantity": quantity, "variants": []}]

        if not restaurant_id or not cart_items:
            _LOGGER.warning(
                "Could not resolve restaurant/item for '%s' from search_menu "
                "(tried JSON parse, fuzzy text parse, and ai_task fallback); "
                "search_text was: %r",
                item_name, (search_text or "")[:500],
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

        Uses search_products → get spinId → update_cart.
        Per docs: data.products[i].variants[j].spinId
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

        _LOGGER.debug("search_products raw response for '%s': %r", item_name, (search_text or "")[:800])

        if search_text:
            parsed = _try_parse_json(search_text)
            if parsed is not None:
                data = _unwrap_data(parsed) if isinstance(parsed, dict) else parsed

                # Guard: _unwrap_data may return None when data key is null
                if not data:
                    _LOGGER.warning(
                        "search_products returned success but empty data for '%s'", item_name
                    )
                else:
                    products = []
                    if isinstance(data, dict):
                        products = (
                            data.get("products")
                            or data.get("items")
                            or data.get("listings")
                            or data.get("results")
                            or []
                        )
                    elif isinstance(data, list):
                        products = data

                    for p in products[:1]:
                        # Per docs: each product has variations[] or variants[],
                        # each entry has spinId. Swiggy returns "variations" in practice.
                        variants = p.get("variations") or p.get("variants") or []
                        if variants:
                            spin_id = variants[0].get("spinId")
                        # Fallback: spinId directly on the product
                        if not spin_id:
                            spin_id = p.get("spinId")
                        if spin_id:
                            _LOGGER.debug(
                                "search_products match: product=%s spinId=%s",
                                p.get("name", "?"), spin_id,
                            )
                            break
            else:
                # JSON parse failed — Swiggy returned plain text
                _LOGGER.warning(
                    "search_products returned non-JSON for '%s'; raw text: %r",
                    item_name, search_text[:500],
                )

        if not spin_id:
            _LOGGER.warning(
                "Could not resolve spinId for '%s'; search_text was: %r",
                item_name, (search_text or "")[:500],
            )
            raise UpdateFailed(
                f"Could not find '{item_name}' on Swiggy Instamart — "
                "check the product name and try again"
            )

        # Step 2: fetch current cart and merge (update_cart REPLACES entire cart)
        existing_items: list[dict] = []
        try:
            current = await self.get_cart("instamart", address_id)
            existing_items = current.get("raw_items") or []
            if not existing_items and current.get("items"):
                # raw_items empty means plain-text response — can't merge; warn
                _LOGGER.warning(
                    "Instamart cart has items but spinIds could not be parsed "
                    "(plain-text response) — existing cart items will be replaced"
                )
        except Exception as err:
            _LOGGER.debug("Could not fetch current Instamart cart for merge: %s", err)

        # Merge: increment quantity if spinId already in cart, else append
        merged: dict[str, dict] = {i["spinId"]: dict(i) for i in existing_items}
        if spin_id in merged:
            merged[spin_id]["quantity"] = merged[spin_id].get("quantity", 0) + quantity
        else:
            merged[spin_id] = {"spinId": spin_id, "quantity": quantity}

        # Step 3: update cart
        raw = await self._post(
            "instamart",
            _mcp_payload("update_cart", {
                "selectedAddressId": address_id,
                "items": list(merged.values()),
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
        """Clear cart. Both flush_food_cart and clear_cart take NO parameters per Swiggy docs."""
        if service == "instamart":
            raw = await self._post(
                "instamart",
                _mcp_payload("clear_cart", {}),
            )
        else:
            raw = await self._post(
                "food",
                _mcp_payload("flush_food_cart", {}),
            )
        _LOGGER.debug("flush_cart(%s) raw envelope: %r", service, str(raw)[:500])
        text = _extract_content_text(raw)
        _LOGGER.debug("flush_cart(%s) content text: %r", service, (text or "")[:300])
        if text is None:
            _LOGGER.info("flush_cart(%s): empty content — assuming success", service)
            return {"success": True}
        parsed = _try_parse_json(text)
        if parsed is not None:
            result = _unwrap_data(parsed) if isinstance(parsed, dict) else {"success": True}
            _LOGGER.info("flush_cart(%s) success: %r", service, result)
            return result
        # Plain-text response — check for error keywords
        lower = text.lower()
        if any(kw in lower for kw in ("error", "failed", "invalid", "unauthorized")):
            _LOGGER.error("flush_cart(%s) returned error text: %r", service, text[:300])
            raise UpdateFailed(f"Clear cart failed: {text[:200]}")
        _LOGGER.info("flush_cart(%s) plain-text response: %s", service, text[:200])
        return {"success": True, "message": text}

    async def get_instamart_orders(self, active_only: bool = False, count: int = 1) -> dict:
        """Fetch Instamart orders.

        Per Swiggy docs: get_orders accepts count, orderType, activeOnly.
        Use active_only=True when polling for order status (coordinator).
        Use active_only=False for order history (reorder_last).
        """
        args: dict = {"count": count}
        if active_only:
            args["activeOnly"] = True
        raw = await self._post(
            "instamart",
            _mcp_payload("get_orders", args),
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

    async def place_instamart_order(self, address_id: str) -> dict:
        """Place Instamart grocery order via checkout tool. Cart value must be < ₹1000."""
        raw = await self._post(
            "instamart",
            _mcp_payload("checkout", {"addressId": address_id}),
        )
        text = _extract_content_text(raw)
        if text is None:
            return {"success": True}
        parsed = _try_parse_json(text)
        if parsed is not None:
            return _unwrap_data(parsed) if isinstance(parsed, dict) else {"success": True}
        _LOGGER.info("place_instamart_order response: %s", text[:300])
        return {"success": True, "message": text}
