"""
Shipment Planning Agent — standard LangGraph approach.

Uses the official LangChain MCP adapter and prebuilt ReAct agent:

    MultiServerMCPClient  →  fetches real BaseTool objects from the Apollo MCP Server
    create_react_agent    →  handles the entire plan-execute loop (no custom graph)
    interrupt_before=["tools"]  →  lets us inspect pending tool calls before they run

HITL logic (server-side, transparent to the agent):
  • Non-mutating tools  →  auto-resumed immediately (user never sees a prompt)
  • Mutating tools      →  paused; caller receives "needs_confirmation"
    CreateShipment / BookCarrier / BookDockSlot

Flow visible to the caller
─────────────────────────────
  POST /api/v1/plan
        │
        ▼
  run_agent_hitl()
        │
        ├── read-only tools → auto-resume → runs to completion → "done"
        │
        └── mutating tool   → returns "needs_confirmation" + thread_id
                                        │
                                 POST /api/v1/plan/confirm
                                        │
                                 resume_agent_hitl(approved)
                                        │
                                   approved → continues → "done"
                                   rejected → rejection message → "done"
"""

import uuid
from collections import OrderedDict
from time import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command

from config import MCP_SERVER_URL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL

# ── Monkey-patch: MCP SDK empty-SSE priming-event bug (#1672) ────────────────
# The Apollo MCP Server sends an empty SSE event to open the stream; the MCP
# Python SDK tries to JSON-parse it and crashes.  Skip events with no data.
def _patch_mcp_empty_sse_bug() -> None:
    try:
        from mcp.client.streamable_http import StreamableHTTPTransport

        _orig = StreamableHTTPTransport._handle_sse_event

        async def _patched(self, sse, *args, **kwargs):
            if not sse.data or sse.data.strip() == "":
                return False          # silently discard the priming event
            return await _orig(self, sse, *args, **kwargs)

        StreamableHTTPTransport._handle_sse_event = _patched
    except Exception:
        pass  # SDK version without the bug; nothing to do


_patch_mcp_empty_sse_bug()


# ── Tools that require human approval before execution ────────────────────────
MUTATING_TOOLS = {"CreateShipment", "BookCarrier", "BookDockSlot"}


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert shipment planning AI assistant.
You have access to a set of tools that interact with a live logistics system via GraphQL.

When the user asks about shipments, routes, carriers, or warehouses:
1. Identify which tools you need to call.
2. Call them in the right order:
   check warehouse capacity → optimize route → get available carriers →
   get carrier quote → CREATE SHIPMENT → book carrier → book dock slot.
3. Present a clear, actionable response with concrete recommendations.

Always prefer data from tools over assumptions.
If a tool call fails, explain why and suggest alternatives.
"""


# ── Tool cache: keyed by auth token, TTL = 300 s, max 200 entries ─────────────
_CACHE_TTL: int = 300
_CACHE_MAX: int = 200
_tools_cache: OrderedDict[str, tuple[list, float]] = OrderedDict()


async def _get_tools(authorization: str | None = None) -> list:
    """
    Return LangChain BaseTool objects from the Apollo MCP Server.

    Results are cached per auth token with a 300-second TTL to avoid
    rebuilding the MultiServerMCPClient on every request.
    """
    key = authorization or "__anon__"

    if key in _tools_cache:
        tools, ts = _tools_cache[key]
        if time() - ts < _CACHE_TTL:
            _tools_cache.move_to_end(key)   # LRU refresh
            return tools
        del _tools_cache[key]

    client = MultiServerMCPClient(
        {
            "shipment-planner": {
                "transport": "streamable_http",
                "url": MCP_SERVER_URL,
                **({"headers": {"Authorization": authorization}} if authorization else {}),
            }
        }
    )
    tools = await client.get_tools()   # real BaseTool objects — no hand-crafting

    if len(_tools_cache) >= _CACHE_MAX:
        _tools_cache.popitem(last=False)   # evict oldest (LRU)
    _tools_cache[key] = (tools, time())
    return tools


# ── LLM ───────────────────────────────────────────────────────────────────────
def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=OPENROUTER_MODEL,
        openai_api_key=OPENROUTER_API_KEY,
        openai_api_base=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://shipment-planner.local",
            "X-Title": "Shipment Planner",
        },
        temperature=0,
        streaming=True,
    )


# ── Checkpointer — module-level singleton shared across all requests ───────────
_checkpointer = MemorySaver()


# ── Agent factory ─────────────────────────────────────────────────────────────
async def _build_agent(authorization: str | None = None):
    """
    Build a standard create_react_agent.

    interrupt_before=["tools"] tells LangGraph to pause the graph just before
    the tools node executes so we can inspect which tools are about to be called
    and decide whether human approval is required.
    """
    tools = await _get_tools(authorization)
    return create_react_agent(
        _get_llm(),
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=_checkpointer,
        interrupt_before=["tools"],   # pause before every tool execution
    )


# ── Pending-tool inspection ───────────────────────────────────────────────────
def _pending_tool_calls(out: dict) -> list[dict]:
    """
    After an interrupt, the last AIMessage in state["messages"] holds the
    tool_calls the agent wants to make next.  Return them as plain dicts.
    """
    messages = out.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            return [
                {"name": tc["name"], "args": tc.get("args", tc.get("arguments", {}))}
                for tc in msg.tool_calls
            ]
    return []


# ── Result extraction ─────────────────────────────────────────────────────────
def _extract(out: dict, thread_id: str) -> dict:
    """Translate raw graph output into the API response shape."""
    interrupts = out.get("__interrupt__", [])

    if interrupts:
        # The interrupt value is the list of ToolCall objects about to run
        pending = _pending_tool_calls(out)
        tc = pending[0] if pending else {}
        tool_name = tc.get("name", "unknown")
        tool_args = tc.get("args", {})
        return {
            "status":    "needs_confirmation",
            "thread_id": thread_id,
            "tool":      tool_name,
            "arguments": tool_args,
            "summary":   f"Agent wants to call '{tool_name}'",
            "question":  f"Approve '{tool_name}'?",
        }

    # Graph ran to completion
    messages     = out.get("messages", [])
    ai_msgs      = [m for m in messages if isinstance(m, AIMessage)]
    tool_msgs    = [m for m in messages if isinstance(m, ToolMessage)]
    final_answer = ai_msgs[-1].content if ai_msgs else "No answer generated."
    tools_called = [m.name for m in tool_msgs if hasattr(m, "name")]

    return {
        "status":        "done",
        "thread_id":     thread_id,
        "answer":        final_answer,
        "tools_called":  tools_called,
        "message_count": len(messages),
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def run_agent_hitl(
    user_message: str,
    thread_id: Optional[str] = None,
    authorization: Optional[str] = None,
) -> dict:
    """
    Start a planning conversation.

    Non-mutating tools are auto-resumed so the caller never has to confirm them.
    Mutating tools (CreateShipment, BookCarrier, BookDockSlot) pause and return
    "needs_confirmation" with the thread_id needed for /plan/confirm.
    """
    thread_id = thread_id or str(uuid.uuid4())
    agent  = await _build_agent(authorization)
    config = {"configurable": {"thread_id": thread_id}}

    out = await agent.ainvoke(
        {"messages": [{"role": "user", "content": user_message}]},
        config=config,
    )

    # Auto-resume non-mutating tool calls so only write operations surface to users
    while out.get("__interrupt__"):
        pending = _pending_tool_calls(out)
        first_tool = pending[0]["name"] if pending else ""

        if first_tool in MUTATING_TOOLS:
            # Pause — let the caller decide
            return _extract(out, thread_id)

        # Non-mutating: auto-approve and keep running
        out = await agent.ainvoke(Command(resume=None), config=config)

    return _extract(out, thread_id)


async def resume_agent_hitl(
    thread_id: str,
    approved: bool,
    authorization: Optional[str] = None,
) -> dict:
    """
    Resume a paused conversation after the human has decided.

    approved=True  → the tool executes normally
    approved=False → we inject a rejection ToolMessage and let the agent conclude
    """
    agent  = await _build_agent(authorization)
    config = {"configurable": {"thread_id": thread_id}}

    if approved:
        # Let the tool run
        out = await agent.ainvoke(Command(resume=None), config=config)
    else:
        # Reject: skip tool execution, send a rejection back as a ToolMessage
        # so the agent can produce a clean "not approved" final answer.
        out = await agent.ainvoke(
            Command(resume="rejected — operation not approved by user"),
            config=config,
        )

    # Continue auto-resuming non-mutating tools that follow
    while out.get("__interrupt__"):
        pending   = _pending_tool_calls(out)
        first_tool = pending[0]["name"] if pending else ""
        if first_tool in MUTATING_TOOLS:
            return _extract(out, thread_id)
        out = await agent.ainvoke(Command(resume=None), config=config)

    return _extract(out, thread_id)


async def close_session(thread_id: str) -> None:
    """Delete a completed / abandoned thread from the checkpointer."""
    try:
        await _checkpointer.adelete_thread(thread_id)
    except Exception:
        pass
