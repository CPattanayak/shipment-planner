import { useState } from 'react';
import { useQuery } from '@apollo/client';
import { Link } from 'react-router-dom';
import { GET_SHIPMENTS } from '../graphql/queries';
import StatusBadge from '../components/StatusBadge';
import LoadingSpinner from '../components/LoadingSpinner';

const STATUSES = [
  { value: '',                  label: 'All statuses' },
  { value: 'DRAFT',             label: 'Draft' },
  { value: 'PENDING_CARRIER',   label: 'Pending Carrier' },
  { value: 'CARRIER_CONFIRMED', label: 'Carrier Confirmed' },
  { value: 'PICKUP_SCHEDULED',  label: 'Pickup Scheduled' },
  { value: 'IN_TRANSIT',        label: 'In Transit' },
  { value: 'OUT_FOR_DELIVERY',  label: 'Out for Delivery' },
  { value: 'DELIVERED',         label: 'Delivered' },
  { value: 'EXCEPTION',         label: 'Exception' },
  { value: 'CANCELLED',         label: 'Cancelled' },
];

const PRIORITIES = [
  { value: '',          label: 'All priorities' },
  { value: 'STANDARD', label: 'Standard' },
  { value: 'EXPRESS',   label: 'Express' },
  { value: 'OVERNIGHT', label: 'Overnight' },
  { value: 'SAME_DAY',  label: 'Same Day' },
];

const PAGE_SIZE = 20;

export default function ShipmentList() {
  const [statusFilter,   setStatusFilter]   = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [offset,         setOffset]         = useState(0);

  /* Apollo query — re-runs whenever status/offset change */
  const { data, loading, error, refetch } = useQuery(GET_SHIPMENTS, {
    variables: {
      status: statusFilter || null,
      limit:  PAGE_SIZE,
      offset,
    },
    fetchPolicy: 'cache-and-network',
  });

  const shipments = data?.shipments ?? [];

  /* Client-side priority filter (the GraphQL schema only supports status filter) */
  const filtered = priorityFilter
    ? shipments.filter(s => s.priority === priorityFilter)
    : shipments;

  const handleStatusChange = (val) => {
    setStatusFilter(val);
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <h1 className="text-2xl font-bold text-gray-900 flex-1">📦 Shipments</h1>
        <button
          onClick={() => refetch()}
          className="btn-ghost self-start sm:self-auto"
        >
          ↻ Refresh
        </button>
        <Link to="/plan" className="btn-primary self-start sm:self-auto">
          + Plan new shipment
        </Link>
      </div>

      {/* Filters row — backed by Apollo (status) and client-side (priority) */}
      <div className="card py-4 flex flex-wrap gap-4">
        {/* Status dropdown → triggers Apollo refetch */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Status
          </label>
          <select
            className="form-select min-w-44"
            value={statusFilter}
            onChange={e => handleStatusChange(e.target.value)}
          >
            {STATUSES.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        {/* Priority dropdown → client-side filter */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Priority
          </label>
          <select
            className="form-select min-w-40"
            value={priorityFilter}
            onChange={e => setPriorityFilter(e.target.value)}
          >
            {PRIORITIES.map(p => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        <div className="self-end text-sm text-gray-400">
          {loading ? 'Loading…' : `${filtered.length} shipment${filtered.length !== 1 ? 's' : ''}`}
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        {loading && !data && <LoadingSpinner message="Loading shipments…" />}

        {error && (
          <div className="p-6 text-red-600 text-sm">
            ⚠️ Failed to load shipments: {error.message}
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="p-12 text-center text-gray-400">
            <p className="text-4xl mb-3">📭</p>
            <p className="font-medium">No shipments found</p>
            <p className="text-sm mt-1">
              {statusFilter
                ? `No ${statusFilter.replace('_', ' ').toLowerCase()} shipments`
                : 'Create your first shipment using the Plan page'}
            </p>
          </div>
        )}

        {filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  {['Tracking #', 'Status', 'Priority', 'Destination', 'Weight', 'Est. Delivery', 'Created'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      {h}
                    </th>
                  ))}
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filtered.map(s => (
                  <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-brand-700 font-semibold">
                      {s.trackingNumber}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={s.status} />
                    </td>
                    <td className="px-4 py-3">
                      <PriorityBadge priority={s.priority} />
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {s.destinationAddress?.city}, {s.destinationAddress?.country}
                      <span className="text-gray-400 ml-1">{s.destinationAddress?.postalCode}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 tabular-nums">
                      {s.totalWeight?.toFixed(1)} kg
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {s.estimatedDelivery
                        ? new Date(s.estimatedDelivery).toLocaleDateString()
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {new Date(s.createdAt).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/shipments/${s.id}`}
                        className="text-brand-600 hover:text-brand-800 font-medium text-xs"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!loading && filtered.length === PAGE_SIZE && (
          <div className="flex justify-between items-center px-4 py-3 border-t border-gray-100">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
              className="btn-ghost text-xs disabled:opacity-30"
            >
              ← Previous
            </button>
            <span className="text-xs text-gray-400">Showing {offset + 1}–{offset + filtered.length}</span>
            <button
              disabled={filtered.length < PAGE_SIZE}
              onClick={() => setOffset(o => o + PAGE_SIZE)}
              className="btn-ghost text-xs disabled:opacity-30"
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Priority badge ───────────────────────────────────────────────────────── */

const PRIORITY_STYLES = {
  STANDARD: 'bg-gray-100 text-gray-600',
  EXPRESS:  'bg-blue-100 text-blue-700',
  OVERNIGHT:'bg-purple-100 text-purple-700',
  SAME_DAY: 'bg-red-100 text-red-700',
};

function PriorityBadge({ priority }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${PRIORITY_STYLES[priority] ?? 'bg-gray-100 text-gray-600'}`}>
      {priority?.replace('_', ' ')}
    </span>
  );
}
