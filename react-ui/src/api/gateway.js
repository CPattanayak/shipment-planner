/**
 * REST helpers for the FastAPI gateway endpoints.
 * All URLs are relative (/api/...) so they go through the Nginx / Vite proxy.
 */

const V1     = '/api/v1';
const V2     = '/api/v2';
const V3     = '/api/v3';
const HYBRID = '/api/hybrid';

/**
 * Extract a clean, human-readable message from a failed response body.
 * Handles three layers of nesting that can arrive from FastAPI + GraphQL:
 *   1. {"errors":[{"message":"..."}]}          ← direct GraphQL body
 *   2. {"detail":"{\"errors\":[{\"message\":\"...\"}]}"}  ← FastAPI wrapping GraphQL JSON string
 *   3. {"detail":"plain message"}               ← FastAPI plain error
 */
function extractErrorMessage(status, statusText, text) {
  try {
    const outer = JSON.parse(text);

    // Layer 1: top-level GraphQL errors array
    if (Array.isArray(outer.errors) && outer.errors.length > 0) {
      const msg = outer.errors[0]?.message;
      if (msg) return msg;
    }

    // Layer 2a: FastAPI Pydantic validation — detail is an array of field errors
    if (Array.isArray(outer.detail) && outer.detail.length > 0) {
      return outer.detail.map(e => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : 'field';
        return `"${field}": ${e.msg}`;
      }).join('; ');
    }

    // Layer 2b: FastAPI {"detail": "..."} — detail may itself be a JSON string
    if (typeof outer.detail === 'string') {
      if (outer.detail === 'Not Found') return 'Service not found — check that all containers are running.';
      try {
        const inner = JSON.parse(outer.detail);
        if (Array.isArray(inner.errors) && inner.errors.length > 0) {
          const msg = inner.errors[0]?.message;
          if (msg) return msg;
        }
        if (inner.message) return inner.message;
      } catch {
        // detail is a plain string — use it directly
        return outer.detail;
      }
    }
  } catch {
    // Not JSON at all — fall back to raw text (trimmed)
  }
  // httpx exception: "Client error '4xx ...' for url 'http://internal-host/...'"
  // Strip the internal URL — it's meaningless to the end user.
  const httpxMatch = text.match(/Client error '(\d{3} [^']+)' for url/);
  if (httpxMatch) return `GraphQL service returned ${httpxMatch[1]} — check the backend logs.`;

  return text.trim() || `${status} ${statusText}`;
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(extractErrorMessage(res.status, res.statusText, text));
  }
  return res.json();
}

async function get(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/* ─── Planning V2 (Simplified — parallel reads, no LangGraph) ───────────── */

/**
 * Phase 1 — Fan-out parallel reads. Returns a ShipmentPlan.
 * Nothing is written to the DB until /execute is called.
 */
export const planShipmentV2 = (body)            => post(`${V2}/plan`,         body);

/**
 * Phase 2 — Execute the approved plan.
 * Runs CreateShipment + BookCarrier; returns needs_dock_confirmation.
 */
export const executePlanV2  = (planId)          => post(`${V2}/plan/execute`, { planId });

/**
 * Phase 3 — Approve or reject the dock-slot booking.
 * Returns { status: "done", dockBooked, shipment, booking, dockSlot? }
 */
export const confirmDockV2  = (planId, approved) => post(`${V2}/plan/dock`,   { planId, approved });

/* ─── Planning V3 (LangGraph StateGraph + Apollo supergraph fan-out) ────── */

/**
 * Phase 1 — Apollo supergraph fan-out (warehouse + route parallelised by Router).
 * Pauses at Gate 1. Returns { status: "needs_plan_confirmation", threadId, plan }
 * or { status: "error", error }.
 */
export const planShipmentV3  = (body)               => post(`${V3}/plan`,         body);

/**
 * Gate 1 resume — approve or reject the plan.
 * approved → CreateShipment + BookCarrier run; returns needs_dock_confirmation.
 * rejected → nothing written; returns rejected_at_plan.
 */
export const confirmPlanV3   = (threadId, approved) => post(`${V3}/plan/confirm`, { threadId, approved });

/**
 * Gate 2 resume — approve or skip dock-slot booking.
 * Returns { status: "done", dockBooked, shipment, booking, dockSlot? }
 */
export const confirmDockV3   = (threadId, approved) => post(`${V3}/dock/confirm`, { threadId, approved });

/* ─── Planning Hybrid (MCP tool nodes + LangGraph StateGraph) ───────────── */

/**
 * Phase 1 — two MCP nodes.
 *   mcp_node_1: asyncio.gather(get_warehouse_capacity, optimize_route)
 *               then get_available_carriers (needs origin postal)
 *   mcp_node_2: get_carrier_quote  (tool-chains from best carrier)
 * Pauses at Gate 1. Returns { status: "needs_plan_confirmation", threadId, plan }
 */
export const planShipmentHybrid  = (body)               => post(`${HYBRID}/plan`,         body);

/**
 * Gate 1 resume — approve or reject the plan.
 * approved → CreateShipment + BookCarrier (direct GraphQL); returns needs_dock_confirmation.
 * rejected → nothing written; returns rejected_at_plan.
 */
export const confirmPlanHybrid   = (threadId, approved) => post(`${HYBRID}/plan/confirm`, { threadId, approved });

/**
 * Gate 2 resume — approve or skip dock-slot booking.
 * Returns { status: "done", dockBooked, shipment, booking, dockSlot? }
 */
export const confirmDockHybrid   = (threadId, approved) => post(`${HYBRID}/dock/confirm`, { threadId, approved });

/* ─── Planning V4 (LLM MCP reads + direct GraphQL mutations) ────────────── */

const V4 = '/api/v4';

/**
 * Phase 1 — LLM agentic loop over 4 MCP read tools.
 * Returns { status: "needs_plan_confirmation", threadId, plan }
 */
export const planShipmentV4  = (body)               => post(`${V4}/plan`,         body);
export const confirmPlanV4   = (threadId, approved) => post(`${V4}/plan/confirm`, { threadId, approved });
export const confirmDockV4   = (threadId, approved) => post(`${V4}/dock/confirm`, { threadId, approved });

/* ─── AI Planning V1 (LangGraph HITL — kept for reference) ──────────────── */

export const planShipmentV1  = (body)               => post(`${V1}/plan`,         body);
export const confirmPlanV1   = (threadId, approved) => post(`${V1}/plan/confirm`, { threadId, approved });

/* ─── Free-form agent chat ───────────────────────────────────────────────── */

export const askAgent = (question) => post(`${V1}/ask`, { question });

/* ─── MCP tools catalogue ────────────────────────────────────────────────── */

export const listTools = () => get(`${V1}/tools`);

/* ─── Streaming (SSE) ────────────────────────────────────────────────────── */

export const streamAgent = (question) =>
  new EventSource(`${V1}/stream?q=${encodeURIComponent(question)}`);
