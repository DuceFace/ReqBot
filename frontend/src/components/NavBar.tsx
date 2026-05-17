import { NavLink } from 'react-router-dom'
import StatusDot from './StatusDot'

const NAV_LINKS = [
  { to: '/search', label: 'Search' },
  { to: '/compare', label: 'Compare' },
  { to: '/evidence', label: 'Evidence' },
  { to: '/docs', label: 'Docs' },
]

export default function NavBar() {
  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <span className="text-xl font-bold text-gray-900">ReqBot</span>
        <nav className="flex gap-4">
          {NAV_LINKS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `text-sm font-medium ${isActive ? 'text-blue-600' : 'text-gray-500 hover:text-gray-900'}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
      <StatusDot />
    </header>
  )
}
