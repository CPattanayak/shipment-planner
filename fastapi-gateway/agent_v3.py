"""
Shipment Planning — V3 (LangGraph StateGraph + Apollo Federation supergraph fan-out)

Flow
────
  plan_reads ──[ok]──► plan_gate (HLT 1: review plan) ──[approved]──► create_shipment
             ──[err]──► END                             ──[rejected]──► END
                                                                          │
                                                          dock_gate (HLT 2: review dock slot)
                                                          ──[approved]──► book_dock ──► END
                                                          ──[rejected]──► END

Parallelism
───────────
  Round 1  Single supergraph query: warehouse + warehouseCapacity + optimizeRoute
           Apollo Router query-plans the warehouse subgraph call and the route
           subgraph call in PARALLEL — no asyncio.gather needed in Python.

  Round 2  availableCarriers (needs origin postal code from Round 1)

  Round 3  carrierQuote (needs best-carrier ID from Round 2)

  Apollo Gateway also applies its response cache to every subgraph call,
  so repeated read queries (same warehouse, same route) are served from cache.

Error handling
──────────────
  If any read returns missing/empty data (warehouse not found, route missing,
  no carriers), plan_reads stores an error in state and the conditional edge
  routes straight to END — the HITL gates are never shown.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from typing_extensions import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from config import GRAPHQL_ENDPOINT
import httpx


# ── GraphQL helpers ───────────────────────────────────────────────────────────

async def _gql(query: str, variables: dict) -> dict:
    """Execute one GraphQL operation against the Apollo Router.

    Always parses the response body before checking the HTTP status so that
    Apollo Router's GraphQL error messages (returned even on 400 responses)
    are surfaced as clean ValueError strings instead of raw httpx exceptions.
    """
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            resp = await c.post(
                GRAPHQL_ENDPOINT,
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json"},
            )
        except httpx.RequestError as exc:
            raise ValueError(f"Cannot reach GraphQL service ({exc.__class__.__name__})") from exc

        # Parse JSON body regardless of HTTP status — Apollo Router embeds
        # structured errors in the body even for 4xx responses.
        try:
            body = resp.json()
        except Exception:
            raise ValueError(f"GraphQL service returned {resp.status_code} (non-JSON body)")

        if not resp.is_success:
            if isinstance(body.get("errors"), list) and body["errors"]:
                msg = body["errors"][0].get("message", f"GraphQL error ({resp.status_code})")
            else:
                msg = f"GraphQL service returned {resp.status_code}"
            raise ValueError(msg)

        return body


def _check(result: dict, label: str) -> dict:
    """Raise ValueError if the result contains GraphQL errors."""
    if result.get("errors"):
        msg = result["errors"][0].get("message", str(result["errors"]))
        raise ValueError(f"{label} failed: {msg}")
    return result.get("data", {})


# ── Mutation strings ──────────────────────────────────────────────────────────

_M_CREATE_SHIPMENT = """
mutation CreateShipment(
  $originWarehouseId: ID!
  $destinationStreet: String
  $destinationCity: String!
  $destinationState: String
  $destinationCountry: String!
  $destinationPostalCode: String!
  $items: [ShipmentItemInput!]!
  $priority: ShipmentPriority!
  $scheduledPickup: String
  $specialInstructions: String
) {
  createShipment(input: {
    originWarehouseId: $originWarehouseId
    destinationAddress: {
      street: $destinationStreet
      city: $destinationCity
      state: $destinationState
      country: $destinationCountry
      postalCode: $destinationPostalCode
    }
    items: $items
    priority: $priority
    scheduledPickup: $scheduledPickup
    specialInstructions: $specialInstructions
  }) {
    id trackingNumber status priority originWarehouseId
    totalWeight totalVolume totalValue createdAt
    destinationAddress { street city state country postalCode }
  }
}
"""

_M_BOOK_CARRIER = """
mutation BookCarrier(
  $carrierId: ID!
  $shipmentId: ID!
  $serviceLevel: String!
  $requestedPickupDate: String!
) {
  bookCarrier(input: {
    carrierId: $carrierId
    shipmentId: $shipmentId
    serviceLevel: $serviceLevel
    requestedPickupDate: $requestedPickupDate
  }) {
    bookingId carrierId shipmentId confirmedAt
    pickupWindow estimatedDelivery trackingNumber
  }
}
"""

_M_BOOK_DOCK_SLOT = """
mutation BookDockSlot(
  $warehouseId: ID!
  $dockNumber: Int!
  $date: String!
  $startTime: String!
  $endTime: String!
  $shipmentId: ID!
  $type: DockSlotType!
) {
  bookDockSlot(input: {
    warehouseId: $warehouseId
    dockNumber: $dockNumber
    date: $date
    startTime: $startTime
    endTime: $endTime
    shipmentId: $shipmentId
    type: $type
  }) {
    id warehouseId dockNumber date startTime endTime shipmentId type status
  }
}
"""

log = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class ShipmentState(TypedDict):
    # ── input ──────────────────────────────────────────────────────────────
    request: dict

    # ── plan data (phase 1) ────────────────────────────────────────────────
    warehouse: dict
    capacity: dict
    route: dict
    all_carriers: list
    selected_carrier: dict
    quote: dict
    delivery_date: str
    origin_postal: str
    weight_kg: float
    volume_m3: float
    service_level: str

    # ── shipment + booking (phase 2) ───────────────────────────────────────
    shipment: dict
    booking: dict

    # ── dock slot (phase 3) ────────────────────────────────────────────────
    dock_slot: dict
    dock_booked: bool

    # ── outcome ────────────────────────────────────────────────────────────
    status: str
    error: Optional[str]


# ── Combined supergraph queries ───────────────────────────────────────────────
#
# Round 1: one document → Apollo Router fetches warehouse subgraph AND route
# subgraph in parallel (its query planner sees they are independent entities).
#
_Q_PLAN_INITIAL = """
query PlanInitial(
  $warehouseId: ID!
  $destPostalCode: String!
  $destCountry: String!
  $weightKg: Float!
  $volumeM3: Float!
  $totalValueUsd: Float!
  $hasHazardous: Boolean!
  $requiresTemperatureControl: Boolean!
  $priority: String!
) {
  warehouse(id: $warehouseId) {
    id name code
    address { street city state country postalCode }
  }
  warehouseCapacity(id: $warehouseId) {
    warehouseId totalM3 usedM3 availableM3 utilizationPct pendingShipments
  }
  optimizeRoute(input: {
    originWarehouseId: $warehouseId
    destinationPostalCode: $destPostalCode
    destinationCountry: $destCountry
    weightKg: $weightKg
    volumeM3: $volumeM3
    totalValueUsd: $totalValueUsd
    hasHazardous: $hasHazardous
    requiresTemperatureControl: $requiresTemperatureControl
    priority: $priority
  }) {
    recommendedRoute {
      name transportMode totalDistanceKm estimatedDurationHours
    }
    estimatedDeliveryDate
    estimatedCost
  }
}
"""

# Round 2: carriers (needs origin postal resolved in round 1)
_Q_CARRIERS = """
query GetAvailableCarriers(
  $originPostalCode: String!
  $destinationPostalCode: String!
  $weightKg: Float!
  $hasHazardous: Boolean!
  $requiresTemperatureControl: Boolean!
  $serviceLevel: String!
) {
  availableCarriers(input: {
    originPostalCode: $originPostalCode
    destinationPostalCode: $destinationPostalCode
    weightKg: $weightKg
    hasHazardous: $hasHazardous
    requiresTemperatureControl: $requiresTemperatureControl
    serviceLevel: $serviceLevel
  }) {
    id name code
    performance { onTimeDeliveryRate averageDelayHours }
    capabilities {
      maxWeightKg hazardousAllowed temperatureControlled trackingAvailable
    }
  }
}
"""

# Round 3: quote (needs best carrier ID resolved in round 2)
_Q_QUOTE = """
query GetCarrierQuote(
  $carrierId: ID!
  $originPostalCode: String!
  $destinationPostalCode: String!
  $weightKg: Float!
  $volumeM3: Float!
  $serviceLevel: String!
) {
  carrierQuote(input: {
    carrierId: $carrierId
    originPostalCode: $originPostalCode
    destinationPostalCode: $destinationPostalCode
    weightKg: $weightKg
    volumeM3: $volumeM3
    serviceLevel: $serviceLevel
  }) {
    carrierId carrierName totalCost baseRate fuelSurcharge handlingFee
    transitDays serviceLevel validUntil
  }
}
"""


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def plan_reads(state: ShipmentState) -> dict:
    """
    Phase 1 — read-only supergraph queries.

    Round 1: PlanInitial (warehouse + capacity + route) sent as ONE document.
             Apollo Router parallelises warehouse subgraph ↔ route subgraph.
    Round 2: availableCarriers (needs origin postal from round 1)
    Round 3: carrierQuote     (needs best-carrier ID from round 2)

    Sets state["error"] and returns early if any required data is missing.
    """
    request     = state["request"]
    wh_id       = request["originWarehouseId"]
    dest        = request["destinationAddress"]
    dest_postal = dest["postalCode"]
    dest_country = dest.get("country", "US")
    items       = request.get("items", [])

    weight_kg = (
        sum(float(i.get("weight", 0)) * int(i.get("quantity", 1)) for i in items)
        or 100.0
    )
    volume_m3 = (
        sum(float(i.get("volume", 0)) * int(i.get("quantity", 1)) for i in items)
        or 1.0
    )
    total_value_usd = (
        sum(float(i.get("value", 0)) * int(i.get("quantity", 1)) for i in items)
        or 0.0
    )
    has_hazardous              = any(i.get("hazardous", False) for i in items)
    requires_temp_control      = any(i.get("temperatureControlled", False) for i in items)
    priority                   = request.get("priority", "STANDARD")
    service_level              = "EXPRESS" if priority in ("EXPRESS", "OVERNIGHT", "SAME_DAY") else "STANDARD"

    log.info("v3 plan_reads: wh=%s dest=%s %.1fkg %.2fm³", wh_id, dest_postal, weight_kg, volume_m3)

    # ── Round 1: Apollo Router fans out warehouse + route subgraphs in parallel ──
    try:
        initial_data = _check(
            await _gql(_Q_PLAN_INITIAL, {
                "warehouseId":               wh_id,
                "destPostalCode":            dest_postal,
                "destCountry":               dest_country,
                "weightKg":                  weight_kg,
                "volumeM3":                  volume_m3,
                "totalValueUsd":             total_value_usd,
                "hasHazardous":              has_hazardous,
                "requiresTemperatureControl": requires_temp_control,
                "priority":                  priority,
            }),
            "PlanInitial",
        )
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    warehouse = initial_data.get("warehouse")
    if not warehouse:
        return {"status": "error", "error": f"Warehouse '{wh_id}' not found."}

    capacity = initial_data.get("warehouseCapacity") or {}
    route    = initial_data.get("optimizeRoute")
    if not route:
        return {
            "status": "error",
            "error": f"No route found from warehouse '{wh_id}' to {dest_postal}, {dest_country}.",
        }

    origin_postal = warehouse.get("address", {}).get("postalCode", "")
    if not origin_postal:
        return {"status": "error", "error": "Warehouse address / postal code missing."}

    log.info("v3 plan_reads: origin_postal=%s", origin_postal)

    # ── Round 2: carriers ────────────────────────────────────────────────────
    try:
        carriers_data = _check(
            await _gql(_Q_CARRIERS, {
                "originPostalCode":          origin_postal,
                "destinationPostalCode":     dest_postal,
                "weightKg":                  weight_kg,
                "hasHazardous":              has_hazardous,
                "requiresTemperatureControl": requires_temp_control,
                "serviceLevel":              service_level,
            }),
            "GetAvailableCarriers",
        )
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    carriers = carriers_data.get("availableCarriers", [])
    if not carriers:
        return {
            "status": "error",
            "error": f"No carriers available from {origin_postal} to {dest_postal} for {weight_kg:.0f} kg.",
        }

    # Pick carrier with highest on-time delivery rate
    best = max(carriers, key=lambda c: c.get("performance", {}).get("onTimeDeliveryRate", 0))
    log.info("v3 plan_reads: best carrier=%s id=%s", best.get("name"), best.get("id"))

    # ── Round 3: quote ───────────────────────────────────────────────────────
    try:
        quote_data = _check(
            await _gql(_Q_QUOTE, {
                "carrierId":             best["id"],
                "originPostalCode":      origin_postal,
                "destinationPostalCode": dest_postal,
                "weightKg":              weight_kg,
                "volumeM3":              volume_m3,
                "serviceLevel":          service_level,
            }),
            "GetCarrierQuote",
        )
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    quote = quote_data.get("carrierQuote")
    if not quote:
        return {"status": "error", "error": "Carrier quote unavailable."}

    raw_date    = route.get("estimatedDeliveryDate", "")
    delivery_dt = raw_date[:10] if raw_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log.info("v3 plan_reads: done — delivery=%s cost=%s", delivery_dt, quote.get("totalCost"))
    return {
        "warehouse":       warehouse,
        "capacity":        capacity,
        "route":           route,
        "all_carriers":    carriers,
        "selected_carrier": best,
        "quote":           quote,
        "delivery_date":   delivery_dt,
        "origin_postal":   origin_postal,
        "weight_kg":       weight_kg,
        "volume_m3":       volume_m3,
        "service_level":   service_level,
        "status":          "planned",
        "error":           None,
    }


async def plan_gate(state: ShipmentState) -> Command:
    """
    HLT Gate 1 — human reviews the plan before any DB write.
    interrupt() pauses the graph; the resume value (True/False) is returned
    when the caller sends Command(resume=approved).
    """
    approved = interrupt({
        "gate":            "plan_review",
        "warehouse":       state.get("warehouse", {}),
        "capacity":        state.get("capacity", {}),
        "route":           state.get("route", {}),
        "selectedCarrier": state.get("selected_carrier", {}),
        "allCarriers":     state.get("all_carriers", []),
        "quote":           state.get("quote", {}),
        "deliveryDate":    state.get("delivery_date", ""),
        "weightKg":        state.get("weight_kg", 0),
        "volumeM3":        state.get("volume_m3", 0),
    })
    if approved:
        return Command(goto="create_shipment")
    return Command(goto=END, update={"status": "rejected_at_plan", "dock_booked": False})


async def create_shipment(state: ShipmentState) -> dict:
    """
    Phase 2 — CreateShipment then BookCarrier (automatic, no HITL between them).
    """
    request       = state["request"]
    dest          = request["destinationAddress"]
    carrier       = state["selected_carrier"]
    delivery_date = state["delivery_date"]
    service_level = state.get("service_level", "STANDARD")

    log.info("v3 create_shipment: carrier=%s", carrier.get("id"))

    # CreateShipment
    try:
        ship_data = _check(
            await _gql(_M_CREATE_SHIPMENT, {
                "originWarehouseId":     request["originWarehouseId"],
                "destinationStreet":     dest.get("street", ""),
                "destinationCity":       dest["city"],
                "destinationState":      dest.get("state", ""),
                "destinationCountry":    dest.get("country", "US"),
                "destinationPostalCode": dest["postalCode"],
                "items":                 request["items"],
                "priority":              request.get("priority", "STANDARD"),
                "specialInstructions":   request.get("specialInstructions", ""),
            }),
            "CreateShipment",
        )
    except ValueError as exc:
        return {"status": "error", "error": f"CreateShipment failed: {exc}"}

    shipment    = ship_data.get("createShipment", {})
    shipment_id = shipment.get("id")
    log.info("v3 create_shipment: id=%s tracking=%s", shipment_id, shipment.get("trackingNumber"))

    # BookCarrier (auto)
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
    log.info("v3 create_shipment: bookingId=%s", booking.get("bookingId"))

    return {"shipment": shipment, "booking": booking, "status": "shipment_created"}


async def dock_gate(state: ShipmentState) -> Command:
    """
    HLT Gate 2 — human reviews and approves (or skips) the dock-slot booking.
    """
    # Surface an error from create_shipment if it happened
    if state.get("status") == "error":
        return Command(goto=END)

    shipment      = state.get("shipment", {})
    delivery_date = state.get("delivery_date", "")

    approved = interrupt({
        "gate":      "dock_review",
        "shipment":  shipment,
        "booking":   state.get("booking", {}),
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


async def book_dock(state: ShipmentState) -> dict:
    """Phase 3 — BookDockSlot (only reached if Gate 2 was approved)."""
    request       = state["request"]
    shipment      = state.get("shipment", {})
    delivery_date = state.get("delivery_date", "")

    log.info("v3 book_dock: shipmentId=%s", shipment.get("id"))

    try:
        dock_data = _check(
            await _gql(_M_BOOK_DOCK_SLOT, {
                "warehouseId": request["originWarehouseId"],
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
    log.info("v3 book_dock: dockSlotId=%s", dock_slot.get("id"))
    return {"dock_slot": dock_slot, "dock_booked": True, "status": "done"}


# ── Routing ───────────────────────────────────────────────────────────────────

def _after_plan_reads(state: ShipmentState) -> str:
    """Route to END on any data error; otherwise proceed to Gate 1."""
    return END if state.get("error") else "plan_gate"


def _after_create_shipment(state: ShipmentState) -> str:
    """Route to END on mutation error; otherwise proceed to Gate 2."""
    return END if state.get("status") == "error" else "dock_gate"


# ── Graph ─────────────────────────────────────────────────────────────────────

_checkpointer = MemorySaver()


def _build_graph():
    g = StateGraph(ShipmentState)

    g.add_node("plan_reads",      plan_reads)
    g.add_node("plan_gate",       plan_gate)
    g.add_node("create_shipment", create_shipment)
    g.add_node("dock_gate",       dock_gate)
    g.add_node("book_dock",       book_dock)

    g.add_edge(START, "plan_reads")
    g.add_conditional_edges("plan_reads", _after_plan_reads, {"plan_gate": "plan_gate", END: END})
    # plan_gate returns Command(goto=...) — no static outgoing edges needed
    g.add_conditional_edges("create_shipment", _after_create_shipment, {"dock_gate": "dock_gate", END: END})
    # dock_gate returns Command(goto=...) — no static outgoing edges needed
    g.add_edge("book_dock", END)

    return g.compile(checkpointer=_checkpointer)


_graph = _build_graph()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _get_interrupt(snapshot) -> dict | None:
    """Extract the first interrupt payload from a graph snapshot."""
    for task in (getattr(snapshot, "tasks", None) or []):
        for intr in (getattr(task, "interrupts", None) or []):
            return getattr(intr, "value", None)
    return None


def _is_complete(snapshot) -> bool:
    nxt = getattr(snapshot, "next", None)
    return not nxt  # empty tuple/list → graph finished


# ── Public API ────────────────────────────────────────────────────────────────

import uuid


async def start_plan(request: dict) -> dict:
    """
    Start the planning graph.

    Runs plan_reads then pauses at Gate 1 (plan review).
    Returns {"status": "needs_plan_confirmation", "threadId": …, "plan": {…}}
    or      {"status": "error", "error": "…"}
    """
    thread_id = str(uuid.uuid4())
    config    = _config(thread_id)

    await _graph.ainvoke({"request": request, "status": "planning"}, config=config)
    snapshot = await _graph.aget_state(config)

    # Error path — plan_reads set an error and routed to END
    state_vals = snapshot.values
    if state_vals.get("status") == "error":
        return {"status": "error", "threadId": thread_id, "error": state_vals.get("error")}

    intr = _get_interrupt(snapshot)
    if intr:
        return {"status": "needs_plan_confirmation", "threadId": thread_id, "plan": intr}

    # Unexpected — graph finished without pause
    return {"status": "done", "threadId": thread_id, **state_vals}


async def confirm_plan(thread_id: str, approved: bool) -> dict:
    """
    Resume Gate 1.

    approved=True  → runs create_shipment + BookCarrier, pauses at Gate 2
    approved=False → graph ends; nothing is written to the DB
    """
    config = _config(thread_id)
    await _graph.ainvoke(Command(resume=approved), config=config)
    snapshot = await _graph.aget_state(config)
    vals = snapshot.values

    if vals.get("status") == "error":
        return {"status": "error", "threadId": thread_id, "error": vals.get("error"),
                "shipment": vals.get("shipment")}

    intr = _get_interrupt(snapshot)
    if intr:
        return {"status": "needs_dock_confirmation", "threadId": thread_id, "dockData": intr}

    # Rejected at Gate 1 or graph finished
    return {
        "status":    vals.get("status", "rejected_at_plan"),
        "threadId":  thread_id,
        "shipment":  vals.get("shipment"),
        "booking":   vals.get("booking"),
        "dockBooked": vals.get("dock_booked", False),
    }


async def confirm_dock(thread_id: str, approved: bool) -> dict:
    """
    Resume Gate 2.

    approved=True  → runs BookDockSlot → status "done", dockBooked True
    approved=False → dock skipped    → status "done", dockBooked False
    """
    config = _config(thread_id)
    await _graph.ainvoke(Command(resume=approved), config=config)
    snapshot = await _graph.aget_state(config)
    vals = snapshot.values

    return {
        "status":    "done",
        "threadId":  thread_id,
        "shipment":  vals.get("shipment"),
        "booking":   vals.get("booking"),
        "dockBooked": vals.get("dock_booked", False),
        "dockSlot":  vals.get("dock_slot"),
        "error":     vals.get("error"),
    }
