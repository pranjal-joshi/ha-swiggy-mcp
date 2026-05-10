# Swiggy MCP — Documentation

Connect your Swiggy account to Home Assistant. Get live order sensors, trigger automations on delivery events, restock groceries automatically, and control ordering with voice commands — all without touching a token.

---

## Requirements

- Home Assistant 2024.1 or newer
- A Swiggy account (India)
- HACS installed ([hacs.xyz](https://hacs.xyz))

---

## Installation

### 1 — Add via HACS

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pranjal-joshi&repository=ha-swiggy-mcp&category=integration)

Or manually:
1. Open **HACS → Integrations**
2. Click ⋮ (top right) → **Custom repositories**
3. Enter `https://github.com/pranjal-joshi/ha-swiggy-mcp`
4. Category: **Integration** → click **Add**
5. Find **Swiggy MCP** in the list → **Download**
6. Restart Home Assistant

### 2 — Add the integration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration** (bottom right)
3. Search for **Swiggy MCP** and select it

### 3 — Log in with Swiggy

A button appears: **"Open Swiggy login page"**

Click it. Your browser opens Swiggy's secure OAuth consent screen. Log in to your Swiggy account and click **Allow**.

Your browser will redirect back to Home Assistant automatically. No tokens to copy or paste.

### 4 — Pick your address and polling interval

After login, HA fetches your saved Swiggy addresses. Select the one you want to use as your default for order tracking and cart actions.

Set the **poll interval** (default: 30 seconds). This controls how often HA checks your active order status.

### 5 — Done

Your sensors appear immediately under **Settings → Devices & Services → Swiggy MCP**.

---

## Sensors

| Entity | Unit | Description |
|---|---|---|
| `sensor.swiggy_order_status` | — | Current order state: `Ordered`, `Preparing`, `Out for Delivery`, `Delivered` |
| `sensor.swiggy_eta` | min | Estimated minutes until delivery |
| `sensor.swiggy_restaurant` | — | Restaurant name for the active order |
| `sensor.swiggy_billed_amount` | ₹ | Total billed amount |
| `sensor.swiggy_last_order_items` | — | Comma-separated list of ordered items |
| `sensor.swiggy_order_id` | — | Active order ID |
| `binary_sensor.swiggy_order_active` | — | `on` when an active order is in progress, `off` otherwise |

Sensors show `unavailable` when there is no active or recent order.

---

## Services

### `swiggy_mcp.reorder_last`
Re-places your most recent food order — same items, same restaurant.

```yaml
service: swiggy_mcp.reorder_last
```

> ⚠️ Orders are placed as **Cash on Delivery** and cannot be cancelled. Always review before automating.

---

### `swiggy_mcp.add_to_cart`
Adds an item to your Food or Instamart cart.

```yaml
service: swiggy_mcp.add_to_cart
data:
  service: instamart   # 'food' or 'instamart'
  item: "Maggi Noodles 70g"
  quantity: 2
```

| Field | Required | Default | Description |
|---|---|---|---|
| `service` | No | `instamart` | Which Swiggy service — `food` or `instamart` |
| `item` | Yes | — | Item name to search and add |
| `quantity` | No | `1` | Number of units |

---

### `swiggy_mcp.clear_cart`
Removes all items from your Food or Instamart cart.

```yaml
service: swiggy_mcp.clear_cart
data:
  service: food   # 'food' or 'instamart'
```

---

## Events

These HA events fire automatically when your order status changes. Use them as automation triggers.

| Event | Data | Fires when |
|---|---|---|
| `swiggy_mcp_out_for_delivery` | `{ order_id }` | Delivery partner has picked up your order |
| `swiggy_mcp_order_delivered` | `{ order_id }` | Order has been delivered |

---

## Automations

### Porch light on Out for Delivery

```yaml
alias: Porch light — Swiggy out for delivery
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

### TTS announcement on delivery

```yaml
alias: Announce Swiggy delivered
trigger:
  - platform: event
    event_type: swiggy_mcp_order_delivered
action:
  - service: tts.speak
    data:
      message: "Your Swiggy order has arrived. Enjoy your meal!"
      media_player_entity_id: media_player.living_room
mode: single
```

### Dashboard order status card

Add a Glance card to your dashboard:

```yaml
type: glance
title: Swiggy Order
entities:
  - entity: binary_sensor.swiggy_order_active
    name: Active
  - entity: sensor.swiggy_order_status
    name: Status
  - entity: sensor.swiggy_eta
    name: ETA
  - entity: sensor.swiggy_restaurant
    name: Restaurant
  - entity: sensor.swiggy_billed_amount
    name: Amount
```

### Auto-restock groceries with a weight sensor

Place a pressure/weight sensor under a container. When it drops below threshold, add the item to your Instamart cart automatically.

```yaml
alias: Auto-reorder rice when running low
trigger:
  - platform: numeric_state
    entity_id: sensor.rice_container_weight
    below: 1           # kg
    for:
      minutes: 5       # debounce — ignore brief bumps
condition:
  - condition: state
    entity_id: input_boolean.swiggy_auto_restock
    state: "on"        # optional kill-switch (off when travelling)
action:
  - service: swiggy_mcp.add_to_cart
    data:
      service: instamart
      item: "India Gate Basmati Rice 5kg"
      quantity: 1
  - service: notify.mobile_app
    data:
      title: "🛒 Rice running low!"
      message: "Added to Instamart cart. Review and checkout in Swiggy."
mode: single
```

---

## Voice Commands (HA Assist)

Add these to `configuration.yaml` to enable voice control:

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

Restart HA after saving, then say:
- *"Hey Home Assistant, reorder my last Swiggy order"*
- *"Hey Home Assistant, where's my Swiggy order?"*
- *"How long until my food arrives?"*

### What voice can and can't do

| Command | Works? | Notes |
|---|---|---|
| Reorder last order | ✅ | `reorder_last` service |
| Add a known item to cart | ✅ | `add_to_cart` service |
| Check order ETA | ✅ | Reads `sensor.swiggy_eta` |
| Find best restaurant | ❌ | Needs LLM + Swiggy MCP |
| Browse menus | ❌ | Needs LLM + Swiggy MCP |
| Full conversational ordering | ❌ | Use Claude / ChatGPT with Swiggy MCP |

For full conversational ordering, connect an AI client (Claude, ChatGPT) directly to Swiggy's MCP servers and use HA for automation and status only.

---

## Authentication

This integration uses **OAuth 2.1 + PKCE** — the same secure standard used by banks and major apps.

**What happens under the hood:**
1. On first setup, HA registers itself with Swiggy (Dynamic Client Registration) and gets a unique `client_id`
2. A PKCE code verifier + S256 challenge is generated for your session
3. You log in on Swiggy's own OAuth page — your password never touches HA
4. HA receives an access token + refresh token, encrypted and stored locally
5. The access token auto-refreshes 60 seconds before expiry — completely transparent

**If your session is revoked** (e.g. you changed your Swiggy password):
- HA shows a **"Re-authenticate"** banner on the integration card
- Click it → log in again → integration resumes

---

## Troubleshooting

### Sensors show `unavailable`
No active or recent order was found. Place an order in the Swiggy app and sensors will populate within one poll cycle (default 30 s).

### "Re-authenticate" banner appears
Your Swiggy session was revoked. Click the banner → log in again via the OAuth flow.

### Swiggy app shows session conflict
Close the Swiggy app while the integration is running. Swiggy's session system doesn't support concurrent access from both the app and MCP at the same time.

### `add_to_cart` doesn't find my item
Use the exact product name as it appears in Swiggy. Abbreviations or brand variants may not match. Check the HA logs (`Settings → System → Logs`) for the raw Swiggy response.

### Services aren't placing orders
All orders via services are **Cash on Delivery only**. Ensure your default address has COD available. Swiggy prepaid ordering via MCP is not supported yet.

---

## Conversational Ordering with HA Assist + LLM

With the LLM Tool Layer (Phase 8), full conversational ordering works directly inside HA Assist — no separate AI client needed. The integration registers a **Swiggy MCP API** that any configured conversation agent (Claude, OpenAI, Gemini, Ollama) picks up automatically.

### Setup

No extra configuration needed. As long as you have:
1. A conversation agent configured in HA (e.g. OpenAI Conversation, Anthropic, LocalAI)
2. The Swiggy MCP integration set up

...the agent automatically gets access to all Swiggy tools.

To expose it, go to your conversation agent's settings and select **Swiggy MCP** under **LLM API**.

### What you can say

```
"Find me the best biryani near me"
"What's on the menu at Behrouz Biryani?"
"Add a Chicken Dum Biryani to my cart"
"Show me what's in my cart"
"Apply the best available coupon"
"Place my order"   ← LLM shows cart first and asks to confirm
"Search for milk on Instamart"
"Add 2 packets of Amul milk to my Instamart cart"
"What's the status of my current order?"
```

### Available LLM tools

| Tool | What it does |
|---|---|
| `swiggy_search_restaurants` | Find restaurants by dish, cuisine, or keyword |
| `swiggy_get_restaurant_menu` | Browse a restaurant's full menu |
| `swiggy_get_food_cart` | View current cart and bill breakdown |
| `swiggy_add_to_food_cart` | Add an item to the food cart |
| `swiggy_flush_food_cart` | Clear the food cart |
| `swiggy_fetch_coupons` | List available coupons for the cart |
| `swiggy_apply_coupon` | Apply a coupon code |
| `swiggy_place_food_order` | Place the order (requires explicit user confirmation) |
| `swiggy_get_food_orders` | Check active order status |
| `swiggy_get_food_order_details` | Get ETA and tracking for a specific order |
| `swiggy_search_instamart` | Search Instamart for groceries |
| `swiggy_get_instamart_cart` | View Instamart cart |
| `swiggy_add_to_instamart_cart` | Add a grocery item to the Instamart cart |

### Order confirmation gate

The `swiggy_place_food_order` tool has a hard confirmation gate built in. The LLM **cannot** place an order without first:
1. Showing you the full cart contents and total
2. Asking for explicit confirmation
3. Receiving your "yes" before calling the tool with `confirmed=true`

This is enforced at the code level, not just by prompt — the tool returns an error if called without confirmation.

---

## Known Limitations

- **COD only** — orders placed via HA services are Cash on Delivery and cannot be cancelled
- **Close the Swiggy app** while the integration is active — session conflicts may occur
- **Dineout** — free table bookings only; paid reservations are not supported
- **Past orders** — only the most recent active order is tracked; history is not available
- **Instamart cart** — item search is by name; out-of-stock items will silently fail (check logs)

---

## Support

- **Issues:** [github.com/pranjal-joshi/ha-swiggy-mcp/issues](https://github.com/pranjal-joshi/ha-swiggy-mcp/issues)
- **Discussions:** [github.com/pranjal-joshi/ha-swiggy-mcp/discussions](https://github.com/pranjal-joshi/ha-swiggy-mcp/discussions)
