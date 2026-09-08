import { NavLink } from 'react-router-dom';

const NAV = [
  { to: '/plan',      label: '🚀 Plan Shipment' },
  { to: '/shipments', label: '📦 Shipments'     },
  { to: '/ask',       label: '🤖 Ask Agent'     },
  { to: '/admin',     label: '🛠 Admin'         },
];

export default function Layout({ children }) {
  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Top Bar ──────────────────────────────────────────────────────── */}
      <header className="bg-brand-600 shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center gap-6 h-16">
          <span className="text-white font-bold text-lg tracking-tight select-none">
            🚚 Shipment Planner
          </span>

          <nav className="flex gap-1 ml-4">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
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
      </header>

      {/* ── Page Content ─────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>

      <footer className="text-center text-xs text-gray-400 py-4 border-t border-gray-200">
        LangGraph · Apollo Federation v2 · Apollo MCP Server · Spring Boot 3 · FastAPI
      </footer>
    </div>
  );
}
