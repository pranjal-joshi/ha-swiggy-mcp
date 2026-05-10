# Contributing to ha-swiggy-mcp

Thanks for your interest in contributing! This guide covers everything you need to get started — from local setup to submitting a PR.

---

## Before you start

Please **open an issue first** before starting any non-trivial work. This lets us align on direction and avoid wasted effort. For small bug fixes, a PR without a prior issue is fine.

---

## Development setup

### Prerequisites

- Python 3.12+
- Home Assistant development environment (see [HA dev docs](https://developers.home-assistant.io/docs/development_environment/))
- A Swiggy account (India)

### Clone and install

```bash
git clone https://github.com/pranjal-joshi/ha-swiggy-mcp.git
cd ha-swiggy-mcp

# Copy the integration into your HA config directory
cp -r custom_components/swiggy_mcp /path/to/your/ha/config/custom_components/
```

### Running locally

1. Start your HA dev instance
2. Go to **Settings → Devices & Services → Add Integration → Swiggy MCP**
3. Complete the OAuth flow (see [DOCS.md](./custom_components/swiggy_mcp/DOCS.md))

---

## Project structure

```
custom_components/swiggy_mcp/
├── auth/          OAuth 2.1 + PKCE — token storage and refresh
├── api/           HTTP client — MCP calls, 401 retry middleware
├── llm/           LLM Tool Layer — 13 tools for conversational ordering
├── coordinator.py Polls Swiggy every N seconds, fires HA events
├── sensor.py      Live order sensors
├── binary_sensor.py Order active state
├── services.py    HA services: reorder_last, add_to_cart, clear_cart
└── config_flow.py DCR → PKCE → OAuth → address picker → reauth
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for full diagrams and decision log.

---

## Making changes

### Adding a new LLM tool

1. Open `custom_components/swiggy_mcp/llm/tools.py`
2. Subclass `homeassistant.helpers.llm.Tool`:

```python
class SwiggyMyNewTool(llm.Tool):
    name = "swiggy_my_new_tool"
    description = "Clear, single-sentence description for the LLM."
    parameters = vol.Schema({
        vol.Required("param_name"): str,
        vol.Optional("optional_param", default=1): int,
    })

    async def async_call(self, hass, tool_input, llm_context):
        return await _call_mcp(
            hass,
            SWIGGY_FOOD_URL,       # or SWIGGY_INSTAMART_URL
            "swiggy_mcp_tool_name", # exact tool name from Swiggy docs
            tool_input.tool_args,
        )
```

3. Add the class to `ALL_TOOL_CLASSES` at the bottom of `tools.py`
4. Test by asking your HA conversation agent to invoke it

### Adding a new HA sensor

1. Open `custom_components/swiggy_mcp/sensor.py`
2. Add a `SwiggyMcpSensorDescription` entry to the `SENSORS` tuple
3. Ensure the `coordinator_key` matches a key returned by `coordinator.py`'s `_async_update_data()`

### Adding a new HA service

1. Add the service name constant to `const.py`
2. Add handler + `hass.services.async_register(...)` in `services.py`
3. Add UI definition in `services.yaml`

### Modifying auth

The auth layer lives in `auth/`. The public interface is `SwiggyAuthManager.async_get_access_token()` — callers should never touch tokens directly.

- `auth/pkce.py` — PKCE primitives (no HA deps, pure Python)
- `auth/store.py` — reads/writes from config entry data
- `auth/manager.py` — orchestrates refresh, raises `ConfigEntryAuthFailed` on rejection

---

## Code style

- **Type hints** on all public functions
- **`from __future__ import annotations`** at the top of every file
- Keep auth, transport, and entity logic in separate modules — don't mix concerns
- No tokens in logs — use `_LOGGER.debug("token: %s", "***")` if needed

---

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     new feature
fix:      bug fix
docs:     documentation only
refactor: code change without feature/fix
test:     tests
chore:    build, CI, tooling
```

Examples:
```
feat(llm): add swiggy_dineout_book_table tool
fix(auth): handle 400 on token refresh as auth failure
docs: update DOCS.md with Instamart voice commands
```

Always append the co-author trailer for AI-assisted commits:
```
Co-authored-by: CyberKeys <noreply@openclaw.ai>
```

---

## Pull request checklist

- [ ] Issue opened and discussed (for non-trivial changes)
- [ ] Code follows project structure — auth / api / llm separation maintained
- [ ] No tokens, PII, or secrets in logs or error messages
- [ ] `manifest.json` keys are sorted: `domain`, `name`, then alphabetical
- [ ] `translations/en.json` updated if config flow steps changed
- [ ] CI passes — HACS validation + hassfest both green
- [ ] DOCS.md updated if user-visible behaviour changed

---

## CI / validation

Every push and PR runs:

```yaml
# .github/workflows/validate.yml
- HACS validation   (hacs/action@main)
- hassfest          (home-assistant/actions/hassfest@master)
```

Run these locally before pushing:

```bash
# hassfest (requires HA dev environment)
python -m script.hassfest --integration-path custom_components/swiggy_mcp

# JSON validation
python3 -c "import json; json.load(open('custom_components/swiggy_mcp/manifest.json'))"
python3 -c "import json; json.load(open('custom_components/swiggy_mcp/translations/en.json'))"

# Syntax check all Python files
python3 -c "
import ast, pathlib
files = list(pathlib.Path('custom_components/swiggy_mcp').rglob('*.py'))
for f in files:
    ast.parse(f.read_text())
print(f'All {len(files)} .py files OK')
"
```

---

## Release process

Releases are tag-driven. When a maintainer pushes a `v*.*.*` tag:

1. `release.yml` bumps `manifest.json` version to match the tag
2. Creates a GitHub Release with auto-generated release notes
3. HACS users see the new version in their update queue

```bash
git tag v0.2.0
git push origin v0.2.0
```

---

## Key constraints to keep in mind

| Constraint | Details |
|---|---|
| **COD only** | `swiggy_place_food_order` must keep the `confirmed: true` gate |
| **No client secret** | Public client (PKCE) — never add a client secret to the codebase |
| **Token isolation** | Entities and services must never receive or log tokens |
| **hassfest sort order** | `manifest.json` keys: `domain`, `name`, then alphabetical |
| **`http` dependency** | Must stay in `manifest.json` — required for OAuth callback |

---

## Questions?

Open a [GitHub Discussion](https://github.com/pranjal-joshi/ha-swiggy-mcp/discussions) or file an [issue](https://github.com/pranjal-joshi/ha-swiggy-mcp/issues).
