"""
FastAPI Gateway – Shipment Planner AI backend.

Endpoints
─────────────────────────────────────────────────────────────
  POST /api/v1/plan            AI-driven shipment plan (HITL, LangGraph ReAct)
  POST /api/v1/plan/confirm    Approve / reject a pending tool call
  POST /api/v1/ask             Free-form agent question
  GET  /api/v1/stream?q=...    SSE streaming agent response
  POST /api/v1/graphql         GraphQL pass-through → Apollo Router
  GET  /api/v1/tools           List MCP tools (from Apollo MCP Server)
  GET  /health                 Health check

  POST /api/v3/plan            V3: Apollo supergraph fan-out → plan (Gate 1 HITL)
  POST /api/v3/plan/confirm    V3: Gate 1 resume → CreateShipment + BookCarrier
  POST /api/v3/dock/confirm    V3: Gate 2 resume → BookDockSlot (approve/skip)

  POST /api/hybrid/plan          Hybrid: explicit MCP nodes (asyncio.gather) → plan (Gate 1 HITL)
  POST /api/hybrid/plan/confirm  Hybrid: Gate 1 resume → CreateShipment + BookCarrier
  POST /api/hybrid/dock/confirm  Hybrid: Gate 2 resume → BookDockSlot (approve/skip)
"""
import json
import os
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import run_agent, stream_agent
from agent_hitl import _get_tools, run_agent_hitl, resume_agent_hitl
from agent_v3 import (
    start_plan   as start_plan_v3,
    confirm_plan as confirm_plan_v3,
    confirm_dock as confirm_dock_v3,
)
from agent_hybrid import (
    start_plan   as start_plan_hybrid,
    confirm_plan as confirm_plan_hybrid,
    confirm_dock as confirm_dock_hybrid,
)
from config import GRAPHQL_ENDPOINT
from models import (
    AskRequest,
    AskResponse,
    ConfirmationPayload,
    GraphQLRequest,
    GraphQLResponse,
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanShipmentRequest,
)

app = FastAPI(
    title="Shipment Planner – API Gateway",
    description=(
        "AI-powered shipment planning engine. "
        "V1: LangGraph ReAct agent with MCP tools. "
        "V3: LangGraph StateGraph + Apollo Federation supergraph fan-out, two HITL gates."
    ),
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {
        "status":  "ok",
        "graphql": GRAPHQL_ENDPOINT,
        "model":   os.getenv("OPENROUTER_MODEL", "not set"),
    }


# ── MCP tool catalogue ────────────────────────────────────────────────────────

@app.get("/api/v1/tools", tags=["MCP"])
async def list_mcp_tools():
    """
    Return all MCP tools the Apollo MCP Server currently exposes.
    Each tool maps to one .graphql operation file (hot-reloaded).
    """
    try:
        tools = await _get_tools()
        return {
            "count": len(tools),
            "tools": [
                {"name": t.name, "description": t.description}
                for t in tools
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MCP server unreachable: {exc}")


# ── Free-form agent chat ──────────────────────────────────────────────────────

@app.post("/api/v1/ask", response_model=AskResponse, tags=["Agent"])
async def ask(body: AskRequest):
    """
    Ask the LangGraph agent any shipment-planning question in plain English.

    Examples
    --------
    - "What is the status of shipment SP-ABC12345?"
    - "Find the cheapest carrier from warehouse wh-001 to postal code 10001"
    - "Show me all in-transit shipments"
    """
    try:
        result = await run_agent(body.question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return AskResponse(
        answer=result["answer"],
        toolsCalled=result["tools_called"],
        messageCount=result["message_count"],
    )


# ── Streaming SSE ─────────────────────────────────────────────────────────────

@app.get("/api/v1/stream", tags=["Agent"])
async def stream(q: str = Query(..., description="Shipment planning question")):
    """
    Stream the agent's response as Server-Sent Events.

    Each event is JSON: ``{"type": "token"|"tool_call"|"tool_result", "data": "…"}``

    Connect with ``EventSource`` in the browser or ``curl --no-buffer``.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for chunk in stream_agent(q):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── AI Shipment Planner V1 (LangGraph ReAct HITL) ────────────────────────────

@app.post("/api/v1/plan", response_model=PlanConfirmResponse, tags=["Planning V1"])
async def plan_shipment(body: PlanShipmentRequest):
    """
    AI-driven shipment planning with human-in-the-loop confirmation.

    The agent checks warehouse capacity, optimises the route, selects a carrier,
    and gets a quote.  When it is ready to *write* (CreateShipment / BookDockSlot)
    it **pauses** and returns ``needs_confirmation``.

    Call **POST /api/v1/plan/confirm** with the ``threadId`` to approve or reject.
    """
    question = (
        f"Plan a complete shipment:\n"
        f"- Origin warehouse: {body.originWarehouseId}\n"
        f"- Destination: {body.destinationAddress.city}, "
        f"{body.destinationAddress.state or ''}, "
        f"{body.destinationAddress.country} "
        f"({body.destinationAddress.postalCode})\n"
        f"- Items: {len(body.items)} item(s), "
        f"total weight: {sum(i.weight * i.quantity for i in body.items):.1f} kg, "
        f"total volume: {sum(i.volume * i.quantity for i in body.items):.3f} m³\n"
        f"- Priority: {body.priority}\n"
        + (f"- Required by: {body.requiredDeliveryDate}\n" if body.requiredDeliveryDate else "")
        + (f"- Special instructions: {body.specialInstructions}\n" if body.specialInstructions else "")
        + "\nSteps: check warehouse capacity → find best route → select carrier → "
          "get quote → create shipment → book carrier → book dock slot. "
          "Return shipment ID, tracking number, carrier, route, estimated cost, and delivery date."
    )

    try:
        result = await run_agent_hitl(question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return _to_plan_response(result)


@app.post("/api/v1/plan/confirm", response_model=PlanConfirmResponse, tags=["Planning V1"])
async def confirm_plan(body: PlanConfirmRequest):
    """
    Resume a paused V1 planning session after human review.

    - ``approved: true``  → the mutating tool executes, planning continues
    - ``approved: false`` → operation is discarded, nothing is written

    If another mutating tool follows you receive a second ``needs_confirmation``.
    """
    try:
        result = await resume_agent_hitl(body.threadId, body.approved)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return _to_plan_response(result)


def _to_plan_response(result: dict) -> PlanConfirmResponse:
    if result["status"] == "needs_confirmation":
        return PlanConfirmResponse(
            status="needs_confirmation",
            threadId=result.get("thread_id"),
            confirmation=ConfirmationPayload(
                tool=result.get("tool", ""),
                arguments=result.get("arguments", {}),
                summary=result.get("summary", ""),
                question=result.get("question", ""),
            ),
        )
    return PlanConfirmResponse(
        status="done",
        threadId=result.get("thread_id"),
        agentReasoning=result.get("answer", ""),
        toolsCalled=result.get("tools_called", []),
    )


# ── GraphQL pass-through ──────────────────────────────────────────────────────

@app.post("/api/v1/graphql", response_model=GraphQLResponse, tags=["GraphQL"])
async def graphql_passthrough(body: GraphQLRequest):
    """
    Direct GraphQL pass-through to the Apollo Federation Router.

    Apollo Client in the React UI calls this endpoint for all queries.
    The router fans out to the correct subgraph(s) transparently.
    """
    payload: dict = {"query": body.query}
    if body.variables:
        payload["variables"] = body.variables

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(GRAPHQL_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GraphQL router unreachable: {exc}")

    return GraphQLResponse(data=data.get("data"), errors=data.get("errors"))


# ── V3 Shipment Planner (LangGraph StateGraph + Apollo supergraph fan-out) ────
#
# Three-phase HITL flow:
#   Phase 1  POST /api/v3/plan          Apollo supergraph fan-out → plan
#                                        Pauses at Gate 1 (plan review). Nothing written to DB.
#   Phase 2  POST /api/v3/plan/confirm  Gate 1 resume → CreateShipment + BookCarrier
#                                        Pauses at Gate 2 (dock slot review).
#   Phase 3  POST /api/v3/dock/confirm  Gate 2 resume → BookDockSlot (if approved)

class V3ConfirmRequest(BaseModel):
    threadId: str
    approved: bool


@app.post("/api/v3/plan", tags=["Planning V3 (LangGraph)"])
async def v3_start_plan(body: PlanShipmentRequest):
    """
    V3 Phase 1 — Apollo supergraph fan-out.

    Sends one GraphQL document (warehouse + capacity + route) to Apollo Router;
    the Router's query planner fetches warehouse and route subgraphs in parallel.
    Then fetches carriers, then quote. Nothing is written to the DB.

    Returns ``needs_plan_confirmation`` with the full plan for Gate 1 review,
    or ``error`` if warehouse / route / carriers / quote data is missing.
    """
    try:
        request_dict = {
            "originWarehouseId": body.originWarehouseId,
            "destinationAddress": {
                "street":     body.destinationAddress.street or "",
                "city":       body.destinationAddress.city,
                "state":      body.destinationAddress.state or "",
                "country":    body.destinationAddress.country,
                "postalCode": body.destinationAddress.postalCode,
            },
            "items": [
                {
                    "sku":                   i.sku,
                    "description":           i.description,
                    "quantity":              i.quantity,
                    "weight":                i.weight,
                    "volume":                i.volume,
                    "value":                 i.value,
                    "hazardous":             i.hazardous,
                    "temperatureControlled": i.temperatureControlled,
                    "fragile":               i.fragile,
                }
                for i in body.items
            ],
            "priority":             body.priority,
            "requiredDeliveryDate": body.requiredDeliveryDate,
            "specialInstructions":  body.specialInstructions or "",
        }
        return await start_plan_v3(request_dict)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v3/plan/confirm", tags=["Planning V3 (LangGraph)"])
async def v3_confirm_plan(body: V3ConfirmRequest):
    """
    V3 Gate 1 resume — human approved or rejected the plan.

    - ``approved: true``  → CreateShipment + BookCarrier run automatically;
                            response is ``needs_dock_confirmation`` (Gate 2).
    - ``approved: false`` → nothing is written to the DB; response is ``rejected_at_plan``.
    """
    try:
        return await confirm_plan_v3(body.threadId, body.approved)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v3/dock/confirm", tags=["Planning V3 (LangGraph)"])
async def v3_confirm_dock(body: V3ConfirmRequest):
    """
    V3 Gate 2 resume — human approved or skipped the dock-slot booking.

    - ``approved: true``  → BookDockSlot executes; ``dockBooked: true``.
    - ``approved: false`` → dock slot skipped; shipment + carrier booking remain active.

    Response ``status`` is always ``"done"``.
    """
    try:
        return await confirm_dock_v3(body.threadId, body.approved)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Hybrid Shipment Planner (LangGraph StateGraph + explicit MCP tool nodes) ──
#
# Three-phase HITL flow, same gates as V3, but reads use named MCP tools
# with asyncio.gather() for Python-side parallelism instead of Apollo supergraph.
#
#   Phase 1  POST /api/hybrid/plan          mcp_node_1 (gather) + mcp_node_2 (quote)
#                                            Pauses at Gate 1 (plan review)
#   Phase 2  POST /api/hybrid/plan/confirm  Gate 1 resume → CreateShipment + BookCarrier
#                                            Pauses at Gate 2 (dock slot review)
#   Phase 3  POST /api/hybrid/dock/confirm  Gate 2 resume → BookDockSlot (if approved)

@app.post("/api/hybrid/plan", tags=["Planning Hybrid (MCP + LangGraph)"])
async def hybrid_start_plan(body: PlanShipmentRequest):
    """
    Hybrid Phase 1 — explicit MCP tool nodes.

    mcp_node_1 calls get_warehouse_capacity and optimize_route in parallel
    (asyncio.gather), then calls get_available_carriers sequentially (needs
    origin postal from the first pair).

    mcp_node_2 tool-chains into get_carrier_quote using the best carrier found
    in mcp_node_1.

    Nothing is written to the DB. Returns ``needs_plan_confirmation`` with the
    full plan for Gate 1 review, or ``error`` if any MCP tool fails.
    """
    try:
        request_dict = {
            "originWarehouseId": body.originWarehouseId,
            "destinationAddress": {
                "street":     body.destinationAddress.street or "",
                "city":       body.destinationAddress.city,
                "state":      body.destinationAddress.state or "",
                "country":    body.destinationAddress.country,
                "postalCode": body.destinationAddress.postalCode,
            },
            "items": [
                {
                    "sku":                   i.sku,
                    "description":           i.description,
                    "quantity":              i.quantity,
                    "weight":                i.weight,
                    "volume":                i.volume,
                    "value":                 i.value,
                    "hazardous":             i.hazardous,
                    "temperatureControlled": i.temperatureControlled,
                    "fragile":               i.fragile,
                }
                for i in body.items
            ],
            "priority":             body.priority,
            "requiredDeliveryDate": body.requiredDeliveryDate,
            "specialInstructions":  body.specialInstructions or "",
        }
        return await start_plan_hybrid(request_dict)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/hybrid/plan/confirm", tags=["Planning Hybrid (MCP + LangGraph)"])
async def hybrid_confirm_plan(body: V3ConfirmRequest):
    """
    Hybrid Gate 1 resume — human approved or rejected the plan.

    - ``approved: true``  → CreateShipment + BookCarrier run (direct GraphQL);
                            response is ``needs_dock_confirmation`` (Gate 2).
    - ``approved: false`` → nothing is written; response is ``rejected_at_plan``.
    """
    try:
        return await confirm_plan_hybrid(body.threadId, body.approved)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/hybrid/dock/confirm", tags=["Planning Hybrid (MCP + LangGraph)"])
async def hybrid_confirm_dock(body: V3ConfirmRequest):
    """
    Hybrid Gate 2 resume — human approved or skipped the dock-slot booking.

    - ``approved: true``  → BookDockSlot executes (direct GraphQL); ``dockBooked: true``.
    - ``approved: false`` → dock slot skipped; shipment + carrier booking remain active.

    Response ``status`` is always ``"done"``.
    """
    try:
        return await confirm_dock_hybrid(body.threadId, body.approved)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
