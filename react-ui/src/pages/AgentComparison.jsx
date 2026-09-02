/**
 * AgentComparison.jsx — Study-material landing page.
 *
 * Side-by-side comparison of V1 (LangGraph ReAct + MCP) and
 * V3 (LangGraph StateGraph + Apollo supergraph fan-out).
 */
import { Link } from 'react-router-dom';

/* ── Data ─────────────────────────────────────────────────────────────────── */

const V1 = {
  version: 'V1',
  title:   'ReAct Agent',
  color:   'amber',
  emoji:   '🤖',
  tagline: 'LangGraph ReAct + MCP Tools + Per-mutation HITL',
  path:    '/plan/v1',
  cta:     'Try V1 →',
  stack: [
    { layer: 'Orchestration',  value: 'LangGraph create_react_agent'             },
    { layer: 'Tool protocol',  value: 'MCP (Apollo MCP Server on port 8090)'     },
    { layer: 'HITL strategy',  value: 'interrupt() before every mutating tool'   },
    { layer: 'Data reads',     value: 'Agent decides which MCP tools to call'    },
    { layer: 'Data writes',    value: 'CreateShipment, BookCarrier, BookDockSlot via MCP' },
    { layer: 'State storage',  value: 'MemorySaver checkpointer + thread_id'     },
    { layer: 'Confirmation',   value: 'ConfirmationDialog per tool call'         },
    { layer: 'Gateway',        value: 'FastAPI /api/v1/plan + /api/v1/plan/confirm' },
  ],
  flow: [
    { step: 1, label: 'POST /api/v1/plan',        desc: 'Agent starts; calls MCP read tools autonomously' },
    { step: 2, label: 'interrupt() fires',         desc: 'Pauses before CreateShipment (or any mutation)' },
    { step: 3, label: 'POST /api/v1/plan/confirm', desc: 'User approves → mutation executes; or rejects'  },
    { step: 4, label: 'Loop',                      desc: 'Repeats for each subsequent mutation until done' },
  ],
  pros: [
    'Flexible — agent decides the plan dynamically',
    'MCP is a standard, reusable tool protocol',
    'Easy to add new tools (just add a .graphql file)',
    'Great for exploratory / ad-hoc queries',
  ],
  cons: [
    'Multiple interrupt() round-trips (one per mutation)',
    'Agent may call tools in unexpected order',
    'No explicit parallelism — reads are sequential',
    'Harder to audit: tool selection is non-deterministic',
  ],
};

const V3 = {
  version: 'V3',
  title:   'StateGraph',
  color:   'violet',
  emoji:   '🔗',
  tagline: 'LangGraph StateGraph + Apollo Supergraph fan-out + Two-gate HITL',
  path:    '/plan/v3',
  cta:     'Try V3 →',
  stack: [
    { layer: 'Orchestration',  value: 'LangGraph StateGraph (explicit nodes + edges)'   },
    { layer: 'Tool protocol',  value: 'Direct GraphQL to Apollo Router (supergraph)'     },
    { layer: 'HITL strategy',  value: 'Two named interrupt() gates (plan + dock)'        },
    { layer: 'Data reads',     value: 'One combined query → Apollo Router fans out subgraphs in parallel' },
    { layer: 'Data writes',    value: 'CreateShipment + BookCarrier auto after Gate 1; BookDockSlot at Gate 2' },
    { layer: 'State storage',  value: 'MemorySaver checkpointer + thread_id'             },
    { layer: 'Confirmation',   value: 'PlanReviewDialog (Gate 1) + DockDialog (Gate 2)' },
    { layer: 'Gateway',        value: 'FastAPI /api/v3/plan + /api/v3/plan/confirm + /api/v3/dock/confirm' },
  ],
  flow: [
    { step: 1, label: 'POST /api/v3/plan',          desc: 'plan_reads node: one Apollo query, Router fans out warehouse+route subgraphs in parallel; then carriers + quote sequentially' },
    { step: 2, label: 'Gate 1 interrupt()',          desc: 'plan_gate node: pauses with full plan for human review. Nothing written yet.' },
    { step: 3, label: 'POST /api/v3/plan/confirm',  desc: 'Approved → create_shipment + BookCarrier run automatically. Rejected → graph ends.' },
    { step: 4, label: 'Gate 2 interrupt()',          desc: 'dock_gate node: pauses with shipment + carrier info for dock-slot review.' },
    { step: 5, label: 'POST /api/v3/dock/confirm',  desc: 'Approved → BookDockSlot. Skipped → shipment stays active without dock.' },
  ],
  pros: [
    'Deterministic flow — sequence is always the same',
    'Apollo Router caches subgraph responses',
    'Parallel subgraph reads without asyncio.gather in Python',
    'Clear audit trail: two named gates with explicit payloads',
    'Error-stop before Gate 1 if warehouse/route/carriers/quote missing',
  ],
  cons: [
    'Less flexible — flow is hardcoded in the graph',
    'More infrastructure (Apollo Router required)',
    'Mutations are tightly coupled to graph nodes',
  ],
};

/* ── Shared concepts ─────────────────────────────────────────────────────── */

const CONCEPTS = [
  {
    term: 'interrupt()',
    desc: 'LangGraph primitive that pauses a graph mid-execution and serialises its state. The HTTP response carries the interrupt payload. Calling graph.ainvoke(Command(resume=value)) continues from exactly where it stopped.',
  },
  {
    term: 'MemorySaver',
    desc: 'In-memory LangGraph checkpointer. Every node execution is snapshotted keyed by thread_id. Resuming a graph re-loads the snapshot so state survives across separate HTTP calls.',
  },
  {
    term: 'thread_id',
    desc: 'A UUID generated at plan start, returned to the UI, and sent back in every confirm call. It is the key that links the three HTTP calls of a V3 session (or N calls in V1) into one graph run.',
  },
  {
    term: 'Apollo Supergraph',
    desc: 'A combined schema composed from multiple subgraph schemas by Apollo Federation. The Router\'s query planner splits a single GraphQL document into subgraph-specific fetches and executes independent ones in parallel.',
  },
  {
    term: 'MCP (Model Context Protocol)',
    desc: 'A standard for exposing tools to AI agents. The Apollo MCP Server converts each .graphql operation file into an MCP tool, hot-reloaded. The V1 agent calls these tools autonomously via LangChain\'s MCP adapter.',
  },
  {
    term: 'Command(resume=)',
    desc: 'LangGraph primitive used to continue a paused graph. Passed as the input to graph.ainvoke() after an interrupt(). The resume value is delivered to the node that called interrupt() as its return value.',
  },
  {
    term: 'Conditional edges',
    desc: 'In V3\'s StateGraph, routing functions (_after_plan_reads, _after_create_shipment) inspect state["error"] and direct the graph to END (on failure) or to the next HITL gate (on success).',
  },
  {
    term: 'TypedDict state',
    desc: 'V3 uses a ShipmentState TypedDict as the LangGraph state schema. Each node receives the full state dict and returns only the keys it changes. LangGraph merges the returned dict back into the shared state.',
  },
];

/* ── Sub-components ──────────────────────────────────────────────────────── */

const COLOR = {
  amber: {
    header:  'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700',
    badge:   'bg-amber-100 dark:bg-amber-800 text-amber-700 dark:text-amber-300',
    cta:     'bg-amber-500 hover:bg-amber-600 text-white',
    step:    'bg-amber-100 dark:bg-amber-800 text-amber-700 dark:text-amber-200',
    pro:     'text-amber-600 dark:text-amber-400',
    con:     'text-red-500 dark:text-red-400',
    border:  'border-amber-200 dark:border-amber-700',
    title:   'text-amber-700 dark:text-amber-300',
  },
  violet: {
    header:  'bg-violet-50 dark:bg-violet-900/20 border-violet-200 dark:border-violet-700',
    badge:   'bg-violet-100 dark:bg-violet-800 text-violet-700 dark:text-violet-300',
    cta:     'bg-violet-600 hover:bg-violet-700 text-white',
    step:    'bg-violet-100 dark:bg-violet-800 text-violet-700 dark:text-violet-200',
    pro:     'text-violet-600 dark:text-violet-400',
    con:     'text-red-500 dark:text-red-400',
    border:  'border-violet-200 dark:border-violet-700',
    title:   'text-violet-700 dark:text-violet-300',
  },
};

function VersionCard({ data }) {
  const c = COLOR[data.color];
  return (
    <div className={`rounded-2xl border-2 ${c.border} overflow-hidden flex flex-col`}>
      {/* Header */}
      <div className={`${c.header} p-6 border-b-2 ${c.border}`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <span className={`inline-block text-xs font-bold px-2.5 py-1 rounded-full mb-3 ${c.badge}`}>
              {data.version}
            </span>
            <h2 className={`text-2xl font-bold ${c.title}`}>
              {data.emoji} {data.title}
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{data.tagline}</p>
          </div>
          <Link
            to={data.path}
            className={`shrink-0 text-sm font-semibold px-4 py-2 rounded-lg transition-colors ${c.cta}`}
          >
            {data.cta}
          </Link>
        </div>
      </div>

      <div className="p-6 flex flex-col gap-6 flex-1">
        {/* Tech stack */}
        <section>
          <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">
            Tech Stack
          </h3>
          <div className="space-y-2">
            {data.stack.map(({ layer, value }) => (
              <div key={layer} className="grid grid-cols-[10rem_1fr] gap-2 text-sm">
                <span className="font-medium text-gray-500 dark:text-gray-400 truncate">{layer}</span>
                <span className="text-gray-800 dark:text-gray-200">{value}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Flow */}
        <section>
          <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">
            HTTP Flow
          </h3>
          <ol className="space-y-3">
            {data.flow.map(({ step, label, desc }) => (
              <li key={step} className="flex gap-3 text-sm">
                <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${c.step}`}>
                  {step}
                </span>
                <div>
                  <span className="font-mono font-semibold text-gray-800 dark:text-gray-200">{label}</span>
                  <span className="text-gray-500 dark:text-gray-400"> — {desc}</span>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* Pros / Cons */}
        <section className="grid grid-cols-2 gap-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">Pros</h3>
            <ul className="space-y-1.5">
              {data.pros.map((p) => (
                <li key={p} className={`flex gap-1.5 text-sm ${c.pro}`}>
                  <span>✓</span> {p}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">Cons</h3>
            <ul className="space-y-1.5">
              {data.cons.map((p) => (
                <li key={p} className={`flex gap-1.5 text-sm ${c.con}`}>
                  <span>✗</span> {p}
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ── Architecture diagram (text-based) ─────────────────────────────────────── */

function ArchDiagram() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* V1 */}
      <div className="bg-amber-50 dark:bg-amber-900/10 rounded-xl p-4 border border-amber-200 dark:border-amber-700 font-mono text-xs leading-relaxed text-gray-700 dark:text-gray-300">
        <p className="font-bold text-amber-700 dark:text-amber-300 mb-3">V1 — ReAct Loop</p>
        <pre>{`UI ──► POST /api/v1/plan
        │
        ▼
   FastAPI Gateway
        │
        ▼
 LangGraph ReAct Agent
  ┌─────────────────────┐
  │  think → act → obs  │
  │  MCP tool calls:    │
  │  • GetWarehouse     │
  │  • OptimizeRoute    │
  │  • GetCarriers      │◄── Apollo MCP Server
  │  • GetQuote         │    (port 8090)
  │  • CreateShipment ──┼──► interrupt()
  │  • BookCarrier    ──┼──► interrupt()
  │  • BookDockSlot   ──┼──► interrupt()
  └─────────────────────┘
        │
        ▼
   MemorySaver (thread_id)
        │
        ▼
   UI confirm → POST /api/v1/plan/confirm
   Command(resume=approved) → graph continues`}
        </pre>
      </div>

      {/* V3 */}
      <div className="bg-violet-50 dark:bg-violet-900/10 rounded-xl p-4 border border-violet-200 dark:border-violet-700 font-mono text-xs leading-relaxed text-gray-700 dark:text-gray-300">
        <p className="font-bold text-violet-700 dark:text-violet-300 mb-3">V3 — StateGraph</p>
        <pre>{`UI ──► POST /api/v3/plan
        │
        ▼
   FastAPI Gateway
        │
        ▼
 LangGraph StateGraph
  START
    │
    ▼
  plan_reads ──────────────► Apollo Router
    │    one combined query    │  ├─ warehouse-svc (parallel)
    │                          │  └─ route-svc     (parallel)
    │    then carriers + quote │  └─ carrier-svc
    │                          └─ quote-svc
    ▼
  _after_plan_reads
    │ error? ──────────────► END
    │ ok
    ▼
  plan_gate ──────────────► interrupt()  ← Gate 1
    │
    │ Command(resume=True/False)
    │ POST /api/v3/plan/confirm
    ▼
  create_shipment (auto: CreateShipment + BookCarrier)
    │ error? ──────────────► END
    │ ok
    ▼
  dock_gate ──────────────► interrupt()  ← Gate 2
    │
    │ Command(resume=True/False)
    │ POST /api/v3/dock/confirm
    ▼
  book_dock (BookDockSlot if approved)
    │
    ▼
   END`}
        </pre>
      </div>
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────────── */

export default function AgentComparison() {
  return (
    <div className="space-y-12">
      {/* Hero */}
      <div className="text-center space-y-3 pt-2">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
          Agentic Shipment Planning — Study Guide
        </h1>
        <p className="text-gray-500 dark:text-gray-400 max-w-2xl mx-auto">
          Two implementations of the same business flow demonstrating different
          agentic architectures: <strong>LangGraph ReAct + MCP</strong> (V1) vs.{' '}
          <strong>LangGraph StateGraph + Apollo Supergraph</strong> (V3).
          Explore the live demos, compare the approaches, and read the concept glossary below.
        </p>
        <div className="flex gap-3 justify-center pt-2">
          <Link to="/plan/v1" className="px-5 py-2.5 bg-amber-500 hover:bg-amber-600 text-white font-semibold rounded-lg transition-colors">
            🤖 Try V1 — ReAct Agent
          </Link>
          <Link to="/plan/v3" className="px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white font-semibold rounded-lg transition-colors">
            🔗 Try V3 — StateGraph
          </Link>
        </div>
      </div>

      {/* Side-by-side cards */}
      <section>
        <h2 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-4">Architecture Comparison</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <VersionCard data={V1} />
          <VersionCard data={V3} />
        </div>
      </section>

      {/* Diagrams */}
      <section>
        <h2 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-4">Flow Diagrams</h2>
        <ArchDiagram />
      </section>

      {/* Key concepts glossary */}
      <section>
        <h2 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-4">Key Concepts</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {CONCEPTS.map(({ term, desc }) => (
            <div
              key={term}
              className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm"
            >
              <h3 className="font-mono font-bold text-sm text-gray-900 dark:text-white mb-1.5">{term}</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* When to use which */}
      <section>
        <h2 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-4">When to Use Which</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-700 rounded-xl p-5">
            <h3 className="font-semibold text-amber-700 dark:text-amber-300 mb-3">🤖 Choose V1 (ReAct + MCP) when…</h3>
            <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300">
              <li>• The sequence of steps is not known up front</li>
              <li>• Users ask open-ended / exploratory questions</li>
              <li>• You want to add new capabilities without changing orchestration (just add a .graphql file)</li>
              <li>• Individual mutation approval is important for every write</li>
              <li>• You prefer the MCP standard for tool interoperability</li>
            </ul>
          </div>
          <div className="bg-violet-50 dark:bg-violet-900/10 border border-violet-200 dark:border-violet-700 rounded-xl p-5">
            <h3 className="font-semibold text-violet-700 dark:text-violet-300 mb-3">🔗 Choose V3 (StateGraph + Apollo) when…</h3>
            <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300">
              <li>• The business process is well-defined and sequential</li>
              <li>• You want deterministic, auditable execution</li>
              <li>• Read parallelism matters (Apollo Router fan-out)</li>
              <li>• You want Apollo Gateway-level caching of subgraph responses</li>
              <li>• Two explicit review gates are the right UX (plan then dock)</li>
              <li>• Early-exit on missing data (error-stop before Gate 1)</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
