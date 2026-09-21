"""
AutoGen Chat Router — SSE subscription API
──────────────────────────────────────────
Three endpoints form the chat contract:

  POST   /api/chat/sessions                Create session + start AutoGen thread.
                                           Body: { "firstMessage"?: "..." }
                                           Returns: { "sessionId": "uuid" }

  GET    /api/chat/{sessionId}/stream      SSE subscription — push events to client.
                                           Event types:
                                             ready        — agent waiting for input
                                             message      — assistant text reply
                                             tool_call    — MCP tool being invoked
                                             tool_result  — MCP tool response
                                             error        — unrecoverable error
                                             done         — session ended

  POST   /api/chat/{sessionId}/send        User sends a message.
                                           Body: { "message": "..." }
                                           Returns: { "queued": true }

  DELETE /api/chat/{sessionId}             Terminate session.

Design
──────
  AutoGen runs in a background thread.
  A threading.Queue bridges both directions:
    out_q : AutoGen events   →  SSE generator (polled via run_in_executor)
    in_q  : HTTP POST /send  →  AutoGen's get_human_input() (blocks thread)

  The SSE generator uses FastAPI StreamingResponse (same pattern as /api/v1/stream
  which is already proven to work in this gateway) and polls out_q via
  run_in_executor so the asyncio event loop is never blocked.
"""

import asyncio
import json
import logging
import queue as _tqueue
import threading
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("chat-router")
# Raise to WARNING level so messages appear in docker logs without extra config
logging.getLogger("chat-router").setLevel(logging.DEBUG)

router = APIRouter(prefix="/api/chat", tags=["Chat (AutoGen SSE)"])


# ── Session store ─────────────────────────────────────────────────────────────

class _Session:
    """One live AutoGen chatbot conversation."""

    def __init__(self):
        # queue.Queue is thread-safe and supports get(timeout=…).
        self.out_q: _tqueue.Queue = _tqueue.Queue()  # autogen → SSE
        self.in_q:  _tqueue.Queue = _tqueue.Queue()  # user → autogen
        self.alive: bool = True

    def push(self, event: dict) -> None:
        """Thread-safe: enqueue an event for the SSE generator."""
        log.warning("PUSH event: %s", event.get("type", "?"))
        self.out_q.put(event)

    def put_user_message(self, message: str) -> None:
        """Thread-safe: queue a user message into the autogen thread."""
        self.in_q.put(message)


_sessions: dict[str, _Session] = {}

_EXIT_WORDS = {"exit", "quit", "bye", "goodbye"}


# ── Agent background thread ───────────────────────────────────────────────────

def _run_autogen(session: _Session, first_message: str) -> None:
    """
    Run a pyautogen 0.2.x conversation in a background thread.

    _StreamingAssistant overrides send() to push every assistant reply to the
    SSE queue.  _QueueProxy overrides get_human_input() to block on the in_q
    (fed by POST /send) and execute_function() to emit tool_call / tool_result
    events before and after each MCP tool call.
    """
    session.push({"type": "message", "role": "assistant",
                  "content": "⚙️ AutoGen thread started — loading agent…"})

    try:
        import autogen
    except ImportError:
        session.push({"type": "error", "content": "pyautogen is not installed"})
        session.push({"type": "done"})
        return

    from chatbot import (
        _build_llm_config, _SYSTEM_MESSAGE,
        get_warehouse_capacity, optimize_route,
        get_available_carriers, get_carrier_quote,
    )
    push = session.push

    # ── Subclasses that bridge AutoGen events → SSE queue ────────────────────

    class _StreamingAssistant(autogen.AssistantAgent):
        def send(self, message, recipient, request_reply=None, silent=False):
            content = message if isinstance(message, str) else (message.get("content") or "")
            if content.strip():
                push({"type": "message", "role": "assistant", "content": content})
            return super().send(message, recipient, request_reply, silent)

    class _QueueProxy(autogen.UserProxyAgent):
        def get_human_input(self, prompt: str) -> str:
            # If the last assistant message has pending tool/function calls,
            # return "" so AutoGen auto-executes them without blocking for user
            # input.  Only ask the user for input when there are no tool calls.
            last_msg = None
            for msgs in self.chat_messages.values():
                if msgs:
                    last_msg = msgs[-1]
            if last_msg and (last_msg.get("tool_calls") or last_msg.get("function_call")):
                return ""   # auto-proceed → AutoGen will call execute_function

            push({"type": "ready"})
            try:
                msg = session.in_q.get(timeout=600)
            except _tqueue.Empty:
                return "exit"
            if msg.strip().lower() in _EXIT_WORDS:
                session.alive = False
            return msg

        def execute_function(self, func_call, verbose=False):
            name = func_call.get("name", "")
            try:
                args = json.loads(func_call.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            push({"type": "tool_call", "tool": name, "args": args})
            result = super().execute_function(func_call, verbose)
            push({"type": "tool_result", "tool": name, "content": str(result[1])})
            return result

    # ── Build LLM config ─────────────────────────────────────────────────────

    try:
        llm_config = _build_llm_config()
    except SystemExit as exc:
        session.push({"type": "error", "content": str(exc)})
        session.push({"type": "done"})
        return

    # ── Create agents ─────────────────────────────────────────────────────────

    assistant = _StreamingAssistant(
        name="ShipmentPlannerBot",
        system_message=_SYSTEM_MESSAGE,
        llm_config=llm_config,
    )
    user_proxy = _QueueProxy(
        name="User",
        human_input_mode="ALWAYS",
        is_termination_msg=lambda msg: (
            "terminate" in (msg.get("content") or "").lower()
        ),
        code_execution_config=False,
        # Must be > 0.  With max=0, check_termination_and_human_reply sees
        # counter(0) >= max(0) → True and short-circuits BEFORE the function-
        # call handler runs, producing "USER INTERRUPTED" for every tool call.
        # A large value lets tool-call turns fall through to execute_function
        # while human turns (non-empty get_human_input return) still route
        # through the normal human-reply branch.
        max_consecutive_auto_reply=100,
    )

    for fn in [get_warehouse_capacity, optimize_route,
               get_available_carriers, get_carrier_quote]:
        autogen.register_function(
            fn,
            caller=assistant,
            executor=user_proxy,
            description=fn.__doc__ or fn.__name__,
        )

    # ── Run conversation ──────────────────────────────────────────────────────

    try:
        user_proxy.initiate_chat(assistant, message=first_message)
    except Exception as exc:
        log.error("AutoGen error: %s", exc, exc_info=True)
        push({"type": "error", "content": str(exc)})
    finally:
        push({"type": "done"})
        session.alive = False


# ── Request / response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    firstMessage: str = "Hello! I need help planning a shipment."


class SendMessageRequest(BaseModel):
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(body: CreateSessionRequest):
    """Create a new chat session and start the AutoGen conversation."""
    session_id = str(uuid.uuid4())
    session    = _Session()
    _sessions[session_id] = session

    thread = threading.Thread(
        target=_run_autogen,
        args=(session, body.firstMessage),
        daemon=True,
        name=f"autogen-{session_id[:8]}",
    )
    thread.start()
    log.warning("chat session created: %s", session_id)

    return {"sessionId": session_id}


@router.get("/{session_id}/stream")
async def stream_session(session_id: str):
    """
    SSE subscription — receive all agent events for this session.

    Uses FastAPI StreamingResponse with text/event-stream media type (same
    pattern as /api/v1/stream which is proven to work in this gateway).
    out_q is polled via run_in_executor so the event loop is never blocked.
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    log.warning("SSE stream opened: %s", session_id)

    async def _generator() -> AsyncGenerator[bytes, None]:
        loop = asyncio.get_running_loop()

        # Send the SSE headers comment so the browser's EventSource knows
        # the stream is alive immediately.
        yield b": connected\n\n"

        def _blocking_get() -> dict | None:
            """Block a thread-pool worker for up to 25 s; return None on timeout."""
            try:
                item = session.out_q.get(timeout=25)
                log.warning("SSE dequeued event type=%s", item.get("type", "?"))
                return item
            except _tqueue.Empty:
                return None

        try:
            while True:
                event = await loop.run_in_executor(None, _blocking_get)

                if event is None:
                    # Keep-alive comment (not a data event — won't trigger onmessage)
                    log.warning("SSE keep-alive ping for %s", session_id)
                    yield b"event: ping\ndata: {}\n\n"
                    continue

                payload = json.dumps(event)
                log.warning("SSE yielding: %s", payload[:120])
                yield f"data: {payload}\n\n".encode()

                if event.get("type") == "done":
                    _sessions.pop(session_id, None)
                    break

        except asyncio.CancelledError:
            log.warning("SSE client disconnected: %s", session_id)
        except Exception as exc:
            log.error("SSE generator error: %s", exc, exc_info=True)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",     # tell nginx not to buffer
            "Connection": "keep-alive",
        },
    )


@router.post("/{session_id}/send")
async def send_message(session_id: str, body: SendMessageRequest):
    """Send a user message to the AutoGen thread."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or already closed")
    if not session.alive and body.message.strip().lower() not in _EXIT_WORDS:
        raise HTTPException(status_code=410, detail="Session has ended")

    session.put_user_message(body.message)
    log.warning("message queued → session %s: %.60s", session_id, body.message)
    return {"queued": True}


@router.delete("/{session_id}")
async def close_session(session_id: str):
    """Terminate a session by injecting an exit signal."""
    session = _sessions.get(session_id)
    if session:
        session.put_user_message("exit")
    _sessions.pop(session_id, None)
    return {"closed": True}
