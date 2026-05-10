"""OAuth 2.1 + PKCE + Dynamic Client Registration for Swiggy MCP.

Uses the code-paste flow:
  1. Add-on performs DCR to get a client_id (stored in /data/tokens.json)
  2. Builds an authorization URL with PKCE (redirect_uri = http://localhost/callback)
  3. User opens URL in browser, logs in to Swiggy
  4. Swiggy redirects to http://localhost/callback?code=XXX (may fail to load for remote HA)
  5. User copies the full redirect URL from browser address bar
  6. User pastes URL into add-on UI → add-on extracts code, exchanges for tokens
"""
import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode, urlparse, parse_qs

import aiohttp

_LOGGER = logging.getLogger(__name__)

SWIGGY_DCR_URL = "https://mcp.swiggy.com/auth/register"
SWIGGY_AUTH_URL = "https://mcp.swiggy.com/auth/authorize"
SWIGGY_TOKEN_URL = "https://mcp.swiggy.com/auth/token"
# localhost is whitelisted by Swiggy — no approval needed
REDIRECT_URI = "http://localhost/callback"
SCOPES = "openid profile email offline_access"


def _generate_verifier() -> str:
    return secrets.token_urlsafe(64)


def _generate_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def do_dcr(session: aiohttp.ClientSession) -> str:
    """Dynamic Client Registration — returns client_id."""
    payload = {
        "client_name": "Swiggy MCP HA Proxy",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    async with session.post(SWIGGY_DCR_URL, json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json()
    return data["client_id"]


def build_auth_url(client_id: str, verifier: str, state: str) -> str:
    challenge = _generate_challenge(verifier)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{SWIGGY_AUTH_URL}?{urlencode(params)}"


def extract_code_from_url(pasted_url: str) -> tuple:
    """Extract code and state from the pasted redirect URL."""
    pasted_url = pasted_url.strip()
    parsed = urlparse(pasted_url)
    qs = parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    state = qs.get("state", [None])[0]
    if not code:
        # If they pasted just the code directly (no URL structure)
        if "?" not in pasted_url and "&" not in pasted_url and "=" not in pasted_url:
            return pasted_url, ""
    return code, state


async def exchange_code(
    session: aiohttp.ClientSession,
    code: str,
    verifier: str,
    client_id: str,
) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
    }
    async with session.post(
        SWIGGY_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as resp:
        if resp.status in (400, 401):
            body = await resp.text()
            raise ValueError(f"Token exchange failed ({resp.status}): {body}")
        resp.raise_for_status()
        return await resp.json()


async def refresh_access_token(
    session: aiohttp.ClientSession,
    refresh_token: str,
    client_id: str,
) -> dict:
    """Refresh access token using refresh_token."""
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    async with session.post(
        SWIGGY_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as resp:
        resp.raise_for_status()
        return await resp.json()
