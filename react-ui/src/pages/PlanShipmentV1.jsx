/**
 * PlanShipment — V1 LangGraph ReAct Agent (Human-in-the-Loop)
 *
 * Architecture:
 *   LangGraph create_react_agent  +  Apollo MCP Server tools
 *   The AI model reasons step-by-step, calling MCP tools as needed.
 *   When it reaches a mutating tool (CreateShipment / BookDockSlot)
 *   it PAUSES and asks for human approval before executing.
 *
 * State machine:
 *   idle          → form
 *   planning      → loading  (agent reasoning + read-only tools)
 *   needs_confirm → ConfirmationDialog (agent wants to run a mutation)
 *   confirming    → loading  (resuming agent after approval)
 *   done          → result card (agent reasoning + tools called)
 *   error         → error card
 *
 * API:  POST /api/v1/plan  →  POST /api/v1/plan/confirm (repeat if multiple mutations)
 */

import { useState } from 'react';
import { useQuery }  from '@apollo/client';
import { GET_WAREHOUSES } from '../graphql/queries';
import { planShipmentV1, confirmPlanV1 } from '../api/gateway';
import ConfirmationDialog from '../components/ConfirmationDialog';
import LoadingSpinner from '../components/LoadingSpinner';

const PRIORITIES = ['STANDARD', 'EXPRESS', 'OVERNIGHT', 'SAME_DAY'];
const COUNTRIES  = ['US', 'CA', 'GB', 'DE', 'FR', 'AU', 'IN', 'SG', 'JP', 'MX'];
const EMPTY_ITEM = {
  sku: '', description: '', quantity: 1,
  weight: 0.1, volume: 0.1, value: 0,
  hazardous: false, temperatureControlled: false, fragile: false,
};

/* ─── Concept badge ──────────────────────────────────────────────────────── */
function ConceptBadge({ label, color }) {
  const colors = {
    blue:   'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
    purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300',
    amber:  'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    green:  'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${colors[color]}`}>{label}</span>
  );
}

/* ─── Architecture banner ────────────────────────────────────────────────── */
function ArchBanner() {
  return (
    <div className="rounded-xl border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20 px-5 py-4 mb-6 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-lg">🤖</span>
        <p className="font-semibold text-purple-900 dark:text-purple-200">V1 — LangGraph ReAct Agent</p>
        <ConceptBadge label="AI Reasoning" color="purple" />
        <ConceptBadge label="MCP Tools" color="blue" />
        <ConceptBadge label="HITL" color="amber" />
      </div>
      <p className="text-sm text-purple-800 dark:text-purple-300 leading-relaxed">
        A <strong>create_react_agent</strong> with an AI model (OpenRouter) reasons step-by-step.
        It calls read-only MCP tools automatically (warehouse capacity, route optimisation,
        carrier selection, quote). When it is about to mutate data
        (<code className="bg-purple-100 dark:bg-purple-900 px-1 rounded text-xs">CreateShipment</code> /
        <code className="bg-purple-100 dark:bg-purple-900 px-1 rounded text-xs">BookDockSlot</code>)
        it <strong>pauses</strong> and asks for human approval — you see exactly what the agent will do
        before it executes. Rejecting at any gate leaves the database untouched.
      </p>
      <div className="flex flex-wrap gap-2 text-xs text-purple-700 dark:text-purple-400">
        <span>📍 POST /api/v1/plan</span>
        <span>→</span>
        <span>📍 POST /api/v1/plan/confirm</span>
        <span className="text-purple-400">(repeated per mutation)</span>
      </div>
    </div>
  );
}

/* ─── Done card ──────────────────────────────────────────────────────────── */
function DoneCard({ result, onReset }) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 px-5 py-4 flex items-start gap-3">
        <span className="text-2xl mt-0.5">✅</span>
        <div>
          <p className="font-semibold text-emerald-900 dark:text-emerald-200">Agent completed planning</p>
          <p className="text-sm text-emerald-700 dark:text-emerald-400 mt-0.5">
            {result.toolsCalled?.length ?? 0} MCP tools called across {result.messageCount ?? '?'} agent messages.
          </p>
        </div>
      </div>

      {/* Tools called */}
      {result.toolsCalled?.length > 0 && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">MCP Tools Called</p>
          <div className="flex flex-wrap gap-2">
            {result.toolsCalled.map((t, i) => (
              <span key={i} className="font-mono text-xs bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 px-2 py-1 rounded-lg">
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Agent reasoning */}
      {result.agentReasoning && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Agent Reasoning</p>
          <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed">
            {result.agentReasoning}
          </p>
        </div>
      )}

      <button onClick={onReset} className="btn-secondary">Plan another shipment</button>
    </div>
  );
}

/* ─── Item row ───────────────────────────────────────────────────────────── */
function ItemRow({ item, idx, onChange, onRemove, canRemove }) {
  const set = (field, val) => onChange(idx, { ...item, [field]: val });
  const chk = (f) => (e) => set(f, e.target.checked);
  const inp = (f, num) => (e) => set(f, num ? Number(e.target.value) : e.target.value);

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Item {idx + 1}</p>
        {canRemove && (
          <button onClick={() => onRemove(idx)} className="text-xs text-red-500 hover:text-red-700 font-medium">Remove</button>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div><label className="form-label">SKU</label>
          <input className="form-input" value={item.sku} onChange={inp('sku')} placeholder="SKU-001" /></div>
        <div><label className="form-label">Description</label>
          <input className="form-input" value={item.description} onChange={inp('description')} placeholder="Product name" /></div>
        <div><label className="form-label">Qty</label>
          <input className="form-input" type="number" min={1} value={item.quantity} onChange={inp('quantity', true)} /></div>
        <div><label className="form-label">Weight (kg)</label>
          <input className="form-input" type="number" min={0.001} step={0.1} value={item.weight} onChange={inp('weight', true)} /></div>
        <div><label className="form-label">Volume (m³)</label>
          <input className="form-input" type="number" min={0.001} step={0.001} value={item.volume} onChange={inp('volume', true)} /></div>
        <div><label className="form-label">Value (USD)</label>
          <input className="form-input" type="number" min={0} step={0.01} value={item.value} onChange={inp('value', true)} /></div>
      </div>
      <div className="flex gap-4 text-sm">
        {['hazardous', 'temperatureControlled', 'fragile'].map(f => (
          <label key={f} className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" className="rounded" checked={item[f]} onChange={chk(f)} />
            <span className="text-gray-600 dark:text-gray-300 capitalize">{f.replace(/([A-Z])/g, ' $1')}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

/* ─── Main page ──────────────────────────────────────────────────────────── */
export default function PlanShipmentV1() {
  const [originWarehouseId,    setOriginWarehouseId]    = useState('');
  const [destinationAddress,   setDestinationAddress]   = useState({ street: '', city: '', state: '', country: 'US', postalCode: '' });
  const [items,                setItems]                = useState([{ ...EMPTY_ITEM }]);
  const [priority,             setPriority]             = useState('STANDARD');
  const [requiredDeliveryDate, setRequiredDeliveryDate] = useState('');
  const [specialInstructions,  setSpecialInstructions]  = useState('');

  const [stage,        setStage]        = useState('idle');  // idle | planning | needs_confirm | confirming | done | error
  const [threadId,     setThreadId]     = useState(null);
  const [confirmation, setConfirmation] = useState(null);
  const [result,       setResult]       = useState(null);
  const [error,        setError]        = useState('');

  const { data: whData } = useQuery(GET_WAREHOUSES);
  const warehouses = whData?.warehouses || [];

  const setAddr    = (f, v) => setDestinationAddress(a => ({ ...a, [f]: v }));
  const addItem    = ()     => setItems(is => [...is, { ...EMPTY_ITEM }]);
  const removeItem = (i)   => setItems(is => is.filter((_, j) => j !== i));
  const changeItem = (i, it) => setItems(is => is.map((x, j) => j === i ? it : x));

  /* Handle a response from /plan or /plan/confirm */
  function handleResponse(res) {
    if (res.status === 'needs_confirmation') {
      setThreadId(res.threadId);
      setConfirmation(res.confirmation);
      setStage('needs_confirm');
    } else {
      setResult(res);
      setStage('done');
    }
  }

  /* Phase 1: submit form → agent runs */
  async function handleSubmit(e) {
    e.preventDefault();
    setStage('planning');
    setError('');
    try {
      const res = await planShipmentV1({
        originWarehouseId,
        destinationAddress,
        items,
        priority,
        requiredDeliveryDate: requiredDeliveryDate || null,
        specialInstructions,
      });
      handleResponse(res);
    } catch (err) {
      setError(err.message);
      setStage('error');
    }
  }

  /* Resume: user approved/rejected a mutation */
  async function handleConfirm(approved) {
    setStage('confirming');
    setConfirmation(null);
    try {
      const res = await confirmPlanV1(threadId, approved);
      handleResponse(res);
    } catch (err) {
      setError(err.message);
      setStage('error');
    }
  }

  function handleReset() {
    setStage('idle');
    setThreadId(null);
    setConfirmation(null);
    setResult(null);
    setError('');
  }

  /* Loading */
  const LOADING_MSG = {
    planning:   'AI agent reasoning… calling MCP read tools (warehouse, route, carriers, quote)…',
    confirming: 'Agent resuming after your approval… executing mutation…',
  };
  if (LOADING_MSG[stage]) return (
    <div className="flex flex-col items-center justify-center min-h-64 gap-4 text-gray-500 dark:text-gray-400">
      <LoadingSpinner />
      <p className="text-sm text-center max-w-xs">{LOADING_MSG[stage]}</p>
    </div>
  );

  if (stage === 'done') return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-4">
      <ArchBanner />
      <DoneCard result={result} onReset={handleReset} />
    </div>
  );

  if (stage === 'error') return (
    <div className="max-w-xl mx-auto px-4 py-12">
      <div className="rounded-2xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-6 space-y-4">
        <div className="flex items-start gap-3">
          <span className="text-2xl mt-0.5" aria-hidden="true">🚫</span>
          <div>
            <p className="text-base font-semibold text-red-800 dark:text-red-200">Planning failed</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">No data was written to the database.</p>
          </div>
        </div>
        <div className="rounded-lg bg-white dark:bg-red-950/40 border border-red-100 dark:border-red-800 px-4 py-3">
          <p className="text-sm text-red-700 dark:text-red-300 leading-relaxed break-words">{error}</p>
        </div>
        {/"weight"|"volume"/i.test(error) && (
          <p className="text-xs text-red-600 dark:text-red-400">💡 <strong>Hint:</strong> Item weight and volume must be greater than 0. Check each item row.</p>
        )}
        {/route|destination|postal/i.test(error) && (
          <p className="text-xs text-red-600 dark:text-red-400">💡 <strong>Hint:</strong> No shipping route is configured for this destination. Ask an admin to add a route from the origin warehouse to this postal code.</p>
        )}
        {/carrier|quote/i.test(error) && (
          <p className="text-xs text-red-600 dark:text-red-400">💡 <strong>Hint:</strong> No carriers are available for this route or weight. Try adjusting shipment details or check carrier configurations.</p>
        )}
        {/warehouse/i.test(error) && (
          <p className="text-xs text-red-600 dark:text-red-400">💡 <strong>Hint:</strong> The selected warehouse could not be found. Please choose a valid origin warehouse.</p>
        )}
        {/service not found|containers/i.test(error) && (
          <p className="text-xs text-red-600 dark:text-red-400">💡 <strong>Hint:</strong> One or more backend services are not responding. Run <code className="bg-red-100 dark:bg-red-900 px-1 rounded">docker compose up</code> and try again.</p>
        )}
        <div className="flex gap-3 pt-1">
          <button onClick={handleReset} className="btn-primary">Try again</button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* HITL confirmation dialog — shown whenever agent wants to mutate */}
      {stage === 'needs_confirm' && confirmation && (
        <ConfirmationDialog
          confirmation={confirmation}
          onApprove={() => handleConfirm(true)}
          onReject={() => handleConfirm(false)}
          loading={false}
        />
      )}

      <div className="max-w-2xl mx-auto px-4 py-8">
        <ArchBanner />

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Plan Shipment</h1>
          <p className="text-sm text-gray-500 mt-1">
            V1 · LangGraph ReAct · Apollo MCP Server · AI-driven tool selection · Multi-gate HITL
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Origin */}
          <section className="card p-5 space-y-3">
            <h2 className="section-title">Origin Warehouse</h2>
            <div>
              <label className="form-label">Warehouse</label>
              <select className="form-input" value={originWarehouseId} onChange={e => setOriginWarehouseId(e.target.value)} required>
                <option value="">Select warehouse…</option>
                {warehouses.map(w => <option key={w.id} value={w.id}>{w.name} ({w.code})</option>)}
              </select>
            </div>
          </section>

          {/* Destination */}
          <section className="card p-5 space-y-3">
            <h2 className="section-title">Destination</h2>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="form-label">Street</label>
                <input className="form-input" value={destinationAddress.street} onChange={e => setAddr('street', e.target.value)} placeholder="123 Main St" />
              </div>
              <div>
                <label className="form-label">City *</label>
                <input className="form-input" required value={destinationAddress.city} onChange={e => setAddr('city', e.target.value)} placeholder="New York" />
              </div>
              <div>
                <label className="form-label">State</label>
                <input className="form-input" value={destinationAddress.state} onChange={e => setAddr('state', e.target.value)} placeholder="NY" />
              </div>
              <div>
                <label className="form-label">Country *</label>
                <select className="form-input" value={destinationAddress.country} onChange={e => setAddr('country', e.target.value)} required>
                  {COUNTRIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="form-label">Postal code *</label>
                <input className="form-input" required value={destinationAddress.postalCode} onChange={e => setAddr('postalCode', e.target.value)} placeholder="10001" />
              </div>
            </div>
          </section>

          {/* Items */}
          <section className="card p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="section-title">Items</h2>
              <button type="button" onClick={addItem} className="btn-secondary text-xs">+ Add item</button>
            </div>
            {items.map((it, i) => (
              <ItemRow key={i} item={it} idx={i} onChange={changeItem} onRemove={removeItem} canRemove={items.length > 1} />
            ))}
          </section>

          {/* Options */}
          <section className="card p-5 space-y-3">
            <h2 className="section-title">Options</h2>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="form-label">Priority</label>
                <select className="form-input" value={priority} onChange={e => setPriority(e.target.value)}>
                  {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className="form-label">Required by</label>
                <input className="form-input" type="date" value={requiredDeliveryDate} onChange={e => setRequiredDeliveryDate(e.target.value)} />
              </div>
              <div className="col-span-2">
                <label className="form-label">Special instructions</label>
                <textarea className="form-input" rows={2} value={specialInstructions} onChange={e => setSpecialInstructions(e.target.value)} placeholder="Fragile, keep upright…" />
              </div>
            </div>
          </section>

          <button type="submit" className="btn-primary w-full text-base py-3">
            🤖 Plan with AI Agent
          </button>
        </form>
      </div>
    </>
  );
}
