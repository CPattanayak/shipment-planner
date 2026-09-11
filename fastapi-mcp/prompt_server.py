"""
fastapi-mcp / prompt_server.py
──────────────────────────────
Lightweight FastMCP server that owns and serves versioned agent prompts.

Why this exists
───────────────
  agent_v4 previously had the planning system prompt hard-coded.  Any
  prompt change required rebuilding and redeploying the FastAPI gateway.

  This server externalises prompts so they can be:
    • versioned independently of gateway code
    • swapped at runtime (point ACTIVE_PLANNING_PROMPT to a new file)
    • A/B tested (two gateway instances, different prompt versions)

Versioning scheme
─────────────────
  prompts/planning_v1.txt   ← initial release
  prompts/planning_v2.txt   ← future iterations
  ...

  ACTIVE_PLANNING_PROMPT env var (default "planning_v1") controls which
  file is served.  Change the env var and restart this service — no gateway
  redeploy needed.

MCP surface
───────────
  Resource  prompt://planning/current
              → text of the active planning prompt

  Resource  prompt://planning/versions
              → JSON list of available prompt versions

  Prompt    planning_system_prompt
              → same text, exposed via MCP prompts/get protocol

Transport
─────────
  Streamable HTTP on port 8091 (configurable via PORT env var).
  URL: http://localhost:8091/mcp
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("prompt-server")

# ── Config ────────────────────────────────────────────────────────────────────

PROMPTS_DIR           = Path(__file__).parent / "prompts"
ACTIVE_VERSION        = os.getenv("ACTIVE_PLANNING_PROMPT", "planning_v1")
PORT                  = int(os.getenv("PORT", "8091"))

# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP("prompt-server", port=PORT)


def _load_prompt(version: str) -> str:
    """Load a prompt file by version name; raises FileNotFoundError if absent."""
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt version '{version}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()


def _list_versions() -> list[str]:
    """Return sorted list of available prompt version names (stem of .txt files)."""
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.txt"))


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource("prompt://planning/current")
def current_planning_prompt() -> str:
    """
    The active planning system prompt.
    Controlled by ACTIVE_PLANNING_PROMPT env var (default: planning_v1).
    agent_v4 fetches this URI at the start of every planning run.
    """
    text = _load_prompt(ACTIVE_VERSION)
    log.info("resource prompt://planning/current  version=%s  chars=%d", ACTIVE_VERSION, len(text))
    return text


@mcp.resource("prompt://planning/versions")
def available_prompt_versions() -> str:
    """
    JSON list of all available prompt versions in the prompts/ directory.
    Useful for inspection / tooling.
    """
    versions = _list_versions()
    log.info("resource prompt://planning/versions  → %s", versions)
    return json.dumps({"active": ACTIVE_VERSION, "available": versions})


# ── Prompts (MCP prompts/get protocol) ────────────────────────────────────────

@mcp.prompt()
def planning_system_prompt() -> str:
    """
    Planning system prompt via the MCP prompts protocol.
    Equivalent to reading prompt://planning/current but accessed
    via prompts/get instead of resources/read.
    """
    return _load_prompt(ACTIVE_VERSION)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    versions = _list_versions()
    log.info("prompt-server starting  port=%d  active=%s  versions=%s",
             PORT, ACTIVE_VERSION, versions)
    mcp.run(transport="streamable-http")