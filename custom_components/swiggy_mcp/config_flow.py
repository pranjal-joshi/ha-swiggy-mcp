"""Config flow for Swiggy MCP — OAuth 2.1 + PKCE + Dynamic Client Registration.

Flow steps:
  user      → triggers DCR (once per HA instance) then redirects to Swiggy login
  oauth     → HA external-step; user logs in at Swiggy, returns with auth code
  address   → user picks default delivery address + poll interval
  reauth    → restarts the oauth step for existing entries

Tokens are NEVER surfaced to the UI — they live in encrypted config entry data.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .auth.pkce import generate_code_challenge, generate_code_verifier
from .auth.store import TokenStore
from .api.client import SwiggyApiClient
from .auth.manager import SwiggyAuthManager
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ADDRESS_ID,
    CONF_CLIENT_ID,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    SWIGGY_AUTH_AUTHORIZE,
    SWIGGY_AUTH_REGISTER,
    SWIGGY_AUTH_TOKEN,
    SWIGGY_AUTH_SCOPES,
)

_LOGGER = logging.getLogger(__name__)

OAUTH_CALLBACK_PATH = "/auth/external/callback"


async def _do_dcr(hass: HomeAssistant, redirect_uri: str) -> str:
    """Dynamic Client Registration — returns a client_id for this HA instance."""
    session = async_get_clientsession(hass)
    payload = {
        "client_name": "Home Assistant Swiggy MCP",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    async with session.post(SWIGGY_AUTH_REGISTER, json=payload) as resp:
        if resp.status not in (200, 201):
            body = await resp.text()
            raise CannotConnect(f"DCR failed ({resp.status}): {body}")
        data = await resp.json()

    client_id = data.get("client_id")
    if not client_id:
        raise CannotConnect("DCR response missing client_id")
    return client_id


async def _exchange_code(
    hass: HomeAssistant,
    code: str,
    verifier: str,
    client_id: str,
    redirect_uri: str,
) -> dict:
    """Exchange an auth code for access_token + refresh_token."""
    session = async_get_clientsession(hass)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    async with session.post(
        SWIGGY_AUTH_TOKEN,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as resp:
        if resp.status in (400, 401):
            body = await resp.text()
            raise InvalidAuth(f"Token exchange failed ({resp.status}): {body}")
        resp.raise_for_status()
        return await resp.json()


class SwiggyMcpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Swiggy MCP config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._client_id: str = ""
        self._redirect_uri: str = ""
        self._verifier: str = ""
        self._state: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._expires_in: int = 3600
        self._addresses: list[dict] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # ── Step: user (entry point) ──────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start OAuth flow: DCR if needed, then redirect to Swiggy login."""
        await self.async_set_unique_id(DOMAIN)
        if not self._reauth_entry:
            self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None or self._reauth_entry:
            try:
                return await self._async_start_oauth()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error starting OAuth")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={"docs_url": "https://github.com/pranjal-joshi/ha-swiggy-mcp"},
            errors=errors,
        )

    async def _async_start_oauth(self) -> FlowResult:
        """Perform DCR + build authorization URL → external step."""
        ha_url = get_url(self.hass, prefer_external=True)
        self._redirect_uri = f"{ha_url}{OAUTH_CALLBACK_PATH}"

        # DCR: reuse stored client_id if the entry already exists
        existing_entry = self.hass.config_entries.async_get_entry(
            self.unique_id or ""
        ) or self._reauth_entry
        if existing_entry:
            self._client_id = existing_entry.data.get(CONF_CLIENT_ID, "")

        if not self._client_id:
            _LOGGER.debug("Performing Dynamic Client Registration")
            self._client_id = await _do_dcr(self.hass, self._redirect_uri)

        # PKCE
        self._verifier = generate_code_verifier()
        challenge = generate_code_challenge(self._verifier)
        self._state = secrets.token_urlsafe(32)

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": self._state,
            "scope": SWIGGY_AUTH_SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{SWIGGY_AUTH_AUTHORIZE}?{urlencode(params)}"

        return self.async_external_step(
            step_id="oauth",
            url=auth_url,
        )

    # ── Step: oauth (callback from Swiggy) ───────────────────────────────────

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the OAuth callback; exchange code for tokens."""
        return self.async_external_step_done(next_step_id="exchange")

    async def async_step_exchange(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Exchange auth code → tokens, then proceed to address selection."""
        errors: dict[str, str] = {}

        # The auth code is delivered via the HA callback view into the flow
        code = (user_input or {}).get("code", "")
        if not code:
            # HA injects it via the external step mechanism
            code = self.hass.data.get(DOMAIN, {}).get("oauth_code_" + self.flow_id, "")

        try:
            token_data = await _exchange_code(
                self.hass,
                code=code,
                verifier=self._verifier,
                client_id=self._client_id,
                redirect_uri=self._redirect_uri,
            )
        except InvalidAuth:
            errors["base"] = "invalid_auth"
            return self.async_show_form(step_id="exchange", data_schema=vol.Schema({}), errors=errors)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Token exchange error")
            errors["base"] = "unknown"
            return self.async_show_form(step_id="exchange", data_schema=vol.Schema({}), errors=errors)

        self._access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token", "")
        self._expires_in = int(token_data.get("expires_in", 3600))

        # Fetch addresses to present picker
        try:
            import time  # noqa: PLC0415
            tmp_store_data = {
                CONF_ACCESS_TOKEN: self._access_token,
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_TOKEN_EXPIRES_AT: time.time() + self._expires_in,
                CONF_CLIENT_ID: self._client_id,
            }
            # Build a temporary thin client to list addresses
            session = async_get_clientsession(self.hass)
            from homeassistant.helpers.aiohttp_client import async_get_clientsession  # noqa: PLC0415
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            import json  # noqa: PLC0415
            from .const import SWIGGY_FOOD_URL  # noqa: PLC0415
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_addresses", "arguments": {}},
                "id": 1,
            }
            async with session.post(SWIGGY_FOOD_URL, json=payload, headers=headers) as resp:
                raw = await resp.json()
            content = raw.get("result", {}).get("content", [])
            if content:
                text = content[0].get("text", "{}")
                parsed = json.loads(text) if isinstance(text, str) else text
                self._addresses = parsed.get("data", {}).get("addresses", [])
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not fetch addresses during setup — will use free-text entry")
            self._addresses = []

        return await self.async_step_address()

    # ── Step: address ─────────────────────────────────────────────────────────

    async def async_step_address(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let user pick default delivery address + poll interval."""
        if user_input is not None:
            import time  # noqa: PLC0415
            entry_data = {
                CONF_CLIENT_ID: self._client_id,
                CONF_ACCESS_TOKEN: self._access_token,
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_TOKEN_EXPIRES_AT: time.time() + self._expires_in,
                CONF_ADDRESS_ID: user_input[CONF_ADDRESS_ID],
                CONF_POLL_INTERVAL: user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            }

            if self._reauth_entry:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=entry_data
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            return self.async_create_entry(title="Swiggy MCP", data=entry_data)

        if self._addresses:
            addr_options = {
                a["id"]: a.get("label") or a.get("address", a["id"])
                for a in self._addresses
            }
            addr_validator = vol.In(addr_options)
        else:
            addr_validator = str

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS_ID): addr_validator,
                vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
                    int, vol.Range(min=10, max=300)
                ),
            }
        )
        return self.async_show_form(step_id="address", data_schema=schema)

    # ── Step: reauth ──────────────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Triggered by ConfigEntryAuthFailed — restart OAuth for existing entry."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()


class CannotConnect(HomeAssistantError):
    """Cannot reach Swiggy servers."""


class InvalidAuth(HomeAssistantError):
    """Invalid/expired OAuth code or tokens."""
