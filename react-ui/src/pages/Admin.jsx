import { useState, useEffect, useRef } from 'react';
import { askAgent, listTools } from '../api/gateway';

/* ─── MCP Tools Panel ────────────────────────────────────────────────────── */

function ToolCard({ tool, index }) {
  const [open, setOpen] = useState(false);
  // CreateShipment runs automatically; only carrier/dock bookings need approval.
  const MUTATING = ['BookCarrier', 'BookDockSlot',
                    'AssignCarrier', 'AssignRoute', 'UpdateShipmentStatus'];
  const isMutating = MUTATING.includes(tool.name);

  return (
    <div className="card p-0 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-3 p-4 text-left hover:bg-gray-50 transition-colors"
      >
        <span className="mt-0.5 flex-shrink-0 w-7 h-7 rounded-full bg-brand-100 text-brand-700
                         text-xs font-bold flex items-center justify-center">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono font-semibold text-sm text-gray-900">{tool.name}</span>
            {isMutating
              ? <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">
                  ✏️ mutating · HITL
                </span>
              : <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                  👁 read-only
                </span>
            }
          </div>
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{tool.description}</p>
        </div>
        <span className="text-gray-400 flex-shrink-0 mt-0.5">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 bg-gray-50 px-4 py-3 text-sm text-gray-700 leading-relaxed">
          {tool.description || <em className="text-gray-400">No description</em>}
        </div>
      )}
    </div>
  );
}

function McpToolsPanel() {
  const [tools,   setTools]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [search,  setSearch]  = useState('');

  useEffect(() => {
    listTools()
      .then(d => setTools(d.tools ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = (tools ?? []).filter(t =>
    t.name.toLowerCase().includes(search.toLowerCase()) ||
    (t.description ?? '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input
          className="form-input flex-1"
          placeholder="Search tools…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        {tools && (
          <span className="text-sm text-gray-400 whitespace-nowrap">
            {filtered.length} / {tools.length} tools
          </span>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-3 text-sm text-gray-400 py-6 justify-center">
          <span className="animate-spin text-lg">⚙️</span> Loading tools from Apollo MCP Server…
        </div>
      )}

      {error && (
        <div className="card border-l-4 border-red-400 text-red-700 text-sm">
          ⚠️ {error}
          <p className="text-xs mt-1 text-red-500">Is the MCP server running on port 8090?</p>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-8 text-gray-400">
          {search ? `No tools match "${search}"` : 'No tools returned by the server'}
        </div>
      )}

      <div className="space-y-2">
        {filtered.map((t, i) => <ToolCard key={t.name} tool={t} index={i} />)}
      </div>

      {/* Legend */}
      {tools && tools.length > 0 && (
        <div className="flex gap-4 text-xs text-gray-400 pt-2">
          <span>
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1" />
            Carrier/dock booking — pauses for human approval (HITL)
          </span>
          <span>
            <span className="inline-block w-2 h-2 rounded-full bg-green-400 mr-1" />
            Read &amp; create tools run automatically
          </span>
        </div>
      )}
    </div>
  );
}

/* ─── Chat Bot Panel ─────────────────────────────────────────────────────── */

function ChatMessage({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-sm
                       ${isUser ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600'}`}>
        {isUser ? '👤' : '🤖'}
      </div>
      <div className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
                       ${isUser
                         ? 'bg-brand-600 text-white rounded-tr-sm'
                         : 'bg-white border border-gray-200 text-gray-800 rounded-tl-sm'}`}>
        {msg.role === 'thinking'
          ? <span className="flex items-center gap-2 text-gray-400 italic">
              <span className="animate-pulse">●●●</span> Thinking…
            </span>
          : <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
        }
        {msg.tools && msg.tools.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {msg.tools.map(t => (
              <span key={t} className="px-1.5 py-0.5 bg-brand-50 text-brand-700 border
                                       border-brand-200 rounded text-xs font-mono">
                🔧 {t}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const QUICK_ASKS = [
  'What MCP tools are available?',
  'List all in-transit shipments',
  'What warehouses do we have?',
  'Show all carriers and their capabilities',
  'Find the cheapest carrier from Chicago to New York for 50 kg',
];

function ChatBotPanel() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hi! I\'m the Shipment Planner agent. Ask me anything about shipments, warehouses, carriers, or routes — I\'ll call the right MCP tools automatically.',
      tools: [],
    },
  ]);
  const [input,   setInput]   = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (question) => {
    const q = (question ?? input).trim();
    if (!q || loading) return;

    setInput('');
    setMessages(m => [...m,
      { role: 'user',     content: q,      tools: [] },
      { role: 'thinking', content: '',     tools: [] },
    ]);
    setLoading(true);

    try {
      const res = await askAgent(q);
      setMessages(m => [
        ...m.slice(0, -1),   // remove "thinking" bubble
        { role: 'assistant', content: res.answer, tools: res.toolsCalled ?? [] },
      ]);
    } catch (e) {
      setMessages(m => [
        ...m.slice(0, -1),
        { role: 'assistant', content: `⚠️ Error: ${e.message}`, tools: [] },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-[600px]">
      {/* Message thread */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1 pb-2">
        {messages.map((msg, i) => <ChatMessage key={i} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* Quick asks */}
      <div className="flex flex-wrap gap-1.5 py-2 border-t border-gray-100">
        {QUICK_ASKS.map(q => (
          <button
            key={q}
            onClick={() => send(q)}
            disabled={loading}
            className="text-xs px-2.5 py-1 rounded-full bg-gray-50 text-gray-600
                       border border-gray-200 hover:border-brand-400 hover:text-brand-700
                       transition-colors disabled:opacity-40"
          >
            {q}
          </button>
        ))}
      </div>

      {/* Input row */}
      <div className="flex gap-2 pt-2">
        <input
          className="form-input flex-1"
          placeholder="Ask about shipments, carriers, warehouses…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
          disabled={loading}
        />
        <button
          onClick={() => send()}
          disabled={loading || !input.trim()}
          className="btn-primary px-5 disabled:opacity-40"
        >
          {loading ? '⏳' : '➤'}
        </button>
      </div>
    </div>
  );
}

/* ─── Admin page ─────────────────────────────────────────────────────────── */

const TABS = [
  { id: 'tools', label: '⚙️ MCP Tools',  panel: McpToolsPanel },
  { id: 'chat',  label: '💬 Chat Agent', panel: ChatBotPanel  },
];

export default function Admin() {
  const [tab, setTab] = useState('tools');
  const Panel = TABS.find(t => t.id === tab).panel;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">🛠 Admin</h1>
        <p className="text-sm text-gray-500 mt-1">
          Inspect the live MCP tool catalogue and chat directly with the LangGraph agent.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-5 py-2.5 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
              tab === t.id
                ? 'border-brand-600 text-brand-700 bg-brand-50'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Active panel */}
      <Panel />
    </div>
  );
}
