# Swiggy MCP for Home Assistant

[![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/pranjal-joshi/ha-swiggy-mcp)](https://github.com/pranjal-joshi/ha-swiggy-mcp/releases)
[![Validate](https://github.com/pranjal-joshi/ha-swiggy-mcp/actions/workflows/validate.yml/badge.svg)](https://github.com/pranjal-joshi/ha-swiggy-mcp/actions/workflows/validate.yml)

Bring Swiggy Food, Instamart, and Dineout into Home Assistant — sensors, automations, voice commands, and more.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Home Assistant                                             │
│                                                             │
│  [Swiggy MCP Proxy Add-on]  ←── port 9584 ───────────────  │
│    • OAuth 2.1 + PKCE (code-paste flow)                     │
│    • Uses localhost redirect URI (Swiggy whitelisted ✓)     │
│    • Stores tokens in /data/ (persistent volume)            │
│    • Auto refresh, multi-arch Docker build                  │
│         ↕                                                   │
│  [swiggy_mcp HACS Integration]                             │
│    • Sensors, Services, Events                              │
│    • Talks to add-on at http://homeassistant.local:9584     │
│    • No tokens needed — add-on handles auth                 │
│         ↕                                                   │
│  [HA Automations / Voice / Assist]                          │
└─────────────────────────────────────────────────────────────┘
         ↕ (proxied with Bearer token)
   mcp.swiggy.com  (food / instamart / dineout)
```

**Why the add-on?** Swiggy's OAuth server only whitelists specific redirect URIs. `http://localhost` and `http://localhost/callback` are on that list — HA's external callback URL is not. The add-on runs on your HA host, performs OAuth using a `localhost` redirect, and proxies all MCP calls with the stored token. The HACS integration simply talks to the add-on endpoint, no OAuth complexity needed.

---

## Features

| Feature | Add-on mode | Direct mode |
|---|---|---|
| Food order tracking (status, ETA) | ✅ | ✅ |
| Instamart / Dineout support | ✅ | ✅ |
| OAuth without whitelist approval | ✅ | ❌ |
| Sensors & binary sensors | ✅ | ✅ |
| HA Services (reorder, cart) | ✅ | ✅ |
| Voice / Assist integration | ✅ | ✅ |
| Auto token refresh | ✅ | ✅ |

---

## Installation

### Step 1 — Add this repository as an HA Add-on source

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the ⋮ menu → **Repositories**
3. Add: `https://github.com/pranjal-joshi/ha-swiggy-mcp`
4. Find **Swiggy MCP Proxy** and install it
5. Start the add-on and open its Web UI

### Step 2 — Log in with Swiggy (code-paste flow)

1. Open the add-on UI from the sidebar (or via **Open Web UI**)
2. Click **Login with Swiggy**
3. A Swiggy login page opens in your browser
4. After logging in, your browser redirects to `http://localhost/callback?code=...` — this page won't load, that's expected
5. **Copy the full URL** from your browser's address bar
6. Paste it into the add-on UI and click **Submit**
7. The UI will show ✅ Authenticated

### Step 3 — Install the HACS integration

1. In HACS, add this repository as a custom integration source
2. Search for **Swiggy MCP** and install
3. Go to **Settings → Integrations → Add Integration → Swiggy MCP**
4. Select **Use Swiggy MCP Proxy add-on (recommended)**
5. Enter the add-on URL (default: `http://homeassistant.local:9584`)
6. Done — sensors appear automatically

---

## Sensors

| Entity | Description |
|---|---|
| `sensor.swiggy_order_status` | Current order status (Ordered / Preparing / Out for Delivery / Delivered) |
| `sensor.swiggy_eta` | Estimated delivery time (minutes) |
| `sensor.swiggy_restaurant` | Restaurant name for active order |
| `sensor.swiggy_billed_amount` | Order total (₹) |
| `sensor.swiggy_last_order_items` | Comma-separated item names |
| `binary_sensor.swiggy_order_active` | `on` when an active order exists |

---

## Services

### `swiggy_mcp.reorder_last`
Re-places the most recent order.
```yaml
service: swiggy_mcp.reorder_last
```

### `swiggy_mcp.add_to_cart`
```yaml
service: swiggy_mcp.add_to_cart
data:
  service: instamart   # food | instamart
  item: "Maggi Noodles 70g"
  quantity: 2
```

### `swiggy_mcp.clear_cart`
```yaml
service: swiggy_mcp.clear_cart
data:
  service: food   # food | instamart
```

---

## Automation Examples

### Notify when order is out for delivery
```yaml
automation:
  trigger:
    - platform: event
      event_type: swiggy_mcp_out_for_delivery
  action:
    - service: notify.mobile_app
      data:
        title: "🛵 Order on the way!"
        message: "Your Swiggy order is out for delivery."
```

### Reorder last order with a voice command
```yaml
intent_script:
  SwiggyReorder:
    speech:
      text: "Reordering your last Swiggy order."
    action:
      service: swiggy_mcp.reorder_last
```

---

## Troubleshooting

**Add-on UI shows "Not authenticated"** — Re-open the add-on UI and repeat the code-paste flow.

**Integration shows "Cannot connect"** — Make sure the add-on is started and the URL is correct (check port 9584).

**Token expired** — The add-on auto-refreshes tokens. If it fails, log out from the add-on UI and re-authenticate.

**Direct mode whitelist error** — Use add-on mode instead. The add-on uses `localhost` redirect URIs which are whitelisted by Swiggy by default.

---

## Contributing

PRs welcome. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design.

---

## License

MIT
