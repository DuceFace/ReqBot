import { Link } from 'react-router-dom'
import AppShell from '../components/AppShell'

export default function NotFoundView() {
  return (
    <AppShell>
      <div className="max-w-4xl mx-auto px-6 py-8">
        <h1 className="text-2xl font-bold text-gray-900">Not found</h1>
        <p className="mt-2 text-gray-500">This page does not exist.</p>
        <Link to="/search" className="mt-4 inline-block text-blue-600 hover:underline">
          ← Back to search
        </Link>
      </div>
    </AppShell>
  )
}
