"""SwiggyLLMApi — registers a custom llm.API with Home Assistant.

Once registered, any conversation agent (Claude, OpenAI, Gemini, Ollama)
configured in HA can call Swiggy MCP tools via natural language through
HA Assist.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..const import DOMAIN
from .tools import ALL_TOOL_CLASSES

SWIGGY_LLM_API_ID = "swiggy_mcp"


class SwiggyLLMApi(llm.API):
    """Custom LLM API exposing Swiggy MCP tools to HA conversation agents."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            id=SWIGGY_LLM_API_ID,
            name="Swiggy MCP",
        )

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        return llm.APIInstance(
            api=self,
            api_prompt=(
                "You have access to the user's Swiggy account. "
                "You can search restaurants, browse menus, manage carts, and place food or grocery orders. "
                "IMPORTANT: Before placing any food order (swiggy_place_food_order), you MUST: "
                "1. Show the user the full cart contents and total amount. "
                "2. Ask for explicit confirmation. "
                "3. Only call the tool with confirmed=true after the user says yes. "
                "Orders are Cash on Delivery and CANNOT be cancelled after placement. "
                "For Instamart grocery orders, always show the cart before checkout."
            ),
            llm_context=llm_context,
            tools=[cls() for cls in ALL_TOOL_CLASSES],
        )
