# Swiggy MCP for Home Assistant — Architecture

## Overview

This repository contains two components:

1. **`ha-swiggy-mcp-addon/`** — A Home Assistant add-on that runs a local HTTP proxy server. It performs OAuth 2.1 + PKCE authentication with Swiggy using a `localhost` redirect URI (whitelisted by Swiggy), stores tokens persistently in `/data/`, auto-refreshes them, and proxies all MCP calls to `mcp.swiggy.com` with the stored Bearer token.

2. **`custom_components/swiggy_mcp/`** — A HACS custom integration that exposes Swiggy order data as HA sensors and provides HA services. In **add-on mode** it talks to the local proxy; in **direct mode** it connects to Swiggy directly (requires Swiggy whitelist approval for the HA callback URL).

---

## Why the Add-on?

Swiggy's OAuth server validates redirect URIs against a fixed whitelist:

```
http://localhost
http://localhost/callback
http://127.0.0.1
http://127.0.0.1/callback
https://claude.ai/api/mcp/auth_callback
https://chatgpt.com/connector_platform_oauth_redirect
...
```

Home Assistant's OAuth callback (`https://your-ha-instance/auth/external/callback`) is **not** on this list for new/unregistered clients, causing a "not whitelisted" error during setup.

The add-on solves this by running directly on the HA host and using `http://localhost/callback` as the redirect URI — which is always whitelisted. The user pastes the redirect URL into the add-on's web UI (the "code-paste flow"), the add-on exchanges the code for tokens, and stores them locally. The integration then simply POSTs to the add-on's HTTP endpoints.

---

## Add-on Architecture

```
ha-swiggy-mcp-addon/
├── config.yaml        # HA add-on metadata (port 9584, ingress, arch)
├── build.yaml         # Multi-arch base images (amd64/aarch64/armv7)
├── Dockerfile         # Alpine Python 3.12, installs aiohttp
├── requirements.txt   # aiohttp, cryptography
├── logo.png / icon.png
└── src/
    ├── server.py      # aiohttp app, all HTTP routes
    ├── oauth.py       # DCR, PKCE, auth URL builder, code extractor, token exchange
    ├── proxy.py       # Token injection, auto-refresh, Swiggy endpoint routing
    └── storage.py     # /data/tokens.json read/write/clear
```

### Add-on Routes

| Method | Path | Description |
|---|---|---|
| GET | `/` | Dashboard (auth status, login/logout button) |
| GET | `/auth/start` | DCR + builds auth URL, shows code-paste form |
| POST | `/auth/submit` | Extracts code from pasted URL, exchanges for tokens |
| GET | `/auth/logout` | Clears stored tokens |
| GET | `/health` | `{"status":"ok","authenticated":true/false}` |
| POST | `/food` | Proxy → `https://mcp.swiggy.com/food` |
| POST | `/instamart` | Proxy → `https://mcp.swiggy.com/im` |
| POST | `/im` | Proxy → `https://mcp.swiggy.com/im` |
| POST | `/dineout` | Proxy → `https://mcp.swiggy.com/dineout` |

### OAuth Code-Paste Flow

```
User clicks "Login with Swiggy"
  → Add-on: DCR → gets client_id (stored in /data/)
  → Add-on: builds PKCE auth URL (redirect_uri=http://localhost/callback)
  → User: opens URL, logs in at mcp.swiggy.com
  → Swiggy: redirects browser to http://localhost/callback?code=XXX
  → Browser: fails to load (localhost on remote HA)
  → User: copies URL from address bar, pastes into add-on UI
  → Add-on: extracts code, exchanges for access+refresh tokens (PKCE)
  → Add-on: stores tokens in /data/tokens.json
  → Done ✅
```

---

## Integration Architecture

```
custom_components/swiggy_mcp/
├── __init__.py         # Entry setup, migration guard, service registration
├── config_flow.py      # Mode selection → addon step OR OAuth → address step
├── coordinator.py      # DataUpdateCoordinator, polls Swiggy, fires HA events
├── sensor.py           # Sensor entities
├── binary_sensor.py    # Binary sensor entities
├── services.py         # reorder_last, add_to_cart, clear_cart
├── services.yaml       # Service schemas
├── const.py            # Constants (endpoints, config keys, defaults)
├── manifest.json       # HA manifest
├── translations/en.json
├── DOCS.md
├── auth/
│   ├── pkce.py         # PKCE code verifier/challenge (direct mode)
│   ├── manager.py      # Token lifecycle manager (direct mode)
│   └── store.py        # Encrypted token storage in config entry (direct mode)
└── api/
    └── client.py       # HTTP client — add-on mode or direct mode
```

### Config Entry Modes

**Add-on mode** (`use_addon: true`):
```json
{
  "use_addon": true,
  "addon_url": "http://homeassistant.local:9584",
  "poll_interval": 30
}
```
No tokens in the config entry. Auth is fully handled by the add-on.

**Direct mode** (`use_addon: false`):
```json
{
  "use_addon": false,
  "client_id": "...",
  "access_token": "...",
  "refresh_token": "...",
  "token_expires_at": 1234567890.0,
  "address_id": "addr_xxx",
  "poll_interval": 30
}
```

### API Client Routing

`SwiggyApiClient._resolve_url(service)`:
- Add-on mode: `{addon_url}/{service}` (e.g., `http://homeassistant.local:9584/food`)
- Direct mode: maps to `https://mcp.swiggy.com/food`, `.../im`, `.../dineout`

In add-on mode, no `Authorization` header is sent — the add-on injects it. In direct mode, the client fetches a token from `SwiggyAuthManager` and injects it.

---

## CI/CD

| Workflow | Trigger | Action |
|---|---|---|
| `validate.yml` | PR / push | hassfest + HACS validation |
| `release.yml` | Tag `v*.*.*` | GitHub Release + manifest version bump |
| `addon-build.yml` | Tag `addon-v*.*.*` | Multi-arch Docker build → GHCR push |

### Add-on Image Naming
```
ghcr.io/pranjal-joshi/ha-swiggy-mcp-addon-amd64:0.1.0
ghcr.io/pranjal-joshi/ha-swiggy-mcp-addon-aarch64:0.1.0
ghcr.io/pranjal-joshi/ha-swiggy-mcp-addon-armv7:0.1.0
```
