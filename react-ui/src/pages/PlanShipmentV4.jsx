/**
 * PlanShipmentV4 — LLM agentic loop over MCP read tools + direct GraphQL mutations
 *
 * Architecture
 * ────────────
 *   llm_plan_node  LLM (ChatOpenAI) drives an agentic tool-use loop:
 *                    tool_call → GetWarehouseCapacity(id)
 *                    tool_call → OptimizeRoute(...)
 *                    tool_call → GetAvailableCarriers(...)
 *                    tool_call → GetCarrierQuote(...)
 *                  LLM decides order & args; prompt constrains to these 4 tools.
 *                  Structured plan extracted from ToolMessage results in state.
 *   [Gate 1]       Human reviews full plan — Approve / Reject        interrupt()
 *   create_ship    CreateShipment + BookCarrier                     ← direct GraphQL
 *   [Gate 2]       Human reviews dock slot — Book / Skip             interrupt()
 *   book_dock      BookDockSlot                                     ← direct GraphQL
 *
 * vs Hybrid
 * ─────────
 *   Hybrid  Python code names each MCP tool explicitly; asyncio.gather() parallelism
 *           is visible in code; tool-chain passes state node → node.
 *   V4      LLM orchestrates the same 4 tools via its native tool-use loop;
 *           any MCP-exposing service (GitHub, Stripe, Slack, …) works without
 *           code changes — just add tools to the client and update the prompt.
 *
 * Backend
 * ───────
 *   POST /api/v4/plan          Phase 1 (LLM tool loop)
 *   POST /api/v4/plan/confirm  Gate 1 resume
 *   POST /api/v4/dock/confirm  Gate 2 resume
 */

import { useState } from 'react';
import { useQuery }  from '@apollo/client';
import { GET_WAREHOUSES } from '../graphql/queries';
import { planShipmentV4, confirmPlanV4, confirmDockV4 } from '../api/gateway';
import LoadingSpinner from '../components/LoadingSpinner';

const PRIORITIES = ['STANDARD', 'EXPRESS', 'OVERNIGHT', 'SAME_DAY'];
const COUNTRIES  = ['US', 'CA', 'GB', 'DE', 'FR', 'AU', 'IN', 'SG', 'JP', 'MX'];
const EMPTY_ITEM = {
  sku: '', description: '', quantity: 1,
  weight: 0, volume: 0, value: 0,
  hazardous: false, temperatureControlled: false, fragile: false,
};

/* ─── Helpers ────────────────────────────────────────────────────────────── */
const fmt  = (n, d = 2) => Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtK = (n)        => `${fmt(n, 0)} kg`;
const fmtM = (n)        => `${Number(n ?? 0).toFixed(3)} m³`;
const fmtC = (n)        => `USD ${fmt(n)}`;

/* ─── Architecture banner ────────────────────────────────────────────────── */
function ArchBanner() {
  return (
    <div className="rounded-xl border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-900/20 p-4 mb-6 text-sm space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">🤖</span>
        <p className="font-semibold text-sky-900 dark:text-sky-200">V4 Agent — LLM-driven MCP reads + direct GraphQL writes</p>
      </div>

      {/* Flow diagram */}
      <div className="font-mono text-xs text-sky-800 dark:text-sky-300 space-y-0.5 leading-5">
        <div>
          <span className="bg-sky-200 dark:bg-sky-800 px-1.5 py-0.5 rounded font-semibold">llm_plan_node</span>
          {' '}<span className="text-gray-400">LLM tool-use loop:</span>
        </div>
        <div className="pl-4">
          tool_call → <span className="text-amber-700 dark:text-amber-400">GetWarehouseCapacity</span>
          {' '}<span className="text-gray-400">→ result stored in messages</span>
        </div>
        <div className="pl-4">
          tool_call → <span className="text-amber-700 dark:text-amber-400">OptimizeRoute</span>
          {' '}<span className="text-gray-400">→ delivery date, distance</span>
        </div>
        <div className="pl-4">
          tool_call → <span className="text-amber-700 dark:text-amber-400">GetAvailableCarriers</span>
          {' '}<span className="text-gray-400">→ picks best by onTimeDeliveryRate</span>
        </div>
        <div className="pl-4">
          tool_call → <span className="text-amber-700 dark:text-amber-400">GetCarrierQuote</span>
          {' '}<span className="text-gray-400">→ final cost breakdown</span>
        </div>
        <div className="pl-4 text-gray-400">↓ plan extracted from ToolMessage history → interrupt()</div>
        <div><span className="bg-blue-200 dark:bg-blue-800 px-1.5 py-0.5 rounded font-semibold">Gate 1</span> Human reviews plan</div>
        <div className="pl-4 text-gray-400">↓ Command(resume=True)</div>
        <div><span className="bg-violet-200 dark:bg-violet-800 px-1.5 py-0.5 rounded font-semibold">create_shipment</span> CreateShipment + BookCarrier <span className="text-gray-400">← direct GraphQL (MCP is read-only)</span></div>
        <div className="pl-4 text-gray-400">↓ interrupt()</div>
        <div><span className="bg-amber-200 dark:bg-amber-800 px-1.5 py-0.5 rounded font-semibold">Gate 2</span> Human reviews dock slot</div>
        <div className="pl-4 text-gray-400">↓ Command(resume=True)</div>
        <div><span className="bg-violet-200 dark:bg-violet-800 px-1.5 py-0.5 rounded font-semibold">book_dock</span> BookDockSlot <span className="text-gray-400">← direct GraphQL</span></div>
      </div>

      {/* Key concepts */}
      <div className="flex flex-wrap gap-2 pt-1">
        {[
          ['LLM tool-use loop',  'LLM calls tools natively — no explicit Python orchestration'],
          ['Any MCP server',     'Add GitHub/Stripe/Slack tools without code changes'],
          ['Zero-mutation LLM',  'Writes bypass LLM — direct GraphQL, cheaper + reliable'],
          ['interrupt()',        'Typed HITL pause — resumes with Command(resume=bool)'],
          ['ToolMessage parse',  'Plan data extracted from LangChain message history'],
        ].map(([label, tip]) => (
          <span key={label} title={tip}
            className="px-2 py-0.5 rounded-full bg-sky-100 dark:bg-sky-800/60 text-sky-800 dark:text-sky-300 text-xs font-medium cursor-help border border-sky-200 dark:border-sky-700">
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ─── Stat tile ──────────────────────────────────────────────────────────── */
function Stat({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400 mb-0.5">{label}</p>
      <p className="text-lg font-semibold text-gray-900 dark:text-gray-100 tabular-nums">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

/* ─── Capacity bar ───────────────────────────────────────────────────────── */
function CapacityBar({ cap }) {
  const pct   = Math.min(Math.round(cap?.utilizationPct ?? 0), 100);
  const color = pct > 85 ? 'bg-red-500' : pct > 65 ? 'bg-amber-400' : 'bg-emerald-500';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-gray-500">
        <span>Warehouse capacity</span><span>{pct}% used</span>
      </div>
      <div className="h-2 w-full rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-gray-400">
        {fmtM(cap?.availableM3)} available of {fmtM(cap?.totalM3)} total
      </p>
    </div>
  );
}

/* ─── Info table ─────────────────────────────────────────────────────────── */
function Row({ label, value }) {
  return (
    <tr className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
      <td className="px-3 py-2 text-xs font-medium text-gray-500 whitespace-nowrap w-2/5">{label}</td>
      <td className="px-3 py-2 text-sm text-gray-800 dark:text-gray-200 break-all">{value ?? '—'}</td>
    </tr>
  );
}
function InfoTable({ rows }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-sm">
      <table className="w-full"><tbody className="divide-y divide-gray-100 dark:divide-gray-700">
        {rows.map(([l, v]) => <Row key={l} label={l} value={v} />)}
      </tbody></table>
    </div>
  );
}

/* ─── LLM tool step indicator ────────────────────────────────────────────── */
function ToolBadge({ label, done }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
      done
        ? 'bg-sky-100 dark:bg-sky-800/60 text-sky-800 dark:text-sky-300'
        : 'bg-gray-100 dark:bg-gray-700 text-gray-400'
    }`}>
      {done ? '✓' : '○'} {label}
    </span>
  );
}

/* ─── Gate 1: Plan review dialog ─────────────────────────────────────────── */
function PlanReviewDialog({ plan, onApprove, onReject, loading }) {
  const wh   = plan.warehouse        || {};
  const cap  = plan.capacity         || {};
  const rt   = plan.route            || {};
  const rec  = rt.recommendedRoute   || {};
  const car  = plan.selectedCarrier  || {};
  const perf = car.performance       || {};
  const cap2 = car.capabilities      || {};
  const q    = plan.quote            || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="bg-sky-50 dark:bg-sky-900/30 border-b border-sky-200 dark:border-sky-800 px-6 py-4 flex items-start gap-3 shrink-0">
          <span className="text-2xl">🤖</span>
          <div>
            <p className="font-semibold text-sky-900 dark:text-sky-200">Gate 1 — Review Shipment Plan</p>
            <p className="text-sm text-sky-700 dark:text-sky-400 mt-0.5">
              LLM called 4 MCP read tools and extracted a structured plan.
              Approve to create the shipment and book the carrier via direct GraphQL.
            </p>
            <div className="flex flex-wrap gap-2 mt-2">
              <ToolBadge label="GetWarehouseCapacity" done />
              <ToolBadge label="OptimizeRoute" done />
              <ToolBadge label="GetAvailableCarriers" done />
              <ToolBadge label="GetCarrierQuote" done />
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-5">

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Est. cost"  value={fmtC(q.totalCost)} />
            <Stat label="Delivery"   value={plan.deliveryDate || '—'} />
            <Stat label="Transit"    value={`${q.transitDays ?? '?'} days`} />
            <Stat label="Distance"   value={`${fmt(rec.totalDistanceKm, 0)} km`} />
          </div>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              Origin Warehouse
              <span className="ml-2 font-mono text-sky-500 normal-case">← GetWarehouseCapacity (MCP)</span>
            </p>
            <CapacityBar cap={cap} />
            <div className="mt-2">
              <InfoTable rows={[
                ['Name',    wh.name],
                ['Code',    wh.code],
                ['Address', [wh.address?.street, wh.address?.city, wh.address?.state, wh.address?.country].filter(Boolean).join(', ')],
              ]} />
            </div>
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              Recommended Route
              <span className="ml-2 font-mono text-sky-500 normal-case">← OptimizeRoute (MCP)</span>
            </p>
            <InfoTable rows={[
              ['Route name',    rec.name],
              ['Mode',          rec.transportMode],
              ['Distance',      `${fmt(rec.totalDistanceKm, 0)} km`],
              ['Duration',      `${fmt(rec.estimatedDurationHours, 0)} h`],
              ['Est. delivery', plan.deliveryDate],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              Selected Carrier
              <span className="ml-2 font-mono text-sky-500 normal-case">← GetAvailableCarriers (MCP)</span>
            </p>
            <InfoTable rows={[
              ['Carrier',         car.name],
              ['Code',            car.code],
              ['On-time rate',    `${fmt((perf.onTimeDeliveryRate ?? 0) * 100, 1)}%`],
              ['Avg delay',       `${perf.averageDelayHours ?? '?'} h`],
              ['Max weight',      fmtK(cap2.maxWeightKg)],
              ['Hazardous',       cap2.hazardousAllowed      ? '✅ Yes' : '❌ No'],
              ['Temp-controlled', cap2.temperatureControlled ? '✅ Yes' : '❌ No'],
              ['Tracking',        cap2.trackingAvailable     ? '✅ Yes' : '❌ No'],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              Quote Breakdown
              <span className="ml-2 font-mono text-sky-500 normal-case">← GetCarrierQuote (MCP)</span>
            </p>
            <InfoTable rows={[
              ['Base rate',        fmtC(q.baseRate)],
              ['Fuel surcharge',   fmtC(q.fuelSurcharge)],
              ['Handling fee',     fmtC(q.handlingFee)],
              ['Total cost',       fmtC(q.totalCost)],
              ['Service level',    q.serviceLevel],
              ['Quote valid until', q.validUntil ? new Date(q.validUntil).toLocaleDateString() : '—'],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Shipment Details</p>
            <InfoTable rows={[
              ['Total weight', fmtK(plan.weightKg)],
              ['Total volume', fmtM(plan.volumeM3)],
            ]} />
          </section>
        </div>

        {/* Actions */}
        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex gap-3 justify-end bg-gray-50 dark:bg-gray-800 shrink-0">
          <button onClick={onReject} disabled={loading} className="btn-danger">
            {loading ? '…' : '❌ Reject Plan'}
          </button>
          <button onClick={onApprove} disabled={loading} className="btn-success">
            {loading ? '…' : '✅ Approve — Create Shipment'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Gate 2: Dock slot dialog ───────────────────────────────────────────── */
function DockDialog({ data, onApprove, onReject, loading }) {
  const ship = data.shipment  || {};
  const book = data.booking   || {};
  const dock = data.dockSlot  || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">

        <div className="bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-800 px-6 py-4 flex items-start gap-3">
          <span className="text-2xl">🚚</span>
          <div>
            <p className="font-semibold text-amber-900 dark:text-amber-200">Gate 2 — Confirm Dock Slot</p>
            <p className="text-sm text-amber-700 dark:text-amber-400 mt-0.5">
              Shipment created and carrier booked. Approve to reserve a dock slot.
            </p>
          </div>
        </div>

        <div className="px-6 py-5 space-y-4">
          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Shipment Created</p>
            <InfoTable rows={[
              ['Shipment ID', ship.id],
              ['Tracking',    ship.trackingNumber],
              ['Status',      ship.status],
              ['Priority',    ship.priority],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Carrier Booked</p>
            <InfoTable rows={[
              ['Booking ID',    book.bookingId],
              ['Pickup window', book.pickupWindow],
              ['Est. delivery', book.estimatedDelivery],
              ['Tracking #',    book.trackingNumber],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Proposed Dock Slot</p>
            <InfoTable rows={[
              ['Date',  dock.date],
              ['Time',  `${dock.startTime} – ${dock.endTime}`],
              ['Dock #', dock.dockNumber],
              ['Type',  dock.type],
            ]} />
          </section>
        </div>

        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex gap-3 justify-end bg-gray-50 dark:bg-gray-800">
          <button onClick={onReject} disabled={loading} className="btn-secondary">
            {loading ? '…' : 'Skip dock booking'}
          </button>
          <button onClick={onApprove} disabled={loading} className="btn-success">
            {loading ? '…' : '✅ Book Dock Slot'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Done card ──────────────────────────────────────────────────────────── */
function DoneCard({ result, onReset }) {
  const ship = result.shipment  || {};
  const book = result.booking   || {};
  const dock = result.dockSlot  || {};

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 px-5 py-4 flex items-center gap-3">
        <span className="text-3xl">✅</span>
        <div>
          <p className="font-semibold text-emerald-900 dark:text-emerald-200">Shipment Complete</p>
          <p className="text-sm text-emerald-700 dark:text-emerald-400">
            {result.dockBooked
              ? 'Shipment created, carrier booked, and dock slot reserved.'
              : 'Shipment created and carrier booked. Dock slot skipped.'}
          </p>
        </div>
      </div>

      <div className={`grid gap-4 ${result.dockBooked ? 'grid-cols-1 sm:grid-cols-3' : 'grid-cols-1 sm:grid-cols-2'}`}>
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Shipment</p>
          <p className="font-mono text-sm font-medium text-gray-900 dark:text-gray-100">{ship.id}</p>
          <InfoTable rows={[
            ['Tracking',  ship.trackingNumber],
            ['Status',    ship.status],
            ['Priority',  ship.priority],
          ]} />
        </div>

        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Carrier Booking</p>
          <p className="font-mono text-sm font-medium text-gray-900 dark:text-gray-100">{book.bookingId}</p>
          <InfoTable rows={[
            ['Pickup',   book.pickupWindow],
            ['Delivery', book.estimatedDelivery],
            ['Tracking', book.trackingNumber],
          ]} />
        </div>

        {result.dockBooked && (
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Dock Slot</p>
            <p className="font-mono text-sm font-medium text-gray-900 dark:text-gray-100">{dock.id}</p>
            <InfoTable rows={[
              ['Date',   dock.date],
              ['Time',   `${dock.startTime} – ${dock.endTime}`],
              ['Dock #', dock.dockNumber],
              ['Type',   dock.type],
            ]} />
          </div>
        )}
      </div>

      <button onClick={onReset} className="btn-secondary">Plan another shipment</button>
    </div>
  );
}

/* ─── Item row ───────────────────────────────────────────────────────────── */
function ItemRow({ item, idx, onChange, onRemove, canRemove }) {
  const set = (field, val) => onChange(idx, { ...item, [field]: val });
  const chk = (field)      => (e) => set(field, e.target.checked);
  const inp = (field, num) => (e) => set(field, num ? Number(e.target.value) : e.target.value);

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Item {idx + 1}</p>
        {canRemove && (
          <button onClick={() => onRemove(idx)} className="text-xs text-red-500 hover:text-red-700 font-medium">
            Remove
          </button>
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
          <input className="form-input" type="number" min={0} step={0.1} value={item.weight} onChange={inp('weight', true)} /></div>
        <div><label className="form-label">Volume (m³)</label>
          <input className="form-input" type="number" min={0} step={0.001} value={item.volume} onChange={inp('volume', true)} /></div>
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
export default function PlanShipmentV4() {
  /* form */
  const [originWarehouseId,    setOriginWarehouseId]    = useState('');
  const [destinationAddress,   setDestinationAddress]   = useState({ street: '', city: '', state: '', country: 'US', postalCode: '' });
  const [items,                setItems]                = useState([{ ...EMPTY_ITEM }]);
  const [priority,             setPriority]             = useState('STANDARD');
  const [requiredDeliveryDate, setRequiredDeliveryDate] = useState('');
  const [specialInstructions,  setSpecialInstructions]  = useState('');

  /* flow */
  const [stage,    setStage]    = useState('idle');
  const [threadId, setThreadId] = useState(null);
  const [planData, setPlanData] = useState(null);
  const [dockData, setDockData] = useState(null);
  const [result,   setResult]   = useState(null);
  const [error,    setError]    = useState('');

  const { data: whData } = useQuery(GET_WAREHOUSES);
  const warehouses = whData?.warehouses || [];

  const setAddr    = (f, v) => setDestinationAddress(a => ({ ...a, [f]: v }));
  const addItem    = ()     => setItems(is => [...is, { ...EMPTY_ITEM }]);
  const removeItem = (i)   => setItems(is => is.filter((_, j) => j !== i));
  const changeItem = (i, it) => setItems(is => is.map((x, j) => j === i ? it : x));

  const body = () => ({
    originWarehouseId,
    destinationAddress,
    items,
    priority,
    requiredDeliveryDate: requiredDeliveryDate || null,
    specialInstructions,
  });

  /* Phase 1 — LLM tool-use loop */
  async function handleSubmit(e) {
    e.preventDefault();
    setStage('planning');
    setError('');
    try {
      const res = await planShipmentV4(body());
      if (res.status === 'error') {
        setError(res.error || 'LLM MCP tool loop failed.');
        setStage('error');
        return;
      }
      setThreadId(res.threadId);
      setPlanData(res.plan);
      setStage('plan_review');
    } catch (err) {
      setError(err.message);
      setStage('error');
    }
  }

  /* Gate 1 approve */
  async function handleApprovePlan() {
    setStage('creating');
    try {
      const res = await confirmPlanV4(threadId, true);
      if (res.status === 'error') {
        setError(res.error || 'Shipment creation failed.');
        setStage('error');
        return;
      }
      if (res.status === 'needs_dock_confirmation') {
        setDockData(res.dockData);
        setStage('dock_review');
      } else {
        setResult(res);
        setStage('done');
      }
    } catch (err) {
      setError(err.message);
      setStage('error');
    }
  }

  /* Gate 1 reject */
  async function handleRejectPlan() {
    setStage('creating');
    try { await confirmPlanV4(threadId, false); } catch (_) { /* ignore */ }
    setStage('rejected');
  }

  /* Gate 2 */
  async function handleDock(approved) {
    setStage('confirming');
    try {
      const res = await confirmDockV4(threadId, approved);
      setResult(res);
      setStage('done');
    } catch (err) {
      setError(err.message);
      setStage('error');
    }
  }

  function handleReset() {
    setStage('idle');
    setThreadId(null);
    setPlanData(null);
    setDockData(null);
    setResult(null);
    setError('');
  }

  /* Loading states */
  const LOADING_MSG = {
    planning:   'LLM calling MCP tools: GetWarehouseCapacity → OptimizeRoute → GetAvailableCarriers → GetCarrierQuote…',
    creating:   'LangGraph: creating shipment and booking carrier (direct GraphQL)…',
    confirming: 'LangGraph: finalising dock slot booking (direct GraphQL)…',
  };
  if (LOADING_MSG[stage]) {
    return (
      <div className="flex flex-col items-center justify-center min-h-64 gap-4 text-gray-500 dark:text-gray-400">
        <LoadingSpinner />
        <p className="text-sm text-center max-w-sm">{LOADING_MSG[stage]}</p>
        {stage === 'planning' && (
          <div className="flex flex-wrap justify-center gap-2">
            <ToolBadge label="GetWarehouseCapacity" done={false} />
            <ToolBadge label="OptimizeRoute" done={false} />
            <ToolBadge label="GetAvailableCarriers" done={false} />
            <ToolBadge label="GetCarrierQuote" done={false} />
          </div>
        )}
      </div>
    );
  }

  if (stage === 'done') return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <DoneCard result={result} onReset={handleReset} />
    </div>
  );

  if (stage === 'rejected') return (
    <div className="max-w-lg mx-auto px-4 py-12 text-center space-y-4">
      <span className="text-5xl">❌</span>
      <p className="text-xl font-semibold text-gray-800 dark:text-gray-200">Plan rejected</p>
      <p className="text-sm text-gray-500">No data was written to the database.</p>
      <button onClick={handleReset} className="btn-secondary">Start over</button>
    </div>
  );

  if (stage === 'error') return (
    <div className="max-w-lg mx-auto px-4 py-12 text-center space-y-4">
      <span className="text-5xl">⚠️</span>
      <p className="text-xl font-semibold text-gray-800 dark:text-gray-200">Error</p>
      <p className="text-sm text-red-600 dark:text-red-400 break-words">{error}</p>
      <button onClick={handleReset} className="btn-secondary">Try again</button>
    </div>
  );

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Gate overlays */}
      {stage === 'plan_review' && planData && (
        <PlanReviewDialog
          plan={planData}
          onApprove={handleApprovePlan}
          onReject={handleRejectPlan}
          loading={false}
        />
      )}
      {stage === 'dock_review' && dockData && (
        <DockDialog
          data={dockData}
          onApprove={() => handleDock(true)}
          onReject={() => handleDock(false)}
          loading={false}
        />
      )}

      <ArchBanner />

      {/* ── Form ── */}
      <form onSubmit={handleSubmit} className="space-y-6">

        {/* Origin warehouse */}
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
          <p className="font-semibold text-gray-800 dark:text-gray-200">Origin Warehouse</p>
          <div>
            <label className="form-label">Warehouse</label>
            <select className="form-input" value={originWarehouseId} onChange={e => setOriginWarehouseId(e.target.value)} required>
              <option value="">Select warehouse…</option>
              {warehouses.map(w => (
                <option key={w.id} value={w.id}>{w.name} ({w.code})</option>
              ))}
            </select>
          </div>
        </section>

        {/* Destination */}
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
          <p className="font-semibold text-gray-800 dark:text-gray-200">Destination</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="form-label">Street</label>
              <input className="form-input" value={destinationAddress.street} onChange={e => setAddr('street', e.target.value)} placeholder="123 Main St" />
            </div>
            <div><label className="form-label">City</label>
              <input className="form-input" value={destinationAddress.city} onChange={e => setAddr('city', e.target.value)} placeholder="City" required /></div>
            <div><label className="form-label">State / Province</label>
              <input className="form-input" value={destinationAddress.state} onChange={e => setAddr('state', e.target.value)} placeholder="CA" /></div>
            <div><label className="form-label">Postal Code</label>
              <input className="form-input" value={destinationAddress.postalCode} onChange={e => setAddr('postalCode', e.target.value)} placeholder="90210" required /></div>
            <div><label className="form-label">Country</label>
              <select className="form-input" value={destinationAddress.country} onChange={e => setAddr('country', e.target.value)}>
                {COUNTRIES.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>
        </section>

        {/* Items */}
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-gray-800 dark:text-gray-200">Items</p>
            <button type="button" onClick={addItem} className="btn-secondary text-xs">+ Add item</button>
          </div>
          {items.map((item, idx) => (
            <ItemRow key={idx} item={item} idx={idx}
              onChange={changeItem} onRemove={removeItem} canRemove={items.length > 1} />
          ))}
        </section>

        {/* Options */}
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
          <p className="font-semibold text-gray-800 dark:text-gray-200">Options</p>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="form-label">Priority</label>
              <select className="form-input" value={priority} onChange={e => setPriority(e.target.value)}>
                {PRIORITIES.map(p => <option key={p}>{p}</option>)}
              </select>
            </div>
            <div><label className="form-label">Required delivery date</label>
              <input className="form-input" type="date" value={requiredDeliveryDate} onChange={e => setRequiredDeliveryDate(e.target.value)} />
            </div>
            <div className="col-span-2">
              <label className="form-label">Special instructions</label>
              <textarea className="form-input" rows={2} value={specialInstructions} onChange={e => setSpecialInstructions(e.target.value)} placeholder="Handle with care…" />
            </div>
          </div>
        </section>

        <button type="submit" disabled={!originWarehouseId} className="btn-primary w-full">
          🤖 Run LLM + MCP planning
        </button>
      </form>
    </div>
  );
}
