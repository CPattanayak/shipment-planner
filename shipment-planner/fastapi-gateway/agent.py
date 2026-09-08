"""
Free-form shipment planning agent (no HITL).

Uses the same standard LangGraph approach as agent_hitl.py:
    MultiServerMCPClient  →  real BaseTool objects
    create_react_agent    →  standard ReAct loop (no custom graph)

Used by:
    POST /api/v1/ask      – single question → single answer
    GET  /api/v1/stream   – SSE streaming response
"""

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent_hitl import _get_llm, _get_tools, SYSTEM_PROMPT   # shared helpers


async def run_agent(user_message: str) -> dict:
    """Run the agent for a single question and return the final answer."""
    from langchain_core.messages import AIMessage, ToolMessage

    tools = await _get_tools()
    agent = create_react_agent(_get_llm(), tools, prompt=SYSTEM_PROMPT)

    out = await agent.ainvoke({"messages": [{"role": "user", "content": user_message}]})

    messages     = out.get("messages", [])
    ai_msgs      = [m for m in messages if isinstance(m, AIMessage)]
    tool_msgs    = [m for m in messages if isinstance(m, ToolMessage)]
    final_answer = ai_msgs[-1].content if ai_msgs else "No answer generated."

    return {
        "answer":        final_answer,
        "tools_called":  [m.name for m in tool_msgs if hasattr(m, "name")],
        "message_count": len(messages),
    }


async def stream_agent(user_message: str):
    """Async generator that yields SSE-friendly chunks as the agent runs."""
    tools = await _get_tools()
    agent = create_react_agent(_get_llm(), tools, prompt=SYSTEM_PROMPT)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": user_message}]},
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield {"type": "token", "data": chunk.content}
        elif kind == "on_tool_start":
            yield {"type": "tool_call", "data": event.get("name", "")}
        elif kind == "on_tool_end":
            yield {"type": "tool_result", "data": "done"}
