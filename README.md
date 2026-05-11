<div align="center">
  <img src="./custom_components/swiggy_mcp/brand/logo.png"
       srcset="./custom_components/swiggy_mcp/brand/logo.png 1x, ./custom_components/swiggy_mcp/brand/logo@2x.png 2x"
       alt="Swiggy MCP — Home Assistant Integration" width="256" />

  <h1>Swiggy MCP — Home Assistant Integration</h1>

  <p><strong>Automate grocery restocking & track deliveries — right from your smart home.</strong><br/>
  A HACS custom integration + local add-on powered by the official <a href="https://mcp.swiggy.com">Swiggy MCP servers</a>.</p>

  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/releases"><img src="https://img.shields.io/github/v/release/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge&color=FC8019&label=Release" alt="Release"/></a>
  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/stargazers"><img src="https://img.shields.io/github/stars/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge&color=FC8019" alt="Stars"/></a>
  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/issues"><img src="https://img.shields.io/github/issues/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge" alt="Issues"/></a>
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge" alt="License"/></a>
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-orange?style=for-the-badge&logo=HomeAssistantCommunityStore" alt="HACS"/></a>
  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/actions/workflows/validate.yml"><img src="https://img.shields.io/github/actions/workflow/status/pranjal-joshi/ha-swiggy-mcp/validate.yml?style=for-the-badge&label=CI" alt="CI"/></a>

  <br/><br/>

  > ⚠️ **Early Development / POC** — Not yet in the HACS default store. Add via custom repository URL below.
  >
  > 🛒 **`main` branch**: Swiggy **Instamart** (grocery) only.
  > 🍕 **`food` branch**: Food ordering (work in progress).

</div>

---

## 🛒 What is this?

**ha-swiggy-mcp** brings Swiggy Instamart into Home Assistant as a first-class citizen. Track your grocery orders, monitor your cart, automate restocking, and get delivery notifications — all from HA automations and dashboards.

| Component | What it does |
|---|---|
| **Swiggy MCP Proxy Add-on** | Runs on your HA host. Handles OAuth via a simple code-paste flow, stores tokens securely, and proxies all MCP calls to Swiggy. |
| **swiggy_mcp HACS Integration** | Exposes live sensors, HA services, and events. Talks to the local add-on — no tokens, no OAuth complexity. |

See [ARCHITECTURE.md](./ARCHITECTURE.md) for full design decisions and diagrams.

---

## ✨ What you get

### 📊 Sensors

| Entity | Example state |
|---|---|
| `sensor.instamart_order_status` | `Out for Delivery` |
| `sensor.instamart_eta` | `8` (min) |
| `sensor.instamart_store` | `Swiggy Instamart` |
| `sensor.instamart_billed_amount` | `249` (₹) |
| `sensor.instamart_order_items` | `Maggi, Milk, Bread` |
| `sensor.instamart_order_id` | `ORD789012` |
| `sensor.instamart_cart_items` | `Eggs x12, Butter` |
| `sensor.instamart_cart_total` | `195` (₹) |
| `sensor.delivery_address` | `42, Sunshine Apartments, MG Road, Bengaluru` |
| `binary_sensor.instamart_order_active` | `on` / `off` |

### ⚡ Services

| Service | What it does |
|---|---|
| `swiggy_mcp.add_to_cart` | Adds an item to your Instamart cart by name |
| `swiggy_mcp.clear_cart` | Clears your Instamart cart |

### 🎛️ Controls

| Entity | What it does |
|---|---|
| `button.instamart_clear_cart` | One-tap cart clear from dashboard |
| `select.delivery_address` | Switch delivery address from HA UI |

### 🔔 Events

| Event | Fires when |
|---|---|
| `swiggy_mcp_instamart_out_for_delivery` | Order is picked up by delivery partner |
| `swiggy_mcp_instamart_order_delivered` | Order is delivered |

---

## 📦 Installation

### Step 1 — Add the repository as an HA Add-on source

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add: `https://github.com/pranjal-joshi/ha-swiggy-mcp`
3. Find **Swiggy MCP Proxy** and install it
4. Start the add-on and click **Open Web UI**

### Step 2 — Log in with Swiggy (code-paste flow)

1. In the add-on UI click **Login with Swiggy**
2. A Swiggy OAuth page opens in your browser — log in and approve
3. Your browser will try to redirect to `http://localhost:9584/callback?code=…` — **this page won't load, that's expected**
4. **Copy the full URL** from your browser's address bar (it contains `?code=...`)
5. Paste it into the add-on UI and click **Submit**
6. The UI shows ✅ Authenticated

### Step 3 — Install the HACS integration

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pranjal-joshi&repository=ha-swiggy-mcp&category=integration)

Or manually:
1. HACS → Integrations → ⋮ → **Custom repositories**
2. URL: `https://github.com/pranjal-joshi/ha-swiggy-mcp` · Category: **Integration**
3. Download and restart Home Assistant

### Step 4 — Add the integration

1. **Settings → Devices & Services → + Add Integration**
2. Search **Swiggy MCP** and click it
3. Select **Use Swiggy MCP Proxy add-on (recommended)**
4. Enter the add-on URL (default: `http://homeassistant.local:9584`)
5. Done — sensors appear immediately

> **No tokens to copy in HA.** The add-on owns all auth. The integration just reads data from the add-on endpoint.

---

## 🤖 Automation Examples

**Turn on the porch light when your delivery is near:**
```yaml
alias: Porch light when Instamart is near
trigger:
  - platform: numeric_state
    entity_id: sensor.instamart_eta
    below: 5
condition:
  - condition: state
    entity_id: binary_sensor.instamart_order_active
    state: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.porch
mode: single
```

**TTS announcement when groceries arrive:**
```yaml
alias: Announce Instamart delivery
trigger:
  - platform: event
    event_type: swiggy_mcp_instamart_order_delivered
action:
  - service: tts.speak
    data:
      message: "Your Instamart groceries have been delivered!"
      media_player_entity_id: media_player.living_room_speaker
mode: single
```

**Smart pantry restocking with a weight sensor:**
```yaml
alias: Auto-reorder rice when running low
trigger:
  - platform: numeric_state
    entity_id: sensor.rice_container_weight
    below: 1
    for:
      minutes: 5
condition:
  - condition: state
    entity_id: input_boolean.swiggy_auto_restock
    state: "on"
action:
  - service: swiggy_mcp.add_to_cart
    data:
      query: "India Gate Basmati Rice 5kg"
      quantity: 1
  - service: notify.mobile_app
    data:
      title: "🛒 Rice running low!"
      message: "Added to your Instamart cart. Review and checkout in Swiggy."
mode: single
```

---

## ⚠️ Important Limitations

- **COD only** — Instamart orders placed via HA services are Cash on Delivery. Always review your cart in the Swiggy app before checkout.
- **Close the Swiggy app** while the integration is active — running both simultaneously causes session conflicts on Swiggy's side.
- **Food ordering** is in the [`food` branch](https://github.com/pranjal-joshi/ha-swiggy-mcp/tree/food) (work in progress — not yet stable).

---

## 🗺️ Roadmap

- [x] Project planning & architecture
- [x] Logo & branding
- [x] HACS custom integration scaffold
- [x] OAuth 2.1 + PKCE config flow (Dynamic Client Registration, direct mode)
- [x] Encrypted token storage + auto-refresh (direct mode)
- [x] DataUpdateCoordinator — live Instamart order polling
- [x] Instamart sensors + binary sensors
- [x] Instamart services — add_to_cart, clear_cart
- [x] Instamart HA events — out_for_delivery, order_delivered
- [x] GitHub Actions CI/CD (HACS + hassfest validation, release)
- [x] **Swiggy MCP Proxy Add-on** — local OAuth proxy with code-paste flow
- [x] **Add-on mode** in HACS integration (no OAuth needed in HA)
- [x] Multi-arch Docker build (amd64 / aarch64 / armv7)
- [x] Delivery Address select entity
- [x] Instamart Clear Cart button
- [x] thefuzz fuzzy matching for robust cart item search
- [ ] Food ordering integration (see `food` branch)
- [ ] Dashboard card (Lovelace custom card)
- [ ] HACS default store submission

---

## 📈 Star History

<a href="https://star-history.com/#pranjal-joshi/ha-swiggy-mcp&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=pranjal-joshi/ha-swiggy-mcp&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=pranjal-joshi/ha-swiggy-mcp&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=pranjal-joshi/ha-swiggy-mcp&type=Date" />
  </picture>
</a>

---

## 🤝 Contributing

PRs and issues welcome! Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before starting a large change.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for full design decisions and diagrams.

---

## 📄 License

[MIT](./LICENSE) — © [pranjal-joshi](https://github.com/pranjal-joshi)

---

<div align="center">
  <sub>Built with ❤️ by <a href="https://github.com/pranjal-joshi">pranjal-joshi</a> · Powered by <a href="https://mcp.swiggy.com">Swiggy MCP</a></sub>
</div>
