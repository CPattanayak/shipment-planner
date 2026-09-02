"""Central configuration – reads from environment / .env file."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── OpenRouter ────────────────────────────────────────────────────────────────
# OpenRouter is OpenAI-API-compatible; we point langchain-openai at it.
OPENROUTER_API_KEY  = os.environ["OPENROUTER_API_KEY"]           # required
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "shipment-planner")

# ── MCP Server ────────────────────────────────────────────────────────────────
MCP_SERVER_URL      = os.getenv("MCP_SERVER_URL", "http://localhost:8090/mcp")

# ── Apollo Router ─────────────────────────────────────────────────────────────
GRAPHQL_ENDPOINT    = os.getenv("GRAPHQL_ENDPOINT", "http://localhost:4000/graphql")
