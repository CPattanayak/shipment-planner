import { NavLink, useLocation } from 'react-router-dom';

/* ── Navigation groups ─────────────────────────────────────────────────────── */
const NAV_GROUPS = [
  {
    label: 'Plan Shipment',
    items: [
      { to: '/plan/v1',     label: 'V1 · ReAct',    badge: 'MCP',         color: 'amber'  },
      { to: '/plan/v3',     label: 'V3 · Graph',     badge: 'LangGraph',   color: 'violet' },
      { to: '/plan/hybrid', label: 'Hybrid · MCP↑↑', badge: 'asyncio',     color: 'teal'   },
      { to: '/plan/v4',     label: 'V4 · LLM+MCP',   badge: 'LLM reads',   color: 'sky'    },
    ],
  },
  {
    label: null,
    items: [
      { to: '/compare',   label: '📊 Compare',  badge: null },
      { to: '/shipments', label: '📦 Shipments', badge: null },
      { to: '/ask',       label: '🤖 Ask Agent', badge: null },
      { to: '/admin',     label: '🛠 Admin',     badge: null },
    ],
  },
];

const BADGE_COLORS = {
  amber:  'bg-amber-400/20 text-amber-200 ring-1 ring-amber-300/30',
  violet: 'bg-violet-400/20 text-violet-200 ring-1 ring-violet-300/30',
  teal:   'bg-teal-400/20 text-teal-200 ring-1 ring-teal-300/30',
  sky:    'bg-sky-400/20 text-sky-200 ring-1 ring-sky-300/30',
};

export default function Layout({ children }) {
  const location = useLocation();
  const isPlanV1     = location.pathname.startsWith('/plan/v1');
  const isPlanV3     = location.pathname.startsWith('/plan/v3');
  const isPlanHybrid = location.pathname.startsWith('/plan/hybrid');
  const isPlanV4     = location.pathname.startsWith('/plan/v4');

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Top Bar ──────────────────────────────────────────────────────── */}
      <header className="bg-brand-600 shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center gap-2 h-16 flex-wrap">
          <NavLink to="/compare" className="text-white font-bold text-lg tracking-tight select-none hover:text-white/90 mr-2">
            🚚 Shipment Planner
          </NavLink>

          <nav className="flex gap-1 flex-wrap">
            {/* Plan sub-group with label */}
            <div className="flex items-center gap-1 bg-white/10 rounded-lg px-1 py-0.5">
              <span className="text-white/40 text-xs font-medium px-1 hidden sm:inline">Plan:</span>
              {NAV_GROUPS[0].items.map(({ to, label, badge, color }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    `flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-white/25 text-white'
                        : 'text-white/70 hover:text-white hover:bg-white/15'
                    }`
                  }
                >
                  {label}
                  {badge && (
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${BADGE_COLORS[color]}`}>
                      {badge}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>

            {/* Other nav items */}
            {NAV_GROUPS[1].items.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-white/20 text-white'
                      : 'text-white/70 hover:text-white hover:bg-white/10'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* ── Version context strip ─────────────────────────────────────── */}
        {(isPlanV1 || isPlanV3 || isPlanHybrid || isPlanV4) && (
          <div className={`text-xs text-center py-1 font-medium ${
            isPlanV1     ? 'bg-amber-500/30 text-amber-100'  :
            isPlanHybrid ? 'bg-teal-500/30  text-teal-100'   :
            isPlanV4     ? 'bg-sky-500/30   text-sky-100'    :
                           'bg-violet-500/30 text-violet-100'
          }`}>
            {isPlanV1     ? '📖 V1 Study Mode — LangGraph ReAct Agent · MCP Tools · Per-mutation HITL interrupt()'
            : isPlanHybrid ? '📖 Hybrid Study Mode — Explicit MCP Nodes · asyncio.gather() · Tool chain · Two-gate HITL'
            : isPlanV4    ? '🤖 V4 Study Mode — LLM parallel rounds · asyncio.gather() · MCPToolStep extraction · Two-gate HITL'
            :                '📖 V3 Study Mode — LangGraph StateGraph · Apollo Supergraph fan-out · Two-gate HITL interrupt()'}
          </div>
        )}
      </header>

      {/* ── Page Content ─────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>

      <footer className="text-center text-xs text-gray-400 py-4 border-t border-gray-200 dark:border-gray-700">
        LangGraph · Apollo Federation v2 · Apollo MCP Server · Spring Boot 3 · FastAPI
      </footer>
    </div>
  );
}
