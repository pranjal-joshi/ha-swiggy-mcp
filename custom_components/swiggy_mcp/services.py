"""HA services for Swiggy MCP — zero auth knowledge.

All calls go through coordinator.client (SwiggyApiClient).
Auth is handled transparently inside the client's _post() method.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_ADDRESS_ID,
    DOMAIN,
    SERVICE_ADD_TO_CART,
    SERVICE_CLEAR_CART,
    SERVICE_REORDER_LAST,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_TO_CART_SCHEMA = vol.Schema(
    {
        vol.Required("item"): str,
        vol.Optional("quantity", default=1): vol.All(int, vol.Range(min=1)),
        vol.Optional("service", default="instamart"): vol.In(["food", "instamart"]),
    }
)

SERVICE_CLEAR_CART_SCHEMA = vol.Schema(
    {
        vol.Optional("service", default="food"): vol.In(["food", "instamart"]),
    }
)


def _get_coordinator(hass: HomeAssistant):
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("Swiggy MCP integration not configured")
    return next(iter(entries.values()))


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Swiggy MCP HA services."""

    async def handle_reorder_last(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        order_id = (coordinator.data or {}).get("order_id")
        if not order_id:
            _LOGGER.warning("No recent order found — cannot reorder")
            return
        details = await coordinator.client.get_food_order_details(order_id)
        _LOGGER.info("Reorder triggered for order %s: %s", order_id, details)

    async def handle_add_to_cart(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        address_id = (coordinator._entry.data.get(CONF_ADDRESS_ID) or coordinator._address_id or "")
        result = await coordinator.client.add_to_cart(
            service=call.data.get("service", "instamart"),
            item=call.data["item"],
            quantity=call.data.get("quantity", 1),
            address_id=address_id,
        )
        _LOGGER.info("Add to cart: %s", result)

    async def handle_clear_cart(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        address_id = (coordinator._entry.data.get(CONF_ADDRESS_ID) or coordinator._address_id or "")
        result = await coordinator.client.flush_cart(
            service=call.data.get("service", "food"),
            address_id=address_id,
        )
        _LOGGER.info("Cart cleared: %s", result)

    hass.services.async_register(DOMAIN, SERVICE_REORDER_LAST, handle_reorder_last)
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TO_CART, handle_add_to_cart, schema=SERVICE_ADD_TO_CART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_CART, handle_clear_cart, schema=SERVICE_CLEAR_CART_SCHEMA
    )
