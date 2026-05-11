"""LLM Tool definitions for the Swiggy MCP integration.

Each tool subclasses homeassistant.helpers.llm.Tool and delegates
HTTP to the SwiggyApiClient stored in hass.data[DOMAIN].
"""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.llm import ToolInput

from ..const import DOMAIN, SWIGGY_FOOD_URL, SWIGGY_INSTAMART_URL

_LOGGER = logging.getLogger(__name__)

_URL_TO_SERVICE = {
    SWIGGY_FOOD_URL: "food",
    SWIGGY_INSTAMART_URL: "instamart",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(hass: HomeAssistant):
    """Return (client, address_id) from the first configured Swiggy entry."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("Swiggy MCP is not configured")
    coord = next(iter(entries.values()))
    return coord.client, coord._address_id


def _mcp_call(name: str, arguments: dict, req_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
        "id": req_id,
    }


async def _call_mcp(hass: HomeAssistant, url: str, tool_name: str, args: dict) -> dict:
    """Call a Swiggy MCP tool and return a JSON-serialisable dict."""
    client, addr_id = _get_client(hass)
    # Only inject addressId if the caller hasn't already provided it or
    # an equivalent key (selectedAddressId used by Instamart tools).
    if "addressId" not in args and "selectedAddressId" not in args:
        args_with_addr = {**args, "addressId": addr_id}
    else:
        args_with_addr = args
    # Resolve service name ("food"/"instamart") from the endpoint URL so
    # client._resolve_url() works correctly in both direct and add-on mode.
    service = _URL_TO_SERVICE.get(url, "food")
    raw = await client._post(service, _mcp_call(tool_name, args_with_addr))
    content = raw.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "{}")
        try:
            return json.loads(text) if isinstance(text, str) else text
        except (json.JSONDecodeError, ValueError):
            return {"success": True, "message": text}
    return {"success": False, "error": "No response from Swiggy"}


# ---------------------------------------------------------------------------
# Food Tools
# ---------------------------------------------------------------------------

class SwiggySearchRestaurantsTool(llm.Tool):
    name = "swiggy_search_restaurants"
    description = (
        "Search Swiggy for restaurants by dish name, cuisine, or keyword "
        "near the user's default delivery address."
    )
    parameters = vol.Schema(
        {
            vol.Required("query"): str,
            vol.Optional("cuisine"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "search_restaurants", args)


class SwiggyGetRestaurantMenuTool(llm.Tool):
    name = "swiggy_get_restaurant_menu"
    description = (
        "Get the menu of a specific restaurant. "
        "Use restaurant_id from search results."
    )
    parameters = vol.Schema(
        {
            vol.Required("restaurant_id"): str,
            vol.Optional("page", default=1): int,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        # Remap snake_case schema key → camelCase MCP param
        payload = {"restaurantId": args.pop("restaurant_id"), **args}
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "get_restaurant_menu", payload)


class SwiggyGetFoodCartTool(llm.Tool):
    name = "swiggy_get_food_cart"
    description = "Get the current food delivery cart contents and bill breakdown."
    parameters = vol.Schema({})

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "get_food_cart", {})


class SwiggyAddToFoodCartTool(llm.Tool):
    name = "swiggy_add_to_food_cart"
    description = (
        "Add an item to the Swiggy food delivery cart. "
        "Requires item_id and restaurant_id from search_menu or get_restaurant_menu results."
    )
    parameters = vol.Schema(
        {
            vol.Required("item_id"): str,
            vol.Required("restaurant_id"): str,
            vol.Optional("quantity", default=1): int,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        # update_food_cart expects: restaurantId, cartItems[{itemId, quantity}], addressId
        _, addr_id = _get_client(hass)
        payload = {
            "restaurantId": args["restaurant_id"],
            "cartItems": [{"itemId": args["item_id"], "quantity": args.get("quantity", 1)}],
            "addressId": addr_id,
        }
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "update_food_cart", payload)


class SwiggyFlushFoodCartTool(llm.Tool):
    name = "swiggy_flush_food_cart"
    description = "Clear all items from the food delivery cart."
    parameters = vol.Schema({})

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "flush_food_cart", {})


class SwiggyFetchCouponsTool(llm.Tool):
    name = "swiggy_fetch_coupons"
    description = "Fetch available coupons and offers for the current cart."
    parameters = vol.Schema({})

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "fetch_food_coupons", {})


class SwiggyApplyCouponTool(llm.Tool):
    name = "swiggy_apply_coupon"
    description = "Apply a coupon code to the food delivery cart."
    parameters = vol.Schema(
        {
            vol.Required("coupon_code"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        # Remap snake_case schema key → camelCase MCP param
        payload = {"couponCode": args.pop("coupon_code"), **args}
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "apply_food_coupon", payload)


class SwiggyPlaceFoodOrderTool(llm.Tool):
    name = "swiggy_place_food_order"
    description = (
        "Place the food delivery order. "
        "ONLY call this after showing the user the cart contents and receiving explicit confirmation. "
        "This is a COD order and CANNOT be cancelled after placement."
    )
    parameters = vol.Schema(
        {
            vol.Required("confirmed"): bool,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        if not tool_input.tool_args.get("confirmed"):
            return {
                "error": (
                    "Order not confirmed. Show the cart to the user and ask for explicit "
                    "confirmation before calling this tool again with confirmed=true."
                )
            }
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "place_food_order", {})


class SwiggyGetFoodOrdersTool(llm.Tool):
    name = "swiggy_get_food_orders"
    description = "Get active food delivery orders and their current status."
    parameters = vol.Schema({})

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "get_food_orders", {})


class SwiggyGetFoodOrderDetailsTool(llm.Tool):
    name = "swiggy_get_food_order_details"
    description = (
        "Get detailed information about a specific order including ETA and tracking."
    )
    parameters = vol.Schema(
        {
            vol.Required("order_id"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        # Remap snake_case schema key → camelCase MCP param
        payload = {"orderId": args.pop("order_id"), **args}
        return await _call_mcp(hass, SWIGGY_FOOD_URL, "get_food_order_details", payload)


# ---------------------------------------------------------------------------
# Instamart Tools
# ---------------------------------------------------------------------------

class SwiggySearchInstamartTool(llm.Tool):
    name = "swiggy_search_instamart"
    description = (
        "Search Swiggy Instamart for grocery products by name, brand or category. "
        "Returns products with their variations; each variation has a spinId needed for add-to-cart."
    )
    parameters = vol.Schema(
        {
            vol.Required("query"): str,
            vol.Optional("category"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        return await _call_mcp(hass, SWIGGY_INSTAMART_URL, "search_products", args)


class SwiggyGetInstamartCartTool(llm.Tool):
    name = "swiggy_get_instamart_cart"
    description = "Get current Instamart grocery cart contents and bill breakdown."
    parameters = vol.Schema({})

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        return await _call_mcp(hass, SWIGGY_INSTAMART_URL, "get_cart", {})


class SwiggyAddToInstamartCartTool(llm.Tool):
    name = "swiggy_add_to_instamart_cart"
    description = (
        "Add a grocery item to the Instamart cart. "
        "Use spin_id from swiggy_search_instamart results (variations[i].spinId)."
    )
    parameters = vol.Schema(
        {
            vol.Required("spin_id"): str,
            vol.Optional("quantity", default=1): int,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: llm.LLMContext
    ) -> dict:
        args = dict(tool_input.tool_args)
        # update_cart expects: selectedAddressId, items[{spinId, quantity}]
        _, addr_id = _get_client(hass)
        payload = {
            "selectedAddressId": addr_id,
            "items": [{"spinId": args["spin_id"], "quantity": args.get("quantity", 1)}],
        }
        return await _call_mcp(hass, SWIGGY_INSTAMART_URL, "update_cart", payload)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

ALL_TOOL_CLASSES = [
    SwiggySearchRestaurantsTool,
    SwiggyGetRestaurantMenuTool,
    SwiggyGetFoodCartTool,
    SwiggyAddToFoodCartTool,
    SwiggyFlushFoodCartTool,
    SwiggyFetchCouponsTool,
    SwiggyApplyCouponTool,
    SwiggyPlaceFoodOrderTool,
    SwiggyGetFoodOrdersTool,
    SwiggyGetFoodOrderDetailsTool,
    SwiggySearchInstamartTool,
    SwiggyGetInstamartCartTool,
    SwiggyAddToInstamartCartTool,
]
