"""
Shipment Planning — V2 (Simplified, No LangGraph)

Replaces the 7-step sequential LangGraph HITL agent with three clean async phases:

  Phase 1  POST /api/v2/plan          Fan-out parallel GraphQL reads → ShipmentPlan
                                       Nothing is written to the DB.

  Phase 2  POST /api/v2/plan/execute  Mutations: CreateShipment + BookCarrier
                                       Returns dock-slot confirmation data.

  Phase 3  POST /api/v2/plan/dock     HITL: BookDockSlot approve / reject

Parallel reads in Phase 1
──────────────────────────
  Round trip 1  GetWarehouseCapacity     (need origin postal code first)
  Round trip 2  OptimizeRoute            ┐ parallel via asyncio.gather()
                GetAvailableCarriers     ┘
  Round trip 3  GetCarrierQuote          (need best-carrier ID from round trip 2)

Total: 3 sequential round trips instead of 7.  No AI model needed.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx

from config import GRAPHQL_ENDPOINT

log = logging.getLogger(__name__)

# ── In-memory plan store ──────────────────────────────────────────────────────
# Maps planId → plan dict that survives across the three HTTP calls.
# Production replacement: Redis or a DB-backed store with TTL.
_plans: dict[str, dict] = {}

# ── GraphQL helper ────────────────────────────────────────────────────────────

async def _gql(query: str, variables: dict) -> dict:
    """Execute one GraphQL operation against the Apollo Router."""
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            GRAPHQL_ENDPOINT,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def _check(result: dict, label: str) -> dict:
    """Raise ValueError if the result contains GraphQL errors."""
    if result.get("errors"):
        msg = result["errors"][0].get("message", str(result["errors"]))
        raise ValueError(f"{label} failed: {msg}")
    return result.get("data", {})


# ── Phase 1 queries ───────────────────────────────────────────────────────────

_Q_WAREHOUSE = """
query GetWarehouseCapacity($id: ID!) {
  warehouseCapacity(id: $id) {
    warehouseId totalM3 usedM3 availableM3 utilizationPct pendingShipments
  }
  warehouse(id: $id) {
    id name code
    address { street city state country postalCode }
  }
}
"""

_Q_ROUTE = """
query OptimizeRoute(
  $originWarehouseId: ID!
  $destinationPostalCode: String!
  $destinationCountry: String!
  $weightKg: Float!
  $volumeM3: Float!
) {
  optimizeRoute(input: {
    originWarehouseId: $originWarehouseId
    destinationPostalCode: $destinationPostalCode
    destinationCountry: $destinationCountry
    weightKg: $weightKg
    volumeM3: $volumeM3
  }) {
    recommendedRoute { name transportMode totalDistanceKm estimatedDurationHours }
    estimatedDeliveryDate
    estimatedCost
  }
}
"""

_Q_CARRIERS = """
query GetAvailableCarriers(
  $originPostalCode: String!
  $destinationPostalCode: String!
  $weightKg: Float!
) {
  availableCarriers(input: {
    originPostalCode: $originPostalCode
    destinationPostalCode: $destinationPostalCode
    weightKg: $weightKg
  }) {
    id name code
    performance { onTimeDeliveryRate avgTransitDays }
    capabilities { maxWeightKg hazardousAllowed temperatureControlled trackingAvailable }
  }
}
"""

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
    transitDays serviceLevel currency validUntil
  }
}
"""

# ── Phase 2 mutations ─────────────────────────────────────────────────────────

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

# ── Public API ────────────────────────────────────────────────────────────────

async def plan_shipment(request: dict) -> dict:
    """
    Phase 1 — Fan-out all reads; return a plan dict.
    Nothing is written to the DB at this point.

    Round trip 1: GetWarehouseCapacity (need origin postal code first)
    Round trip 2: OptimizeRoute + GetAvailableCarriers  ← asyncio.gather (parallel)
    Round trip 3: GetCarrierQuote (need best-carrier ID from round trip 2)
    """
    wh_id       = request["originWarehouseId"]
    dest        = request["destinationAddress"]
    dest_postal = dest["postalCode"]
    dest_country = dest.get("country", "US")

    weight_kg = sum(float(i.get("weight", 0)) * int(i.get("quantity", 1)) for i in request["items"]) or 100.0
    volume_m3 = sum(float(i.get("volume", 0)) * int(i.get("quantity", 1)) for i in request["items"]) or 1.0

    log.info("plan_shipment v2: wh=%s dest=%s weight=%.1fkg vol=%.2fm³", wh_id, dest_postal, weight_kg, volume_m3)

    # ── Round trip 1: warehouse capacity + address ────────────────────────────
    wh_data = _check(await _gql(_Q_WAREHOUSE, {"id": wh_id}), "GetWarehouseCapacity")
    origin_postal = wh_data.get("warehouse", {}).get("address", {}).get("postalCode", "")
    log.info("plan_shipment v2: origin_postal=%s", origin_postal)

    # ── Round trip 2: route + carriers in parallel ────────────────────────────
    route_raw, carriers_raw = await asyncio.gather(
        _gql(_Q_ROUTE, {
            "originWarehouseId": wh_id,
            "destinationPostalCode": dest_postal,
            "destinationCountry": dest_country,
            "weightKg": weight_kg,
            "volumeM3": volume_m3,
        }),
        _gql(_Q_CARRIERS, {
            "originPostalCode": origin_postal,
            "destinationPostalCode": dest_postal,
            "weightKg": weight_kg,
        }),
    )
    route_data    = _check(route_raw,    "OptimizeRoute")
    carriers_data = _check(carriers_raw, "GetAvailableCarriers")

    carriers = carriers_data.get("availableCarriers", [])
    if not carriers:
        raise ValueError("No carriers available for this route")

    # Pick the carrier with the best on-time delivery rate
    best = max(carriers, key=lambda c: c.get("performance", {}).get("onTimeDeliveryRate", 0))
    log.info("plan_shipment v2: selected carrier=%s id=%s", best.get("name"), best.get("id"))

    # ── Round trip 3: quote for selected carrier ──────────────────────────────
    quote_data = _check(
        await _gql(_Q_QUOTE, {
            "carrierId": best["id"],
            "originPostalCode": origin_postal,
            "destinationPostalCode": dest_postal,
            "weightKg": weight_kg,
            "volumeM3": volume_m3,
            "serviceLevel": "STANDARD",
        }),
        "GetCarrierQuote",
    )

    route       = route_data.get("optimizeRoute", {})
    quote       = quote_data.get("carrierQuote", {})
    raw_date    = route.get("estimatedDeliveryDate", "")
    delivery_dt = raw_date[:10] if raw_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    plan_id = str(uuid.uuid4())
    plan = {
        "planId":         plan_id,
        "warehouse":      wh_data.get("warehouse", {}),
        "capacity":       wh_data.get("warehouseCapacity", {}),
        "route":          route,
        "allCarriers":    carriers,
        "selectedCarrier": best,
        "quote":          quote,
        "deliveryDate":   delivery_dt,
        "request":        request,
        "weightKg":       weight_kg,
        "volumeM3":       volume_m3,
        "originPostalCode": origin_postal,
    }
    _plans[plan_id] = plan
    log.info("plan_shipment v2: plan stored planId=%s deliveryDate=%s", plan_id, delivery_dt)
    return plan


async def execute_plan(plan_id: str) -> dict:
    """
    Phase 2 — User approved the plan.
    CreateShipment → BookCarrier (automatic, no separate HITL)
    Returns dock-slot parameters for the Phase 3 HITL step.
    """
    plan = _plans.get(plan_id)
    if not plan:
        raise ValueError(f"Plan not found or expired: {plan_id}")

    request       = plan["request"]
    dest          = request["destinationAddress"]
    carrier       = plan["selectedCarrier"]
    delivery_date = plan["deliveryDate"]

    log.info("execute_plan v2: planId=%s carrier=%s", plan_id, carrier.get("id"))

    # ── CreateShipment ────────────────────────────────────────────────────────
    ship_data = _check(
        await _gql(_M_CREATE_SHIPMENT, {
            "originWarehouseId":    request["originWarehouseId"],
            "destinationStreet":    dest.get("street", ""),
            "destinationCity":      dest["city"],
            "destinationState":     dest.get("state", ""),
            "destinationCountry":   dest.get("country", "US"),
            "destinationPostalCode": dest["postalCode"],
            "items":                request["items"],
            "priority":             request.get("priority", "STANDARD"),
            "specialInstructions":  request.get("specialInstructions", ""),
        }),
        "CreateShipment",
    )
    shipment    = ship_data.get("createShipment", {})
    shipment_id = shipment["id"]
    log.info("execute_plan v2: shipment id=%s tracking=%s", shipment_id, shipment.get("trackingNumber"))

    # ── BookCarrier (auto — no HITL) ──────────────────────────────────────────
    booking_data = _check(
        await _gql(_M_BOOK_CARRIER, {
            "carrierId":           carrier["id"],
            "shipmentId":          shipment_id,
            "serviceLevel":        "STANDARD",
            "requestedPickupDate": delivery_date,
        }),
        "BookCarrier",
    )
    booking = booking_data.get("bookCarrier", {})
    log.info("execute_plan v2: bookingId=%s", booking.get("bookingId"))

    # Persist for Phase 3
    plan["shipment"]   = shipment
    plan["booking"]    = booking
    plan["shipmentId"] = shipment_id

    return {
        "status":    "needs_dock_confirmation",
        "planId":    plan_id,
        "shipment":  shipment,
        "booking":   booking,
        "dockSlot": {
            "warehouseId": request["originWarehouseId"],
            "shipmentId":  shipment_id,
            "dockNumber":  1,
            "date":        delivery_date,
            "startTime":   "08:00",
            "endTime":     "10:00",
            "type":        "PICKUP",
        },
    }


async def confirm_dock(plan_id: str, approved: bool) -> dict:
    """
    Phase 3 — User approved or rejected the dock-slot booking.
    """
    plan = _plans.get(plan_id)
    if not plan:
        raise ValueError(f"Plan not found or expired: {plan_id}")

    shipment = plan.get("shipment", {})
    booking  = plan.get("booking", {})

    if not approved:
        log.info("confirm_dock v2: planId=%s rejected — dock not booked", plan_id)
        _plans.pop(plan_id, None)
        return {
            "status":     "done",
            "planId":     plan_id,
            "dockBooked": False,
            "shipment":   shipment,
            "booking":    booking,
            "message":    "Dock slot skipped. Shipment and carrier booking are active.",
        }

    request       = plan["request"]
    delivery_date = plan["deliveryDate"]
    shipment_id   = plan["shipmentId"]

    dock_data = _check(
        await _gql(_M_BOOK_DOCK_SLOT, {
            "warehouseId": request["originWarehouseId"],
            "dockNumber":  1,
            "date":        delivery_date,
            "startTime":   "08:00",
            "endTime":     "10:00",
            "shipmentId":  shipment_id,
            "type":        "PICKUP",
        }),
        "BookDockSlot",
    )
    dock_slot = dock_data.get("bookDockSlot", {})
    log.info("confirm_dock v2: planId=%s dockSlotId=%s", plan_id, dock_slot.get("id"))

    _plans.pop(plan_id, None)

    return {
        "status":     "done",
        "planId":     plan_id,
        "dockBooked": True,
        "shipment":   shipment,
        "booking":    booking,
        "dockSlot":   dock_slot,
    }
