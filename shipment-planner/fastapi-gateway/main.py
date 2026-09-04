"""
FastAPI Gateway – Shipment Planner AI backend.

Endpoints
─────────────────────────────────────────────────────────────
  POST /api/v1/plan            AI-driven shipment plan (HITL)
  POST /api/v1/plan/confirm    Approve / reject a pending tool call
  POST /api/v1/ask             Free-form agent question
  GET  /api/v1/stream?q=...    SSE streaming agent response
  POST /api/v1/graphql         GraphQL pass-through → Apollo Router
  GET  /api/v1/tools           List MCP tools (from Apollo MCP Server)
  GET  /health                 Health check

Human-in-the-loop flow
─────────────────────────────────────────────────────────────
  1. POST /api/v1/plan
       Read-only tools run automatically.
       When the agent is about to call CreateShipment / BookCarrier /
       BookDockSlot it pauses and returns:
           {"status": "needs_confirmation", "threadId": "…", "confirmation": {…}}

  2. POST /api/v1/plan/confirm  {"threadId": "…", "approved": true | false}
       approved=true  → tool executes, planning continues → "done"
       approved=false → rejected, nothing written → "done"
       If another mutating tool follows you get a second "needs_confirmation".
"""
import json
import os
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent import run_agent, stream_agent
from agent_hitl import _get_tools, run_agent_hitl, resume_agent_hitl
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
        "LangGraph agent (MultiServerMCPClient + create_react_agent) "
        "orchestrates Apollo Federation GraphQL domain services via OpenRouter."
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


# ── AI Shipment Planner (Human-in-the-Loop) ───────────────────────────────────

@app.post("/api/v1/plan", response_model=PlanConfirmResponse, tags=["Planning"])
async def plan_shipment(body: PlanShipmentRequest):
    """
    AI-driven shipment planning with human-in-the-loop confirmation.

    The agent checks warehouse capacity, optimises the route, selects a carrier,
    and gets a quote.  When it is ready to *write* (CreateShipment / BookCarrier /
    BookDockSlot) it **pauses** and returns ``needs_confirmation``.

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


@app.post("/api/v1/plan/confirm", response_model=PlanConfirmResponse, tags=["Planning"])
async def confirm_plan(body: PlanConfirmRequest):
    """
    Resume a paused planning session after human review.

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
