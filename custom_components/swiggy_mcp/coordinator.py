"""DataUpdateCoordinator for Swiggy MCP — Instamart focused.

All HTTP is delegated to SwiggyApiClient.
All auth is delegated to SwiggyAuthManager (inside the client).
This class only orchestrates polling and event firing.

Food ordering features are available in the 'food' branch.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import SwiggyApiClient
from .const import (
    CONF_ADDRESS_ID,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    EVENT_INSTAMART_OUT_FOR_DELIVERY,
    EVENT_INSTAMART_ORDER_DELIVERED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_OUT_FOR_DELIVERY,
)

_LOGGER = logging.getLogger(__name__)


class SwiggyDataUpdateCoordinator(DataUpdateCoordinator):
    """Polls Swiggy Instamart state; exposes clean data dict to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SwiggyApiClient,
    ) -> None:
        self.client = client  # exposed so services.py can call cart methods
        self._address_id: str = entry.data.get(CONF_ADDRESS_ID, "")
        self._address_text: str | None = None  # full address string for sensor
        self._addresses: list[dict] = []  # full list for address select entity
        self._prev_im_status: str | None = None

        interval = timedelta(
            seconds=entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
        )

    async def async_update_address(self, address_id: str) -> None:
        """Switch active delivery address and persist to config entry.

        Called by the address select entity when the user picks a new address.
        Triggers an immediate data refresh so all sensors update instantly.
        """
        matched = next(
            (a for a in self._addresses if a.get("id") == address_id), None
        )
        if matched is None:
            _LOGGER.warning("async_update_address: id %r not in cached list", address_id)
            return
        self._address_id = address_id
        self._address_text = matched.get("address") or matched.get("name") or matched.get("label")
        _LOGGER.info("Delivery address changed to: %s (%s)", self._address_text, address_id)
        # Persist to config entry so the choice survives a restart
        self.hass.config_entries.async_update_entry(
            self._entry,  # type: ignore[attr-defined]
            data={**self._entry.data, CONF_ADDRESS_ID: address_id},  # type: ignore[attr-defined]
        )
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict:
        """Fetch latest Instamart state from Swiggy; returns normalised state dict."""
        empty: dict = {
            # Instamart order
            "instamart_order_active": False,
            "instamart_order_id": None,
            "instamart_order_status": None,
            "instamart_store": None,
            "instamart_billed_amount": None,
            "instamart_eta": None,
            "instamart_order_items": None,
            # Instamart cart
            "instamart_cart_items": None,
            "instamart_cart_total": None,
            # Delivery address
            "address": None,
        }

        try:
            # Resolve address lazily on first poll or when missing
            if not self._address_id or self._address_text is None:
                try:
                    addresses = await self.client.get_addresses()
                    if addresses:
                        self._addresses = addresses
                        first = addresses[0]
                        if not self._address_id:
                            self._address_id = first.get("id", "")
                            _LOGGER.debug("Resolved address_id from Swiggy: %s", self._address_id)
                        matched = next(
                            (a for a in addresses if a.get("id") == self._address_id),
                            first,
                        )
                        self._address_text = matched.get("address") or matched.get("name")
                    else:
                        _LOGGER.warning("Swiggy returned no addresses; will retry next poll")
                        if not self._address_id:
                            return empty
                except UpdateFailed as err:
                    _LOGGER.warning("Could not fetch addresses: %s; will retry next poll", err)
                    if not self._address_id:
                        return empty

        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("Unexpected error in coordinator setup: %s", err)
            return empty

        result: dict = dict(empty)
        result["address"] = self._address_text

        # ── Instamart active order ────────────────────────────────────────────
        try:
            im_orders_data = await self.client.get_instamart_orders(active_only=True, count=1)
            im_orders = (im_orders_data or {}).get("orders") or []
            im_active = im_orders[0] if im_orders else None
            if im_active:
                im_status = (
                    im_active.get("status") or im_active.get("orderStatus")
                    or im_active.get("orderState")
                )
                im_items_raw = im_active.get("items") or im_active.get("orderItems") or []
                im_items_str = ", ".join(
                    (i.get("name") or i.get("productName") or i if isinstance(i, str) else "")
                    for i in im_items_raw
                ) or None
                result.update({
                    "instamart_order_active": im_status not in (ORDER_STATUS_DELIVERED, "Delivered", None),
                    "instamart_order_id": im_active.get("orderId") or im_active.get("order_id"),
                    "instamart_order_status": im_status,
                    "instamart_store": im_active.get("storeName") or im_active.get("restaurantName"),
                    "instamart_billed_amount": (
                        im_active.get("billedAmount") or im_active.get("orderTotal")
                        or im_active.get("totalAmount")
                    ),
                    "instamart_eta": im_active.get("sla") or im_active.get("eta") or im_active.get("deliveryEta"),
                    "instamart_order_items": im_items_str,
                })
                # Fire HA events on Instamart order status transitions
                if im_status != self._prev_im_status:
                    if im_status == ORDER_STATUS_OUT_FOR_DELIVERY:
                        self.hass.bus.async_fire(
                            EVENT_INSTAMART_OUT_FOR_DELIVERY,
                            {"order_id": result["instamart_order_id"]},
                        )
                    elif im_status in (ORDER_STATUS_DELIVERED, "Delivered"):
                        self.hass.bus.async_fire(
                            EVENT_INSTAMART_ORDER_DELIVERED,
                            {"order_id": result["instamart_order_id"]},
                        )
                    self._prev_im_status = im_status
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.debug("Instamart order fetch failed (non-fatal): %s", err)

        # ── Instamart cart ────────────────────────────────────────────────────
        try:
            im_cart = await self.client.get_cart("instamart", self._address_id)
            result["instamart_cart_items"] = ", ".join(im_cart.get("items") or []) or None
            result["instamart_cart_total"] = im_cart.get("total")
        except Exception as err:
            _LOGGER.debug("Instamart cart fetch failed (non-fatal): %s", err)

        return result
