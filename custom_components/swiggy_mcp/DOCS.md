# Swiggy MCP Integration — User Guide

> This integration focuses on **Swiggy Instamart** (grocery delivery).
> Food ordering features are being developed separately in the `food` branch.

## Prerequisites

### AI Task (Required dependency)

This integration lists `ai_task` as a required HA dependency. It enables a LLM-powered fallback when Swiggy's search tools return unstructured text that regex cannot parse.

You do not need to configure an AI assistant for the integration to function. If none is set up, the LLM fallback is silently skipped and the regex parser handles most real-world responses.

To get the best `add_to_cart` reliability, configure one of these AI integrations first:
- **Google Generative AI** (Settings → Integrations → Google Generative AI)
- **OpenAI Conversation** (Settings → Integrations → OpenAI Conversation)

---

## Using with the Swiggy MCP Proxy Add-on (Recommended)

### Step 1 — Install and configure the add-on

1. Go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add `https://github.com/pranjal-joshi/ha-swiggy-mcp`
3. Find **Swiggy MCP Proxy** → Install → Start
4. Open the add-on Web UI

### Step 2 — Authenticate with Swiggy (code-paste flow)

1. Click **Login with Swiggy →** in the add-on UI
2. A Swiggy login page opens in your browser
3. Log in with your Swiggy account
4. After login, your browser will try to redirect to `http://localhost/callback?code=...` — **this page will fail to load** (expected)
5. **Copy the full URL** from your browser's address bar
6. Paste it into the add-on's text box and click **Submit**
7. You'll see ✅ **Authentication successful**

> The add-on stores your token in `/data/tokens.json` and auto-refreshes before expiry.

### Step 3 — Set up the integration

1. Install **Swiggy MCP** via HACS (custom repository: `https://github.com/pranjal-joshi/ha-swiggy-mcp`)
2. Go to **Settings → Integrations → Add Integration → Swiggy MCP**
3. Select **Use Swiggy MCP Proxy add-on (recommended)**
4. Enter the add-on URL: `http://homeassistant.local:9584` (default)
5. Click Submit — sensors appear automatically

---

## Direct Mode (Advanced / Fallback)

If you don't want to use the add-on, the integration can connect directly to Swiggy's MCP servers via OAuth 2.1 + PKCE. However, HA's callback URL must be on Swiggy's redirect URI whitelist.

To use direct mode: uncheck **Use add-on** during integration setup.

---

## Available Entities

### Sensors — Instamart Order
| Entity | Example |
|---|---|
| `sensor.instamart_order_status` | `Out for Delivery` |
| `sensor.instamart_eta` | `8` (minutes) |
| `sensor.instamart_store` | `Swiggy Instamart` |
| `sensor.instamart_billed_amount` | `249` (₹) |
| `sensor.instamart_order_items` | `Maggi, Milk, Bread` |
| `sensor.instamart_order_id` | `ORD789012` |

### Sensors — Instamart Cart
| Entity | Example |
|---|---|
| `sensor.instamart_cart_items` | `Eggs x12, Butter` |
| `sensor.instamart_cart_total` | `195` (₹) |

### Sensors — Delivery
| Entity | Example |
|---|---|
| `sensor.delivery_address` | `A4, 902 Kumar Palmcrest, Pune` |

### Binary Sensors
| Entity | Description |
|---|---|
| `binary_sensor.instamart_order_active` | `on` when an active Instamart order exists |

### Buttons
| Entity | Action |
|---|---|
| `button.instamart_clear_cart` | Instantly clears your Instamart cart |

### Select
| Entity | Description |
|---|---|
| `select.delivery_address` | Pick your active delivery address from all saved addresses |

### Events
| Event | Fired when |
|---|---|
| `swiggy_mcp_instamart_out_for_delivery` | Instamart order is out for delivery |
| `swiggy_mcp_instamart_order_delivered` | Instamart order is delivered |

---

## Services

### `swiggy_mcp.add_to_cart`
Add an item to your Instamart cart by name.
```yaml
service: swiggy_mcp.add_to_cart
data:
  query: "Maggi Noodles 70g"
  quantity: 2
```

### `swiggy_mcp.clear_cart`
Clear your Instamart cart.
```yaml
service: swiggy_mcp.clear_cart
```

---

## Automation Examples

### Notify when Instamart order is out for delivery
```yaml
automation:
  - alias: Instamart Out for Delivery Alert
    trigger:
      - platform: event
        event_type: swiggy_mcp_instamart_out_for_delivery
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "🛵 On the way!"
          message: "Your Instamart order is out for delivery."
```

### Auto-restock when pantry item runs low
```yaml
automation:
  - alias: Auto-reorder rice when running low
    trigger:
      - platform: numeric_state
        entity_id: sensor.rice_container_weight
        below: 1
    action:
      - service: swiggy_mcp.add_to_cart
        data:
          query: "India Gate Basmati Rice 5kg"
          quantity: 1
      - service: notify.mobile_app
        data:
          title: "🛒 Rice running low!"
          message: "Added to your Instamart cart."
```

### Turn on porch light when delivery is near
```yaml
automation:
  - alias: Porch light when Instamart is near
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
```

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

**`add_to_cart` can't find the item**
- Try a more specific item name (e.g. "Kissan Tomato Ketchup 850g" instead of "ketchup")
- Configuring an AI assistant (Google Generative AI, OpenAI) improves success on novel response formats

**Direct mode whitelist error**
- Switch to add-on mode — it uses `localhost` redirect URIs which Swiggy has pre-approved

---

## Limitations

- Instamart orders are COD only — always review your cart in the Swiggy app before checkout
- Close the Swiggy app while using MCP (session conflicts)
- Food ordering is available in the `food` branch (work in progress)
