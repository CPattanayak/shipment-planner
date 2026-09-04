"""
Shipment Planning — V4 (LangGraph StateGraph + LLM agentic loop over MCP read tools)

Architecture
────────────
  llm_plan_node   LLM (ChatOpenAI via OpenRouter) with all four MCP read tools
                  bound.  The LLM runs a native tool-use loop and decides:
                    • which tools to call
                    • in what order
                    • with what arguments
                  guided by a system prompt.

                  After the loop, raw tool results are processed through the
                  mcp_pipeline MCPToolStep classes — their extract() and
                  validate() methods normalise and validate each result with the
                  same standardised ✓ / ✗ logging used by the Hybrid pipeline.

  plan_gate       HLT interrupt — Gate 1: human reviews plan; nothing written yet.

  create_shipment CreateShipment + BookCarrier (direct GraphQL mutations).

  dock_gate       HLT interrupt — Gate 2: human reviews dock slot.

  book_dock       BookDockSlot (direct GraphQL mutation).

vs Hybrid
─────────
  Hybrid uses run_planning_pipeline() — a fixed PLANNING_STEPS list the Python
  code executes deterministically.

  V4 lets the LLM orchestrate the same four tools via its native tool-use loop.
  The LLM controls order and arguments; any MCP-exposing service can be added by
  simply passing more tools to bind_tools() and updating the system prompt — no
  Python orchestration changes required.

  Both share the MCPToolStep classes for result extraction and validation, so
  error messages and log format are identical across both agents.

Imports
───────
  agent_hitl   — imported for side-effects only: patches MCP protocol version.
  agent_v3     — _gql / _check helpers and the three mutation strings.
  mcp_pipeline — MCPToolStep subclasses reused for extract() + validate().
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from typing_extensions import TypedDict

import agent_hitl  # noqa: F401 — side-effect: patches MCP protocol version

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
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
from mcp_pipeline import (
    ToolContext,
    MCPToolStep,
    GetWarehouseCapacityStep,
    OptimizeRouteStep,
    GetAvailableCarriersStep,
    GetCarrierQuoteStep,
)

log = logging.getLogger(__name__)


def _clean_error(exc_or_str) -> str:
    """
    Extract a clean, human-readable message from an exception or raw string that
    may contain a JSON GraphQL error response, a FastAPI detail blob, or a
    Python repr of an errors list.

    Priority:
      1. JSON body → errors[0].message
      2. JSON body → detail (string)
      3. Python-repr list → first element's 'message' key
      4. Original string as-is
    """
    s = str(exc_or_str)

    # 1. Try to parse a JSON object inside the string
    match = re.search(r'\{.*\}', s, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            # GraphQL errors array
            errors = data.get("errors")
            if isinstance(errors, list) and errors:
                msg = errors[0].get("message") if isinstance(errors[0], dict) else None
                if msg:
                    return msg
            # FastAPI detail
            detail = data.get("detail")
            if isinstance(detail, str) and detail:
                # detail might itself be a JSON string
                try:
                    inner = json.loads(detail)
                    errors2 = inner.get("errors")
                    if isinstance(errors2, list) and errors2:
                        msg = errors2[0].get("message") if isinstance(errors2[0], dict) else None
                        if msg:
                            return msg
                except Exception:
                    pass
                return detail
        except Exception:
            pass

    # 2. Python repr of a list, e.g. "[{'message': 'No route...', ...}]"
    match2 = re.search(r"\[.*\]", s, re.DOTALL)
    if match2:
        try:
            import ast
            items = ast.literal_eval(match2.group())
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict) and first.get("message"):
                    return first["message"]
        except Exception:
            pass

    return s


# ── Constants ─────────────────────────────────────────────────────────────────

READ_TOOLS = {"GetWarehouseCapacity", "OptimizeRoute", "GetAvailableCarriers", "GetCarrierQuote"}

SYSTEM_PROMPT = (
    "You are a shipment planning agent. Call tools in exactly THREE rounds:\n\n"
    "Round 1 — call BOTH simultaneously in a single response (they are independent):\n"
    "  • GetWarehouseCapacity(id=warehouseId)\n"
    "  • OptimizeRoute(originWarehouseId, destinationPostalCode, destinationCountry, weightKg, volumeM3)\n\n"
    "Round 2 — after Round 1 results arrive, call:\n"
    "  • GetAvailableCarriers(originPostalCode=<postalCode from GetWarehouseCapacity result>, "
    "destinationPostalCode, weightKg)\n\n"
    "Round 3 — after Round 2 results arrive:\n"
    "  1. From the GetAvailableCarriers result, pick the carrier with the HIGHEST "
    "performance.onTimeDeliveryRate.\n"
    "  2. Use that carrier's `id` field as carrierId — this is the full string identifier "
    "(e.g. 'carrier-abc-123'), NOT the carrier `code` (e.g. 'SRC'), NOT the `name`. "
    "The `id` field is what the system uses to look up the carrier; using any other field "
    "will cause a 'Carrier not found' error.\n"
    "  3. Call: GetCarrierQuote(carrierId=<carrier.id>, originPostalCode, "
    "destinationPostalCode, weightKg, volumeM3, serviceLevel)\n\n"
    "Do NOT call any other tools. Do NOT call mutations. "
    "Always emit Round 1 tools together in one response."
)

# Map each MCP tool name to the MCPToolStep that knows how to extract/validate it.
# The LLM decides IF and WHEN to call each tool; the step handles result processing.
_STEP_MAP: dict[str, MCPToolStep] = {
    "GetWarehouseCapacity":  GetWarehouseCapacityStep(),
    "OptimizeRoute":         OptimizeRouteStep(),
    "GetAvailableCarriers":  GetAvailableCarriersStep(),
    "GetCarrierQuote":       GetCarrierQuoteStep(),
}

_MCP_CFG = {"shipment-planner": {"transport": "streamable_http", "url": MCP_SERVER_URL}}


# ── State ─────────────────────────────────────────────────────────────────────

class V4State(TypedDict):
    # conversation messages from the agentic loop
    messages: list

    # input
    request: dict

    # plan data — packed into a single dict after the LLM loop
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


# ── LLM plan node ─────────────────────────────────────────────────────────────

async def llm_plan_node(state: V4State) -> dict:
    """
    Phase 1 — LLM agentic tool-use loop.

    The LLM is given all four MCP read tools and a system prompt that instructs
    it to call them in order.  It drives the loop entirely; Python only executes
    whatever tool calls the LLM emits and feeds the results back as ToolMessages.

    After the loop ends (no more tool_calls), each raw result is processed
    through its MCPToolStep.extract() + validate() — same logic and log format
    as the Hybrid pipeline — so errors surface consistently.
    """
    req   = state["request"]
    dst   = req["destinationAddress"]
    items = req.get("items", [])

    weight_kg = sum(float(i.get("weight", 0)) * int(i.get("quantity", 1)) for i in items) or 100.0
    volume_m3 = sum(float(i.get("volume", 0)) * int(i.get("quantity", 1)) for i in items) or 1.0
    priority  = req.get("priority", "STANDARD")
    service_level = "EXPRESS" if priority in ("EXPRESS", "OVERNIGHT", "SAME_DAY") else "STANDARD"

    log.info("v4 llm_plan_node: wh=%s dest=%s %.1fkg", req["originWarehouseId"], dst["postalCode"], weight_kg)

    # ── Build MCP client and filter to read tools only ────────────────────────
    client    = MultiServerMCPClient(_MCP_CFG)
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

    request_payload = {
        **req,
        "_derived": {
            "weightKg":    weight_kg,
            "volumeM3":    volume_m3,
            "serviceLevel": service_level,
        },
    }

    messages: list = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(request_payload)),
    ]

    # ── Agentic loop — LLM decides which tools to call ────────────────────────
    # When the LLM emits multiple tool_calls in one response (e.g. Round 1:
    # GetWarehouseCapacity + OptimizeRoute) we run them concurrently with
    # asyncio.gather() so independent tools don't wait on each other.
    raw_results: dict = {}

    while True:
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        # Filter to known read tools only
        valid = [tc for tc in response.tool_calls if tc["name"] in tool_map]
        unknown = [tc["name"] for tc in response.tool_calls if tc["name"] not in tool_map]
        if unknown:
            log.warning("v4 llm_plan_node: LLM tried unknown tools %s, skipping", unknown)

        if not valid:
            continue

        log.info("→ round: %s%s",
                 [tc["name"] for tc in valid],
                 "  [parallel]" if len(valid) > 1 else "")

        # Execute all tool calls in this round in parallel
        try:
            results = await asyncio.gather(*[
                tool_map[tc["name"]].ainvoke(tc["args"]) for tc in valid
            ])
        except Exception as exc:
            clean = _clean_error(exc)
            log.error("v4 llm_plan_node: tool gather raised: %s", clean)
            return {"messages": messages, "status": "error", "error": clean}

        for tc, result in zip(valid, results):
            raw_results[tc["name"]] = result
            messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"], name=tc["name"])
            )

    log.info("v4 llm_plan_node: tools_called=%s", list(raw_results.keys()))

    # ── Post-loop: extract + validate via MCPToolStep classes ─────────────────
    # Build a ToolContext so extract() calls can chain (e.g. OptimizeRoute
    # inputs read origin_postal that GetWarehouseCapacity wrote).
    ctx = ToolContext({
        "request":       req,
        "weight_kg":     weight_kg,
        "volume_m3":     volume_m3,
        "service_level": service_level,
    })

    for tool_name, step in _STEP_MAP.items():
        raw = raw_results.get(tool_name)
        if raw is None:
            err = f"LLM did not call {tool_name}. Tools called: {list(raw_results.keys())}"
            log.error("✗ %-30s  %s", tool_name, err)
            return {"messages": messages, "status": "error", "error": err}

        parsed  = MCPToolStep._parse(raw)
        data    = parsed.get("data", parsed)

        # Surface GraphQL errors
        gql_errors = parsed.get("errors") or data.get("errors")
        if gql_errors:
            first = gql_errors[0] if isinstance(gql_errors, list) else gql_errors
            raw_msg = first.get("message", str(gql_errors)) if isinstance(first, dict) else str(gql_errors)
            err = f"[{tool_name}] {raw_msg}"
            log.error("✗ %-30s  errors=%s", tool_name, gql_errors)
            return {"messages": messages, "status": "error", "error": err}

        try:
            extracted = step.extract(data, ctx)
        except Exception as exc:
            err = f"{tool_name} extract() raised: {exc}"
            log.error("✗ %-30s  %s", tool_name, err)
            return {"messages": messages, "status": "error", "error": err}

        validation_err = step.validate(extracted, ctx)
        if validation_err:
            log.warning("✗ %-30s  %s", tool_name, validation_err)
            return {"messages": messages, "status": "error", "error": validation_err}

        ctx.update(extracted)

        summary = {
            k: (f"{str(v)[:60]}…" if isinstance(v, str) and len(v) > 60
                else type(v).__name__ if not isinstance(v, (str, int, float, bool))
                else v)
            for k, v in extracted.items()
        }
        log.info("✓ %-30s  → %s", tool_name, summary)

    # ── Pack extracted context into a plan dict ───────────────────────────────
    raw_date      = (ctx.get("route") or {}).get("estimatedDeliveryDate", "")
    delivery_date = ctx.get("delivery_date") or (
        raw_date[:10] if raw_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )

    plan = {
        "warehouse":     ctx["warehouse"],
        "capacity":      ctx["capacity"],
        "origin_postal": ctx["origin_postal"],
        "route":         ctx["route"],
        "delivery_date": delivery_date,
        "carriers":      ctx["carriers"],
        "best_carrier":  ctx["best_carrier"],
        "quote":         ctx["quote"],
        "weight_kg":     weight_kg,
        "volume_m3":     volume_m3,
        "service_level": service_level,
    }

    log.info("v4 llm_plan_node: plan ready — delivery=%s cost=%s",
             delivery_date, (ctx.get("quote") or {}).get("totalCost"))
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

    g.add_node("llm_plan_node",    llm_plan_node)
    g.add_node("plan_gate",        plan_gate)
    g.add_node("create_shipment",  create_shipment)
    g.add_node("dock_gate",        dock_gate)
    g.add_node("book_dock",        book_dock)

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
    Phase 1 — llm_plan_node (LLM agentic loop + MCPToolStep extraction).
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
