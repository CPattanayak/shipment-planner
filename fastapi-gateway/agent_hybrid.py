"""
Shipment Planning — Hybrid (LangGraph StateGraph + explicit MCP tool nodes)

Architecture
────────────
  Two dedicated MCP nodes replace the single Apollo-supergraph fan-out of V3.
  Each node creates its own MultiServerMCPClient, calls tools by name, and
  uses asyncio.gather() for the operations that are independent of each other.

  mcp_node_1   Round 1: asyncio.gather(get_warehouse_capacity, optimize_route)
               Round 2: get_available_carriers   (needs origin postal from R1)

  mcp_node_2   get_carrier_quote                 (tool-chains from best carrier)

  plan_gate    HLT interrupt – Gate 1 (review plan; nothing written yet)

  create_ship  CreateShipment + BookCarrier  ← direct GraphQL (MCP is read-only)

  dock_gate    HLT interrupt – Gate 2 (review dock slot)

  book_dock    BookDockSlot                  ← direct GraphQL

vs V3
─────
  V3  sends one combined GraphQL document; Apollo Router's query planner fans
      out warehouse + route subgraphs in parallel on the server side.

  Hybrid explicitly names each MCP tool, runs asyncio.gather() in Python, and
  chains node outputs as typed state — parallelism is visible in the code.

Imports
───────
  agent_hitl  — imported for side-effects only: applies the MCP protocol patch
                ("2024-11-05") that Apollo MCP Server requires.
  agent_v3    — _gql / _check helpers and the three mutation strings are reused
                as-is; no boilerplate is duplicated.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from typing_extensions import TypedDict

import agent_hitl  # noqa: F401 — side-effect: patches MCP protocol version

from langchain_mcp_adapters.client import MultiServerMCPClient
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
from config import MCP_SERVER_URL

log = logging.getLogger(__name__)

_MCP_CFG = {"shipment-planner": {"transport": "streamable_http", "url": MCP_SERVER_URL}}


# ── MCP helpers ───────────────────────────────────────────────────────────────

async def _get_tools() -> dict:
    """Return {tool_name: tool} dict from a fresh MCP client."""
    client = MultiServerMCPClient(_MCP_CFG)
    tools = await client.get_tools()
    tool_map = {t.name: t for t in tools}
    log.info("hybrid _get_tools: available=%s", list(tool_map.keys()))
    return tool_map


def _tool(t: dict, name: str):
    """Look up a tool by name; raise a clear error listing available tools."""
    if name not in t:
        available = list(t.keys())
        raise KeyError(f"MCP tool '{name}' not found. Available: {available}")


def _parse(raw) -> dict:
    """Normalise an MCP tool result (str, list-of-blocks, or dict) → dict."""
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, list):
        text = " ".join(b.get("text", "") for b in raw if isinstance(b, dict))
        return json.loads(text)
    return raw if isinstance(raw, dict) else {}


# ── State ─────────────────────────────────────────────────────────────────────

class HState(TypedDict):
    # input
    request: dict

    # phase 1 — plan data
    warehouse: dict
    capacity: dict
    route: dict
    carriers: list
    best_carrier: dict
    quote: dict
    origin_postal: str
    delivery_date: str
    weight_kg: float
    volume_m3: float
    service_level: str

    # phase 2 — shipment + booking
    shipment: dict
    booking: dict

    # phase 3 — dock slot
    dock_slot: dict
    dock_booked: bool

    # outcome
    status: str
    error: Optional[str]


# ── MCP Node 1 ────────────────────────────────────────────────────────────────

async def mcp_node_1(state: HState) -> dict:
    """
    Round 1  asyncio.gather(get_warehouse_capacity, optimize_route)
             Both need only warehouseId — they are fully independent.
    Round 2  get_available_carriers
             Needs origin postal code resolved in Round 1.
    """
    req  = state["request"]
    dst  = req["destinationAddress"]
    items = req.get("items", [])

    weight_kg = sum(float(i.get("weight", 0)) * int(i.get("quantity", 1)) for i in items) or 100.0
    volume_m3 = sum(float(i.get("volume", 0)) * int(i.get("quantity", 1)) for i in items) or 1.0
    priority  = req.get("priority", "STANDARD")
    service_level = "EXPRESS" if priority in ("EXPRESS", "OVERNIGHT", "SAME_DAY") else "STANDARD"

    log.info("hybrid mcp_node_1: wh=%s dest=%s %.1fkg", req["originWarehouseId"], dst["postalCode"], weight_kg)

    t = await _get_tools()

    # ── Round 1: parallel ──────────────────────────────────────────────────
    cap_raw, route_raw = await asyncio.gather(
        t["GetWarehouseCapacity"].ainvoke({"id": req["originWarehouseId"]}),
        t["OptimizeRoute"].ainvoke({
            "originWarehouseId":      req["originWarehouseId"],
            "destinationPostalCode":  dst["postalCode"],
            "destinationCountry":     dst.get("country", "US"),
            "weightKg":               weight_kg,
            "volumeM3":               volume_m3,
        }),
    )

    cap_data   = _parse(cap_raw).get("data", {})
    warehouse  = cap_data.get("warehouse")
    if not warehouse:
        return {"status": "error", "error": f"Warehouse '{req['originWarehouseId']}' not found."}

    capacity   = cap_data.get("warehouseCapacity", {})
    origin_postal = warehouse.get("address", {}).get("postalCode", "")
    if not origin_postal:
        return {"status": "error", "error": "Warehouse address / postal code missing."}

    opt_data = _parse(route_raw).get("data", {})
    route    = opt_data.get("optimizeRoute")
    if not route:
        return {"status": "error", "error": f"No route found from '{req['originWarehouseId']}' to {dst['postalCode']}."}

    log.info("hybrid mcp_node_1: origin_postal=%s route_ok", origin_postal)

    # ── Round 2: carriers (needs postal from Round 1) ──────────────────────
    carr_raw = await t["GetAvailableCarriers"].ainvoke({
        "originPostalCode":      origin_postal,
        "destinationPostalCode": dst["postalCode"],
        "weightKg":              weight_kg,
    })

    carriers = _parse(carr_raw).get("data", {}).get("availableCarriers", [])
    if not carriers:
        return {"status": "error", "error": f"No carriers available from {origin_postal} to {dst['postalCode']}."}

    best = max(carriers, key=lambda c: c.get("performance", {}).get("onTimeDeliveryRate", 0))
    log.info("hybrid mcp_node_1: best_carrier=%s", best.get("name"))

    raw_date    = route.get("estimatedDeliveryDate", "")
    delivery_dt = raw_date[:10] if raw_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "warehouse":    warehouse,
        "capacity":     capacity,
        "route":        route,
        "carriers":     carriers,
        "best_carrier": best,
        "origin_postal": origin_postal,
        "delivery_date": delivery_dt,
        "weight_kg":    weight_kg,
        "volume_m3":    volume_m3,
        "service_level": service_level,
        "status":       "reads_done",
        "error":        None,
    }


# ── MCP Node 2 ────────────────────────────────────────────────────────────────

async def mcp_node_2(state: HState) -> dict:
    """
    Tool-chains from mcp_node_1:
      best_carrier.id + origin_postal + dest postal + weight/volume → carrier quote.
    """
    req = state["request"]

    log.info("hybrid mcp_node_2: quote for carrier=%s", state["best_carrier"].get("id"))

    t = await _get_tools()
    q_raw = await t["GetCarrierQuote"].ainvoke({
        "carrierId":             state["best_carrier"]["id"],
        "originPostalCode":      state["origin_postal"],
        "destinationPostalCode": req["destinationAddress"]["postalCode"],
        "weightKg":              state["weight_kg"],
        "volumeM3":              state["volume_m3"],
        "serviceLevel":          state.get("service_level", "STANDARD"),
    })

    quote = _parse(q_raw).get("data", {}).get("carrierQuote")
    if not quote:
        return {"status": "error", "error": "Carrier quote unavailable."}

    log.info("hybrid mcp_node_2: total_cost=%s transit=%s", quote.get("totalCost"), quote.get("transitDays"))
    return {"quote": quote, "status": "quoted", "error": None}


# ── Gate 1: plan review (HLT interrupt) ───────────────────────────────────────

async def plan_gate(state: HState) -> Command:
    approved = interrupt({
        "gate":            "plan_review",
        "warehouse":       state.get("warehouse", {}),
        "capacity":        state.get("capacity", {}),
        "route":           state.get("route", {}),
        "selectedCarrier": state.get("best_carrier", {}),
        "allCarriers":     state.get("carriers", []),
        "quote":           state.get("quote", {}),
        "deliveryDate":    state.get("delivery_date", ""),
        "weightKg":        state.get("weight_kg", 0),
        "volumeM3":        state.get("volume_m3", 0),
    })
    if approved:
        return Command(goto="create_shipment")
    return Command(goto=END, update={"status": "rejected_at_plan", "dock_booked": False})


# ── Create shipment + book carrier (direct GraphQL — MCP is read-only) ────────

async def create_shipment(state: HState) -> dict:
    req           = state["request"]
    dest          = req["destinationAddress"]
    carrier       = state["best_carrier"]
    delivery_date = state["delivery_date"]
    service_level = state.get("service_level", "STANDARD")

    log.info("hybrid create_shipment: carrier=%s", carrier.get("id"))

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
    log.info("hybrid create_shipment: id=%s tracking=%s", shipment_id, shipment.get("trackingNumber"))

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
    log.info("hybrid create_shipment: bookingId=%s", booking.get("bookingId"))
    return {"shipment": shipment, "booking": booking, "status": "shipment_created"}


# ── Gate 2: dock slot review (HLT interrupt) ──────────────────────────────────

async def dock_gate(state: HState) -> Command:
    if state.get("status") == "error":
        return Command(goto=END)

    shipment      = state.get("shipment", {})
    delivery_date = state.get("delivery_date", "")

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


# ── Book dock slot (direct GraphQL) ──────────────────────────────────────────

async def book_dock(state: HState) -> dict:
    req           = state["request"]
    shipment      = state.get("shipment", {})
    delivery_date = state.get("delivery_date", "")

    log.info("hybrid book_dock: shipmentId=%s", shipment.get("id"))

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
    log.info("hybrid book_dock: slotId=%s", dock_slot.get("id"))
    return {"dock_slot": dock_slot, "dock_booked": True, "status": "done"}


# ── Conditional edges ─────────────────────────────────────────────────────────

def _after_mcp_node_1(state: HState) -> str:
    return END if state.get("error") else "mcp_node_2"


def _after_mcp_node_2(state: HState) -> str:
    return END if state.get("error") else "plan_gate"


def _after_create_shipment(state: HState) -> str:
    return END if state.get("status") == "error" else "dock_gate"


# ── Graph ─────────────────────────────────────────────────────────────────────

_checkpointer = MemorySaver()


def _build_graph():
    g = StateGraph(HState)

    g.add_node("mcp_node_1",      mcp_node_1)
    g.add_node("mcp_node_2",      mcp_node_2)
    g.add_node("plan_gate",       plan_gate)
    g.add_node("create_shipment", create_shipment)
    g.add_node("dock_gate",       dock_gate)
    g.add_node("book_dock",       book_dock)

    g.add_edge(START, "mcp_node_1")
    g.add_conditional_edges("mcp_node_1",      _after_mcp_node_1,      {"mcp_node_2": "mcp_node_2", END: END})
    g.add_conditional_edges("mcp_node_2",      _after_mcp_node_2,      {"plan_gate": "plan_gate",   END: END})
    # plan_gate / dock_gate return Command(goto=…) — no static edges needed
    g.add_conditional_edges("create_shipment", _after_create_shipment, {"dock_gate": "dock_gate",   END: END})
    g.add_edge("book_dock", END)

    return g.compile(checkpointer=_checkpointer)


_graph = _build_graph()


# ── Graph helpers ─────────────────────────────────────────────────────────────

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _get_interrupt(snapshot) -> dict | None:
    for task in (getattr(snapshot, "tasks", None) or []):
        for intr in (getattr(task, "interrupts", None) or []):
            return getattr(intr, "value", None)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

async def start_plan(request: dict) -> dict:
    """
    Phase 1 — mcp_node_1 + mcp_node_2.
    Pauses at Gate 1 (plan_gate).
    Returns {"status": "needs_plan_confirmation", "threadId": …, "plan": {…}}
         or {"status": "error", "error": "…"}
    """
    thread_id = str(uuid.uuid4())
    config    = _config(thread_id)

    await _graph.ainvoke({"request": request, "status": "planning"}, config=config)
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
    approved=False → graph ends; nothing written
    """
    config = _config(thread_id)
    await _graph.ainvoke(Command(resume=approved), config=config)
    snapshot = await _graph.aget_state(config)
    vals     = snapshot.values

    if vals.get("status") == "error":
        return {"status": "error", "threadId": thread_id,
                "error": vals.get("error"), "shipment": vals.get("shipment")}

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
