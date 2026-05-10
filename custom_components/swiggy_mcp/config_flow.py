"""Config flow for Swiggy MCP — supports two modes:

  1. Add-on mode (recommended): Integration talks to the local Swiggy MCP Proxy
     add-on (http://homeassistant.local:9584). The add-on handles OAuth via a
     code-paste flow using localhost redirect URIs (whitelisted by Swiggy).

  2. Direct mode (fallback): Integration connects directly to mcp.swiggy.com
     via OAuth 2.1 + PKCE. Requires Swiggy's external redirect URI whitelist
     approval (may show a "not whitelisted" error for new clients).

Flow steps:
  user    → mode selection (add-on vs direct)
  addon   → ask for add-on URL → create entry
  oauth   → DCR + PKCE redirect (direct mode only)
  address → pick address + poll interval
  reauth  → restarts from mode step for existing entries
"""
from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .auth.pkce import generate_code_challenge, generate_code_verifier
from .api.client import SwiggyApiClient, _safe_mcp_text_to_data
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ADDRESS_ID,
    CONF_ADDON_URL,
    CONF_CLIENT_ID,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    CONF_USE_ADDON,
    DEFAULT_ADDON_URL,
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
    """Dynamic Client Registration — returns a client_id."""
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
        self._use_addon: bool = True
        self._addon_url: str = DEFAULT_ADDON_URL
        self._client_id: str = ""
        self._redirect_uri: str = ""
        self._verifier: str = ""
        self._state: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._expires_in: int = 3600
        self._addresses: list[dict] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # ── Step: user — mode selection ──────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask user whether to use the add-on or connect directly to Swiggy."""
        await self.async_set_unique_id(DOMAIN)
        if not self._reauth_entry:
            self._abort_if_unique_id_configured()

        if user_input is not None:
            self._use_addon = user_input[CONF_USE_ADDON]
            if self._use_addon:
                return await self.async_step_addon()
            else:
                try:
                    return await self._async_start_oauth()
                except CannotConnect:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._mode_schema(),
                        errors={"base": "cannot_connect"},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self._mode_schema(),
            description_placeholders={"docs_url": "https://github.com/pranjal-joshi/ha-swiggy-mcp"},
        )

    def _mode_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_USE_ADDON, default=True): bool,
            }
        )

    # ── Step: addon — confirm add-on URL ─────────────────────────────────────

    async def async_step_addon(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the add-on base URL and create a config entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            addon_url = user_input[CONF_ADDON_URL].rstrip("/")
            # Quick connectivity check
            try:
                session = async_get_clientsession(self.hass)
                async with session.get(
                    f"{addon_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

            if not errors:
                entry_data = {
                    CONF_USE_ADDON: True,
                    CONF_ADDON_URL: addon_url,
                    CONF_POLL_INTERVAL: user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                }
                if self._reauth_entry:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=entry_data
                    )
                    await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                return self.async_create_entry(title="Swiggy MCP (Add-on)", data=entry_data)

        return self.async_show_form(
            step_id="addon",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDON_URL, default=DEFAULT_ADDON_URL): str,
                    vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
                        int, vol.Range(min=10, max=300)
                    ),
                }
            ),
            description_placeholders={"default_url": DEFAULT_ADDON_URL},
            errors=errors,
        )

    # ── OAuth (direct mode) ──────────────────────────────────────────────────

    async def _async_start_oauth(self) -> FlowResult:
        ha_url = get_url(self.hass, prefer_external=True)
        self._redirect_uri = f"{ha_url}{OAUTH_CALLBACK_PATH}"

        existing_entry = self._reauth_entry
        if existing_entry:
            self._client_id = existing_entry.data.get(CONF_CLIENT_ID, "")

        if not self._client_id:
            _LOGGER.debug("Performing Dynamic Client Registration")
            self._client_id = await _do_dcr(self.hass, self._redirect_uri)

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

        return self.async_external_step(step_id="oauth", url=auth_url)

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_external_step_done(next_step_id="exchange")

    async def async_step_exchange(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        import json
        import time

        errors: dict[str, str] = {}
        code = (user_input or {}).get("code", "")
        if not code:
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
        except Exception:
            _LOGGER.exception("Token exchange error")
            errors["base"] = "unknown"
            return self.async_show_form(step_id="exchange", data_schema=vol.Schema({}), errors=errors)

        self._access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token", "")
        self._expires_in = int(token_data.get("expires_in", 3600))

        # Fetch saved addresses
        try:
            session = async_get_clientsession(self.hass)
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            from .const import SWIGGY_FOOD_URL
            mcp_payload = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "get_addresses", "arguments": {}}, "id": 1}
            async with session.post(SWIGGY_FOOD_URL, json=mcp_payload, headers=headers) as resp:
                raw_text = await resp.text()
            try:
                raw = json.loads(raw_text)
            except json.JSONDecodeError:
                _LOGGER.warning("get_addresses returned non-JSON: %r", raw_text[:200])
                raw = {}
            content = (raw.get("result") or {}).get("content") or []
            if content:
                parsed = _safe_mcp_text_to_data(content[0].get("text"))
                self._addresses = (parsed or {}).get("data", {}).get("addresses", []) if isinstance(parsed, dict) else []
        except Exception:
            _LOGGER.warning("Could not fetch addresses during setup")
            self._addresses = []

        return await self.async_step_address()

    # ── Step: address (direct mode) ──────────────────────────────────────────

    async def async_step_address(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        import time

        if user_input is not None:
            entry_data = {
                CONF_USE_ADDON: False,
                CONF_CLIENT_ID: self._client_id,
                CONF_ACCESS_TOKEN: self._access_token,
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_TOKEN_EXPIRES_AT: time.time() + self._expires_in,
                CONF_ADDRESS_ID: user_input[CONF_ADDRESS_ID],
                CONF_POLL_INTERVAL: user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            }
            if self._reauth_entry:
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=entry_data)
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

        return self.async_show_form(
            step_id="address",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS_ID): addr_validator,
                    vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
                        int, vol.Range(min=10, max=300)
                    ),
                }
            ),
        )

    # ── Reauth ───────────────────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()


class CannotConnect(HomeAssistantError):
    """Cannot reach Swiggy servers."""


class InvalidAuth(HomeAssistantError):
    """Invalid/expired OAuth code or tokens."""
