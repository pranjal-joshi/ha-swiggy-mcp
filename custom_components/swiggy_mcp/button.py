"""Button entities for Swiggy MCP — Instamart cart actions."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

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


@dataclass(frozen=True)
class SwiggyButtonDescription(ButtonEntityDescription):
    """Describe a Swiggy MCP button."""

    service: str = "instamart"
    icon: str = "mdi:basket-remove"


BUTTONS: tuple[SwiggyButtonDescription, ...] = (
    SwiggyButtonDescription(
        key="clear_instamart_cart",
        name="Instamart Clear Cart",
        service="instamart",
        icon="mdi:basket-remove",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Swiggy MCP button entities."""
    coordinator: SwiggyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SwiggyMcpButton(coordinator, description, entry) for description in BUTTONS
    )


class SwiggyMcpButton(CoordinatorEntity[SwiggyDataUpdateCoordinator], ButtonEntity):
    """A button that triggers a Swiggy cart action."""

    entity_description: SwiggyButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SwiggyDataUpdateCoordinator,
        description: SwiggyButtonDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_icon = description.icon
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        """Handle button press — clear the Instamart cart."""
        coordinator = self.coordinator
        address_id = coordinator._address_id
        service = self.entity_description.service
        try:
            result = await coordinator.client.flush_cart(
                service=service,
                address_id=address_id,
            )
            msg = result.get("message", "Done") if isinstance(result, dict) else "Done"
            _LOGGER.info("Cart cleared (%s): %s", service, msg)
        except UpdateFailed as err:
            raise HomeAssistantError(f"Clear cart failed: {err}") from err
        await coordinator.async_request_refresh()
