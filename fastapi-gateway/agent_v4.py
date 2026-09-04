"""
Shipment Planning — V4 (LangGraph StateGraph + LLM agentic loop over MCP read tools)

Architecture
────────────
  llm_plan_node   LLM (ChatOpenAI via OpenRouter) with MCP read tools bound.
                  Runs an agentic loop that calls exactly 4 tools IN ORDER:
                    1) GetWarehouseCapacity
                    2) OptimizeRoute
                    3) GetAvailableCarriers
                    4) GetCarrierQuote
                  After the loop, structured plan data is extracted from the
                  ToolMessage results stored in the message history.

  plan_gate       HLT interrupt — Gate 1: human reviews plan; nothing written yet.

  create_shipment CreateShipment + BookCarrier (direct GraphQL mutations).

  dock_gate       HLT interrupt — Gate 2: human reviews dock slot.

  book_dock       BookDockSlot (direct GraphQL mutation).

vs Hybrid
─────────
  Hybrid explicitly orchestrates each MCP call in Python and uses asyncio.gather()
  for parallelism.  V4 delegates the orchestration to the LLM: the model decides
  when to call each tool and with what arguments, guided by a system prompt that
  instructs it to call them in a fixed sequence and never call mutations.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from typing_extensions import TypedDict

import agent_hitl  # noqa: F401 — side-effect: patches MCP protocol version

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent_v3 import (
    _gql,
    _check,
    _M_CREATE_SHIPMENT,
    _M_BOOK_CARRIER,
    _M_BOOK_DOCK_SLOT,
)
from config import (
    MCP_SERVER_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
)

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

READ_TOOLS = {"GetWarehouseCapacity", "OptimizeRoute", "GetAvailableCarriers", "GetCarrierQuote"}

SYSTEM_PROMPT = (
    "You are a shipment planning agent. "
    "Call these tools IN ORDER, each ONCE:\n"
    "  1) GetWarehouseCapacity(id=warehouseId)\n"
    "  2) OptimizeRoute(originWarehouseId, destinationPostalCode, destinationCountry, weightKg, volumeM3)\n"
    "  3) GetAvailableCarriers(originPostalCode from step 1, destinationPostalCode, weightKg)\n"
    "  4) GetCarrierQuote(carrierId=best carrier by onTimeDeliveryRate, originPostalCode, "
    "destinationPostalCode, weightKg, volumeM3, serviceLevel)\n"
    "Do not call any other tools. Do not call mutations."
)


# ── State ─────────────────────────────────────────────────────────────────────

class V4State(TypedDict):
    # conversation messages from the agentic loop
    messages: list

    # input
    request: dict

    # plan data extracted from tool results
    plan: dict

    # phase 2 — shipment + booking
    shipment: dict
    booking: dict

    # phase 3 — dock slot
    dock_slot: dict
    dock_booked: bool

    # outcome
    status: str
    error: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse(raw) -> dict:
    """Normalise an MCP tool result (str, list-of-blocks, or dict) → dict."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, list):
        text = " ".join(b.get("text", "") for b in raw if isinstance(b, dict))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


# ── LLM plan node ─────────────────────────────────────────────────────────────

async def llm_plan_node(state: V4State) -> dict:
    """
    Runs an LLM agentic loop that calls the 4 MCP read tools in order,
    then extracts structured plan data from the ToolMessage results.
    """
    req   = state["request"]
    dst   = req["destinationAddress"]
    items = req.get("items", [])

    weight_kg = sum(float(i.get("weight", 0)) * int(i.get("quantity", 1)) for i in items) or 100.0
    volume_m3 = sum(float(i.get("volume", 0)) * int(i.get("quantity", 1)) for i in items) or 1.0
    priority  = req.get("priority", "STANDARD")

    log.info("v4 llm_plan_node: wh=%s dest=%s %.1fkg", req["originWarehouseId"], dst["postalCode"], weight_kg)

    # ── Build MCP client and filter to read tools only ────────────────────────
    client    = MultiServerMCPClient({"shipment-planner": {"transport": "streamable_http", "url": MCP_SERVER_URL}})
    all_tools = await client.get_tools()
    tool_map  = {t.name: t for t in all_tools if t.name in READ_TOOLS}

    log.info("v4 llm_plan_node: read_tools=%s", list(tool_map.keys()))

    # ── Bind tools to LLM ─────────────────────────────────────────────────────
    llm = ChatOpenAI(
        model=OPENROUTER_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(list(tool_map.values()))

    # Enrich the human message with derived weight/volume so the LLM can pass
    # them directly to OptimizeRoute / GetAvailableCarriers / GetCarrierQuote.
    request_payload = {
        **req,
        "_derived": {
            "weightKg":    weight_kg,
            "volumeM3":    volume_m3,
            "serviceLevel": "EXPRESS" if priority in ("EXPRESS", "OVERNIGHT", "SAME_DAY") else "STANDARD",
        },
    }

    messages: list = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(request_payload)),
    ]

    # ── Agentic loop ──────────────────────────────────────────────────────────
    # Keep raw tool results so _parse() sees the original object, not str(obj).
    raw_results: dict = {}

    while True:
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            if tc["name"] not in tool_map:
                log.warning("v4 llm_plan_node: LLM tried unknown tool '%s', skipping", tc["name"])
                continue
            log.info("v4 llm_plan_node: calling tool=%s args=%s", tc["name"], tc["args"])
            result = await tool_map[tc["name"]].ainvoke(tc["args"])
            raw_results[tc["name"]] = result          # preserve original type
            messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"], name=tc["name"])
            )

    log.info("v4 llm_plan_node: tools_called=%s", list(raw_results.keys()))

    # Diagnose: dump raw result for GetWarehouseCapacity so we can see exactly what came back
    cap_raw_obj = raw_results.get("GetWarehouseCapacity")
    log.info("v4 GetWarehouseCapacity raw type=%s repr=%s",
             type(cap_raw_obj).__name__, repr(cap_raw_obj)[:400])

    if "GetWarehouseCapacity" not in raw_results:
        return {
            "messages": messages,
            "status": "error",
            "error": (
                f"LLM did not call GetWarehouseCapacity. "
                f"Tools actually called: {list(raw_results.keys())}. "
                f"Check the system prompt or LLM tool-choice settings."
            ),
        }

    # ── Extract plan data from raw tool results ───────────────────────────────
    # Use raw_results (not msg.content strings) so _parse() handles list/dict correctly.
    cap_parsed   = _parse(raw_results.get("GetWarehouseCapacity", {}))
    route_parsed = _parse(raw_results.get("OptimizeRoute", {}))
    carr_parsed  = _parse(raw_results.get("GetAvailableCarriers", {}))
    quote_parsed = _parse(raw_results.get("GetCarrierQuote", {}))

    log.info("v4 cap_parsed keys=%s", list(cap_parsed.keys()))

    # Handle both {data: {warehouse: ...}} and direct {warehouse: ...} shapes
    cap_data   = cap_parsed.get("data", cap_parsed)
    route_data = route_parsed.get("data", route_parsed)
    carr_data  = carr_parsed.get("data", carr_parsed)
    quote_data = quote_parsed.get("data", quote_parsed)

    warehouse = cap_data.get("warehouse")
    if not warehouse:
        # Surface the actual response so the error is actionable
        gql_errors = cap_parsed.get("errors") or cap_data.get("errors")
        detail = f"GraphQL errors: {gql_errors}" if gql_errors else f"cap_data keys={list(cap_data.keys())}"
        return {
            "messages": messages,
            "status": "error",
            "error": f"GetWarehouseCapacity returned no warehouse. {detail}",
        }

    capacity      = cap_data.get("warehouseCapacity", {})
    origin_postal = warehouse.get("address", {}).get("postalCode", "")
    if not origin_postal:
        return {
            "messages": messages,
            "status": "error",
            "error": "Warehouse address / postal code missing from GetWarehouseCapacity result.",
        }

    route = route_data.get("optimizeRoute")
    if not route:
        return {
            "messages": messages,
            "status": "error",
            "error": "OptimizeRoute returned no route data.",
        }

    raw_date      = route.get("estimatedDeliveryDate", "")
    delivery_date = raw_date[:10] if raw_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    carriers = carr_data.get("availableCarriers", [])
    if not carriers:
        return {
            "messages": messages,
            "status": "error",
            "error": "GetAvailableCarriers returned no carriers.",
        }

    best_carrier = max(carriers, key=lambda c: c.get("onTimeDeliveryRate", 0) if isinstance(c, dict) else 0)
    # onTimeDeliveryRate may be nested under performance
    if "performance" in best_carrier:
        best_carrier_rate_key = lambda c: c.get("performance", {}).get("onTimeDeliveryRate", 0)
        best_carrier = max(carriers, key=best_carrier_rate_key)

    log.info("v4 llm_plan_node: best_carrier=%s", best_carrier.get("name") or best_carrier.get("id"))

    quote = quote_data.get("carrierQuote")
    if not quote:
        return {
            "messages": messages,
            "status": "error",
            "error": "GetCarrierQuote returned no quote data.",
        }

    service_level = "EXPRESS" if priority in ("EXPRESS", "OVERNIGHT", "SAME_DAY") else "STANDARD"

    plan = {
        "warehouse":    warehouse,
        "capacity":     capacity,
        "origin_postal": origin_postal,
        "route":        route,
        "delivery_date": delivery_date,
        "carriers":     carriers,
        "best_carrier": best_carrier,
        "quote":        quote,
        "weight_kg":    weight_kg,
        "volume_m3":    volume_m3,
        "service_level": service_level,
    }

    log.info("v4 llm_plan_node: plan extracted — delivery=%s cost=%s", delivery_date, quote.get("totalCost"))
    return {"messages": messages, "plan": plan, "status": "llm_done", "error": None}


# ── Gate 1: plan review (HLT interrupt) ──────────────────────────────────────

async def plan_gate(state: V4State) -> Command:
    """Human reviews the plan before any DB write."""
    plan = state.get("plan", {})
    approved = interrupt({
        "gate":            "plan_review",
        "warehouse":       plan.get("warehouse", {}),
        "capacity":        plan.get("capacity", {}),
        "route":           plan.get("route", {}),
        "selectedCarrier": plan.get("best_carrier", {}),
        "allCarriers":     plan.get("carriers", []),
        "quote":           plan.get("quote", {}),
        "deliveryDate":    plan.get("delivery_date", ""),
        "weightKg":        plan.get("weight_kg", 0),
        "volumeM3":        plan.get("volume_m3", 0),
    })
    if approved:
        return Command(goto="create_shipment")
    return Command(goto=END, update={"status": "rejected_at_plan", "dock_booked": False})


# ── Create shipment + book carrier (direct GraphQL) ───────────────────────────

async def create_shipment(state: V4State) -> dict:
    """Phase 2 — CreateShipment then BookCarrier."""
    req           = state["request"]
    dest          = req["destinationAddress"]
    plan          = state["plan"]
    carrier       = plan["best_carrier"]
    delivery_date = plan["delivery_date"]
    service_level = plan.get("service_level", "STANDARD")

    log.info("v4 create_shipment: carrier=%s", carrier.get("id"))

    try:
        ship_data = _check(
            await _gql(_M_CREATE_SHIPMENT, {
                "originWarehouseId":     req["originWarehouseId"],
                "destinationStreet":     dest.get("street", ""),
                "destinationCity":       dest["city"],
                "destinationState":      dest.get("state", ""),
                "destinationCountry":    dest.get("country", "US"),
                "destinationPostalCode": dest["postalCode"],
                "items":                 req["items"],
                "priority":              req.get("priority", "STANDARD"),
                "specialInstructions":   req.get("specialInstructions", ""),
            }),
            "CreateShipment",
        )
    except ValueError as exc:
        return {"status": "error", "error": f"CreateShipment failed: {exc}"}

    shipment    = ship_data.get("createShipment", {})
    shipment_id = shipment.get("id")
    log.info("v4 create_shipment: id=%s tracking=%s", shipment_id, shipment.get("trackingNumber"))

    try:
        booking_data = _check(
            await _gql(_M_BOOK_CARRIER, {
                "carrierId":           carrier["id"],
                "shipmentId":          shipment_id,
                "serviceLevel":        service_level,
                "requestedPickupDate": delivery_date,
            }),
            "BookCarrier",
        )
    except ValueError as exc:
        return {"status": "error", "error": f"BookCarrier failed: {exc}", "shipment": shipment}

    booking = booking_data.get("bookCarrier", {})
    log.info("v4 create_shipment: bookingId=%s", booking.get("bookingId"))
    return {"shipment": shipment, "booking": booking, "status": "shipment_created"}


# ── Gate 2: dock slot review (HLT interrupt) ──────────────────────────────────

async def dock_gate(state: V4State) -> Command:
    """Human reviews and approves (or skips) the dock-slot booking."""
    if state.get("status") == "error":
        return Command(goto=END)

    shipment      = state.get("shipment", {})
    delivery_date = state.get("plan", {}).get("delivery_date", "")

    approved = interrupt({
        "gate":     "dock_review",
        "shipment": shipment,
        "booking":  state.get("booking", {}),
        "dockSlot": {
            "warehouseId": state["request"]["originWarehouseId"],
            "shipmentId":  shipment.get("id", ""),
            "dockNumber":  1,
            "date":        delivery_date,
            "startTime":   "08:00",
            "endTime":     "10:00",
            "type":        "PICKUP",
        },
    })
    if approved:
        return Command(goto="book_dock")
    return Command(goto=END, update={"status": "done", "dock_booked": False})


# ── Book dock slot (direct GraphQL) ───────────────────────────────────────────

async def book_dock(state: V4State) -> dict:
    """Phase 3 — BookDockSlot (only reached if Gate 2 was approved)."""
    req           = state["request"]
    shipment      = state.get("shipment", {})
    delivery_date = state.get("plan", {}).get("delivery_date", "")

    log.info("v4 book_dock: shipmentId=%s", shipment.get("id"))

    try:
        dock_data = _check(
            await _gql(_M_BOOK_DOCK_SLOT, {
                "warehouseId": req["originWarehouseId"],
                "dockNumber":  1,
                "date":        delivery_date,
                "startTime":   "08:00",
                "endTime":     "10:00",
                "shipmentId":  shipment["id"],
                "type":        "PICKUP",
            }),
            "BookDockSlot",
        )
    except ValueError as exc:
        return {"status": "error", "error": f"BookDockSlot failed: {exc}", "dock_booked": False}

    dock_slot = dock_data.get("bookDockSlot", {})
    log.info("v4 book_dock: slotId=%s", dock_slot.get("id"))
    return {"dock_slot": dock_slot, "dock_booked": True, "status": "done"}


# ── Conditional edges ─────────────────────────────────────────────────────────

def _after_llm_plan_node(state: V4State) -> str:
    return END if state.get("error") else "plan_gate"


def _after_create_shipment(state: V4State) -> str:
    return END if state.get("status") == "error" else "dock_gate"


# ── Graph ─────────────────────────────────────────────────────────────────────

_checkpointer = MemorySaver()


def _build_graph():
    g = StateGraph(V4State)

    g.add_node("llm_plan_node",   llm_plan_node)
    g.add_node("plan_gate",       plan_gate)
    g.add_node("create_shipment", create_shipment)
    g.add_node("dock_gate",       dock_gate)
    g.add_node("book_dock",       book_dock)

    g.add_edge(START, "llm_plan_node")
    g.add_conditional_edges("llm_plan_node",   _after_llm_plan_node,   {"plan_gate": "plan_gate", END: END})
    # plan_gate / dock_gate return Command(goto=...) — no static edges needed
    g.add_conditional_edges("create_shipment", _after_create_shipment, {"dock_gate": "dock_gate", END: END})
    g.add_edge("book_dock", END)

    return g.compile(checkpointer=_checkpointer)


_graph = _build_graph()


# ── Graph helpers ─────────────────────────────────────────────────────────────

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _get_interrupt(snapshot) -> dict | None:
    """Extract the first interrupt payload from a graph snapshot."""
    for task in (getattr(snapshot, "tasks", None) or []):
        for intr in (getattr(task, "interrupts", None) or []):
            return getattr(intr, "value", None)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

async def start_plan(request: dict) -> dict:
    """
    Phase 1 — llm_plan_node (LLM agentic loop over MCP read tools).
    Pauses at Gate 1 (plan_gate).
    Returns {"status": "needs_plan_confirmation", "threadId": ..., "plan": {...}}
         or {"status": "error", "threadId": ..., "error": "..."}
    """
    thread_id = str(uuid.uuid4())
    config    = _config(thread_id)

    await _graph.ainvoke({"request": request, "status": "planning", "messages": []}, config=config)
    snapshot  = await _graph.aget_state(config)
    vals      = snapshot.values

    if vals.get("status") == "error":
        return {"status": "error", "threadId": thread_id, "error": vals.get("error")}

    intr = _get_interrupt(snapshot)
    if intr:
        return {"status": "needs_plan_confirmation", "threadId": thread_id, "plan": intr}

    return {"status": "done", "threadId": thread_id, **vals}


async def confirm_plan(thread_id: str, approved: bool) -> dict:
    """
    Gate 1 resume.
    approved=True  → create_shipment + book_carrier → pauses at Gate 2
    approved=False → graph ends; nothing is written to the DB
    """
    config = _config(thread_id)
    await _graph.ainvoke(Command(resume=approved), config=config)
    snapshot = await _graph.aget_state(config)
    vals     = snapshot.values

    if vals.get("status") == "error":
        return {
            "status":   "error",
            "threadId": thread_id,
            "error":    vals.get("error"),
            "shipment": vals.get("shipment"),
        }

    intr = _get_interrupt(snapshot)
    if intr:
        return {"status": "needs_dock_confirmation", "threadId": thread_id, "dockData": intr}

    return {
        "status":    vals.get("status", "rejected_at_plan"),
        "threadId":  thread_id,
        "shipment":  vals.get("shipment"),
        "booking":   vals.get("booking"),
        "dockBooked": vals.get("dock_booked", False),
    }


async def confirm_dock(thread_id: str, approved: bool) -> dict:
    """
    Gate 2 resume.
    approved=True  → BookDockSlot → dockBooked True
    approved=False → dock skipped → dockBooked False
    """
    config = _config(thread_id)
    await _graph.ainvoke(Command(resume=approved), config=config)
    snapshot = await _graph.aget_state(config)
    vals     = snapshot.values

    return {
        "status":    "done",
        "threadId":  thread_id,
        "shipment":  vals.get("shipment"),
        "booking":   vals.get("booking"),
        "dockBooked": vals.get("dock_booked", False),
        "dockSlot":  vals.get("dock_slot"),
        "error":     vals.get("error"),
    }
