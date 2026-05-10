"""Binary sensor entities for Swiggy MCP."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyDataUpdateCoordinator
from .sensor import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Swiggy MCP binary sensors."""
    coordinator: SwiggyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SwiggyOrderActiveSensor(coordinator, entry)])


class SwiggyOrderActiveSensor(
    CoordinatorEntity[SwiggyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor: True when an active Swiggy order is in progress."""

    _attr_has_entity_name = True
    _attr_name = "Order Active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:scooter"

    def __init__(self, coordinator: SwiggyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_order_active"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("order_active"))
