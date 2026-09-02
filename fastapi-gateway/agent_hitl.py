"""
Shipment Planning Agent — LangGraph StateGraph with Human-in-the-Loop.

Graph topology
──────────────
  StateGraph(MessagesState)
    agent        – llm.bind_tools(tools).invoke(messages)
    human_review – interrupt() on mutating tools; pass-through on read-only
    tools        – ToolNode(tools) executes the actual call

  Routing
    agent → human_review   (tool call is mutating)
    agent → tools          (tool call is read-only)
    agent → END            (no tool call → final answer)
    human_review → tools   (approved, or read-only pass-through)
    human_review → END     (rejected → rejection AIMessage already injected)
    tools → END

HITL flow
─────────
  POST /api/v1/plan
      Returns {"status": "needs_confirmation", "thread_id": ..., ...}
      when a mutating tool is about to run.

  POST /api/v1/plan/confirm
      compiled.invoke(Command(resume={"approved": bool}), config)
      approved=True  → ToolNode executes → done
      approved=False → rejection already injected by human_review → done
"""

import logging
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Patch 1: Protocol version — MUST run before langchain_mcp_adapters import ─
#
# Apollo MCP Server only speaks MCP protocol "2024-11-05".
# Newer mcp 1.x releases updated LATEST_PROTOCOL_VERSION to "2025-03-26",
# which causes Apollo to reply "Session terminated" during the initialize
# handshake.  Pydantic captures field defaults at class-definition time, so
# this patch must run before mcp.client.session (and langchain_mcp_adapters)
# is imported.
_MCP_PROTOCOL_VERSION = "2024-11-05"

import mcp.types as _mcp_types                          # noqa: E402
_mcp_types.LATEST_PROTOCOL_VERSION = _MCP_PROTOCOL_VERSION

import mcp.client.session as _mcp_session               # noqa: E402
if hasattr(_mcp_session, "LATEST_PROTOCOL_VERSION"):
    _mcp_session.LATEST_PROTOCOL_VERSION = _MCP_PROTOCOL_VERSION

# Safe to import the rest now — they see the patched constant
from langchain_core.messages import (                   # noqa: E402
    AIMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: E402
from langchain_openai import ChatOpenAI                          # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver            # noqa: E402
from langgraph.errors import GraphRecursionError                  # noqa: E402
from langgraph.graph import END, MessagesState, StateGraph        # noqa: E402
from langgraph.prebuilt import ToolNode                           # noqa: E402
from langgraph.types import Command, interrupt                    # noqa: E402

from config import (                                              # noqa: E402
    MCP_SERVER_URL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
)

# ── Patch 2: filter empty SSE priming events ──────────────────────────────────
# Apollo MCP Server sends a blank SSE event to prime the stream.
# The MCP SDK tries to JSON-parse that empty string → crash inside anyio TaskGroup.
# Upstream: github.com/modelcontextprotocol/python-sdk/issues/1672
# langchain-mcp-adapters==0.2.1 routes SSE through StreamableHTTPTransport._handle_sse_event.
def _patch_mcp_empty_sse_bug() -> None:
    from mcp.client.streamable_http import StreamableHTTPTransport

    _orig = StreamableHTTPTransport._handle_sse_event

    async def _patched(self, sse, *args, **kwargs):
        if not sse.data or sse.data.strip() == "":
            return False
        return await _orig(self, sse, *args, **kwargs)

    StreamableHTTPTransport._handle_sse_event = _patched


_patch_mcp_empty_sse_bug()


# ── Patch 3: silence "Session termination failed: 202" noise ─────────────────
# Apollo MCP Server returns HTTP 202 Accepted on DELETE /mcp (session close).
# The MCP SDK logs a WARNING for anything other than 200, but 202 is fine.
def _patch_mcp_session_termination_log() -> None:
    import logging as _logging
    _mcp_log = _logging.getLogger("mcp.client.streamable_http")
    _orig_warning = _mcp_log.warning

    def _filtered_warning(msg, *args, **kwargs):
        if "Session termination failed" in str(msg):
            _mcp_log.debug(msg, *args, **kwargs)   # demote to DEBUG
            return
        _orig_warning(msg, *args, **kwargs)

    _mcp_log.warning = _filtered_warning


_patch_mcp_session_termination_log()

# ── Direct GraphQL mutation tools ─────────────────────────────────────────────
# The Apollo MCP Server only exposes query operations; mutations are rejected.
# These three tools call the Apollo Router GraphQL endpoint directly via HTTP.

import httpx as _httpx                                              # noqa: E402
from langchain_core.tools import tool as _lc_tool                  # noqa: E402
from config import GRAPHQL_ENDPOINT                                # noqa: E402


async def _graphql(query: str, variables: dict, authorization: str | None = None) -> dict:
    """Execute a GraphQL operation against the Apollo Router."""
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    async with _httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GRAPHQL_ENDPOINT,
            json={"query": query, "variables": variables},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


_CREATE_SHIPMENT_MUTATION = """
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
    id
    trackingNumber
    status
    priority
    originWarehouseId
    totalWeight
    totalVolume
    totalValue
    estimatedDelivery
    createdAt
    destinationAddress { street city state country postalCode }
  }
}
"""

_BOOK_CARRIER_MUTATION = """
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
    bookingId
    carrierId
    shipmentId
    confirmedAt
    pickupWindow
    estimatedDelivery
    trackingNumber
  }
}
"""

_BOOK_DOCK_SLOT_MUTATION = """
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
    id
    warehouseId
    dockNumber
    date
    startTime
    endTime
    shipmentId
    type
    status
  }
}
"""


@_lc_tool
async def CreateShipment(
    originWarehouseId: str,
    destinationCity: str,
    destinationCountry: str,
    destinationPostalCode: str,
    items: list,
    priority: str,
    destinationStreet: str = "",
    destinationState: str = "",
    scheduledPickup: str = "",
    specialInstructions: str = "",
) -> str:
    """Create a new shipment record. Returns the assigned tracking number and shipment ID."""
    import json as _json
    variables = {
        "originWarehouseId": originWarehouseId,
        "destinationCity": destinationCity,
        "destinationCountry": destinationCountry,
        "destinationPostalCode": destinationPostalCode,
        "items": items,
        "priority": priority,
    }
    if destinationStreet:
        variables["destinationStreet"] = destinationStreet
    if destinationState:
        variables["destinationState"] = destinationState
    if scheduledPickup:
        variables["scheduledPickup"] = scheduledPickup
    if specialInstructions:
        variables["specialInstructions"] = specialInstructions
    result = await _graphql(_CREATE_SHIPMENT_MUTATION, variables)
    return _json.dumps(result)


@_lc_tool
async def BookCarrier(
    carrierId: str,
    shipmentId: str,
    serviceLevel: str,
    requestedPickupDate: str,
) -> str:
    """Confirm a carrier booking for a shipment. Returns booking ID and tracking number."""
    import json as _json
    variables = {
        "carrierId": carrierId,
        "shipmentId": shipmentId,
        "serviceLevel": serviceLevel,
        "requestedPickupDate": requestedPickupDate,
    }
    result = await _graphql(_BOOK_CARRIER_MUTATION, variables)
    return _json.dumps(result)


@_lc_tool
async def BookDockSlot(
    warehouseId: str,
    dockNumber: int,
    date: str,
    startTime: str,
    endTime: str,
    shipmentId: str,
    type: str,
) -> str:
    """Reserve a specific dock slot at the warehouse for a shipment pickup or delivery."""
    import json as _json
    variables = {
        "warehouseId": warehouseId,
        "dockNumber": dockNumber,
        "date": date,
        "startTime": startTime,
        "endTime": endTime,
        "shipmentId": shipmentId,
        "type": type,
    }
    result = await _graphql(_BOOK_DOCK_SLOT_MUTATION, variables)
    return _json.dumps(result)


_MUTATION_TOOLS = [CreateShipment, BookCarrier, BookDockSlot]

# ── Constants ─────────────────────────────────────────────────────────────────
# Both CreateShipment and BookDockSlot require human approval:
#   • CreateShipment pauses first so the user confirms the plan before any DB write.
#     Rejecting here means nothing is created at all.
#   • BookCarrier runs automatically between the two pauses (can always be cancelled).
#   • BookDockSlot pauses second so the user confirms the physical dock reservation.
MUTATING_TOOLS = {"CreateShipment", "BookDockSlot"}
_SERVER        = "shipment-planner"

# Mandatory execution order — the agent is forced to call these in sequence.
# tool_choice in _build_agent ensures the LLM cannot deviate or repeat a step.
STEP_TOOLS = [
    "GetWarehouseCapacity",
    "OptimizeRoute",
    "GetAvailableCarriers",
    "GetCarrierQuote",
    "CreateShipment",
    "BookCarrier",
    "BookDockSlot",
]

SYSTEM_PROMPT = """You are an expert shipment planning AI assistant.
You have access to exactly 7 tools. Execute them in the EXACT order below.
Call each tool ONCE and ONLY ONCE. Calling any tool a second time is FORBIDDEN.

MANDATORY SEQUENCE (7 steps — execute IN ORDER, no skipping, no repeating)
────────────────────────────────────────────────────────────────────────────
Step 1 → GetWarehouseCapacity
  Input:  warehouseId  (from the user's request, e.g. "wh-001")
  Output: capacity info.
  → SAVE: warehouseId, originPostalCode from the result for later steps.

Step 2 → OptimizeRoute
  Input:  originWarehouseId, destinationPostalCode, destinationCountry="US",
          weightKg, volumeM3
  Output: estimatedDeliveryDate (YYYY-MM-DD), estimatedCost.
  → SAVE: estimatedDeliveryDate for steps 6 & 7.
  ⛔ OptimizeRoute is called ONLY HERE. Do NOT call it again in any later step.

Step 3 → GetAvailableCarriers
  Input:  originPostalCode (from step 1 result), destinationPostalCode, weightKg
  Output: list of carriers.
  → PICK the carrier with the highest onTimeDeliveryRate.
  → SAVE: that carrier's id as carrierId for steps 4 & 6.
  ⛔ GetAvailableCarriers is called ONLY HERE.

Step 4 → GetCarrierQuote
  Input:  carrierId (saved from step 3),
          originPostalCode (saved from step 1),
          destinationPostalCode (from user request),
          weightKg, volumeM3,
          serviceLevel="STANDARD"
  Output: totalCost, transitDays.
  ⛔ Use ONLY the values already saved. Do NOT call OptimizeRoute or GetAvailableCarriers again.

Step 5 → CreateShipment  *** PAUSES for human approval — submit and wait ***
  Input:  originWarehouseId (from user request),
          destinationCity, destinationCountry="US", destinationPostalCode,
          items=[{sku:"ITEM-001",description:"Cargo",quantity:1,weight:<weightKg>,
                  volume:<volumeM3>,value:500,hazardous:false,
                  temperatureControlled:false,fragile:false}],
          priority="STANDARD"
  Output: the new shipment object.
  → SAVE: the shipment's `id` field (looks like "shp-abc123") as shipmentId.
  ⛔ The warehouseId (e.g. "wh-001") is NEVER the shipmentId.

Step 6 → BookCarrier  (runs automatically after CreateShipment is approved — no separate approval)
  Input:  carrierId (saved from step 3),
          shipmentId (saved from step 5 `id` field),
          serviceLevel="STANDARD",
          requestedPickupDate = estimatedDeliveryDate saved from step 2 (YYYY-MM-DD)
  Output: bookingId, trackingNumber.
  ⛔ Do NOT call OptimizeRoute or GetAvailableCarriers to get these values.

Step 7 → BookDockSlot  *** PAUSES for human approval — submit and wait ***
  Input:  warehouseId (from user request),
          shipmentId (saved from step 5 `id` field),
          dockNumber=1, startTime="08:00", endTime="10:00",
          date = estimatedDeliveryDate saved from step 2 (YYYY-MM-DD),
          type="PICKUP"
  Output: dock slot confirmation.

After step 7 completes, write a one-line summary and STOP immediately.

RULES
─────
• Steps execute 1 → 2 → 3 → 4 → 5 → 6 → 7. No other order is permitted.
• Every tool is called exactly ONCE. A second call to any tool is a critical error.
• warehouseId (e.g. "wh-001") is an INPUT to the workflow, NEVER an output shipmentId.
• All values needed for steps 4-7 come from the saved outputs of steps 1-3.
• If weightKg or volumeM3 are not provided by the user, default to weightKg=100, volumeM3=1.0.
"""

# ── Checkpointer — module-level singleton shared across all requests ──────────
_checkpointer = InMemorySaver()

# ── MCP client config ─────────────────────────────────────────────────────────
def _mcp_config(authorization: str | None = None) -> dict:
    cfg: dict = {"transport": "streamable_http", "url": MCP_SERVER_URL}
    if authorization:
        cfg["headers"] = {"Authorization": authorization}
    return {_SERVER: cfg}


# ── LLM ───────────────────────────────────────────────────────────────────────
def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=OPENROUTER_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://shipment-planner.local",
            "X-Title": "Shipment Planner",
        },
        temperature=0,
        streaming=True,
    )


# ── Tool metadata only (for /api/v1/tools catalogue endpoint) ─────────────────
async def _get_mcp_tools(authorization: str | None = None) -> list:
    """Fetch the 4 query tools from the Apollo MCP Server."""
    client = MultiServerMCPClient(_mcp_config(authorization))
    try:
        return await client.get_tools()
    except Exception:
        log.exception("_get_mcp_tools failed")
        raise


async def _get_tools(authorization: str | None = None) -> list:
    """Return all tools: MCP queries + direct-HTTP mutation tools."""
    mcp_tools = await _get_mcp_tools(authorization)
    # Merge: MCP query tools first, then our mutation tools (direct GraphQL HTTP)
    all_tools = list(mcp_tools) + _MUTATION_TOOLS
    log.info("_get_tools: %d MCP tools + %d mutation tools = %d total",
             len(mcp_tools), len(_MUTATION_TOOLS), len(all_tools))
    return all_tools


# ── HITL graph nodes ──────────────────────────────────────────────────────────

def human_review(state: MessagesState) -> MessagesState:
    """
    Pauses via interrupt() when the pending tool call is mutating.
    Passes through immediately for read-only tools (ToolNode handles them next).
    On rejection inserts an AIMessage so the graph ends cleanly.
    """
    last = state["messages"][-1]
    call = last.tool_calls[0]

    if call["name"] not in MUTATING_TOOLS:
        return state  # read-only → straight to ToolNode

    decision = interrupt({
        "type":      "confirm_tool_call",
        "tool":      call["name"],
        "arguments": call["args"],
        "summary":   f"Agent wants to call '{call['name']}'",
        "question":  f"Confirm running '{call['name']}' with {call['args']}?",
    })

    approved = decision.get("approved") if isinstance(decision, dict) else bool(decision)
    if not approved:
        return {"messages": [AIMessage(
            content=f"Operation '{call['name']}' was not approved; no changes were made.",
        )]}

    return state  # approved → last message still carries tool_calls → ToolNode executes


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_agent(state: MessagesState):
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return END
    return "human_review" if last.tool_calls[0]["name"] in MUTATING_TOOLS else "tools"


def route_after_review(state: MessagesState):
    last = state["messages"][-1]
    # approved → still has tool_calls → ToolNode; rejected → AIMessage → END
    return "tools" if getattr(last, "tool_calls", None) else END


def route_after_tools(state: MessagesState):
    """
    After ToolNode executes:
    - If ALL MUTATING_TOOLS have now run successfully → END.
    - If all STEP_TOOLS have run (none left) → END (summary generation follows).
    - Hard safety cap at 20 tool messages → END.
    - Otherwise → agent for the next forced tool_choice step.
    """
    messages  = state["messages"]
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]

    # Count only successful (non-error) calls
    real_called = {
        getattr(m, "name", None)
        for m in tool_msgs
        if getattr(m, "name", None)
        and not str(getattr(m, "content", "")).startswith("STEP_ERROR:")
    } - {None}

    # Primary exit: all HITL tools have run
    if MUTATING_TOOLS.issubset(real_called):
        return END

    # All planned steps executed
    if real_called.issuperset(set(STEP_TOOLS)):
        return END

    # Hard safety cap
    if len(tool_msgs) >= 20:
        log.warning("route_after_tools: 20-tool safety cap reached; terminating")
        return END

    return "agent"


def _make_tool_node(tools: list):
    """
    Returns an async node function that wraps ToolNode with duplicate-call
    interception.  When a non-mutating tool is about to be called a second
    time, the node injects a STEP_ERROR ToolMessage instead of executing the
    tool again, giving the agent a chance to self-correct and advance.
    """
    inner = ToolNode(tools)

    async def dedup_tool_node(state: MessagesState):
        from collections import Counter
        tool_msgs = [m for m in state["messages"] if isinstance(m, ToolMessage)]

        # Count only real (successful) prior calls
        counts = Counter(
            getattr(m, "name", None)
            for m in tool_msgs
            if getattr(m, "name", None)
            and not str(getattr(m, "content", "")).startswith("STEP_ERROR:")
        )

        last_ai = state["messages"][-1]
        calls   = getattr(last_ai, "tool_calls", None) or []

        for call in calls:
            name = call.get("name", "")
            if name not in MUTATING_TOOLS and counts.get(name, 0) >= 1:
                log.warning(
                    "Intercepting duplicate call to '%s' (already called %d×); injecting error",
                    name, counts[name],
                )
                return {"messages": [ToolMessage(
                    content=(
                        f"STEP_ERROR: Tool '{name}' was already called and its result is "
                        f"already in the conversation history. Do NOT call it again. "
                        f"Use the data already retrieved and proceed to the NEXT step in the sequence."
                    ),
                    tool_call_id=call["id"],
                    name=name,
                )]}

        return await inner.ainvoke(state)

    return dedup_tool_node


# ── Graph wiring ──────────────────────────────────────────────────────────────

def _attach_human_in_the_loop(graph: StateGraph) -> StateGraph:
    """
    Wires human_review + routing into a graph that already has
    'agent' and 'tools' nodes added.

    ReAct loop:
        agent ──(read-only tool)──────► tools ──(not all HITL done)──► agent  (loop)
        agent ──(mutating tool)──────► human_review
            human_review ──(approved)──► tools ──(all HITL done)──► END
            human_review ──(rejected)──► END
        agent ──(no tool call)──────► END
    """
    graph.add_node("human_review", human_review)
    graph.add_conditional_edges(
        "agent", route_after_agent,
        {"human_review": "human_review", "tools": "tools", END: END},
    )
    graph.add_conditional_edges(
        "human_review", route_after_review,
        {"tools": "tools", END: END},
    )
    # Loop back to agent while MUTATING_TOOLS are not yet all done;
    # terminate once both BookCarrier and BookDockSlot have executed.
    graph.add_conditional_edges(
        "tools", route_after_tools,
        {"agent": "agent", END: END},
    )
    return graph


def _next_step(state: MessagesState) -> str | None:
    """
    Return the name of the NEXT tool to call, or None when all steps are done.

    - Skips synthetic STEP_ERROR messages.
    - A tool that returned a GraphQL error is counted as "not done" (retry once).
    - But if the dedup guard already injected a STEP_ERROR for that same tool
      (i.e. the tool has been attempted at least twice), we skip it to avoid
      an infinite loop — the flow will continue and the summary will show the
      error.
    """
    tool_msgs = [m for m in state["messages"] if isinstance(m, ToolMessage)]

    step_errors = {           # tools that already got a dedup STEP_ERROR
        getattr(m, "name", None)
        for m in tool_msgs
        if getattr(m, "name", None)
        and str(getattr(m, "content", "")).startswith("STEP_ERROR:")
    }

    called_ok = set()
    called_err = set()
    for m in tool_msgs:
        name = getattr(m, "name", None)
        if not name or str(getattr(m, "content", "")).startswith("STEP_ERROR:"):
            continue
        if _is_graphql_error(getattr(m, "content", "")):
            called_err.add(name)
            log.warning("_next_step: '%s' returned a GraphQL error", name)
        else:
            called_ok.add(name)

    for tool_name in STEP_TOOLS:
        if tool_name in called_ok:
            continue                          # successfully completed → skip
        if tool_name in called_err:
            if tool_name in step_errors:
                # Already retried once via dedup — skip to avoid infinite loop
                log.warning("_next_step: '%s' failed and retry was intercepted; skipping", tool_name)
                continue
            return tool_name                  # retry this step once
        return tool_name                      # not yet attempted
    return None


# Per-step parameter extraction prompts.
# The LLM is asked ONLY for the JSON parameters for that tool.
# The tool call itself is constructed in code — the model never picks the tool.
STEP_PARAM_PROMPTS = {
    "GetWarehouseCapacity": (
        "Return ONLY a JSON object with the parameter to call GetWarehouseCapacity.\n"
        "Extract the warehouse ID from the user's request.\n"
        'The parameter name MUST be "id" (NOT "warehouseId").\n'
        'Example: {"id": "wh-001"}'
    ),
    "OptimizeRoute": (
        "Return ONLY a JSON object with the parameters to call OptimizeRoute.\n"
        "Use: originWarehouseId (warehouse ID from user request), "
        "destinationPostalCode (from user request), destinationCountry='US', "
        "weightKg (from request or default 100), volumeM3 (from request or default 1.0).\n"
        '{"originWarehouseId":"wh-001","destinationPostalCode":"10001",'
        '"destinationCountry":"US","weightKg":100,"volumeM3":1.0}'
    ),
    "GetAvailableCarriers": (
        "Return ONLY a JSON object with the parameters to call GetAvailableCarriers.\n"
        "Look at the GetWarehouseCapacity tool result — find data.warehouse.address.postalCode for originPostalCode.\n"
        "Use: originPostalCode (from GetWarehouseCapacity data.warehouse.address.postalCode), "
        "destinationPostalCode (from user request), weightKg (from request or 100).\n"
        '{"originPostalCode":"60601","destinationPostalCode":"10001","weightKg":100}'
    ),
    "GetCarrierQuote": (
        "Return ONLY a JSON object with the parameters to call GetCarrierQuote.\n"
        "carrierId: pick the carrier with the highest onTimeDeliveryRate from GetAvailableCarriers result. Use its 'id' field.\n"
        "originPostalCode: from GetWarehouseCapacity result at data.warehouse.address.postalCode.\n"
        "destinationPostalCode: from the user's request.\n"
        "weightKg and volumeM3: from the user's request (or defaults 100 and 1.0).\n"
        "serviceLevel: must be exactly 'STANDARD'.\n"
        '{"carrierId":"car-001","originPostalCode":"60601","destinationPostalCode":"10001",'
        '"weightKg":100,"volumeM3":1.0,"serviceLevel":"STANDARD"}'
    ),
    "CreateShipment": (
        "Return ONLY a JSON object with the parameters to call CreateShipment.\n"
        "originWarehouseId: the warehouse ID from the user request (e.g. 'wh-001').\n"
        "destinationCity: city from user request (e.g. 'New York').\n"
        "destinationCountry: 'US'.\n"
        "destinationPostalCode: from user request.\n"
        "priority: 'STANDARD'.\n"
        "items: [{\"sku\":\"ITEM-001\",\"description\":\"Cargo\",\"quantity\":1,\"weight\":100,"
        "\"volume\":1.0,\"value\":500,\"hazardous\":false,\"temperatureControlled\":false,\"fragile\":false}]\n"
        "IMPORTANT: originWarehouseId is an INPUT. Do NOT put the warehouseId into the shipmentId field."
    ),
    "BookCarrier": (
        "Return ONLY a JSON object with the parameters to call BookCarrier.\n"
        "carrierId: from the GetAvailableCarriers result (same carrier as GetCarrierQuote).\n"
        "shipmentId: from the CreateShipment result — look for the 'id' field (e.g. 'shp-abc123').\n"
        "serviceLevel: 'STANDARD'.\n"
        "requestedPickupDate: the DATE ONLY portion of estimatedDeliveryDate from OptimizeRoute (YYYY-MM-DD, strip any time).\n"
        '{"carrierId":"car-001","shipmentId":"shp-abc123","serviceLevel":"STANDARD","requestedPickupDate":"2026-09-05"}'
    ),
    "BookDockSlot": (
        "Return ONLY a JSON object with the parameters to call BookDockSlot.\n"
        "warehouseId: the warehouse ID from the user request (e.g. 'wh-001').\n"
        "shipmentId: from the CreateShipment result 'id' field (e.g. 'shp-abc123').\n"
        "dockNumber: 1.\n"
        "startTime: '08:00'.\n"
        "endTime: '10:00'.\n"
        "date: DATE ONLY portion of estimatedDeliveryDate from OptimizeRoute (YYYY-MM-DD, strip any time).\n"
        "type: 'PICKUP'.\n"
        '{"warehouseId":"wh-001","shipmentId":"shp-abc123","dockNumber":1,'
        '"startTime":"08:00","endTime":"10:00","date":"2026-09-05","type":"PICKUP"}'
    ),
}


def _is_graphql_error(content) -> bool:
    """Return True if the ToolMessage content is a GraphQL error response."""
    import json as _json
    try:
        raw = content
        if isinstance(raw, list):
            raw = " ".join(
                b.get("text", "") for b in raw
                if isinstance(b, dict) and b.get("type") == "text"
            )
        parsed = _json.loads(str(raw))
        if isinstance(parsed, dict) and "errors" in parsed:
            errs = parsed["errors"]
            return bool(errs)
    except Exception:
        pass
    return False


def _extract_json_params(content) -> dict:
    """
    Robustly extract a JSON object from an LLM response.
    Handles plain JSON, markdown code blocks, and prose with embedded JSON.
    """
    import json as _json, re as _re

    if isinstance(content, list):
        content = " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    text = str(content).strip()

    # 1. Direct parse
    try:
        result = _json.loads(text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # 2. JSON inside code fences
    m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(1))
        except Exception:
            pass

    # 3. First { ... } block in the text
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except Exception:
            pass

    log.error("_extract_json_params: could not parse JSON — content=%.200s", text)
    return {}


def _build_agent(tools: list):
    """
    Build and compile a StateGraph with the provided MCP tools.

    Key design: the agent node asks the LLM ONLY for parameters (JSON) for
    the next step, then constructs the tool call in code.  The model never
    chooses which tool to call — _next_step() determines that deterministically
    from the conversation history.  This eliminates all looping / skipping.
    """
    llm_plain = _get_llm()           # no tools bound — used for param extraction
    llm_tools  = llm_plain.bind_tools(tools)  # used only for the final summary

    async def call_model(state: MessagesState) -> MessagesState:
        next_tool = _next_step(state)

        if not next_tool:
            # All 7 steps done — generate a free-text summary (no tool call needed)
            log.info("call_model: all steps complete — generating summary")
            response = await llm_tools.ainvoke(state["messages"])
            return {"messages": [response]}

        log.info("call_model: next_step='%s' — extracting parameters", next_tool)

        # Ask the LLM for the parameters ONLY (plain text response, no tool call)
        param_prompt = STEP_PARAM_PROMPTS[next_tool]
        messages_for_params = list(state["messages"]) + [HumanMessage(content=param_prompt)]
        param_response = await llm_plain.ainvoke(messages_for_params)
        params = _extract_json_params(param_response.content)
        log.info("call_model: %s → params=%s", next_tool, params)

        # Build the AIMessage with an explicit tool call for the correct tool.
        # This is injected into state and routed by route_after_agent exactly
        # as if the model had generated it — human_review will interrupt if
        # next_tool is in MUTATING_TOOLS (BookDockSlot).
        call_id = f"call_{uuid.uuid4().hex[:12]}"
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id":   call_id,
                "name": next_tool,
                "args": params,
                "type": "tool_call",
            }],
        )
        return {"messages": [ai_msg]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", _make_tool_node(tools))
    graph.set_entry_point("agent")
    _attach_human_in_the_loop(graph)
    return graph.compile(checkpointer=_checkpointer)


# ── Result extraction ─────────────────────────────────────────────────────────

def _extract_result(out: dict, thread_id: str) -> dict:
    """
    Normalise LangGraph output into the dict that main.py / PlanConfirmResponse expect.

    Interrupt (needs_confirmation)
        { status, thread_id, type, tool, arguments, summary, question }
    Done
        { status, thread_id, answer, tools_called, message_count }
    """
    if out.get("__interrupt__"):
        payload = out["__interrupt__"][0].value
        return {"status": "needs_confirmation", "thread_id": thread_id, **payload}

    messages  = out["messages"]
    ai_msgs   = [m for m in messages if isinstance(m, AIMessage)]
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]

    # Prefer the last AI text response; fall back to the last tool output.
    # Claude / Anthropic models (via OpenRouter) return content as a list of
    # content blocks [{"type": "text", "text": "..."}] rather than a plain str.
    def _content_to_str(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content) if content else ""

    import json as _json

    tools_called = [m.name for m in tool_msgs if hasattr(m, "name")]

    # Always prefer the structured summary when tools were called —
    # the AI's last message often contains raw JSON or intermediate reasoning.
    final_answer = _build_summary(tool_msgs, tools_called)

    # Fall back to the last AI text only when the summary is empty
    # (e.g. a pure question-and-answer with no tool calls).
    if not final_answer and ai_msgs:
        final_answer = _content_to_str(ai_msgs[-1].content)

    if not final_answer and tool_msgs:
        final_answer = _content_to_str(tool_msgs[-1].content)

    return {
        "status":        "done",
        "thread_id":     thread_id,
        "answer":        final_answer,
        "tools_called":  tools_called,
        "message_count": len(messages),
    }


def _build_summary(tool_msgs: list, tools_called: list) -> str:
    """
    Parse tool ToolMessage JSON responses and compose a readable
    shipment-plan summary for the UI.
    """
    import json as _json

    sections: list[str] = []

    def _parse(msg) -> dict:
        try:
            raw = msg.content
            # Already a dict — return directly
            if isinstance(raw, dict):
                return raw
            # Content-block list: [{"type": "text", "text": "..."}, ...]
            if isinstance(raw, list):
                # Could be a list of dicts (content blocks) or a plain list
                if raw and isinstance(raw[0], dict) and "type" in raw[0]:
                    raw = " ".join(
                        b.get("text", "") for b in raw
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                else:
                    raw = str(raw)
            if not isinstance(raw, str):
                raw = str(raw)
            parsed = _json.loads(raw)
            log.debug("_parse %s → keys=%s", getattr(msg, "name", "?"), list(parsed.keys()) if isinstance(parsed, dict) else type(parsed))
            return parsed if isinstance(parsed, dict) else {}
        except Exception as exc:
            log.warning("_parse failed for %s: %s | content_type=%s | content_preview=%.120s",
                        getattr(msg, "name", "?"), exc, type(msg.content).__name__, str(msg.content)[:120])
            return {}

    tool_index: dict[str, dict] = {}
    tool_errors: dict[str, str] = {}
    for msg in tool_msgs:
        name = getattr(msg, "name", None)
        # Skip synthetic error messages injected by dedup protection
        if not name or str(getattr(msg, "content", "")).startswith("STEP_ERROR:"):
            continue
        if name in tool_index or name in tool_errors:
            continue                        # keep first real call only
        parsed = _parse(msg)
        if _is_graphql_error(getattr(msg, "content", "")):
            import json as _j
            try:
                errs = _j.loads(str(msg.content) if isinstance(msg.content, str) else str(msg.content))
                tool_errors[name] = "; ".join(e.get("message", str(e)) for e in errs.get("errors", []))
            except Exception:
                tool_errors[name] = str(msg.content)[:200]
        else:
            tool_index[name] = parsed

    # ── Failed steps (show errors prominently) ───────────────────────────────
    for failed_tool, err_msg in tool_errors.items():
        sections.append(f"❌ {failed_tool} FAILED: {err_msg}")

    # ── Warehouse capacity ───────────────────────────────────────────────────
    wh_data = tool_index.get("GetWarehouseCapacity", {}).get("data", {})
    cap = wh_data.get("warehouseCapacity", {})
    wh  = wh_data.get("warehouse", {})
    if cap:
        avail = cap.get("availableM3", 0)
        pct   = cap.get("utilizationPct", 0)
        wh_addr = wh.get("address", {}) if wh else {}
        postal  = wh_addr.get("postalCode", "")
        city    = wh_addr.get("city", "")
        loc     = f"  ({city} {postal})" if (city or postal) else ""
        sections.append(f"📍 Warehouse  {cap.get('warehouseId')}{loc}  —  {avail:.0f} m³ free  ({pct:.0f}% used)")

    # ── Route ────────────────────────────────────────────────────────────────
    opt = tool_index.get("OptimizeRoute", {}).get("data", {}).get("optimizeRoute", {})
    if opt:
        route = opt.get("recommendedRoute") or {}
        dist  = route.get("totalDistanceKm", 0)
        hrs   = route.get("estimatedDurationHours", 0)
        sections.append(
            f"🗺️  Route      {route.get('name', 'N/A')}  ·  {route.get('transportMode', '')}  "
            f"·  {dist:.0f} km  ·  ~{hrs:.0f} h"
        )
        # Trim ISO timestamp to date-only (2026-09-02T06:53:54Z → 2026-09-02)
        raw_date = opt.get("estimatedDeliveryDate", "N/A")
        delivery_date = raw_date[:10] if raw_date and raw_date != "N/A" else raw_date
        sections.append(f"📅 Est. delivery  {delivery_date}"
                        f"  ·  Cost: ${opt.get('estimatedCost', 0):.2f}")

    # ── Carrier quote ────────────────────────────────────────────────────────
    quote = tool_index.get("GetCarrierQuote", {}).get("data", {}).get("carrierQuote", {})
    if quote:
        sections.append(
            f"💰 Quote       {quote.get('carrierName', 'N/A')}  ·  "
            f"${quote.get('totalCost', 0):.2f} total  ·  {quote.get('transitDays', '?')} days  "
            f"·  {quote.get('serviceLevel', '')}"
        )

    # ── Shipment created ─────────────────────────────────────────────────────
    ship = tool_index.get("CreateShipment", {}).get("data", {}).get("createShipment", {})
    if ship:
        sections.append(
            f"📦 Shipment    #{ship.get('trackingNumber', 'N/A')}  ·  "
            f"ID: {ship.get('id', 'N/A')}  ·  Status: {ship.get('status', '')}"
        )
        addr = ship.get("destinationAddress") or {}
        if addr:
            sections.append(f"   →  {addr.get('city')}, {addr.get('state', '')} {addr.get('postalCode')} {addr.get('country')}")

    # ── Carrier booking ──────────────────────────────────────────────────────
    booking = tool_index.get("BookCarrier", {}).get("data", {}).get("bookCarrier", {})
    if booking:
        sections.append(
            f"🚛 Carrier booked  #{booking.get('trackingNumber', 'N/A')}  ·  "
            f"Booking: {booking.get('bookingId', 'N/A')}"
        )
        sections.append(f"   Pickup: {booking.get('pickupWindow', 'N/A')}  ·  Delivery: {booking.get('estimatedDelivery', 'N/A')}")

    # ── Dock slot ────────────────────────────────────────────────────────────
    slot = tool_index.get("BookDockSlot", {}).get("data", {}).get("bookDockSlot", {})
    if slot:
        sections.append(
            f"🏭 Dock slot   Dock #{slot.get('dockNumber')}  ·  "
            f"{slot.get('date')}  ·  {slot.get('startTime')}–{slot.get('endTime')}  ·  {slot.get('type')}"
        )

    if not sections:
        return ""

    header = "✅  Shipment Plan Complete\n" + "─" * 48
    return header + "\n" + "\n".join(sections)


# ── Public API ────────────────────────────────────────────────────────────────

async def run_agent_hitl(
    user_message: str,
    thread_id: Optional[str] = None,
    authorization: Optional[str] = None,
) -> dict:
    """Start a planning conversation."""
    thread_id = thread_id or str(uuid.uuid4())
    config    = {"configurable": {"thread_id": thread_id}}

    tools    = await _get_tools(authorization)
    compiled = _build_agent(tools)
    try:
        out = await compiled.ainvoke(
            {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_message)]},
            config={**config, "recursion_limit": 50},
        )
    except GraphRecursionError:
        log.warning("Recursion limit hit on thread %s; returning best-effort result", thread_id)
        state = compiled.get_state(config)
        out   = dict(state.values) if state else {"messages": []}
    return _extract_result(out, thread_id)


async def resume_agent_hitl(
    thread_id: str,
    approved: bool,
    authorization: Optional[str] = None,
) -> dict:
    """Resume a paused conversation after human approval or rejection."""
    config = {"configurable": {"thread_id": thread_id}}

    tools    = await _get_tools(authorization)
    compiled = _build_agent(tools)
    try:
        out = await compiled.ainvoke(
            Command(resume={"approved": approved}),
            config={**config, "recursion_limit": 50},
        )
    except GraphRecursionError:
        log.warning("Recursion limit hit on thread %s resume; returning best-effort result", thread_id)
        state = compiled.get_state(config)
        out   = dict(state.values) if state else {"messages": []}
    return _extract_result(out, thread_id)
