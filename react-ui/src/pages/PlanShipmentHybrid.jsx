/**
 * PlanShipmentHybrid — Hybrid LangGraph StateGraph with explicit MCP tool nodes
 *
 * Architecture
 * ────────────
 *   mcp_node_1   asyncio.gather(get_warehouse_capacity, optimize_route)   ← parallel in Python
 *                then get_available_carriers                                ← needs postal from ↑
 *   mcp_node_2   get_carrier_quote                                         ← tool-chains best carrier
 *   [Gate 1]     Human reviews full plan — Approve / Reject
 *   create_ship  CreateShipment + BookCarrier                              ← direct GraphQL
 *   [Gate 2]     Human reviews dock slot — Book / Skip
 *   book_dock    BookDockSlot                                              ← direct GraphQL
 *
 * vs V3
 * ─────
 *   V3      sends ONE combined GraphQL document; Apollo Router's query planner
 *           fans out warehouse + route subgraphs on the server side invisibly.
 *   Hybrid  names each MCP tool explicitly; asyncio.gather() makes parallelism
 *           visible in Python code; result is typed state flowing node → node.
 *
 * State machine
 * ─────────────
 *   idle | planning | plan_review | creating | dock_review | confirming | done | rejected | error
 *
 * Backend
 * ───────
 *   POST /api/hybrid/plan          Phase 1
 *   POST /api/hybrid/plan/confirm  Gate 1 resume
 *   POST /api/hybrid/dock/confirm  Gate 2 resume
 */

import { useState } from 'react';
import { useQuery }  from '@apollo/client';
import { GET_WAREHOUSES } from '../graphql/queries';
import { planShipmentHybrid, confirmPlanHybrid, confirmDockHybrid } from '../api/gateway';
import LoadingSpinner from '../components/LoadingSpinner';

const PRIORITIES = ['STANDARD', 'EXPRESS', 'OVERNIGHT', 'SAME_DAY'];
const COUNTRIES  = ['US', 'CA', 'GB', 'DE', 'FR', 'AU', 'IN', 'SG', 'JP', 'MX'];
const EMPTY_ITEM = {
  sku: '', description: '', quantity: 1,
  weight: 0.1, volume: 0.1, value: 0,
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
    <div className="rounded-xl border border-teal-200 dark:border-teal-800 bg-teal-50 dark:bg-teal-900/20 p-4 mb-6 text-sm space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">🔀</span>
        <p className="font-semibold text-teal-900 dark:text-teal-200">Hybrid Agent — Explicit MCP Tool Nodes</p>
      </div>

      {/* Flow diagram */}
      <div className="font-mono text-xs text-teal-800 dark:text-teal-300 space-y-0.5 leading-5">
        <div>
          <span className="bg-teal-200 dark:bg-teal-800 px-1.5 py-0.5 rounded font-semibold">mcp_node_1</span>
          {' '}asyncio.gather(<span className="text-amber-700 dark:text-amber-400">get_warehouse_capacity</span>,{' '}
          <span className="text-amber-700 dark:text-amber-400">optimize_route</span>){' '}
          <span className="text-gray-400">← parallel in Python</span>
        </div>
        <div className="pl-4 text-gray-400">↓ origin postal resolved</div>
        <div className="pl-4">
          <span className="text-amber-700 dark:text-amber-400">get_available_carriers</span>
          {' '}<span className="text-gray-400">← sequential (needs postal)</span>
        </div>
        <div className="pl-4 text-gray-400">↓ best carrier selected</div>
        <div>
          <span className="bg-teal-200 dark:bg-teal-800 px-1.5 py-0.5 rounded font-semibold">mcp_node_2</span>
          {' '}<span className="text-amber-700 dark:text-amber-400">get_carrier_quote</span>
          {' '}<span className="text-gray-400">← tool-chains from mcp_node_1</span>
        </div>
        <div className="pl-4 text-gray-400">↓ interrupt()</div>
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
          ['asyncio.gather', 'Runs independent MCP calls in parallel within Python'],
          ['MCP tool nodes',  'Each node calls named tools — no hidden query planning'],
          ['Tool chain',      'mcp_node_2 consumes best_carrier from mcp_node_1 state'],
          ['interrupt()',     'Typed HLT pause — resumes with Command(resume=bool)'],
          ['Direct GraphQL',  'Mutations bypass MCP (Apollo MCP Server is read-only)'],
        ].map(([label, tip]) => (
          <span key={label} title={tip}
            className="px-2 py-0.5 rounded-full bg-teal-100 dark:bg-teal-800/60 text-teal-800 dark:text-teal-300 text-xs font-medium cursor-help border border-teal-200 dark:border-teal-700">
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

/* ─── MCP node step indicator ────────────────────────────────────────────── */
function NodeBadge({ label, done }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
      done
        ? 'bg-teal-100 dark:bg-teal-800/60 text-teal-800 dark:text-teal-300'
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
        <div className="bg-teal-50 dark:bg-teal-900/30 border-b border-teal-200 dark:border-teal-800 px-6 py-4 flex items-start gap-3 shrink-0">
          <span className="text-2xl">🔀</span>
          <div>
            <p className="font-semibold text-teal-900 dark:text-teal-200">Gate 1 — Review Shipment Plan</p>
            <p className="text-sm text-teal-700 dark:text-teal-400 mt-0.5">
              Two MCP nodes resolved warehouse, route, carriers and quote.
              Approve to create the shipment and book the carrier.
            </p>
            <div className="flex gap-2 mt-2">
              <NodeBadge label="mcp_node_1" done />
              <NodeBadge label="mcp_node_2" done />
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
              <span className="ml-2 font-mono text-teal-500 normal-case">← get_warehouse_capacity (MCP)</span>
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
              <span className="ml-2 font-mono text-teal-500 normal-case">← optimize_route (MCP)</span>
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
              <span className="ml-2 font-mono text-teal-500 normal-case">← get_available_carriers (MCP)</span>
            </p>
            <InfoTable rows={[
              ['Carrier',       car.name],
              ['Code',          car.code],
              ['On-time rate',  `${fmt((perf.onTimeDeliveryRate ?? 0) * 100, 1)}%`],
              ['Avg delay',     `${perf.averageDelayHours ?? '?'} h`],
              ['Max weight',    fmtK(cap2.maxWeightKg)],
              ['Hazardous',     cap2.hazardousAllowed      ? '✅ Yes' : '❌ No'],
              ['Temp-controlled', cap2.temperatureControlled ? '✅ Yes' : '❌ No'],
              ['Tracking',      cap2.trackingAvailable     ? '✅ Yes' : '❌ No'],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              Quote Breakdown
              <span className="ml-2 font-mono text-teal-500 normal-case">← get_carrier_quote (MCP)</span>
            </p>
            <InfoTable rows={[
              ['Base rate',       fmtC(q.baseRate)],
              ['Fuel surcharge',  fmtC(q.fuelSurcharge)],
              ['Handling fee',    fmtC(q.handlingFee)],
              ['Total cost',      fmtC(q.totalCost)],
              ['Service level',   q.serviceLevel],
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
              ['Shipment ID',     ship.id],
              ['Tracking',        ship.trackingNumber],
              ['Status',          ship.status],
              ['Priority',        ship.priority],
            ]} />
          </section>

          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Carrier Booked</p>
            <InfoTable rows={[
              ['Booking ID',      book.bookingId],
              ['Pickup window',   book.pickupWindow],
              ['Est. delivery',   book.estimatedDelivery],
              ['Tracking #',      book.trackingNumber],
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
export default function PlanShipmentHybrid() {
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

  /* Phase 1 — mcp_node_1 + mcp_node_2 */
  async function handleSubmit(e) {
    e.preventDefault();
    setStage('planning');
    setError('');
    try {
      const res = await planShipmentHybrid(body());
      if (res.status === 'error') {
        setError(res.error || 'MCP tool call failed.');
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
      const res = await confirmPlanHybrid(threadId, true);
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
    try { await confirmPlanHybrid(threadId, false); } catch (_) { /* ignore */ }
    setStage('rejected');
  }

  /* Gate 2 */
  async function handleDock(approved) {
    setStage('confirming');
    try {
      const res = await confirmDockHybrid(threadId, approved);
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
    planning:   'MCP nodes running: asyncio.gather(get_warehouse_capacity, optimize_route) → get_available_carriers → get_carrier_quote…',
    creating:   'LangGraph: creating shipment and booking carrier (direct GraphQL)…',
    confirming: 'LangGraph: finalising dock slot booking (direct GraphQL)…',
  };
  if (LOADING_MSG[stage]) {
    return (
      <div className="flex flex-col items-center justify-center min-h-64 gap-4 text-gray-500 dark:text-gray-400">
        <LoadingSpinner />
        <p className="text-sm text-center max-w-xs">{LOADING_MSG[stage]}</p>
        {stage === 'planning' && (
          <div className="flex gap-2">
            <NodeBadge label="mcp_node_1" done={false} />
            <NodeBadge label="mcp_node_2" done={false} />
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

      {/* Architecture banner */}
      <ArchBanner />

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">

        {/* Warehouse */}
        <div>
          <label className="form-label">Origin Warehouse</label>
          <select className="form-input" value={originWarehouseId} onChange={e => setOriginWarehouseId(e.target.value)} required>
            <option value="">Select warehouse…</option>
            {warehouses.map(w => (
              <option key={w.id} value={w.id}>{w.name} — {w.code}</option>
            ))}
          </select>
        </div>

        {/* Destination */}
        <fieldset className="space-y-3 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <legend className="text-xs font-semibold uppercase tracking-wide text-gray-400 px-1">Destination Address</legend>
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
              <select className="form-input" value={destinationAddress.country} onChange={e => setAddr('country', e.target.value)}>
                {COUNTRIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="form-label">Postal Code *</label>
              <input className="form-input" required value={destinationAddress.postalCode} onChange={e => setAddr('postalCode', e.target.value)} placeholder="10001" />
            </div>
          </div>
        </fieldset>

        {/* Items */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">Items</p>
            <button type="button" onClick={addItem} className="btn-secondary text-xs py-1">+ Add item</button>
          </div>
          {items.map((item, idx) => (
            <ItemRow key={idx} item={item} idx={idx} onChange={changeItem} onRemove={removeItem} canRemove={items.length > 1} />
          ))}
        </div>

        {/* Priority + dates */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="form-label">Priority</label>
            <select className="form-input" value={priority} onChange={e => setPriority(e.target.value)}>
              {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="form-label">Required Delivery Date</label>
            <input className="form-input" type="date" value={requiredDeliveryDate} onChange={e => setRequiredDeliveryDate(e.target.value)} />
          </div>
        </div>

        <div>
          <label className="form-label">Special Instructions</label>
          <textarea className="form-input" rows={2} value={specialInstructions} onChange={e => setSpecialInstructions(e.target.value)} placeholder="Handle with care…" />
        </div>

        <button type="submit" className="btn-primary w-full">
          🔀 Run Hybrid MCP Agent
        </button>
      </form>
    </div>
  );
}
