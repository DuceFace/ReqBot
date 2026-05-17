/**
 * Catch-all 404 view for unrecognised client-side routes.
 * Rendered by the path="*" Route in App.tsx.
 */
import { Link } from 'react-router-dom'

export default function NotFoundView() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900">Not found</h1>
      <p className="mt-2 text-gray-500">This page does not exist.</p>
      <Link to="/search" className="mt-4 inline-block text-blue-600 hover:underline">
        ← Back to search
      </Link>
    </div>
  )
}
