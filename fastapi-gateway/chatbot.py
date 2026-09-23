"""
Shipment Planner — AutoGen 0.4.x Chatbot
─────────────────────────────────────────
Shared module imported by chat_router.py.
  • _SYSTEM_MESSAGE  — system prompt used by the web API and CLI
  • main()           — optional CLI entry point for local testing

All MCP tools (GetWarehouseCapacity, OptimizeRoute, etc.) are discovered
automatically via McpWorkbench — no manual function wrappers needed.
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from config import (
    LLM_PROVIDER,
    MCP_SERVER_URL,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    MISTRAL_API_KEY, MISTRAL_MODEL,
)

# ── System prompt ─────────────────────────────────────────────────────────────
# Imported by chat_router.py — keep it here as the single source of truth.

_SYSTEM_MESSAGE = """\
You are the Shipment Planner assistant.

You help users query warehouse capacity, find optimal routes, compare carriers,
and obtain shipping quotes using the tools available to you.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL ARGUMENT REFERENCE  (use EXACTLY these argument names)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GetWarehouseCapacity
  • id: String  — warehouse ID (e.g. "wh-001")

GetAvailableCarriers
  • originPostalCode: String       — origin ZIP/postal (e.g. "60601")
  • destinationPostalCode: String  — destination ZIP/postal (e.g. "10001")
  • weightKg: Float                — shipment weight in kilograms
  ↳ Returns carrier metadata (capabilities, modes, contact) — NOT prices.
    Use ONLY for Scenario A (general route planning), never for price quotes.

GetCarrierQuote
  • carrierId: String       — carrier database ID (see Carrier ID table below).
                              NEVER pass the carrier name here.
  • originPostalCode: String
  • destinationPostalCode: String
  • weightKg: Float
  • volumeM3: Float
  • serviceLevel: String   — REQUIRED. Exactly one of: "STANDARD", "EXPRESS", "OVERNIGHT".
                              "standard"/"normal"/"regular" → "STANDARD"
                              "express"/"fast"/"urgent"     → "EXPRESS"
                              "overnight"/"next day"        → "OVERNIGHT"
                              Default when not specified: "STANDARD"
  ↳ Returns the actual PRICE: totalCost, baseRate, fuelSurcharge, transitDays.

OptimizeRoute
  • originWarehouseId: String      — warehouse ID (e.g. "wh-001")
  • destinationPostalCode: String  — destination ZIP/postal
  • destinationCountry: String     — default "US"
  • weightKg: Float
  • volumeM3: Float
  • requiredDeliveryDate: String   — optional, ISO date "YYYY-MM-DD"

Warehouse → postal code mapping
────────────────────────────────
  wh-001  Chicago Central     60601
  wh-002  New York East       10001
  wh-003  Los Angeles West    90001

Carrier ID table  ← use these IDs directly in GetCarrierQuote
──────────────────────────────────────────────────────────────
  car-001  FastFreight USA    (road, up to 25,000 kg)
  car-002  CoolChain Express  (road, temperature-controlled, up to 10,000 kg)
  car-003  HazMat Logistics   (road, hazardous, up to 5,000 kg)
  car-004  BulkMove Inc       (road + rail, up to 50,000 kg)
  car-005  SkyRush Air Cargo  (air, up to 15,000 kg)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL CALLING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCENARIO A — User gives origin + destination (general route planning):
  Call ALL THREE simultaneously:
  1. GetWarehouseCapacity(id=<warehouseId for origin>)
  2. GetAvailableCarriers(originPostalCode, destinationPostalCode, weightKg)
  3. OptimizeRoute(originWarehouseId, destinationPostalCode, destinationCountry="US",
                   weightKg, volumeM3)

SCENARIO B — User asks for a rate, quote, price, or cost from a carrier:
  Look up the carrierId from the Carrier ID table above.
  Call ONLY GetCarrierQuote — do NOT call GetAvailableCarriers.

  GetCarrierQuote(
    carrierId            = <id from Carrier ID table>
    originPostalCode     = <from message or history>
    destinationPostalCode = <from message or history>
    weightKg             = <from message or history>
    volumeM3             = <from message or history, or weightKg × 0.003>
    serviceLevel         = "STANDARD" | "EXPRESS" | "OVERNIGHT"
  )

  Reply with the totalCost, transitDays, and serviceLevel from the result.

Input shorthand: "<origin postal>,<destination postal>,<weight kg>,<volume m³>"
  Example: "60601,10001,15,5" → origin=60601, dest=10001, weight=15 kg, volume=5 m³
If volumeM3 is missing, estimate: weightKg × 0.003.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GENERAL GUIDELINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Call tools proactively — do not ask for clarification when origin/destination/weight
  are already in the message or conversation history.
• NEVER show raw JSON or tool output to the user. Summarise in plain language.
• After all tool calls are complete, write a clear reply with bullet points.
• When the user has no further questions, end your reply with TERMINATE.
• Never fabricate data; always use the tools.
"""


# ── CLI entry point (optional — for local testing without Docker) ─────────────

async def _run_cli(first_message: str) -> None:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat
    from autogen_ext.models.openai import OpenAIChatCompletionClient
    from autogen_ext.tools.mcp import McpWorkbench, StreamableHttpServerParams

    if LLM_PROVIDER == "mistral":
        model_client = OpenAIChatCompletionClient(
            model=MISTRAL_MODEL,
            api_key=MISTRAL_API_KEY,
            base_url="https://api.mistral.ai/v1",
        )
    else:
        model_client = OpenAIChatCompletionClient(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )

    async with McpWorkbench(
            server_params=StreamableHttpServerParams(url=MCP_SERVER_URL)
    ) as workbench:
        agent = AssistantAgent(
            name="ShipmentPlannerBot",
            model_client=model_client,
            workbench=workbench,
            system_message=_SYSTEM_MESSAGE,
        )

        termination = TextMentionTermination("TERMINATE")
        team = RoundRobinGroupChat([agent], termination_condition=termination)

        print("\n── Shipment Planner Chatbot ──────────────────────────────────")
        print("  MCP tools auto-discovered from:", MCP_SERVER_URL)
        print("  Type exit to end.\n")

        await team.run(task=first_message)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Shipment Planner chatbot (CLI)")
    parser.add_argument(
        "--first-message",
        default="Hello! I need help planning a shipment.",
    )
    args = parser.parse_args()
    asyncio.run(_run_cli(args.first_message))


if __name__ == "__main__":
    main()