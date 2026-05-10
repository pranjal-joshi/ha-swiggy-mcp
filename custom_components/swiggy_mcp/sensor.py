"""Sensor entities for Swiggy MCP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyDataUpdateCoordinator


@dataclass(frozen=True)
class SwiggyMcpSensorDescription(SensorEntityDescription):
    """Describe a Swiggy MCP sensor."""

    coordinator_key: str = ""
    unit: str | None = None
    icon: str = "mdi:food"


SENSORS: tuple[SwiggyMcpSensorDescription, ...] = (
    SwiggyMcpSensorDescription(
        key="order_status",
        coordinator_key="order_status",
        name="Swiggy Order Status",
        icon="mdi:truck-delivery",
    ),
    SwiggyMcpSensorDescription(
        key="eta",
        coordinator_key="eta",
        name="Swiggy ETA",
        icon="mdi:clock-fast",
        native_unit_of_measurement="min",
    ),
    SwiggyMcpSensorDescription(
        key="restaurant",
        coordinator_key="restaurant",
        name="Swiggy Restaurant",
        icon="mdi:silverware-fork-knife",
    ),
    SwiggyMcpSensorDescription(
        key="billed_amount",
        coordinator_key="billed_amount",
        name="Swiggy Billed Amount",
        icon="mdi:currency-inr",
        native_unit_of_measurement="₹",
    ),
    SwiggyMcpSensorDescription(
        key="last_order_items",
        coordinator_key="items",
        name="Swiggy Last Order Items",
        icon="mdi:food-variant",
    ),
    SwiggyMcpSensorDescription(
        key="order_id",
        coordinator_key="order_id",
        name="Swiggy Order ID",
        icon="mdi:identifier",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Swiggy MCP sensors."""
    coordinator: SwiggyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SwiggyMcpSensor(coordinator, description) for description in SENSORS
    )


class SwiggyMcpSensor(CoordinatorEntity[SwiggyDataUpdateCoordinator], SensorEntity):
    """A sensor that reads from the Swiggy coordinator."""

    entity_description: SwiggyMcpSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SwiggyDataUpdateCoordinator,
        description: SwiggyMcpSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"
        self._attr_icon = description.icon

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.get(self.entity_description.coordinator_key)
