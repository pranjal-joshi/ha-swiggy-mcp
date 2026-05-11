"""Sensor entities for Swiggy MCP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwiggyDataUpdateCoordinator


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
    SwiggyMcpSensorDescription(
        key="cart_items",
        coordinator_key="cart_items",
        name="Swiggy Food Cart Items",
        icon="mdi:cart-outline",
    ),
    SwiggyMcpSensorDescription(
        key="cart_total",
        coordinator_key="cart_total",
        name="Swiggy Food Cart Total",
        icon="mdi:currency-inr",
        native_unit_of_measurement="₹",
    ),
    SwiggyMcpSensorDescription(
        key="instamart_cart_items",
        coordinator_key="instamart_cart_items",
        name="Swiggy Instamart Cart Items",
        icon="mdi:basket-outline",
    ),
    SwiggyMcpSensorDescription(
        key="instamart_cart_total",
        coordinator_key="instamart_cart_total",
        name="Swiggy Instamart Cart Total",
        icon="mdi:currency-inr",
        native_unit_of_measurement="₹",
    ),
    SwiggyMcpSensorDescription(
        key="address",
        coordinator_key="address",
        name="Swiggy Delivery Address",
        icon="mdi:map-marker",
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
        SwiggyMcpSensor(coordinator, description, entry) for description in SENSORS
    )


class SwiggyMcpSensor(CoordinatorEntity[SwiggyDataUpdateCoordinator], SensorEntity):
    """A sensor that reads from the Swiggy coordinator."""

    entity_description: SwiggyMcpSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SwiggyDataUpdateCoordinator,
        description: SwiggyMcpSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_icon = description.icon
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.get(self.entity_description.coordinator_key)
