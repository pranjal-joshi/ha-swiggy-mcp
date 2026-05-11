"""Swiggy MCP — Home Assistant Integration entry point.

Wiring order:
  TokenStore → SwiggyAuthManager → SwiggyApiClient → coordinator → entities

Migration: if a config entry still has the old 'bearer_token' key (v0.x),
we trigger reauth immediately so the user goes through the new OAuth flow.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.helpers import llm as ha_llm

from .auth.manager import SwiggyAuthManager
from .auth.store import TokenStore
from .api.client import SwiggyApiClient
from .const import CONF_BEARER_TOKEN, DOMAIN
from .coordinator import SwiggyDataUpdateCoordinator
from .llm.api import SwiggyLLMApi, SWIGGY_LLM_API_ID
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Swiggy MCP from a config entry."""

    # ── Migration guard ───────────────────────────────────────────────────────
    if CONF_BEARER_TOKEN in entry.data:
        _LOGGER.warning(
            "Swiggy MCP: found legacy bearer_token entry — triggering reauth to migrate to OAuth 2.1"
        )
        entry.async_start_reauth(hass)
        return False

    # ── Build auth + API stack ────────────────────────────────────────────────
    from .const import CONF_USE_ADDON
    use_addon = entry.data.get(CONF_USE_ADDON, False)
    if use_addon:
        store = None
        auth = None
    else:
        store = TokenStore(hass, entry)
        auth = SwiggyAuthManager(hass, store)
    client = SwiggyApiClient(hass, auth, entry.data)

    # ── Coordinator ───────────────────────────────────────────────────────────
    coordinator = SwiggyDataUpdateCoordinator(hass, entry, client)
    # Expose entry on coordinator so services can read address_id cleanly
    coordinator._entry = entry  # type: ignore[attr-defined]

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # ── LLM API (optional — requires HA 2024.4+) ────────────────────────────
    try:
        if not any(api.id == SWIGGY_LLM_API_ID for api in ha_llm.async_get_apis(hass)):
            ha_llm.async_register_api(hass, SwiggyLLMApi(hass))
    except Exception:  # noqa: BLE001
        _LOGGER.debug("LLM API registration skipped (HA version too old or API unavailable)")

    # ── Platforms + services ──────────────────────────────────────────────────
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
