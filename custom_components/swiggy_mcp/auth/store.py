"""Token store — reads/writes OAuth tokens from/to HA config entry data.

HA encrypts config entry data at rest in .storage/core.config_entries.
We never expose raw tokens outside this module.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
)

if TYPE_CHECKING:
    pass


class TokenStore:
    """Thin wrapper around config entry data for token persistence."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self) -> dict:
        """Return current token dict (may be empty for a fresh entry)."""
        data = self._entry.data
        return {
            CONF_ACCESS_TOKEN: data.get(CONF_ACCESS_TOKEN, ""),
            CONF_REFRESH_TOKEN: data.get(CONF_REFRESH_TOKEN, ""),
            CONF_TOKEN_EXPIRES_AT: data.get(CONF_TOKEN_EXPIRES_AT, 0.0),
        }

    def get_client_id(self) -> str | None:
        return self._entry.data.get(CONF_CLIENT_ID)

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(
        self,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        client_id: str | None = None,
    ) -> None:
        """Persist new tokens; merges with existing entry data."""
        new_data = {
            **self._entry.data,
            CONF_ACCESS_TOKEN: access_token,
            CONF_REFRESH_TOKEN: refresh_token,
            CONF_TOKEN_EXPIRES_AT: time.time() + expires_in,
        }
        if client_id is not None:
            new_data[CONF_CLIENT_ID] = client_id
        self._hass.config_entries.async_update_entry(self._entry, data=new_data)

    def clear_tokens(self) -> None:
        """Wipe tokens so the next call forces a reauth."""
        new_data = {
            k: v
            for k, v in self._entry.data.items()
            if k not in (CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_TOKEN_EXPIRES_AT)
        }
        self._hass.config_entries.async_update_entry(self._entry, data=new_data)
