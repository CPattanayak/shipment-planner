/**
 * HITL Confirmation Dialog
 *
 * Shown when the agent wants to execute a mutating MCP tool
 * (CreateShipment, BookCarrier, BookDockSlot) and needs human approval.
 *
 * Props:
 *   confirmation  – { tool, summary, arguments, question }
 *   onApprove()   – user clicked Approve
 *   onReject()    – user clicked Reject
 *   loading       – disable buttons while the resume call is in-flight
 */
export default function ConfirmationDialog({ confirmation, onApprove, onReject, loading }) {
  if (!confirmation) return null;

  const { tool, summary, arguments: args, question } = confirmation;

  // Flatten the arguments object into readable key-value rows
  const argRows = flattenArgs(args);

  return (
    /* Backdrop */
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">

        {/* Header */}
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-4 flex items-start gap-3">
          <span className="text-2xl">🛑</span>
          <div>
            <p className="font-semibold text-amber-900">Human Approval Required</p>
            <p className="text-sm text-amber-700 mt-0.5">
              The AI agent wants to execute <code className="font-mono bg-amber-100 px-1 rounded">{tool}</code>
            </p>
          </div>
        </div>

        {/* Summary */}
        <div className="px-6 py-4 space-y-4">
          <div className="rounded-lg bg-gray-50 border border-gray-200 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">What will happen</p>
            <p className="text-sm font-medium text-gray-800">{summary}</p>
          </div>

          {/* Arguments table */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
              Arguments the agent will pass
            </p>
            <div className="rounded-lg border border-gray-200 overflow-hidden text-sm">
              <table className="w-full">
                <tbody className="divide-y divide-gray-100">
                  {argRows.map(([key, val]) => (
                    <tr key={key} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono text-xs text-gray-500 w-2/5 align-top">{key}</td>
                      <td className="px-3 py-2 text-gray-800 break-all">{val}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="border-t border-gray-200 px-6 py-4 flex gap-3 justify-end bg-gray-50">
          <button
            onClick={onReject}
            disabled={loading}
            className="btn-danger"
          >
            {loading ? '…' : '❌ Reject'}
          </button>
          <button
            onClick={onApprove}
            disabled={loading}
            className="btn-success"
          >
            {loading ? '…' : '✅ Approve & Execute'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* Recursively flatten a nested args object into [key, displayValue] pairs */
function flattenArgs(obj, prefix = '') {
  const rows = [];
  for (const [k, v] of Object.entries(obj ?? {})) {
    const label = prefix ? `${prefix}.${k}` : k;
    if (Array.isArray(v)) {
      rows.push([label, `[${v.length} item${v.length !== 1 ? 's' : ''}]`]);
    } else if (v !== null && typeof v === 'object') {
      rows.push(...flattenArgs(v, label));
    } else {
      rows.push([label, String(v ?? '')]);
    }
  }
  return rows;
}
