const STATUS_STYLES = {
  DRAFT:              'bg-gray-100  text-gray-700',
  PENDING_CARRIER:    'bg-yellow-100 text-yellow-800',
  CARRIER_CONFIRMED:  'bg-blue-100   text-blue-800',
  PICKUP_SCHEDULED:   'bg-indigo-100 text-indigo-800',
  IN_TRANSIT:         'bg-purple-100 text-purple-800',
  OUT_FOR_DELIVERY:   'bg-orange-100 text-orange-800',
  DELIVERED:          'bg-green-100  text-green-800',
  EXCEPTION:          'bg-red-100    text-red-800',
  CANCELLED:          'bg-gray-200   text-gray-600',
};

const STATUS_ICONS = {
  DRAFT:              '✏️',
  PENDING_CARRIER:    '⏳',
  CARRIER_CONFIRMED:  '✅',
  PICKUP_SCHEDULED:   '📅',
  IN_TRANSIT:         '🚛',
  OUT_FOR_DELIVERY:   '🏠',
  DELIVERED:          '🎉',
  EXCEPTION:          '⚠️',
  CANCELLED:          '❌',
};

export default function StatusBadge({ status }) {
  const cls  = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700';
  const icon = STATUS_ICONS[status]  ?? '•';
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      <span>{icon}</span>
      {status?.replace(/_/g, ' ')}
    </span>
  );
}
