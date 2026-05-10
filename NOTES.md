# ha-swiggy-mcp — Development Reference Notes

> Created by CyberKeys ⌨️ on 2026-05-10
> Always read this before working on the add-on.
> Last updated: 2026-05-10 (architecture revision — HACS integration, no add-on)

---

## 🔗 Key References

| Resource | URL |
|---|---|
| **Our Repo** | https://github.com/pranjal-joshi/ha-swiggy-mcp |
| **Gold Standard Add-on** | https://github.com/homeassistant-ai/ha-mcp |
| **Swiggy MCP Manifest** | https://github.com/Swiggy/swiggy-mcp-server-manifest |
| **Swiggy Docs (LLM)** | https://mcp.swiggy.com/builders/llms.txt |
| **Swiggy Builders Club** | https://mcp.swiggy.com/builders/docs/index.md |
| **Swiggy Production Access** | https://mcp.swiggy.com/builders/docs/operate/access.md |

---

## 🍕 Swiggy MCP Endpoints

| Service | URL | Protocol |
|---|---|---|
| Food | `https://mcp.swiggy.com/food` | HTTP POST / JSON-RPC 2.0 |
| Instamart (Groceries) | `https://mcp.swiggy.com/im` | HTTP POST / JSON-RPC 2.0 |
| Dineout | `https://mcp.swiggy.com/dineout` | HTTP POST / JSON-RPC 2.0 |

**Auth:** Bearer token in `Authorization` header. Token is per-user, stored in HA credential store.

**Sample call:**
```bash
POST https://mcp.swiggy.com/food
Authorization: Bearer <user_token>
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_food_orders",
    "arguments": { "addressId": "addr_01HXYZ" }
  },
  "id": 1
}
```

---

## ✅ Final Architecture Decision

**No add-on. HACS custom integration only.**

```
┌──────────────────────────────────────────┐
│  AI Client (Claude / ChatGPT)            │
│  ↕ direct OAuth (user's own credentials) │
│  mcp.swiggy.com  ← full ordering UI      │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│  Home Assistant                          │
│                                          │
│  [swiggy_mcp HACS integration]           │
│    • Sensors  (status, ETA, amount, etc) │
│    • Services (reorder, add_to_cart)     │
│    • Events   (delivered, out for del.)  │
│         ↕ HTTP POST (user's own token)   │
│  mcp.swiggy.com                          │
│                                          │
│  [HA Assist / Voice / Automations]       │
│    → calls swiggy_mcp services           │
│    → simple commands work natively       │
└──────────────────────────────────────────┘
```

**Why no add-on:**
- Swiggy MCP is plain HTTP — no Docker proxy needed
- Each user provides their own token — no central auth
- HACS integration = simpler install, proper HA-native entities

---

## 📁 Project Directory Structure

```
ha-swiggy-mcp/
├── custom_components/
│   └── swiggy_mcp/
│       ├── __init__.py          # Integration setup
│       ├── manifest.json        # HACS metadata
│       ├── config_flow.py       # Token entry UI (config flow)
│       ├── coordinator.py       # DataUpdateCoordinator — polls Swiggy
│       ├── sensor.py            # All sensor entities
│       ├── binary_sensor.py     # binary_sensor.swiggy_order_active
│       ├── services.yaml        # Service definitions
│       ├── services.py          # Service handlers (reorder, add_to_cart)
│       ├── const.py             # Constants
│       ├── strings.json         # UI strings
│       └── translations/
│           └── en.json
├── .github/
│   └── workflows/
│       ├── validate.yml         # HACS validation + hassfest
│       └── release.yml          # Tag-based GitHub release
├── hacs.json                    # HACS repo config
├── logo.png                     # Branding
├── NOTES.md                     # This file
└── README.md
```

---

## 🏠 HA Entities Exposed

### Sensors
| Entity ID | Example State | Notes |
|---|---|---|
| `sensor.swiggy_order_status` | `Out for Delivery` | Ordered / Preparing / Out for Delivery / Delivered |
| `sensor.swiggy_eta` | `12` | Minutes remaining (unit: min) |
| `sensor.swiggy_restaurant` | `Behrouz Biryani` | Active order restaurant name |
| `sensor.swiggy_billed_amount` | `349` | INR, unit: ₹ |
| `sensor.swiggy_last_order_items` | `Chicken Dum Biryani, Raita` | Comma-separated items |
| `sensor.swiggy_order_id` | `ORD123456` | Active order ID |

### Binary Sensors
| Entity ID | State | Notes |
|---|---|---|
| `binary_sensor.swiggy_order_active` | `on` / `off` | `on` when an active order exists |

### Events fired
- `swiggy_mcp_order_delivered` — when status transitions to Delivered
- `swiggy_mcp_out_for_delivery` — when status transitions to Out for Delivery

---

## 🛠️ HA Services Exposed

### `swiggy_mcp.reorder_last`
Re-places the exact last order (same items, same restaurant, same address).
```yaml
service: swiggy_mcp.reorder_last
```

### `swiggy_mcp.add_to_cart`
Adds an item to Instamart or Food cart.
```yaml
service: swiggy_mcp.add_to_cart
data:
  service: instamart   # food | instamart
  item: "Maggi Noodles 70g"
  quantity: 3
```

### `swiggy_mcp.clear_cart`
```yaml
service: swiggy_mcp.clear_cart
data:
  service: food   # food | instamart
```

---

## 🛠️ Swiggy MCP Tools Used

### Read (for sensors / coordinator)
- `get_food_orders` — active order list + status
- `get_food_order_details` — ETA, items, amount, restaurant
- `get_addresses` — user's saved addresses (needed for most calls)

### Write (for HA services)
- `get_food_cart` / `flush_food_cart`
- `place_food_order` — **COD only, IRREVERSIBLE**
- `add_to_instamart_cart` (Instamart)

---

## ⚠️ Critical Constraints

1. **COD only** — `place_food_order` is IRREVERSIBLE. Always require explicit user confirmation.
2. **Close Swiggy app** during MCP sessions — session conflicts.
3. **Dineout** — free bookings only.
4. **POC vs Production** — no Swiggy approval needed for POC/dev. Apply for production access before public release.
5. **addressId required** — almost all Swiggy API calls need an `addressId`. Fetch via `get_addresses` on setup and cache.

---

## 🚀 CI/CD

- `validate.yml` — runs `hassfest` + HACS validation on every PR
- `release.yml` — on tag `v*.*.*`: creates GitHub Release, updates `manifest.json` version

---

## 📋 Development Phases

- [x] Phase 0: Repo clone, NOTES.md, README.md
- [x] Phase 1: Scaffold `custom_components/swiggy_mcp/` structure + `manifest.json` + `hacs.json`
- [x] Phase 2: `config_flow.py` — token entry, address selection UI
- [x] Phase 3: `coordinator.py` — DataUpdateCoordinator polling Swiggy
- [x] Phase 4: `sensor.py` + `binary_sensor.py` — all entities
- [x] Phase 5: `services.py` — reorder, add_to_cart, clear_cart
- [x] Phase 6: Events — fire on order state changes (in coordinator.py)
- [x] Phase 7: GitHub Actions CI/CD (validate + release workflows)
- [ ] Phase 8: Local testing + bug fixes
- [ ] Phase 9: HACS submission + README finalization
- [ ] Phase 10: Swiggy Builders Club production access application
