"""SwiggyAuthManager — token lifecycle: get, refresh, reauth trigger.

This is the ONLY place in the integration that touches OAuth tokens.
Every other module calls async_get_access_token() and gets a plain string.
"""
from __future__ import annotations

import logging
import time

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    CONF_REFRESH_TOKEN,
    SWIGGY_AUTH_TOKEN,
    TOKEN_REFRESH_BUFFER_SECONDS,
)
from .store import TokenStore

_LOGGER = logging.getLogger(__name__)


class SwiggyAuthManager:
    """Manages Swiggy OAuth 2.1 token lifecycle for one config entry."""

    def __init__(self, hass, store: TokenStore) -> None:
        self._hass = hass
        self._store = store

    # ── Public API ────────────────────────────────────────────────────────────

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing silently if near expiry."""
        tokens = self._store.get()
        expires_at: float = tokens.get("token_expires_at", 0.0)

        if tokens.get("access_token") and time.time() < expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
            return tokens["access_token"]

        _LOGGER.debug("Access token near/past expiry — refreshing")
        return await self._async_refresh()

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _async_refresh(self) -> str:
        """Exchange refresh_token for a new token pair.

        Raises ConfigEntryAuthFailed (→ HA reauth flow) if Swiggy rejects the
        refresh token (400 / 401).  Any other transport error propagates as-is.
        """
        tokens = self._store.get()
        refresh_token = tokens.get(CONF_REFRESH_TOKEN, "")
        client_id = self._store.get_client_id() or ""

        if not refresh_token:
            _LOGGER.warning("No refresh token available — triggering reauth")
            self._store.clear_tokens()
            raise ConfigEntryAuthFailed("No refresh token — please re-authenticate")

        session = async_get_clientsession(self._hass)
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }

        async with session.post(
            SWIGGY_AUTH_TOKEN,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status in (400, 401):
                body = await resp.text()
                _LOGGER.error("Refresh rejected (%s): %s", resp.status, body)
                self._store.clear_tokens()
                raise ConfigEntryAuthFailed(
                    f"Swiggy token refresh failed ({resp.status}) — please re-authenticate"
                )

            resp.raise_for_status()
            data = await resp.json()

        access_token = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)  # honour rotation
        expires_in = int(data.get("expires_in", 3600))

        self._store.save(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_in=expires_in,
        )
        _LOGGER.debug("Token refreshed successfully, expires_in=%d", expires_in)
        return access_token
