"""Central configuration – reads from environment / .env file."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM Provider ─────────────────────────────────────────────────────────────
# Set LLM_PROVIDER=mistral to use Mistral AI instead of OpenRouter.
# Valid values: "openrouter" (default) | "mistral"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter")

# ── OpenRouter ────────────────────────────────────────────────────────────────
# OpenRouter is OpenAI-API-compatible; we point langchain-openai at it.
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "shipment-planner")

# ── Mistral AI ────────────────────────────────────────────────────────────────
# Used when LLM_PROVIDER=mistral.
# Recommended tool-use models: mistral-large-latest, mistral-medium-latest
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL   = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

# ── MCP Server ────────────────────────────────────────────────────────────────
MCP_SERVER_URL      = os.getenv("MCP_SERVER_URL", "http://localhost:8090/mcp")

# ── Prompt MCP Server ─────────────────────────────────────────────────────────
# fastapi-mcp service that serves versioned system prompts.
# Leave empty ("") to always use the built-in hardcoded fallback.
# When set, agent_v4 fetches the active prompt at runtime; the hardcoded
# SYSTEM_PROMPT in agent_v4.py remains the fallback if this server is down.
PROMPT_MCP_SERVER_URL = os.getenv("PROMPT_MCP_SERVER_URL", "http://localhost:8091/mcp")

# ── Apollo Router ─────────────────────────────────────────────────────────────
GRAPHQL_ENDPOINT    = os.getenv("GRAPHQL_ENDPOINT", "http://localhost:4000/graphql")
