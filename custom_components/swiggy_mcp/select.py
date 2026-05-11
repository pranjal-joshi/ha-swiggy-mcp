"""Select entity for Swiggy MCP — delivery address picker."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Swiggy MCP",
        manufacturer="Swiggy",
        model="MCP Integration",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://github.com/pranjal-joshi/ha-swiggy-mcp",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Swiggy MCP select entities."""
    coordinator: SwiggyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SwiggyAddressSelect(coordinator, entry)])


class SwiggyAddressSelect(CoordinatorEntity[SwiggyDataUpdateCoordinator], SelectEntity):
    """Dropdown to select the active Swiggy delivery address.

    Options are populated from the coordinator's cached address list.
    The option labels use the human-readable address text; internally
    we map back to the address ID for API calls.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-multiple"

    def __init__(
        self,
        coordinator: SwiggyDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_delivery_address"
        self._attr_name = "Delivery Address"
        self._attr_device_info = _device_info(entry)
        # Internal map: label → address_id (rebuilt on each coordinator update)
        self._label_to_id: dict[str, str] = {}

    def _build_options(self) -> list[str]:
        """Build option labels from coordinator's cached address list."""
        options = []
        self._label_to_id = {}
        for addr in self.coordinator._addresses:
            addr_id = addr.get("id", "")
            if not addr_id:
                continue
            # Prefer full address text, fall back to label/name
            label = (
                addr.get("address")
                or addr.get("name")
                or addr.get("label")
                or addr_id
            )
            # Deduplicate labels that are identical
            if label in self._label_to_id:
                label = f"{label} ({addr_id[-6:]})"
            self._label_to_id[label] = addr_id
            options.append(label)
        return options

    @property
    def options(self) -> list[str]:
        return self._build_options()

    @property
    def current_option(self) -> str | None:
        """Return the label for the currently active address."""
        current_id = self.coordinator._address_id
        # Rebuild map in case options changed
        self._build_options()
        for label, addr_id in self._label_to_id.items():
            if addr_id == current_id:
                return label
        # Fallback: return address text directly if already resolved
        return self.coordinator._address_text

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting a different delivery address."""
        # Rebuild map to ensure it's current
        self._build_options()
        addr_id = self._label_to_id.get(option)
        if not addr_id:
            _LOGGER.warning("SwiggyAddressSelect: unknown option %r", option)
            return
        await self.coordinator.async_update_address(addr_id)
