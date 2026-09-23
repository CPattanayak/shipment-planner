"""
AutoGen Chat — Redis-backed, pure async, MCP-native tool discovery
══════════════════════════════════════════════════════════════════
Uses autogen_ext.tools.mcp.McpWorkbench to connect directly to the
apollo-mcp-server so tool schemas are auto-discovered — no manual
tool definitions, no threads, no queues.

  POST   /api/chat/sessions              Create session → {sessionId}
  POST   /api/chat/{sessionId}           Send message → SSE stream
  GET    /api/chat/{sessionId}/history   Full message history
  DELETE /api/chat/{sessionId}           Delete session immediately
  POST   /api/chat/{sessionId}/beacon    sendBeacon cleanup on tab close

SSE event types:
  tool_call    — MCP tool invoked  {tool, call_id, args}
  tool_result  — MCP tool result   {call_id, content}
  message      — assistant text    {content}
  error        — unrecoverable     {content}
  done         — turn complete
"""

import json
import logging
import os
import uuid

import redis as _redis_lib
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import (
    TextMessage,
    ToolCallRequestEvent,
    ToolCallExecutionEvent,
)

log = logging.getLogger(__name__)
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import McpWorkbench, StreamableHttpServerParams

from config import (
    LLM_PROVIDER,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    MISTRAL_API_KEY, MISTRAL_MODEL,
    MCP_SERVER_URL,
)

from chatbot import _SYSTEM_MESSAGE

router = APIRouter(prefix="/api/chat", tags=["Chat"])

# ── Redis ──────────────────────────────────────────────────────────────────────

_r = _redis_lib.Redis.from_url(
    os.getenv("REDIS_URL", "redis://redis:6379"),
    decode_responses=True,
)
TTL = int(os.getenv("CHAT_SESSION_TTL", "3600"))


def get_state(session_id: str) -> dict | None:
    data = _r.get(f"chat:{session_id}")
    return json.loads(data) if data else None


def save_state(session_id: str, state: dict) -> None:
    _r.set(f"chat:{session_id}", json.dumps(state), ex=TTL)


# ── Model client ───────────────────────────────────────────────────────────────

def _make_model_client() -> OpenAIChatCompletionClient:
    if LLM_PROVIDER == "mistral":
        return OpenAIChatCompletionClient(
            model=MISTRAL_MODEL,
            api_key=MISTRAL_API_KEY,
            base_url="https://api.mistral.ai/v1",
        )
    return OpenAIChatCompletionClient(
        model=OPENROUTER_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )


# ── MCP server params ──────────────────────────────────────────────────────────

_MCP_PARAMS = StreamableHttpServerParams(url=MCP_SERVER_URL)


# ── Core async streaming turn ──────────────────────────────────────────────────

async def stream_chat(history: list[dict], user_input: str):
    """
    Pure async generator — yields SSE-ready dicts for one conversation turn.

    McpWorkbench opens a connection to the MCP server, discovers all tools,
    and hands them to AssistantAgent.  run_stream() drives the full
    tool-call loop internally — we just forward the events.
    """
    # Build the task: inject prior history as text context so the LLM has memory
    if history:
        ctx = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in history[-20:]
        )
        task = f"[Conversation so far]\n{ctx}\n\n[New message]\n{user_input}"
    else:
        task = user_input

    final_content: list[str] = []
    # Accumulate raw tool results so we can summarise them if autogen doesn't
    # produce a TextMessage on its own (AssistantAgent.run_stream sometimes
    # skips the follow-up LLM call when using McpWorkbench).
    tool_results_for_summary: list[str] = []

    async with McpWorkbench(server_params=_MCP_PARAMS) as workbench:
        agent = AssistantAgent(
            name="ShipmentPlannerBot",
            model_client=_make_model_client(),
            workbench=workbench,
            system_message=_SYSTEM_MESSAGE,
        )

        async for event in agent.run_stream(task=task):
            log.info("autogen event: %s  source=%s",
                     type(event).__name__, getattr(event, "source", "—"))

            if isinstance(event, ToolCallRequestEvent):
                for tc in event.content:
                    args = tc.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            pass
                    yield {"type": "tool_call", "tool": tc.name,
                           "call_id": tc.id, "args": args}

            elif isinstance(event, ToolCallExecutionEvent):
                for result in event.content:
                    raw = str(result.content)
                    tool_results_for_summary.append(
                        f"Tool {result.call_id} result:\n{raw}"
                    )
                    yield {
                        "type": "tool_result",
                        "call_id": result.call_id,
                        "content": raw,
                    }

            elif isinstance(event, TextMessage) and event.source not in ("user", ""):
                log.info("TextMessage source=%r len=%d", event.source, len(event.content))
                final_content.append(event.content)
                yield {"type": "message", "content": event.content}

    # ── Post-loop: if autogen never emitted a TextMessage, summarise manually ──
    if not final_content:
        if tool_results_for_summary:
            log.info("no TextMessage received — calling LLM to summarise %d tool results",
                     len(tool_results_for_summary))
            summary_prompt = (
                    f"The user asked: {user_input}\n\n"
                    "The following tool results were returned:\n\n"
                    + "\n\n".join(tool_results_for_summary)
                    + "\n\nWrite a friendly, plain-language summary for the user. "
                      "Use short bullet points. Do NOT show raw JSON or IDs."
            )
            model_client = _make_model_client()
            from autogen_core.models import UserMessage as _UserMessage
            try:
                llm_resp = await model_client.create(
                    [_UserMessage(content=summary_prompt, source="user")]
                )
                summary = (
                    llm_resp.content
                    if isinstance(llm_resp.content, str)
                    else str(llm_resp.content)
                )
                log.info("summary generated len=%d", len(summary))
                final_content.append(summary)
                yield {"type": "message", "content": summary}
            except Exception as exc:
                log.error("summary LLM call failed: %s", exc)
                yield {"type": "message",
                       "content": "Tools ran successfully — ask me to explain the results."}
        else:
            log.warning("stream ended with no events at all")
            yield {"type": "message",
                   "content": "I didn't find anything to report. Could you clarify your request?"}


# ── Request models ─────────────────────────────────────────────────────────────

class Message(BaseModel):
    message: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session():
    """Create an empty session in Redis and return its ID."""
    session_id = str(uuid.uuid4())
    save_state(session_id, {"messages": []})
    return {"sessionId": session_id}


@router.post("/{session_id}")
async def chat(session_id: str, body: Message):
    """Send one message — streams SSE events for the full tool-call + reply cycle."""
    state = get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    history  = state.get("messages", [])
    user_msg = body.message
    reply_parts: list[str] = []

    async def _sse():
        try:
            async for event in stream_chat(history, user_msg):
                if event.get("type") == "message":
                    reply_parts.append(event["content"])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
        finally:
            save_state(session_id, {
                "messages": history + [
                    {"role": "user",      "content": user_msg},
                    {"role": "assistant", "content": "".join(reply_parts)},
                ]
            })
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/history")
async def get_history(session_id: str):
    state = get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return {"sessionId": session_id, "messages": state.get("messages", []), "ttl": TTL}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete session from Redis immediately (user clicked End Session)."""
    _r.delete(f"chat:{session_id}")
    return {"deleted": True}


@router.post("/{session_id}/beacon")
async def beacon_delete(session_id: str):
    """Fire-and-forget cleanup via navigator.sendBeacon() on tab close."""
    _r.delete(f"chat:{session_id}")
    return Response(status_code=204)