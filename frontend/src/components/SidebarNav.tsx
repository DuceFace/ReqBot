import { NavLink } from 'react-router-dom'
import StatusDot from './StatusDot'

const NAV_ITEMS = [
  { to: '/search', label: 'Search' },
  { to: '/compare', label: 'Compare' },
  { to: '/evidence', label: 'Evidence' },
  { to: '/checklists', label: 'Checklists' },
  { to: '/corpus', label: 'Corpus' },
  { to: '/system', label: 'System' },
  { to: '/settings', label: 'Settings' },
]

export default function SidebarNav() {
  return (
    <aside className="w-52 shrink-0 bg-white border-r border-gray-200 sticky top-0 h-screen flex flex-col overflow-y-auto">
      <div className="px-5 py-5 border-b border-gray-100">
        <span className="text-base font-bold text-gray-900 tracking-tight">ReqBot</span>
      </div>

      <nav className="flex-1 px-3 py-3 space-y-0.5">
        {NAV_ITEMS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-3 border-t border-gray-100">
        <StatusDot />
      </div>
    </aside>
  )
}
