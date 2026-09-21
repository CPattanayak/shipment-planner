"""
Shipment Planner — AutoGen Chatbot
────────────────────────────────────────────────────────────────────────────────
Interactive conversational interface built on AutoGen's AssistantAgent +
UserProxyAgent pattern.  The AssistantAgent has all four MCP read tools
registered as callable functions; the UserProxyAgent relays real human input
and stops the session when the user types "exit".

Architecture
────────────
  UserProxyAgent  ──→  AssistantAgent (LLM + MCP tools)
       ↑                       │
       └──── reply ────────────┘

  Each MCP tool call is an async coroutine wrapped into a sync shim so
  AutoGen's synchronous function-calling machinery can invoke it without
  restructuring the event loop.

Exit condition
──────────────
  Type  exit  /  quit  /  bye  at any prompt to end the session.
  The AssistantAgent can also end the session by replying with "TERMINATE".

LLM provider
────────────
  Respects the same LLM_PROVIDER / OPENROUTER_* / MISTRAL_* env vars as
  agent_v4 — no separate config needed.

MCP tools registered
────────────────────
  • get_warehouse_capacity   → GetWarehouseCapacity
  • optimize_route           → OptimizeRoute
  • get_available_carriers   → GetAvailableCarriers
  • get_carrier_quote        → GetCarrierQuote

Sample session
──────────────
  User  : What is the capacity of warehouse WH-001?
  Agent : [calls get_warehouse_capacity] Current capacity is 8 400 / 10 000 units …

  User  : Find me the best route from WH-001 to postal code 10001, US for
           500 kg and 2.5 m³.
  Agent : [calls optimize_route] Recommended route: Chicago → New York, ETA …

  User  : Which carriers serve that lane at 500 kg?
  Agent : [calls get_available_carriers] Three carriers found: DHL, FedEx, UPS …

  User  : Get a quote from the top carrier.
  Agent : [calls get_carrier_quote] DHL Express quote: $1 240 for STANDARD …

  User  : exit
  Agent : Goodbye!  Session ended.

Usage
─────
  python chatbot.py
  python chatbot.py --first-message "Plan a shipment from WH-001 to 10001 US"
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Annotated

from dotenv import load_dotenv

load_dotenv()

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,          # keep AutoGen noise off the console
    format="%(levelname)s  %(name)s  %(message)s",
)
log = logging.getLogger("chatbot")

# ── config ────────────────────────────────────────────────────────────────────
from config import (
    LLM_PROVIDER,
    MCP_SERVER_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
)

# ── MCP tool bridge ───────────────────────────────────────────────────────────

_MCP_CFG = {
    "shipment-planner": {
        "transport": "streamable_http",
        "url": MCP_SERVER_URL,
    }
}


def _run(coro):
    """Run an async coroutine from synchronous AutoGen tool callbacks."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (e.g. Jupyter) — use a thread executor.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


async def _invoke_mcp(tool_name: str, args: dict) -> str:
    """Dispatch a single MCP tool call and return a JSON string."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(_MCP_CFG)
    tools = await client.get_tools()
    tool_map = {t.name: t for t in tools}

    if tool_name not in tool_map:
        available = list(tool_map.keys())
        return json.dumps({"error": f"Tool '{tool_name}' not found", "available": available})

    try:
        result = await tool_map[tool_name].ainvoke(args)
        return result if isinstance(result, str) else json.dumps(result, default=str)
    except Exception as exc:
        log.error("MCP tool %s failed: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})


# ── AutoGen tool functions ────────────────────────────────────────────────────

def get_warehouse_capacity(
        warehouse_id: Annotated[str, "The warehouse ID, e.g. 'WH-001'"],
) -> str:
    """Return current capacity and available space for the given warehouse."""
    return _run(_invoke_mcp("GetWarehouseCapacity", {"id": warehouse_id}))


def optimize_route(
        origin_warehouse_id: Annotated[str, "Origin warehouse ID"],
        destination_postal_code: Annotated[str, "Destination postal / ZIP code"],
        destination_country: Annotated[str, "ISO-2 country code, e.g. 'US'"],
        weight_kg: Annotated[float, "Total shipment weight in kilograms"],
        volume_m3: Annotated[float, "Total shipment volume in cubic metres"],
) -> str:
    """Return the optimal route, estimated transit time, and delivery date."""
    return _run(_invoke_mcp("OptimizeRoute", {
        "originWarehouseId":       origin_warehouse_id,
        "destinationPostalCode":   destination_postal_code,
        "destinationCountry":      destination_country,
        "weightKg":                weight_kg,
        "volumeM3":                volume_m3,
    }))


def get_available_carriers(
        origin_postal_code: Annotated[str, "Origin postal / ZIP code"],
        destination_postal_code: Annotated[str, "Destination postal / ZIP code"],
        weight_kg: Annotated[float, "Total shipment weight in kilograms"],
) -> str:
    """List all carriers available for this lane, with performance metrics."""
    return _run(_invoke_mcp("GetAvailableCarriers", {
        "originPostalCode":      origin_postal_code,
        "destinationPostalCode": destination_postal_code,
        "weightKg":              weight_kg,
    }))


def get_carrier_quote(
        carrier_id: Annotated[str, "Carrier ID (the full `id` field, not code or name)"],
        origin_postal_code: Annotated[str, "Origin postal / ZIP code"],
        destination_postal_code: Annotated[str, "Destination postal / ZIP code"],
        weight_kg: Annotated[float, "Shipment weight in kilograms"],
        volume_m3: Annotated[float, "Shipment volume in cubic metres"],
        service_level: Annotated[str, "'STANDARD' or 'EXPRESS'"],
) -> str:
    """Fetch a price quote from the specified carrier for this shipment."""
    return _run(_invoke_mcp("GetCarrierQuote", {
        "carrierId":             carrier_id,
        "originPostalCode":      origin_postal_code,
        "destinationPostalCode": destination_postal_code,
        "weightKg":              weight_kg,
        "volumeM3":              volume_m3,
        "serviceLevel":          service_level,
    }))


# ── LLM config ────────────────────────────────────────────────────────────────

def _build_llm_config() -> dict:
    """
    Build an AutoGen llm_config dict from the same env vars as agent_v4.

    OpenRouter and Mistral AI both expose OpenAI-compatible endpoints, so
    AutoGen's ChatCompletion client works for both by adjusting base_url.
    """
    if LLM_PROVIDER == "mistral":
        if not MISTRAL_API_KEY:
            sys.exit("ERROR: LLM_PROVIDER=mistral but MISTRAL_API_KEY is not set.")
        cfg = {
            "model":    MISTRAL_MODEL,
            "api_key":  MISTRAL_API_KEY,
            "base_url": "https://api.mistral.ai/v1",
            "api_type": "openai",
        }
        log.info("chatbot LLM: mistral  model=%s", MISTRAL_MODEL)
    else:
        if not OPENROUTER_API_KEY:
            sys.exit("ERROR: OPENROUTER_API_KEY is not set.")
        cfg = {
            "model":    OPENROUTER_MODEL,
            "api_key":  OPENROUTER_API_KEY,
            "base_url": OPENROUTER_BASE_URL,
            "api_type": "openai",
        }
        log.info("chatbot LLM: openrouter  model=%s", OPENROUTER_MODEL)

    return {
        "config_list": [cfg],
        "temperature": 0,
    }


# ── Exit condition ────────────────────────────────────────────────────────────

_EXIT_WORDS = {"exit", "quit", "bye", "goodbye"}


def _is_termination(msg: dict) -> bool:
    """
    End the conversation when:
      • the user types exit / quit / bye / goodbye, or
      • the AssistantAgent replies with the word TERMINATE.
    """
    content = (msg.get("content") or "").strip().lower()
    return content in _EXIT_WORDS or "terminate" in content


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_MESSAGE = """\
You are the Shipment Planner assistant.

You help users query warehouse capacity, find optimal routes, compare carriers,
and obtain shipping quotes using the tools available to you.

Warehouse → postal code mapping
────────────────────────────────
Use this table to translate an origin postal code into the correct warehouse ID
for the optimize_route tool.  Always pick the warehouse whose postal code
matches (or is closest to) the origin the user provides.

  wh-001  Chicago Central     60601
  wh-002  New York East       10001
  wh-003  Los Angeles West    90001

Examples:
  • origin = 60601  →  origin_warehouse_id = "wh-001"
  • origin = 10001  →  origin_warehouse_id = "wh-002"
  • origin = 90001  →  origin_warehouse_id = "wh-003"

Guidelines
──────────
• Call tools proactively when the user supplies enough information.
• If a required argument is missing, ask for it before calling the tool.
• Summarise tool results in plain language — do not dump raw JSON.
• When the user has no further questions, end your reply with the word TERMINATE
  on its own line so the session closes cleanly.
• Never fabricate data; always use the tools.

Available tools
───────────────
  get_warehouse_capacity    — check stock / space at a warehouse
  optimize_route            — best route + ETA between origin and destination
  get_available_carriers    — list carriers for a lane
  get_carrier_quote         — price quote from a specific carrier
"""

# ── Build agents ──────────────────────────────────────────────────────────────

def build_agents():
    try:
        import autogen
    except ImportError:
        sys.exit(
            "pyautogen is not installed.\n"
            "Run:  pip install pyautogen>=0.2.0"
        )

    llm_config = _build_llm_config()

    tools = [
        get_warehouse_capacity,
        optimize_route,
        get_available_carriers,
        get_carrier_quote,
    ]

    assistant = autogen.AssistantAgent(
        name="ShipmentPlannerBot",
        system_message=_SYSTEM_MESSAGE,
        llm_config=llm_config,
    )

    user_proxy = autogen.UserProxyAgent(
        name="User",
        human_input_mode="ALWAYS",          # always ask the real human
        is_termination_msg=_is_termination,
        code_execution_config=False,        # no code execution needed
        max_consecutive_auto_reply=0,       # no auto-replies; human drives
    )

    # Register each MCP tool so the AssistantAgent can call it and
    # UserProxyAgent can execute the actual function.
    for fn in tools:
        autogen.register_function(
            fn,
            caller=assistant,
            executor=user_proxy,
            description=fn.__doc__ or fn.__name__,
        )

    return assistant, user_proxy


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Shipment Planner AutoGen chatbot")
    parser.add_argument(
        "--first-message",
        default="Hello! I need help planning a shipment.",
        help="Opening message sent by the user to kick off the conversation.",
    )
    args = parser.parse_args()

    print("\n── Shipment Planner Chatbot ──────────────────────────────────────")
    print("  Type your question and press Enter.")
    print("  Type  exit  to end the session.\n")

    assistant, user_proxy = build_agents()

    user_proxy.initiate_chat(
        assistant,
        message=args.first_message,
    )

    print("\n── Session ended. ────────────────────────────────────────────────\n")


if __name__ == "__main__":
    main()
