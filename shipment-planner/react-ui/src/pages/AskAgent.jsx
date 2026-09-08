import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@apollo/client';
import { GET_WAREHOUSES, GET_AVAILABLE_CARRIERS } from '../graphql/queries';
import { askAgent, streamAgent } from '../api/gateway';

/* ─── Quick-question templates the user can click ───────────────────────── */
const TEMPLATES = [
  'What warehouses do we have and how full are they?',
  'List all in-transit shipments',
  'Find the cheapest carrier from warehouse wh-001 to postal code 10001 for 50 kg',
  'What is the status of our most recent shipment?',
  'Show me all shipments with exceptions',
];

/* ─── Carrier lookup panel (uses Apollo useQuery) ──────────────────────── */
function CarrierLookup() {
  const [params, setParams] = useState({
    originPostalCode: '', destinationPostalCode: '',
    weightKg: 10, hasHazardous: false,
    requiresTemperatureControl: false, serviceLevel: 'STANDARD',
  });
  const [submitted, setSubmitted] = useState(false);

  const SERVICE_LEVELS = ['STANDARD', 'EXPRESS', 'OVERNIGHT', 'SAME_DAY'];

  const { data, loading, error } = useQuery(GET_AVAILABLE_CARRIERS, {
    variables: params,
    skip: !submitted,
    fetchPolicy: 'network-only',
  });

  const setP = (k, v) => { setSubmitted(false); setParams(p => ({ ...p, [k]: v })); };

  return (
    <div className="card space-y-4">
      <h2 className="font-semibold text-gray-800">🚛 Available Carrier Lookup</h2>
      <p className="text-xs text-gray-500">
        GraphQL query via Apollo Client → /api/v1/graphql → Apollo Router → Carrier Service
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
        <div>
          <label className="form-label text-xs">Origin Postal</label>
          <input className="form-input" placeholder="60601"
            value={params.originPostalCode}
            onChange={e => setP('originPostalCode', e.target.value)} />
        </div>
        <div>
          <label className="form-label text-xs">Dest Postal</label>
          <input className="form-input" placeholder="10001"
            value={params.destinationPostalCode}
            onChange={e => setP('destinationPostalCode', e.target.value)} />
        </div>
        <div>
          <label className="form-label text-xs">Weight (kg)</label>
          <input type="number" min="0" className="form-input"
            value={params.weightKg}
            onChange={e => setP('weightKg', parseFloat(e.target.value) || 0)} />
        </div>
        <div>
          <label className="form-label text-xs">Service Level</label>
          <select className="form-select" value={params.serviceLevel}
            onChange={e => setP('serviceLevel', e.target.value)}>
            {SERVICE_LEVELS.map(sl => <option key={sl}>{sl}</option>)}
          </select>
        </div>
        <div className="flex items-end gap-4">
          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
            <input type="checkbox" checked={params.hasHazardous}
              onChange={e => setP('hasHazardous', e.target.checked)}
              className="h-4 w-4 rounded text-brand-600" />
            Hazmat
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
            <input type="checkbox" checked={params.requiresTemperatureControl}
              onChange={e => setP('requiresTemperatureControl', e.target.checked)}
              className="h-4 w-4 rounded text-brand-600" />
            Temp control
          </label>
        </div>
        <div className="flex items-end">
          <button
            onClick={() => setSubmitted(true)}
            disabled={!params.originPostalCode || !params.destinationPostalCode}
            className="btn-primary w-full justify-center"
          >
            Search
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-400">Querying carriers via GraphQL…</p>}
      {error   && <p className="text-sm text-red-500">Error: {error.message}</p>}

      {data?.availableCarriers && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm divide-y divide-gray-100">
            <thead className="bg-gray-50">
              <tr>
                {['Carrier', 'Code', 'Modes', 'Max kg', 'On-time %', 'Tracking', 'Hazmat', 'Temp'].map(h => (
                  <th key={h} className="px-3 py-2 text-xs font-semibold text-left text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.availableCarriers.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-4 text-gray-400 text-center">No carriers found</td></tr>
              )}
              {data.availableCarriers.map(c => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium text-gray-800">{c.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">{c.code}</td>
                  <td className="px-3 py-2 text-gray-600">{c.supportedModes?.join(', ')}</td>
                  <td className="px-3 py-2 tabular-nums">{c.capabilities?.maxWeightKg?.toFixed(0)}</td>
                  <td className="px-3 py-2 tabular-nums text-green-700">
                    {(c.performance?.onTimeDeliveryRate * 100)?.toFixed(1)}%
                  </td>
                  <td className="px-3 py-2 text-center">{c.capabilities?.trackingAvailable ? '✅' : '—'}</td>
                  <td className="px-3 py-2 text-center">{c.capabilities?.hazardousAllowed ? '✅' : '❌'}</td>
                  <td className="px-3 py-2 text-center">{c.capabilities?.temperatureControlled ? '✅' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─── Main page ──────────────────────────────────────────────────────────── */

export default function AskAgent() {
  const [question,   setQuestion]   = useState('');
  const [loading,    setLoading]    = useState(false);
  const [streaming,  setStreaming]  = useState(false);
  const [response,   setResponse]   = useState(null);   // { answer, toolsCalled }
  const [streamText, setStreamText] = useState('');
  const [error,      setError]      = useState(null);
  const esRef = useRef(null);

  /* Warehouse dropdown data (Apollo) */
  const { data: whData } = useQuery(GET_WAREHOUSES, { variables: { activeOnly: true } });

  /* ── Ask (non-streaming) ─────────────────────────────────────────────── */
  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    setStreamText('');
    try {
      const res = await askAgent(question);
      setResponse(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  /* ── Stream ──────────────────────────────────────────────────────────── */
  const handleStream = () => {
    if (!question.trim()) return;
    stopStream();
    setStreaming(true);
    setStreamText('');
    setResponse(null);
    setError(null);

    const es = streamAgent(question);
    esRef.current = es;

    es.onmessage = (e) => {
      if (e.data === '[DONE]') { stopStream(); return; }
      try {
        const chunk = JSON.parse(e.data);
        if (chunk.type === 'token')       setStreamText(t => t + chunk.data);
        if (chunk.type === 'tool_call')   setStreamText(t => t + `\n[🔧 Calling ${chunk.data}…]\n`);
        if (chunk.type === 'error')       { setError(chunk.data); stopStream(); }
      } catch {}
    };
    es.onerror = () => { setError('Stream error — is the gateway running?'); stopStream(); };
  };

  const stopStream = () => {
    esRef.current?.close();
    esRef.current = null;
    setStreaming(false);
  };

  useEffect(() => () => stopStream(), []);

  /* ─────────────────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">🤖 Ask the Agent</h1>
      <p className="text-sm text-gray-500">
        Ask anything about shipments, routes, carriers, or warehouses in plain English.
        The LangGraph agent calls the right MCP tools and synthesises an answer.
      </p>

      {/* Quick templates */}
      <div className="flex flex-wrap gap-2">
        {TEMPLATES.map(t => (
          <button
            key={t}
            onClick={() => setQuestion(t)}
            className="text-xs px-3 py-1.5 rounded-full bg-brand-50 text-brand-700
                       border border-brand-200 hover:bg-brand-100 transition-colors"
          >
            {t}
          </button>
        ))}
      </div>

      {/* Warehouse quick-ref (Apollo) */}
      {whData?.warehouses?.length > 0 && (
        <div className="card py-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
            Available warehouses (via Apollo GraphQL)
          </p>
          <div className="flex flex-wrap gap-3">
            {whData.warehouses.map(wh => (
              <button
                key={wh.id}
                onClick={() => setQuestion(q =>
                  q ? q : `What is the capacity of warehouse ${wh.id}?`
                )}
                className="text-xs bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5 hover:border-brand-400 transition-colors"
              >
                <span className="font-mono font-semibold text-brand-700">{wh.id}</span>
                <span className="text-gray-500 ml-1">{wh.name}</span>
                <span className="ml-2 text-green-600">{(100 - wh.utilizationPct).toFixed(0)}% free</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Question input */}
      <div className="card space-y-3">
        <textarea
          rows={3}
          className="form-input resize-none"
          placeholder="e.g. Find the cheapest carrier for 50 kg from Chicago to New York"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) handleAsk(); }}
        />
        <div className="flex gap-3">
          <button
            onClick={handleAsk}
            disabled={loading || streaming || !question.trim()}
            className="btn-primary"
          >
            {loading ? '⏳ Thinking…' : '🤖 Ask'}
          </button>
          <button
            onClick={streaming ? stopStream : handleStream}
            disabled={loading || !question.trim()}
            className={streaming ? 'btn-danger' : 'btn-ghost'}
          >
            {streaming ? '⏹ Stop stream' : '📡 Stream response'}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="card border-l-4 border-red-400 text-red-700 text-sm">
          ⚠️ {error}
        </div>
      )}

      {/* Stream output */}
      {streamText && (
        <div className="card space-y-3">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Live response {streaming && <span className="animate-pulse">●</span>}
            </p>
          </div>
          <pre className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed font-sans">
            {streamText}
          </pre>
        </div>
      )}

      {/* Answer */}
      {response && (
        <div className="card space-y-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Answer</p>
          <div className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
            {response.answer}
          </div>
          {response.toolsCalled?.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                MCP tools called ({response.toolsCalled.length})
              </p>
              <div className="flex flex-wrap gap-2">
                {response.toolsCalled.map((t, i) => (
                  <span key={i} className="px-2 py-0.5 bg-brand-50 text-brand-700 rounded text-xs font-mono">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="text-xs text-gray-400">
            {response.messageCount} messages in conversation
          </p>
        </div>
      )}

      {/* Divider */}
      <hr className="border-gray-200" />

      {/* Carrier Lookup panel using Apollo */}
      <CarrierLookup />
    </div>
  );
}
