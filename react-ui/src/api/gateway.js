/**
 * REST helpers for the FastAPI gateway endpoints.
 * All URLs are relative (/api/...) so they go through the Nginx / Vite proxy.
 */

const V1 = '/api/v1';
const V2 = '/api/v2';
const V3 = '/api/v3';

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
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
