"""HA services for Swiggy MCP — Instamart focused.

All calls go through coordinator.client (SwiggyApiClient).
Auth is handled transparently inside the client's _post() method.

Food ordering services (reorder_last, place_order, food add_to_cart)
are available in the 'food' branch.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_ADDRESS_ID,
    DOMAIN,
    SERVICE_ADD_TO_CART,
    SERVICE_CLEAR_CART,
    SERVICE_PLACE_ORDER,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_TO_CART_SCHEMA = vol.Schema(
    {
        vol.Required("query"): str,
        vol.Optional("quantity", default=1): vol.All(int, vol.Range(min=1)),
    }
)

SERVICE_CLEAR_CART_SCHEMA = vol.Schema({})


SERVICE_PLACE_ORDER_SCHEMA = vol.Schema(
    {
        vol.Required("confirmed"): bool,
    }
)


def _get_coordinator(hass: HomeAssistant):
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("Swiggy MCP integration not configured")
    return next(iter(entries.values()))


def _get_address_id(coordinator) -> str:
    return (
        coordinator._entry.data.get(CONF_ADDRESS_ID)
        or coordinator._address_id
        or ""
    )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Swiggy MCP HA services."""

    async def handle_add_to_cart(call: ServiceCall) -> None:
        """Add an item to the Instamart cart by name."""
        coordinator = _get_coordinator(hass)
        address_id = _get_address_id(coordinator)
        item = call.data["query"]
        quantity = call.data.get("quantity", 1)

        try:
            result = await coordinator.client.add_to_instamart_cart_by_name(
                item_name=item,
                quantity=quantity,
                address_id=address_id,
            )
            msg = result.get("message", "Done") if isinstance(result, dict) else "Done"
            _LOGGER.info("Add to Instamart cart '%s' x%d: %s", item, quantity, msg)
        except UpdateFailed as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_clear_cart(call: ServiceCall) -> None:
        """Clear the Instamart cart."""
        coordinator = _get_coordinator(hass)
        address_id = _get_address_id(coordinator)
        try:
            result = await coordinator.client.flush_cart(
                service="instamart",
                address_id=address_id,
            )
            msg = result.get("message", "Done") if isinstance(result, dict) else "Done"
            _LOGGER.info("Instamart cart cleared: %s", msg)
        except UpdateFailed as err:
            raise HomeAssistantError(f"Clear cart failed: {err}") from err
        await coordinator.async_request_refresh()

    async def handle_place_order(call: ServiceCall) -> None:
        """Place the current Instamart cart as an order (COD, irreversible)."""
        from homeassistant.exceptions import ServiceValidationError
        if not call.data.get("confirmed"):
            raise ServiceValidationError(
                "You must set confirmed: true to place the order. "
                "⚠️ Orders are COD and CANNOT be cancelled after placement."
            )
        coordinator = _get_coordinator(hass)
        address_id = _get_address_id(coordinator)
        if not address_id:
            raise HomeAssistantError(
                "No delivery address resolved — reload the integration and try again"
            )
        try:
            result = await coordinator.client.place_instamart_order(address_id=address_id)
            msg = result.get("message", "Order placed!") if isinstance(result, dict) else "Order placed!"
            _LOGGER.info("Instamart order placed: %s", msg)
        except UpdateFailed as err:
            raise HomeAssistantError(f"Order placement failed: {err}") from err
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TO_CART, handle_add_to_cart, schema=SERVICE_ADD_TO_CART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_CART, handle_clear_cart, schema=SERVICE_CLEAR_CART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLACE_ORDER, handle_place_order, schema=SERVICE_PLACE_ORDER_SCHEMA
    )
