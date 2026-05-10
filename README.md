<div align="center">
  <img src="./logo.png" alt="Swiggy Home Assistant Integration" width="220" />

  <h1>Swiggy MCP — Home Assistant Integration</h1>

  <p><strong>Order food, restock groceries & automate deliveries — right from your smart home.</strong><br/>
  A HACS custom integration powered by the official <a href="https://mcp.swiggy.com">Swiggy MCP servers</a>.</p>

  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/releases"><img src="https://img.shields.io/github/v/release/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge&color=FC8019&label=Release" alt="Release"/></a>
  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/stargazers"><img src="https://img.shields.io/github/stars/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge&color=FC8019" alt="Stars"/></a>
  <a href="https://github.com/pranjal-joshi/ha-swiggy-mcp/issues"><img src="https://img.shields.io/github/issues/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge" alt="Issues"/></a>
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/pranjal-joshi/ha-swiggy-mcp?style=for-the-badge" alt="License"/></a>
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-orange?style=for-the-badge&logo=HomeAssistantCommunityStore" alt="HACS"/></a>

  <br/><br/>

  > ⚠️ **Early Development / POC** — Not yet in the HACS default store. Add via custom repository URL below.

</div>

---

## 🍕 What is this?

**ha-swiggy-mcp** is a Home Assistant integration that connects your Swiggy account to your smart home via [Swiggy's official MCP servers](https://github.com/Swiggy/swiggy-mcp-server-manifest).

It gives you **live order sensors**, **HA services for automations**, and **voice command support** — all secured with OAuth 2.1 + PKCE. No token copying. No manual setup. Just log in and go.

```
┌─────────────────────────────────────────┐
│  Your AI Client (Claude / ChatGPT)      │
│  ↕ your own Swiggy OAuth               │
│  mcp.swiggy.com  ← conversational      │
│                     ordering            │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  Home Assistant                         │
│                                         │
│  [swiggy_mcp integration]               │
│    • Live sensors  (status, ETA, etc.)  │
│    • Services      (reorder, add cart)  │
│    • Events        (delivered, picked)  │
│    ↕ OAuth 2.1 + PKCE (auto-refresh)   │
│  mcp.swiggy.com                         │
└─────────────────────────────────────────┘
```

No tokens to copy. No cloud relay. Your credentials stay on your HA instance, encrypted at rest.

---

## ✨ What you get

### 📊 Sensors
| Entity | Example state |
|---|---|
| `sensor.swiggy_order_status` | `Out for Delivery` |
| `sensor.swiggy_eta` | `12` (min) |
| `sensor.swiggy_restaurant` | `Behrouz Biryani` |
| `sensor.swiggy_billed_amount` | `349` (₹) |
| `sensor.swiggy_last_order_items` | `Chicken Dum Biryani, Raita` |
| `sensor.swiggy_order_id` | `ORD123456` |
| `binary_sensor.swiggy_order_active` | `on` / `off` |

### ⚡ Services
| Service | What it does |
|---|---|
| `swiggy_mcp.reorder_last` | Re-places your exact last order |
| `swiggy_mcp.add_to_cart` | Adds an item to Food or Instamart cart |
| `swiggy_mcp.clear_cart` | Clears your Food or Instamart cart |

### 🔔 Events
| Event | Fires when |
|---|---|
| `swiggy_mcp_out_for_delivery` | Order is picked up by delivery partner |
| `swiggy_mcp_order_delivered` | Order is delivered |

---

## 📦 Installation

### Step 1 — Add the repository to HACS

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pranjal-joshi&repository=ha-swiggy-mcp&category=integration)

Or manually:
1. HACS → Integrations → ⋮ → **Custom repositories**
2. URL: `https://github.com/pranjal-joshi/ha-swiggy-mcp` · Category: **Integration**
3. Click **Download** → restart Home Assistant

### Step 2 — Add the integration

1. **Settings → Devices & Services → + Add Integration**
2. Search **Swiggy MCP** and click it
3. Click **"Open Swiggy login page"** — your browser opens Swiggy's OAuth consent screen
4. Log in and approve access
5. Browser redirects back to HA automatically
6. Pick your default delivery address and poll interval

That's it. Sensors appear immediately.

> **No tokens to copy.** Auth is fully handled via OAuth 2.1 + PKCE. Tokens are stored encrypted inside HA and refresh automatically before expiry.

---

## 🎙️ Voice Commands (HA Assist)

Add this to your `configuration.yaml` to enable voice ordering:

```yaml
intent_script:
  ReorderSwiggy:
    speech:
      text: "Reordering your last Swiggy order!"
    action:
      service: swiggy_mcp.reorder_last

  SwiggyOrderStatus:
    speech:
      text: >
        {% if is_state('binary_sensor.swiggy_order_active', 'on') %}
          Your order from {{ states('sensor.swiggy_restaurant') }} is
          {{ states('sensor.swiggy_order_status') }},
          arriving in {{ states('sensor.swiggy_eta') }} minutes.
        {% else %}
          No active Swiggy order right now.
        {% endif %}
```

Then just say:
```
"Hey Home Assistant, reorder my last Swiggy order"
"Hey Home Assistant, where's my Swiggy order?"
"How long until my food arrives?"
```

> **Note:** Complex ordering like "find me biryani under ₹200" requires an LLM connected directly to Swiggy's MCP tools. HA Assist handles fixed commands; an AI client handles conversational discovery.

---

## 🤖 Automation Examples

**Turn on the porch light when your delivery is near:**
```yaml
alias: Porch light when Swiggy is out for delivery
trigger:
  - platform: state
    entity_id: sensor.swiggy_order_status
    to: "Out for Delivery"
action:
  - service: light.turn_on
    target:
      entity_id: light.porch
mode: single
```

**TTS announcement when food arrives:**
```yaml
alias: Announce Swiggy delivery
trigger:
  - platform: event
    event_type: swiggy_mcp_order_delivered
action:
  - service: tts.speak
    data:
      message: "Your Swiggy order has been delivered. Enjoy your meal!"
      media_player_entity_id: media_player.living_room_speaker
mode: single
```

**Smart pantry restocking with a weight sensor:**

Place a pressure/weight sensor under your rice container. When stock drops below 1 kg, automatically add it to your Instamart cart.

```yaml
alias: Auto-reorder rice when running low
description: >-
  Triggers when the weight sensor under the rice container drops below 1 kg.
  Adds rice to the Instamart cart for quick checkout.
trigger:
  - platform: numeric_state
    entity_id: sensor.rice_container_weight
    below: 1
    for:
      minutes: 5  # debounce — ignore brief bumps
condition:
  - condition: state
    entity_id: input_boolean.swiggy_auto_restock
    state: "on"  # kill-switch — turn off when travelling
action:
  - service: swiggy_mcp.add_to_cart
    data:
      service: instamart
      item: "India Gate Basmati Rice 5kg"
      quantity: 1
  - service: notify.mobile_app
    data:
      title: "🛒 Rice running low!"
      message: "Added to your Instamart cart. Review and checkout in Swiggy."
mode: single
```

**Weekly grocery restock:**
```yaml
alias: Sunday grocery restock
trigger:
  - platform: time
    at: "10:00:00"
condition:
  - condition: time
    weekday: [sun]
action:
  - service: swiggy_mcp.reorder_last
mode: single
```

---

## 🏗️ Architecture

```
custom_components/swiggy_mcp/
├── auth/
│   ├── pkce.py          PKCE S256 verifier + challenge
│   ├── store.py         Encrypted token storage (HA config entry)
│   └── manager.py       Auto-refresh, ConfigEntryAuthFailed on rejection
├── api/
│   └── client.py        MCP HTTP calls, 401 retry middleware
├── config_flow.py       DCR → OAuth 2.1 → address picker
├── coordinator.py       Polls Swiggy every N seconds
├── sensor.py            Live order sensors
├── binary_sensor.py     Order active binary sensor
└── services.py          reorder_last, add_to_cart, clear_cart
```

**Auth flow:**
1. Dynamic Client Registration — HA registers itself with Swiggy once, gets a `client_id`
2. PKCE challenge generated per session — no client secret ever stored
3. Tokens encrypted at rest in HA's config entry store
4. Auto-refresh 60 s before expiry — completely transparent
5. On revocation → HA shows "Re-authenticate" banner → one click to re-link

---

## ⚠️ Important Limitations

- **COD only** — orders placed via services are Cash on Delivery and **cannot be cancelled**. Always review your cart in the Swiggy app before checkout.
- **Close the Swiggy app** while the integration is active — running both simultaneously causes session conflicts on Swiggy's side.
- **Dineout** — free table bookings only.
- **Conversational ordering** — searching menus, comparing restaurants, and full end-to-end ordering requires an LLM connected to Swiggy's MCP servers directly. HA handles status and simple fixed-action services only.

---

## 🗺️ Roadmap

- [x] Project planning & architecture
- [x] Logo & branding
- [x] HACS custom integration scaffold
- [x] OAuth 2.1 + PKCE config flow (Dynamic Client Registration)
- [x] Encrypted token storage + auto-refresh
- [x] DataUpdateCoordinator — live order polling
- [x] Sensors + binary sensors
- [x] Services — reorder_last, add_to_cart, clear_cart
- [x] HA events — out_for_delivery, order_delivered
- [x] GitHub Actions CI/CD (HACS + hassfest validation, release)
- [ ] Dashboard card (Lovelace custom card)
- [ ] Instamart past orders sensor
- [ ] HACS default store submission
- [ ] Swiggy Builders Club production access

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

See [ARCHITECTURE.md](./ARCHITECTURE.md) for design decisions and diagrams.

---

## 📄 License

[MIT](./LICENSE) — © [pranjal-joshi](https://github.com/pranjal-joshi)

---

<div align="center">
  <sub>Built with ❤️ by <a href="https://github.com/pranjal-joshi">pranjal-joshi</a> · Powered by <a href="https://mcp.swiggy.com">Swiggy MCP</a></sub>
</div>
