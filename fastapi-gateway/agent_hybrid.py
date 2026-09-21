"""
Shipment Planning — Hybrid (LangGraph StateGraph + explicit MCP tool nodes)

Architecture
────────────
  One dedicated pipeline node replaces the two original MCP nodes.
  It delegates all MCP reads to the shared mcp_pipeline framework using
  run_parallel_planning_pipeline():

    Round 1 (parallel) — GetWarehouseCapacity + OptimizeRoute  (asyncio.gather)
    Round 2            — GetAvailableCarriers  (needs origin_postal from R1)
    Round 3            — GetCarrierQuote        (needs best_carrier from R2)

  Each step is a self-contained MCPToolStep subclass (see mcp_pipeline.py)
  that declares its inputs, validates its output, and writes to the shared
  ToolContext.  Adding a new read tool = one new subclass; nothing else changes.

  pipeline_node   Runs all four read steps via run_planning_pipeline()
  plan_gate       HLT interrupt – Gate 1 (review plan; nothing written yet)
  create_ship     CreateShipment + BookCarrier  ← direct GraphQL (MCP is read-only)
  dock_gate       HLT interrupt – Gate 2 (review dock slot)
  book_dock       BookDockSlot                  ← direct GraphQL

vs V3
─────
  V3  sends one combined GraphQL document; Apollo Router fans out subgraphs
      server-side.

  Hybrid explicitly names each MCP tool via the pipeline framework,
  giving full visibility into each tool call (inputs → outputs → errors)
  while the graph controls the HITL gates and mutation nodes.

Imports
───────
  agent_hitl  — imported for side-effects only: applies the MCP protocol patch
                ("2024-11-05") that Apollo MCP Server requires.
  agent_v3    — _gql / _check helpers and the three mutation strings are reused
                as-is; no boilerplate is duplicated.
  mcp_pipeline — ToolContext + run_planning_pipeline (the shared read framework).
"""

import logging
import uuid
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
from mcp_pipeline import ToolContext, run_parallel_planning_pipeline

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


# ── State ─────────────────────────────────────────────────────────────────────

class HState(TypedDict):
    # input
    request: dict

    # phase 1 — plan data (written by pipeline_node)
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


# ── Pipeline node ─────────────────────────────────────────────────────────────

async def pipeline_node(state: HState) -> dict:
    """
    Runs all four MCP read steps through the shared pipeline framework with
    Round 1 parallelised via asyncio.gather():

      Round 1 (parallel) — GetWarehouseCapacity + OptimizeRoute
      Round 2            — GetAvailableCarriers  (needs origin_postal from R1)
      Round 3            — GetCarrierQuote        (needs best_carrier from R2)

    Each step logs → / ✓ / ✗ and writes its extracted values into the shared
    ToolContext.  On the first failure the pipeline stops and returns an error.
    """
    req   = state["request"]
    dst   = req["destinationAddress"]
    items = req.get("items", [])

    weight_kg = sum(float(i.get("weight", 0)) * int(i.get("quantity", 1)) for i in items) or 100.0
    volume_m3 = sum(float(i.get("volume", 0)) * int(i.get("quantity", 1)) for i in items) or 1.0
    priority  = req.get("priority", "STANDARD")
    service_level = "EXPRESS" if priority in ("EXPRESS", "OVERNIGHT", "SAME_DAY") else "STANDARD"

    log.info("hybrid pipeline_node: wh=%s dest=%s %.1fkg", req["originWarehouseId"], dst["postalCode"], weight_kg)

    ctx = ToolContext({
        "request":       req,
        "weight_kg":     weight_kg,
        "volume_m3":     volume_m3,
        "service_level": service_level,
    })

    tool_map = await _get_tools()
    ok, err  = await run_parallel_planning_pipeline(ctx, tool_map)

    if not ok:
        return {"status": "error", "error": err}

    return {
        "warehouse":     ctx["warehouse"],
        "capacity":      ctx["capacity"],
        "route":         ctx["route"],
        "carriers":      ctx["carriers"],
        "best_carrier":  ctx["best_carrier"],
        "quote":         ctx["quote"],
        "origin_postal": ctx["origin_postal"],
        "delivery_date": ctx["delivery_date"],
        "weight_kg":     weight_kg,
        "volume_m3":     volume_m3,
        "service_level": service_level,
        "status":        "reads_done",
        "error":         None,
    }


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

def _after_pipeline_node(state: HState) -> str:
    return END if state.get("error") else "plan_gate"


def _after_create_shipment(state: HState) -> str:
    return END if state.get("status") == "error" else "dock_gate"


# ── Graph ─────────────────────────────────────────────────────────────────────

_checkpointer = MemorySaver()


def _build_graph():
    g = StateGraph(HState)

    g.add_node("pipeline_node",    pipeline_node)
    g.add_node("plan_gate",        plan_gate)
    g.add_node("create_shipment",  create_shipment)
    g.add_node("dock_gate",        dock_gate)
    g.add_node("book_dock",        book_dock)

    g.add_edge(START, "pipeline_node")
    g.add_conditional_edges("pipeline_node",   _after_pipeline_node,   {"plan_gate": "plan_gate", END: END})
    # plan_gate / dock_gate return Command(goto=…) — no static edges needed
    g.add_conditional_edges("create_shipment", _after_create_shipment, {"dock_gate": "dock_gate", END: END})
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
    Phase 1 — pipeline_node (all four MCP read steps via mcp_pipeline framework).
    Pauses at Gate 1 (plan_gate).
    Returns {"status": "needs_plan_confirmation", "threadId": …, "plan": {…}}
         or {"status": "error", "threadId": …, "error": "…"}
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
