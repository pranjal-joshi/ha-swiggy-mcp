"""HA services for Swiggy MCP — zero auth knowledge.

All calls go through coordinator.client (SwiggyApiClient).
Auth is handled transparently inside the client's _post() method.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_ADDRESS_ID,
    DOMAIN,
    SERVICE_ADD_TO_CART,
    SERVICE_CLEAR_CART,
    SERVICE_PLACE_ORDER,
    SERVICE_REORDER_LAST,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_TO_CART_SCHEMA = vol.Schema(
    {
        vol.Required("query"): str,
        vol.Optional("quantity", default=1): vol.All(int, vol.Range(min=1)),
        vol.Optional("service", default="instamart"): vol.In(["food", "instamart"]),
    }
)

SERVICE_CLEAR_CART_SCHEMA = vol.Schema(
    {
        vol.Optional("service", default="food"): vol.In(["food", "instamart"]),
    }
)

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

    async def handle_reorder_last(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        address_id = _get_address_id(coordinator)

        # Try cached order_id from coordinator first
        order_id = (coordinator.data or {}).get("order_id")
        order_source = "food"

        if not order_id:
            # Live fallback: try food orders
            try:
                food_data = await coordinator.client.get_food_orders(address_id, count=5)
                orders = food_data.get("orders") or []
                if orders:
                    order_id = orders[0].get("orderId") or orders[0].get("id")
                    order_source = "food"
            except Exception as err:
                _LOGGER.debug("Live food order fallback failed: %s", err)

        if not order_id:
            # Live fallback: try Instamart orders
            try:
                im_data = await coordinator.client.get_instamart_orders(active_only=False, count=5)
                orders = im_data.get("orders") or []
                if orders:
                    order_id = orders[0].get("orderId") or orders[0].get("id")
                    order_source = "instamart"
            except Exception as err:
                _LOGGER.debug("Live Instamart order fallback failed: %s", err)

        if not order_id:
            raise ServiceValidationError(
                "No recent order found — make sure there is an active or recent order"
            )

        try:
            details = await coordinator.client.get_food_order_details(order_id)
            _LOGGER.info(
                "Reorder triggered for %s order %s: %s",
                order_source, order_id, details,
            )
            # Note: Swiggy MCP has no native reorder tool. This fetches order
            # details for reference; full reorder requires manual cart rebuild.
            raise HomeAssistantError(
                "Swiggy MCP does not support automatic reorder. "
                "Use the Swiggy app to reorder, or use add_to_cart to rebuild your cart."
            )
        except UpdateFailed as err:
            raise HomeAssistantError(f"Swiggy order lookup failed: {err}") from err

    async def handle_add_to_cart(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        address_id = _get_address_id(coordinator)
        service = call.data.get("service", "instamart")
        item = call.data["query"]
        quantity = call.data.get("quantity", 1)

        try:
            if service == "instamart":
                result = await coordinator.client.add_to_instamart_cart_by_name(
                    item_name=item,
                    quantity=quantity,
                    address_id=address_id,
                )
            else:
                result = await coordinator.client.add_to_food_cart_by_name(
                    item_name=item,
                    quantity=quantity,
                    address_id=address_id,
                )
            msg = result.get("message", "Done") if isinstance(result, dict) else "Done"
            _LOGGER.info("Add to cart (%s) '%s' x%d: %s", service, item, quantity, msg)
        except UpdateFailed as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_clear_cart(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        address_id = _get_address_id(coordinator)
        service = call.data.get("service", "food")
        try:
            result = await coordinator.client.flush_cart(
                service=service,
                address_id=address_id,
            )
            msg = result.get("message", "Done") if isinstance(result, dict) else "Done"
            _LOGGER.info("Cart cleared (%s): %s", service, msg)
        except UpdateFailed as err:
            raise HomeAssistantError(f"Clear cart failed: {err}") from err

    async def handle_place_order(call: ServiceCall) -> None:
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
            result = await coordinator.client.place_food_order(address_id=address_id)
            msg = result.get("message", "Order placed!") if isinstance(result, dict) else "Order placed!"
            _LOGGER.info("Food order placed: %s", msg)
        except UpdateFailed as err:
            raise HomeAssistantError(f"Order placement failed: {err}") from err

    hass.services.async_register(DOMAIN, SERVICE_REORDER_LAST, handle_reorder_last)
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TO_CART, handle_add_to_cart, schema=SERVICE_ADD_TO_CART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_CART, handle_clear_cart, schema=SERVICE_CLEAR_CART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLACE_ORDER, handle_place_order, schema=SERVICE_PLACE_ORDER_SCHEMA
    )
