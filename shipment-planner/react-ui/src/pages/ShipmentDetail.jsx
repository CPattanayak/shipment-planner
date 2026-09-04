import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@apollo/client';
import { GET_SHIPMENT } from '../graphql/queries';
import StatusBadge from '../components/StatusBadge';
import LoadingSpinner from '../components/LoadingSpinner';

export default function ShipmentDetail() {
  const { id } = useParams();

  const { data, loading, error } = useQuery(GET_SHIPMENT, {
    variables: { id },
    fetchPolicy: 'cache-and-network',
  });

  const s = data?.shipment;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/shipments" className="hover:text-brand-600">Shipments</Link>
        <span>/</span>
        <span className="font-mono text-gray-700">{s?.trackingNumber ?? id}</span>
      </div>

      {loading && <LoadingSpinner message="Loading shipment…" />}

      {error && (
        <div className="card border-l-4 border-red-400 text-red-700 text-sm">
          ⚠️ {error.message}
        </div>
      )}

      {s && (
        <>
          {/* Header */}
          <div className="card flex flex-col sm:flex-row sm:items-start gap-4">
            <div className="flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-xl font-bold font-mono text-gray-900">{s.trackingNumber}</h1>
                <StatusBadge status={s.status} />
                <PriorityChip priority={s.priority} />
              </div>
              <p className="text-sm text-gray-500">
                Created {new Date(s.createdAt).toLocaleString()}
                {s.updatedAt && ` · Updated ${new Date(s.updatedAt).toLocaleString()}`}
              </p>
            </div>
            <div className="text-right space-y-1 text-sm text-gray-600">
              {s.estimatedDelivery && (
                <p>ETA: <span className="font-semibold">{new Date(s.estimatedDelivery).toLocaleDateString()}</span></p>
              )}
              {s.actualDelivery && (
                <p className="text-green-600">
                  Delivered: <span className="font-semibold">{new Date(s.actualDelivery).toLocaleDateString()}</span>
                </p>
              )}
            </div>
          </div>

          {/* Grid: details + address */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="card space-y-3">
              <h2 className="font-semibold text-gray-800">📊 Summary</h2>
              <dl className="text-sm divide-y divide-gray-100">
                {[
                  ['Warehouse',   s.originWarehouseId],
                  ['Carrier',     s.carrierId  || '—'],
                  ['Route',       s.routeId    || '—'],
                  ['Total weight',`${s.totalWeight?.toFixed(2)} kg`],
                  ['Total volume',`${s.totalVolume?.toFixed(3)} m³`],
                  ['Total value', `$${s.totalValue?.toFixed(2)}`],
                  ['Scheduled pickup', s.scheduledPickup
                    ? new Date(s.scheduledPickup).toLocaleString() : '—'],
                ].map(([label, val]) => (
                  <div key={label} className="flex py-2 gap-2">
                    <dt className="w-36 shrink-0 text-gray-400">{label}</dt>
                    <dd className="text-gray-800 font-medium truncate">{val}</dd>
                  </div>
                ))}
              </dl>
              {s.specialInstructions && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
                  ⚠️ {s.specialInstructions}
                </div>
              )}
            </div>

            <div className="card space-y-3">
              <h2 className="font-semibold text-gray-800">📍 Destination</h2>
              <address className="not-italic text-sm text-gray-700 leading-relaxed">
                {s.destinationAddress.street && <p>{s.destinationAddress.street}</p>}
                <p>{s.destinationAddress.city}, {s.destinationAddress.state} {s.destinationAddress.postalCode}</p>
                <p className="font-medium">{s.destinationAddress.country}</p>
              </address>
            </div>
          </div>

          {/* Items */}
          <div className="card space-y-4">
            <h2 className="font-semibold text-gray-800">
              📋 Items ({s.items?.length ?? 0})
            </h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm divide-y divide-gray-100">
                <thead className="bg-gray-50">
                  <tr>
                    {['SKU', 'Description', 'Qty', 'Weight (kg)', 'Volume (m³)', 'Value ($)', 'Flags'].map(h => (
                      <th key={h} className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {s.items?.map(it => (
                    <tr key={it.id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono text-xs text-gray-700">{it.sku}</td>
                      <td className="px-3 py-2 text-gray-800">{it.description}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{it.quantity}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{it.weight.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{it.volume.toFixed(3)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">${it.value.toFixed(2)}</td>
                      <td className="px-3 py-2">
                        <div className="flex gap-1 flex-wrap">
                          {it.hazardous           && <Flag label="Hazmat"   color="red"    />}
                          {it.temperatureControlled&& <Flag label="Temp"    color="blue"   />}
                          {it.fragile             && <Flag label="Fragile"  color="yellow" />}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Status History Timeline */}
          {s.statusHistory?.length > 0 && (
            <div className="card space-y-4">
              <h2 className="font-semibold text-gray-800">🕐 Status History</h2>
              <ol className="relative border-l border-gray-200 ml-3 space-y-6">
                {[...s.statusHistory].reverse().map((ev, i) => (
                  <li key={i} className="ml-6">
                    <span className="absolute -left-3 flex h-6 w-6 items-center justify-center rounded-full bg-brand-100 ring-4 ring-white">
                      <span className="h-2 w-2 rounded-full bg-brand-600" />
                    </span>
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={ev.status} />
                      <time className="text-xs text-gray-400">
                        {new Date(ev.timestamp).toLocaleString()}
                      </time>
                      {ev.location && (
                        <span className="text-xs text-gray-500">📍 {ev.location}</span>
                      )}
                    </div>
                    {ev.notes && (
                      <p className="mt-1 text-sm text-gray-600">{ev.notes}</p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PriorityChip({ priority }) {
  const map = {
    STANDARD: 'bg-gray-100 text-gray-600',
    EXPRESS:  'bg-blue-100 text-blue-700',
    OVERNIGHT:'bg-purple-100 text-purple-700',
    SAME_DAY: 'bg-red-100 text-red-700',
  };
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${map[priority] ?? 'bg-gray-100 text-gray-600'}`}>
      {priority?.replace('_', ' ')}
    </span>
  );
}

function Flag({ label, color }) {
  const map = {
    red:    'bg-red-100 text-red-700',
    blue:   'bg-blue-100 text-blue-700',
    yellow: 'bg-yellow-100 text-yellow-800',
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${map[color]}`}>{label}</span>
  );
}
