# Swiggy MCP Integration — User Guide

## Prerequisites

### AI Task (Required dependency)

This integration lists `ai_task` as a required HA dependency. This enables a LLM-powered fallback when Swiggy's `search_menu` tool returns unstructured text that regex cannot parse.

**You do not need to configure an AI assistant for the integration to function.** If no AI assistant is set up, the LLM fallback is silently skipped and the regex parser handles most real-world responses.

To get the best `add_to_cart` reliability, configure one of these AI integrations in HA first:
- **Google Generative AI** (Settings → Integrations → Google Generative AI)
- **OpenAI Conversation** (Settings → Integrations → OpenAI Conversation)
- Any other integration that exposes an `ai_task` entity

Once configured, Swiggy's unrecognised menu response formats will be automatically handled by the LLM.

---

## Using with the Swiggy MCP Proxy Add-on (Recommended)

The add-on is the easiest and most reliable way to set up this integration. It handles all OAuth complexity using a `localhost` redirect URI that Swiggy has pre-approved.

### Step 1 — Install and configure the add-on

1. Go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add `https://github.com/pranjal-joshi/ha-swiggy-mcp`
3. Find **Swiggy MCP Proxy** → Install → Start
4. Open the add-on Web UI

### Step 2 — Authenticate with Swiggy (code-paste flow)

1. Click **Login with Swiggy →** in the add-on UI
2. A Swiggy login page opens in your browser
3. Log in with your Swiggy account
4. After login, your browser will try to redirect to `http://localhost/callback?code=...` — **this page will fail to load** (expected — you're on a remote HA instance)
5. **Copy the full URL** from your browser's address bar (the one starting with `http://localhost/callback?code=...`)
6. Paste it into the add-on's text box and click **Submit**
7. You'll see ✅ **Authentication successful**

> ⚠️ The add-on stores your token in `/data/tokens.json` (HA's persistent volume for add-ons). It auto-refreshes before expiry. If you need to re-authenticate, click **Logout / Re-authenticate** in the add-on UI.

### Step 3 — Set up the integration

1. Install **Swiggy MCP** via HACS (custom repository: `https://github.com/pranjal-joshi/ha-swiggy-mcp`)
2. Go to **Settings → Integrations → Add Integration → Swiggy MCP**
3. Select **Use Swiggy MCP Proxy add-on (recommended)**
4. Enter the add-on URL: `http://homeassistant.local:9584` (default)
5. Click Submit — sensors appear automatically

---

## Direct Mode (Advanced / Fallback)

If you don't want to use the add-on, the integration can connect directly to Swiggy's MCP servers via OAuth 2.1 + PKCE. However, HA's callback URL (`https://your-ha.example.com/auth/external/callback`) must be on Swiggy's redirect URI whitelist — which may not be the case for new clients (you'll see a "not whitelisted" error).

To use direct mode: uncheck **Use add-on** during integration setup.

---

## Available Entities

### Sensors — Food
| Entity | Example |
|---|---|
| `sensor.food_order_status` | `Out for Delivery` |
| `sensor.food_eta` | `12` (minutes) |
| `sensor.food_restaurant` | `Behrouz Biryani` |
| `sensor.food_billed_amount` | `349` (₹) |
| `sensor.food_order_items` | `Chicken Biryani, Raita` |
| `sensor.food_order_id` | `ORD123456` |
| `sensor.food_cart_items` | `Vada Pav, Chai` |
| `sensor.food_cart_total` | `89` (₹) |

### Sensors — Instamart
| Entity | Example |
|---|---|
| `sensor.instamart_order_status` | `Out for Delivery` |
| `sensor.instamart_eta` | `8` (minutes) |
| `sensor.instamart_store` | `Swiggy Instamart` |
| `sensor.instamart_billed_amount` | `249` (₹) |
| `sensor.instamart_order_items` | `Maggi, Milk, Bread` |
| `sensor.instamart_order_id` | `ORD789012` |
| `sensor.instamart_cart_items` | `Eggs x12, Butter` |
| `sensor.instamart_cart_total` | `155` (₹) |

### Binary Sensors
| Entity | Description |
|---|---|
| `binary_sensor.food_order_active` | `on` when an active food order exists |
| `binary_sensor.instamart_order_active` | `on` when an active Instamart order exists |

### Buttons
| Entity | Action |
|---|---|
| `button.food_clear_cart` | Instantly clears your food cart |
| `button.instamart_clear_cart` | Instantly clears your Instamart cart |

### Select
| Entity | Description |
|---|---|
| `select.delivery_address` | Pick your active delivery address from all saved addresses |

### Events
| Event | Fired when |
|---|---|
| `swiggy_mcp_out_for_delivery` | Food order status → Out for Delivery |
| `swiggy_mcp_order_delivered` | Food order status → Delivered |
| `swiggy_mcp_instamart_out_for_delivery` | Instamart order status → Out for Delivery |
| `swiggy_mcp_instamart_order_delivered` | Instamart order status → Delivered |

---

## Services

### `swiggy_mcp.reorder_last`
Re-places your most recent Swiggy order.
```yaml
service: swiggy_mcp.reorder_last
```

### `swiggy_mcp.add_to_cart`
```yaml
service: swiggy_mcp.add_to_cart
data:
  service: instamart  # food | instamart
  query: "Maggi Noodles 70g"
  quantity: 2
```

### `swiggy_mcp.clear_cart`
```yaml
service: swiggy_mcp.clear_cart
data:
  service: food  # food | instamart
```

---

## Automation Examples

### Notify on delivery
```yaml
automation:
  - alias: Swiggy Out for Delivery Alert
    trigger:
      - platform: event
        event_type: swiggy_mcp_out_for_delivery
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "🛵 On the way!"
          message: "Your Swiggy order is out for delivery."
```

### Turn on porch light when delivery is near
```yaml
automation:
  - alias: Swiggy Delivery Porch Light
    trigger:
      - platform: numeric_state
        entity_id: sensor.swiggy_eta
        below: 5
    condition:
      - condition: state
        entity_id: binary_sensor.swiggy_order_active
        state: "on"
    action:
      - service: light.turn_on
        target:
          entity_id: light.porch
```

---

## Voice Commands (HA Assist)

Add these to your `configuration.yaml`:

```yaml
intent_script:
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

  SwiggyReorder:
    speech:
      text: "Reordering your last Swiggy order."
    action:
      service: swiggy_mcp.reorder_last
```

Then say: *"What's my Swiggy order status?"* or *"Reorder my last Swiggy order"*

---

## Troubleshooting

**Add-on not authenticating**
- Make sure you copied the full URL including `?code=...&state=...`
- The code is single-use; if you waited too long, click **Login with Swiggy** again

**Integration can't connect to add-on**
- Confirm the add-on is running (green status in HA add-ons page)
- Check the URL — default is `http://homeassistant.local:9584`
- If using a remote HA, use the local IP: `http://192.168.x.x:9584`

**Sensors show "unavailable"**
- Open the add-on UI — if it shows "Not authenticated", re-do the login flow
- Check HA logs for `swiggy_mcp` errors

**Direct mode whitelist error**
- Switch to add-on mode — it uses `localhost` redirect URIs which Swiggy has pre-approved

**`add_to_cart` can't find the item**
- Swiggy's `search_menu` sometimes returns unstructured text. The integration tries JSON parse → regex → ai_task LLM fallback in order.
- If all three fail, try a more specific item name (e.g. "Chicken Dum Biryani" instead of "biryani").
- Configuring an AI assistant (Google Generative AI, OpenAI) dramatically improves success on novel response formats.

---

## Limitations

- COD only — `place_food_order` via MCP is cash-on-delivery only
- Close the Swiggy app while using MCP (session conflicts)
- Dineout bookings: free slots only
- Voice ordering is simple command-based only (no conversational AI built-in)
