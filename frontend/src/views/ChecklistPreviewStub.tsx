/**
 * Interim stub for /checklists/:docId — replaced by ChecklistPreviewView in WP-22.5.
 * Shows the raw checklist envelope while the full table UI is built.
 */
import { useState, useEffect } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import * as api from '../api/client'
import type { ChecklistEnvelope } from '../api/types'
import AppShell from '../components/AppShell'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'

export default function ChecklistPreviewStub() {
  const { docId } = useParams<{ docId: string }>()
  const [searchParams] = useSearchParams()
  const profile = searchParams.get('profile') ?? 'cybersecurity'

  const [data, setData] = useState<ChecklistEnvelope | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!docId) return
    setLoading(true)
    setError(null)
    api
      .checklist({ doc_key: docId, profile })
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load checklist')
      })
      .finally(() => setLoading(false))
  }, [docId, profile])

  return (
    <AppShell>
      <main className="max-w-4xl mx-auto px-6 py-8 space-y-4">
        <div>
          <Link to="/checklists" className="text-sm text-blue-600 hover:underline">
            ← Back to generate
          </Link>
        </div>

        <div>
          <h1 className="text-xl font-bold text-gray-900">Checklist</h1>
          <p className="mt-1 text-xs text-gray-400 font-mono">
            {docId} · {profile}
          </p>
        </div>

        {loading && <LoadingSpinner />}

        {!loading && error && <ErrorBanner message={error} />}

        {!loading && !error && data && (
          <div>
            <p className="text-sm text-gray-500 mb-3">
              {data.summary.total_items} item{data.summary.total_items !== 1 ? 's' : ''}
              {data.summary.items_requiring_review > 0 && (
                <span className="ml-2 text-amber-700">
                  · {data.summary.items_requiring_review} flagged for review
                </span>
              )}
            </p>
            <div className="overflow-x-auto">
              <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words bg-gray-50 border border-gray-200 rounded p-4">
                {JSON.stringify(data, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </main>
    </AppShell>
  )
}
