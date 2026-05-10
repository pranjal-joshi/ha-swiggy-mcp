"""Constants for the Swiggy MCP integration."""

DOMAIN = "swiggy_mcp"

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_ADDRESS_ID = "address_id"
CONF_POLL_INTERVAL = "poll_interval"

# OAuth token keys (stored in config entry data, encrypted at rest by HA)
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"   # float unix timestamp
CONF_CLIENT_ID = "client_id"                 # DCR-issued per HA instance

# Legacy key — presence triggers migration / reauth
CONF_BEARER_TOKEN = "bearer_token"

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_POLL_INTERVAL = 30          # seconds
DEFAULT_NAME = "Swiggy"
TOKEN_REFRESH_BUFFER_SECONDS = 60   # refresh when this many seconds remain

# ── Swiggy OAuth server (from .well-known) ───────────────────────────────────
SWIGGY_AUTH_ISSUER = "https://mcp.swiggy.com/auth"
SWIGGY_AUTH_AUTHORIZE = "https://mcp.swiggy.com/auth/authorize"
SWIGGY_AUTH_TOKEN = "https://mcp.swiggy.com/auth/token"
SWIGGY_AUTH_REGISTER = "https://mcp.swiggy.com/auth/register"
SWIGGY_AUTH_SCOPES = "mcp:tools mcp:resources mcp:prompts"

# ── Swiggy MCP endpoints ─────────────────────────────────────────────────────
SWIGGY_FOOD_URL = "https://mcp.swiggy.com/food"
SWIGGY_INSTAMART_URL = "https://mcp.swiggy.com/im"
SWIGGY_DINEOUT_URL = "https://mcp.swiggy.com/dineout"

# ── Order statuses ────────────────────────────────────────────────────────────
ORDER_STATUS_ORDERED = "Ordered"
ORDER_STATUS_PREPARING = "Preparing"
ORDER_STATUS_OUT_FOR_DELIVERY = "Out for Delivery"
ORDER_STATUS_DELIVERED = "Delivered"

# ── HA event names ────────────────────────────────────────────────────────────
EVENT_OUT_FOR_DELIVERY = f"{DOMAIN}_out_for_delivery"
EVENT_ORDER_DELIVERED = f"{DOMAIN}_order_delivered"

# ── HA service names ──────────────────────────────────────────────────────────
SERVICE_REORDER_LAST = "reorder_last"
SERVICE_ADD_TO_CART = "add_to_cart"
SERVICE_CLEAR_CART = "clear_cart"

# ── Add-on mode ───────────────────────────────────────────────────────────────
CONF_USE_ADDON = "use_addon"
CONF_ADDON_URL = "addon_url"
DEFAULT_ADDON_URL = "http://homeassistant.local:9584"
