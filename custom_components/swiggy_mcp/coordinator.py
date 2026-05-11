"""DataUpdateCoordinator for Swiggy MCP — thin, auth-free.

All HTTP is delegated to SwiggyApiClient.
All auth is delegated to SwiggyAuthManager (inside the client).
This class only orchestrates polling and event firing.
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
    EVENT_ORDER_DELIVERED,
    EVENT_OUT_FOR_DELIVERY,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_OUT_FOR_DELIVERY,
)

_LOGGER = logging.getLogger(__name__)


class SwiggyDataUpdateCoordinator(DataUpdateCoordinator):
    """Polls Swiggy order state; exposes clean data dict to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SwiggyApiClient,
    ) -> None:
        self.client = client  # exposed so services.py can call cart methods
        self._address_id: str = entry.data.get(CONF_ADDRESS_ID, "")
        self._address_text: str | None = None  # full address string for sensor
        self._prev_status: str | None = None

        interval = timedelta(
            seconds=entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
        )

    async def _async_update_data(self) -> dict:
        """Fetch latest order from Swiggy; returns normalised state dict.

        Address and order fetch failures are treated as data issues, not
        setup failures — they return an empty state so HA setup succeeds
        and retries on the next poll interval. Only auth failures re-raise.
        """
        empty: dict = {
            "order_active": False,
            "order_id": None,
            "order_status": None,
            "restaurant": None,
            "billed_amount": None,
            "eta": None,
            "items": None,
            # Food cart
            "cart_items": None,
            "cart_total": None,
            # Instamart cart
            "instamart_cart_items": None,
            "instamart_cart_total": None,
            # Delivery address
            "address": None,
        }

        try:
            # In add-on mode address_id may be empty — fetch it lazily.
            # Also fetch addresses if we have an ID but no text yet (e.g. direct mode
            # where address_id came from config but label was never resolved).
            if not self._address_id or self._address_text is None:
                try:
                    addresses = await self.client.get_addresses()
                    if addresses:
                        first = addresses[0]
                        if not self._address_id:
                            self._address_id = first.get("id", "")
                            _LOGGER.debug("Resolved address_id from Swiggy: %s", self._address_id)
                        # Find the address entry matching our configured id
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

            orders_data = await self.client.get_food_orders(self._address_id, count=1)

        except ConfigEntryAuthFailed:
            raise  # let HA trigger reauth banner
        except UpdateFailed as err:
            _LOGGER.warning("Swiggy order fetch failed: %s; returning empty state", err)
            return empty
        except Exception as err:
            _LOGGER.warning("Unexpected error fetching Swiggy orders: %s", err)
            return empty

        orders = (orders_data or {}).get("orders") or []
        active = orders[0] if orders else None

        result: dict = dict(empty)

        if active:
            status = active.get("status") or active.get("orderStatus")
            result.update(
                {
                    "order_active": status not in (ORDER_STATUS_DELIVERED, None),
                    "order_id": active.get("orderId") or active.get("order_id"),
                    "order_status": status,
                    "restaurant": active.get("restaurantName"),
                    "billed_amount": active.get("billedAmount") or active.get("orderTotal"),
                    "eta": active.get("sla") or active.get("eta"),
                    "items": ", ".join(
                        i.get("name", "") for i in active.get("items", [])
                    ),
                }
            )

            # Fire HA events on status transitions
            if status != self._prev_status:
                if status == ORDER_STATUS_OUT_FOR_DELIVERY:
                    self.hass.bus.async_fire(
                        EVENT_OUT_FOR_DELIVERY, {"order_id": result["order_id"]}
                    )
                elif status == ORDER_STATUS_DELIVERED:
                    self.hass.bus.async_fire(
                        EVENT_ORDER_DELIVERED, {"order_id": result["order_id"]}
                    )
                self._prev_status = status

        # Populate delivery address sensor
        result["address"] = self._address_text

        # Fetch food cart (non-fatal)
        try:
            cart = await self.client.get_cart("food", self._address_id)
            result["cart_items"] = ", ".join(cart.get("items") or []) or None
            result["cart_total"] = cart.get("total")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Food cart fetch failed (non-fatal): %s", err)
            result["cart_items"] = None
            result["cart_total"] = None

        # Fetch Instamart cart (non-fatal)
        try:
            im_cart = await self.client.get_cart("instamart", self._address_id)
            result["instamart_cart_items"] = ", ".join(im_cart.get("items") or []) or None
            result["instamart_cart_total"] = im_cart.get("total")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Instamart cart fetch failed (non-fatal): %s", err)
            result["instamart_cart_items"] = None
            result["instamart_cart_total"] = None

        return result
