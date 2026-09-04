/**
 * AgentComparison.jsx — Study-material landing page.
 *
 * Three-way comparison:
 *   V1      LangGraph ReAct + MCP Tools + Per-mutation HITL
 *   V3      LangGraph StateGraph + Apollo Supergraph fan-out + Two-gate HITL
 *   Hybrid  LangGraph StateGraph + Explicit MCP Tool Nodes + asyncio.gather + Two-gate HITL
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

const HYBRID = {
  version: 'Hybrid',
  title:   'MCP Tool Nodes',
  color:   'teal',
  emoji:   '🔀',
  tagline: 'LangGraph StateGraph + Explicit MCP Nodes + asyncio.gather + Two-gate HITL',
  path:    '/plan/hybrid',
  cta:     'Try Hybrid →',
  stack: [
    { layer: 'Orchestration',  value: 'LangGraph StateGraph (explicit nodes + edges)'                },
    { layer: 'Tool protocol',  value: 'MCP (Apollo MCP Server) called inside StateGraph nodes'       },
    { layer: 'HITL strategy',  value: 'Two named interrupt() gates (plan + dock) — same as V3'       },
    { layer: 'Data reads',     value: 'mcp_node_1: asyncio.gather(capacity, route) then carriers; mcp_node_2: quote' },
    { layer: 'Data writes',    value: 'CreateShipment + BookCarrier + BookDockSlot via direct GraphQL' },
    { layer: 'State storage',  value: 'MemorySaver checkpointer + thread_id'                         },
    { layer: 'Confirmation',   value: 'PlanReviewDialog (Gate 1) + DockDialog (Gate 2)'              },
    { layer: 'Gateway',        value: 'FastAPI /api/hybrid/plan + /api/hybrid/plan/confirm + /api/hybrid/dock/confirm' },
  ],
  flow: [
    { step: 1, label: 'POST /api/hybrid/plan',         desc: 'mcp_node_1: asyncio.gather(get_warehouse_capacity, optimize_route); then get_available_carriers' },
    { step: 2, label: 'mcp_node_2',                    desc: 'get_carrier_quote — tool-chains from best_carrier in mcp_node_1 state'                           },
    { step: 3, label: 'Gate 1 interrupt()',             desc: 'plan_gate: pauses with full plan for human review. Nothing written yet.'                          },
    { step: 4, label: 'POST /api/hybrid/plan/confirm', desc: 'Approved → CreateShipment + BookCarrier (direct GraphQL). Rejected → graph ends.'                 },
    { step: 5, label: 'Gate 2 interrupt()',             desc: 'dock_gate: pauses with shipment + carrier info for dock-slot review.'                             },
    { step: 6, label: 'POST /api/hybrid/dock/confirm', desc: 'Approved → BookDockSlot (direct GraphQL). Skipped → shipment stays active.'                       },
  ],
  pros: [
    'Parallelism is explicit in Python code (asyncio.gather) — easy to read and teach',
    'MCP tool names appear directly in the node code — no hidden query planning',
    'Typed state flows node → node — tool chain is visible and testable',
    'Same two-gate HITL UX as V3 — deterministic and auditable',
    'Easy to add a new MCP tool: call it inside an existing node',
  ],
  cons: [
    'More Python code than V3 (explicit gather vs one Apollo query)',
    'MCP client opens a new connection per node — slight overhead',
    'Less flexible than V1 — flow is still hardcoded in the graph',
    'No Apollo Router query-plan caching (each tool call hits the subgraph directly)',
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
    desc: 'V3 and Hybrid use a TypedDict as the LangGraph state schema. Each node receives the full state dict and returns only the keys it changes. LangGraph merges the returned dict back into the shared state.',
  },
  {
    term: 'asyncio.gather()',
    desc: 'Python coroutine that runs multiple awaitables concurrently in one event-loop tick. In Hybrid mcp_node_1, gather(get_warehouse_capacity, optimize_route) fires both MCP tool calls at the same time, halving Round 1 latency.',
  },
  {
    term: 'Tool chain',
    desc: 'In Hybrid, mcp_node_2 reads best_carrier from state that mcp_node_1 wrote. The output of one node becomes the input of the next via typed state — no LLM needed to decide which carrier to quote.',
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
  teal: {
    header:  'bg-teal-50 dark:bg-teal-900/20 border-teal-200 dark:border-teal-700',
    badge:   'bg-teal-100 dark:bg-teal-800 text-teal-700 dark:text-teal-300',
    cta:     'bg-teal-600 hover:bg-teal-700 text-white',
    step:    'bg-teal-100 dark:bg-teal-800 text-teal-700 dark:text-teal-200',
    pro:     'text-teal-600 dark:text-teal-400',
    con:     'text-red-500 dark:text-red-400',
    border:  'border-teal-200 dark:border-teal-700',
    title:   'text-teal-700 dark:text-teal-300',
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
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* V1 */}
      <div className="bg-amber-50 dark:bg-amber-900/10 rounded-xl p-4 border border-amber-200 dark:border-amber-700 font-mono text-xs leading-relaxed text-gray-700 dark:text-gray-300">
        <p className="font-bold text-amber-700 dark:text-amber-300 mb-3">V1 — ReAct Loop</p>
        <pre>{`POST /api/v1/plan
  │
  ▼
LangGraph ReAct Agent
┌──────────────────────┐
│  think → act → obs   │
│  MCP tool calls:     │
│  • GetWarehouse      │◄─ MCP
│  • OptimizeRoute     │   Server
│  • GetCarriers       │   :8090
│  • GetQuote          │
│  • CreateShipment ───┼─► interrupt()
│  • BookCarrier    ───┼─► interrupt()
│  • BookDockSlot   ───┼─► interrupt()
└──────────────────────┘
  │
  ▼
MemorySaver(thread_id)
  │
  ▼
POST /api/v1/plan/confirm
Command(resume=approved)`}
        </pre>
      </div>

      {/* V3 */}
      <div className="bg-violet-50 dark:bg-violet-900/10 rounded-xl p-4 border border-violet-200 dark:border-violet-700 font-mono text-xs leading-relaxed text-gray-700 dark:text-gray-300">
        <p className="font-bold text-violet-700 dark:text-violet-300 mb-3">V3 — StateGraph</p>
        <pre>{`POST /api/v3/plan
  │
  ▼
LangGraph StateGraph
START → plan_reads
  │  one combined GQL doc
  │  Apollo Router fans out:
  │  ├─ warehouse-svc ║parallel
  │  └─ route-svc     ║
  │  then carriers → quote
  ▼
_after_plan_reads
  │ error? ──► END
  │ ok
  ▼
plan_gate ──► interrupt()
             ← Gate 1
  │ POST /api/v3/plan/confirm
  │ Command(resume=True/False)
  ▼
create_shipment
  CreateShipment + BookCarrier
  │ error? ──► END
  ▼
dock_gate ──► interrupt()
             ← Gate 2
  │ POST /api/v3/dock/confirm
  ▼
book_dock → END`}
        </pre>
      </div>

      {/* Hybrid */}
      <div className="bg-teal-50 dark:bg-teal-900/10 rounded-xl p-4 border border-teal-200 dark:border-teal-700 font-mono text-xs leading-relaxed text-gray-700 dark:text-gray-300">
        <p className="font-bold text-teal-700 dark:text-teal-300 mb-3">Hybrid — Explicit MCP Nodes</p>
        <pre>{`POST /api/hybrid/plan
  │
  ▼
LangGraph StateGraph
START → mcp_node_1
  │
  │  asyncio.gather(          ← Python parallel
  │    get_warehouse_capacity,
  │    optimize_route
  │  )
  │  then get_available_carriers
  │
  ▼
mcp_node_2
  │  get_carrier_quote
  │  (tool-chains best_carrier)
  ▼
_after_mcp_node_2
  │ error? ──► END
  ▼
plan_gate ──► interrupt()
             ← Gate 1
  │ POST /api/hybrid/plan/confirm
  ▼
create_shipment (direct GQL)
  ▼
dock_gate ──► interrupt()
             ← Gate 2
  │ POST /api/hybrid/dock/confirm
  ▼
book_dock → END`}
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
        <p className="text-gray-500 dark:text-gray-400 max-w-3xl mx-auto">
          Three implementations of the same business flow demonstrating different agentic architectures.
          Explore the live demos, compare approaches, and read the concept glossary below.
        </p>
        <div className="flex flex-wrap gap-3 justify-center pt-2">
          <Link to="/plan/v1" className="px-5 py-2.5 bg-amber-500 hover:bg-amber-600 text-white font-semibold rounded-lg transition-colors">
            🤖 Try V1 — ReAct + MCP
          </Link>
          <Link to="/plan/v3" className="px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white font-semibold rounded-lg transition-colors">
            🔗 Try V3 — StateGraph
          </Link>
          <Link to="/plan/hybrid" className="px-5 py-2.5 bg-teal-600 hover:bg-teal-700 text-white font-semibold rounded-lg transition-colors">
            🔀 Try Hybrid — MCP Nodes
          </Link>
        </div>
      </div>

      {/* Side-by-side cards */}
      <section>
        <h2 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-4">Architecture Comparison</h2>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <VersionCard data={V1} />
          <VersionCard data={V3} />
          <VersionCard data={HYBRID} />
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
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-700 rounded-xl p-5">
            <h3 className="font-semibold text-amber-700 dark:text-amber-300 mb-3">🤖 Choose V1 when…</h3>
            <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300">
              <li>• The step sequence is not known up front</li>
              <li>• Users ask open-ended / exploratory questions</li>
              <li>• You want to add tools without changing orchestration</li>
              <li>• Individual mutation approval matters for every write</li>
              <li>• You prefer MCP for tool interoperability</li>
            </ul>
          </div>
          <div className="bg-violet-50 dark:bg-violet-900/10 border border-violet-200 dark:border-violet-700 rounded-xl p-5">
            <h3 className="font-semibold text-violet-700 dark:text-violet-300 mb-3">🔗 Choose V3 when…</h3>
            <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300">
              <li>• The flow is well-defined and deterministic</li>
              <li>• Apollo Router fan-out and caching matter</li>
              <li>• You want minimal Python code for reads</li>
              <li>• Two explicit review gates are the right UX</li>
              <li>• Early-exit on missing data before Gate 1</li>
            </ul>
          </div>
          <div className="bg-teal-50 dark:bg-teal-900/10 border border-teal-200 dark:border-teal-700 rounded-xl p-5">
            <h3 className="font-semibold text-teal-700 dark:text-teal-300 mb-3">🔀 Choose Hybrid when…</h3>
            <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300">
              <li>• You want reads via MCP but explicit control over parallelism</li>
              <li>• Teaching asyncio.gather() in an agent context</li>
              <li>• Tool chains between nodes need to be visible in code</li>
              <li>• You don't have Apollo Router but want parallel reads</li>
              <li>• Same two-gate HITL UX as V3 is the goal</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
