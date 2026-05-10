"""
Swiggy MCP Proxy Add-on — aiohttp web server

Routes:
  GET  /            → OAuth setup UI (shows auth status + login/paste form)
  GET  /auth/start  → Begin OAuth: DCR + redirect to Swiggy
  POST /auth/submit → Accept pasted redirect URL, exchange code for tokens
  GET  /auth/logout → Clear stored tokens
  POST /food        → Proxy to mcp.swiggy.com/food
  POST /instamart   → Proxy to mcp.swiggy.com/im
  POST /im          → Proxy to mcp.swiggy.com/im
  POST /dineout     → Proxy to mcp.swiggy.com/dineout
  GET  /health      → Health check

HA Ingress note:
  When accessed via Nabu Casa / remote ingress, HA proxies all requests
  under a dynamic base path (/api/hassio_ingress/<TOKEN>/). The server
  reads the X-Ingress-Path header injected by HA and prefixes all
  redirects and HTML hrefs with it so the UI works identically on LAN
  and remote.
"""
import logging
import os
import secrets
import time

import aiohttp
from aiohttp import web
from aiohttp.web_middlewares import normalize_path_middleware

from storage import load_tokens, save_tokens, clear_tokens
from oauth import do_dcr, build_auth_url, extract_code_from_url, exchange_code
from proxy import proxy_request

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("swiggy_mcp_proxy")

_session: aiohttp.ClientSession = None
_oauth_state: dict = {}

# ── Ingress base-path helper ─────────────────────────────────────────────────

def _base(request: web.Request) -> str:
    """Return the HA ingress base path (empty string on LAN direct access)."""
    return request.headers.get("X-Ingress-Path", "").rstrip("/")


def _url(request: web.Request, path: str) -> str:
    """Build an absolute-looking href that works under any ingress prefix."""
    return f"{_base(request)}{path}"


# ── Auth / status helpers ────────────────────────────────────────────────────

def _is_authenticated() -> bool:
    return bool(load_tokens().get("access_token"))


# ── HTML template ────────────────────────────────────────────────────────────

HTML_BASE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swiggy MCP Proxy</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 680px; margin: 40px auto; padding: 0 20px; background: #f8f8f8; color: #222; }}
  .card {{ background: white; border-radius: 12px; padding: 28px; box-shadow: 0 2px 8px rgba(0,0,0,.08); margin-bottom: 20px; }}
  h1 {{ color: #fc6203; margin-top: 0; }}
  .badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; }}
  .badge-ok {{ background: #e6f9ed; color: #1a7a3a; }}
  .badge-warn {{ background: #fff3e0; color: #b45309; }}
  .btn {{ display: inline-block; padding: 10px 22px; border-radius: 8px; font-size: 1em;
          font-weight: 600; cursor: pointer; border: none; text-decoration: none; }}
  .btn-primary {{ background: #fc6203; color: white; }}
  .btn-secondary {{ background: #eee; color: #333; }}
  .btn-danger {{ background: #fee2e2; color: #b91c1c; }}
  input[type=text] {{ width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #ddd;
                      border-radius: 8px; font-size: 0.95em; margin: 8px 0 14px; }}
  .note {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 4px; font-size: 0.9em; }}
  .steps {{ padding-left: 20px; }}
  .steps li {{ margin-bottom: 8px; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-family: monospace; word-break: break-all; }}
</style>
</head>
<body>
{body}
</body>
</html>"""

# ── Route handlers ───────────────────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    base = _base(request)
    if _is_authenticated():
        body = f"""
<div class="card">
  <h1>🍕 Swiggy MCP Proxy</h1>
  <p>Status: <span class="badge badge-ok">✓ Authenticated</span></p>
  <p>The proxy is running. Your Home Assistant Swiggy MCP integration can connect to:</p>
  <ul>
    <li><code>http://homeassistant.local:9584/food</code></li>
    <li><code>http://homeassistant.local:9584/instamart</code></li>
    <li><code>http://homeassistant.local:9584/dineout</code></li>
  </ul>
  <a href="{base}/auth/logout" class="btn btn-danger">Logout / Re-authenticate</a>
</div>"""
    else:
        body = f"""
<div class="card">
  <h1>🍕 Swiggy MCP Proxy</h1>
  <p>Status: <span class="badge badge-warn">⚠ Not authenticated</span></p>
  <p>You need to log in with your Swiggy account to start using the proxy.</p>
  <a href="{base}/auth/start" class="btn btn-primary">Login with Swiggy →</a>
</div>"""
    return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")


async def handle_auth_start(request: web.Request) -> web.Response:
    global _oauth_state
    base = _base(request)
    tokens = load_tokens()
    client_id = tokens.get("client_id")

    if not client_id:
        try:
            _LOGGER.info("Performing Dynamic Client Registration")
            client_id = await do_dcr(_session)
            tokens = load_tokens()
            tokens["client_id"] = client_id
            save_tokens(tokens)
        except Exception as e:
            body = f'<div class="card"><h1>🍕 Swiggy MCP Proxy</h1><p>❌ Registration failed: {e}</p><a href="{base}/" class="btn btn-secondary">Back</a></div>'
            return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")

    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    _oauth_state = {"verifier": verifier, "state": state, "client_id": client_id}

    auth_url = build_auth_url(client_id, verifier, state)

    body = f"""
<div class="card">
  <h1>🍕 Swiggy MCP Proxy — Login</h1>
  <div class="note">
    <strong>How this works:</strong> After clicking the link below, Swiggy will redirect your browser to
    <code>http://localhost:9584/callback</code>. That page will fail to load — that's expected.
    Just <strong>copy the full URL</strong> from your browser's address bar and paste it below.
  </div>
  <br>
  <ol class="steps">
    <li><a href="{auth_url}" target="_blank" class="btn btn-primary">Open Swiggy Login ↗</a></li>
    <li>Log in with your Swiggy account</li>
    <li>Your browser redirects to a page that doesn't load — <strong>copy the full URL</strong> from the address bar (it contains <code>?code=...</code>)</li>
    <li>Paste it below and click Submit</li>
  </ol>
  <br>
  <form method="POST" action="{base}/auth/submit">
    <label><strong>Paste the redirect URL here:</strong></label>
    <input type="text" name="redirect_url" placeholder="http://localhost:9584/callback?code=...&state=..." />
    <button type="submit" class="btn btn-primary">Submit</button>
  </form>
</div>"""
    return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")


async def handle_auth_submit(request: web.Request) -> web.Response:
    global _oauth_state
    base = _base(request)
    data = await request.post()
    pasted = data.get("redirect_url", "").strip()

    if not pasted:
        body = f'<div class="card"><h1>🍕 Swiggy MCP Proxy</h1><p>❌ No URL provided.</p><a href="{base}/auth/start" class="btn btn-secondary">Try again</a></div>'
        return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")

    code, state = extract_code_from_url(pasted)

    if not code:
        body = f'<div class="card"><h1>🍕 Swiggy MCP Proxy</h1><p>❌ Could not extract authorization code. Make sure you copied the full URL from your browser\'s address bar.</p><a href="{base}/auth/start" class="btn btn-secondary">Try again</a></div>'
        return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")

    verifier = _oauth_state.get("verifier", "")
    client_id = _oauth_state.get("client_id", "") or load_tokens().get("client_id", "")

    try:
        token_data = await exchange_code(_session, code, verifier, client_id)
    except Exception as e:
        body = f'<div class="card"><h1>🍕 Swiggy MCP Proxy</h1><p>❌ Token exchange failed: {e}</p><a href="{base}/auth/start" class="btn btn-secondary">Try again</a></div>'
        return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")

    tokens = load_tokens()
    tokens["client_id"] = client_id
    tokens["access_token"] = token_data["access_token"]
    tokens["refresh_token"] = token_data.get("refresh_token", "")
    tokens["expires_at"] = time.time() + int(token_data.get("expires_in", 3600))
    save_tokens(tokens)
    _oauth_state = {}

    body = f"""
<div class="card">
  <h1>🍕 Swiggy MCP Proxy</h1>
  <p>✅ <strong>Authentication successful!</strong></p>
  <p>The proxy is now ready. Configure your Home Assistant Swiggy MCP integration to use add-on mode.</p>
  <a href="{base}/" class="btn btn-primary">Go to Dashboard</a>
</div>"""
    return web.Response(text=HTML_BASE.format(body=body), content_type="text/html")


async def handle_auth_logout(request: web.Request) -> web.Response:
    clear_tokens()
    raise web.HTTPFound(_url(request, "/"))


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "authenticated": _is_authenticated()})


async def handle_proxy(request: web.Request) -> web.Response:
    service = request.match_info["service"]
    body = await request.read()
    status, resp_headers, resp_body = await proxy_request(
        service, body, dict(request.headers), _session
    )
    return web.Response(status=status, body=resp_body, headers=resp_headers)


# ── App lifecycle ────────────────────────────────────────────────────────────

async def on_startup(app: web.Application) -> None:
    global _session
    _session = aiohttp.ClientSession()
    _LOGGER.info("Swiggy MCP Proxy started on port 9584")


async def on_cleanup(app: web.Application) -> None:
    if _session:
        await _session.close()


def create_app() -> web.Application:
    # normalize_path_middleware merges consecutive slashes (e.g. //// → /)
    # which HA ingress can produce when proxying add-on UI requests.
    app = web.Application(middlewares=[
        normalize_path_middleware(append_slash=False, remove_slash=True, merge_slashes=True),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_get("/", handle_index)
    app.router.add_get("/auth/start", handle_auth_start)
    app.router.add_post("/auth/submit", handle_auth_submit)
    app.router.add_get("/auth/logout", handle_auth_logout)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/{service}", handle_proxy)

    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=9584)
