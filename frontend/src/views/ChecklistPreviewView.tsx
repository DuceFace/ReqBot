import { useState, useEffect } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import * as api from '../api/client'
import type { ChecklistEnvelope, ChecklistItem } from '../api/types'
import AppShell from '../components/AppShell'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import ChecklistTable from '../components/ChecklistTable'
import ExportButtonGroup from '../components/ExportButtonGroup'

export default function ChecklistPreviewView() {
  const { docId } = useParams<{ docId: string }>()
  const [searchParams] = useSearchParams()
  const profile = searchParams.get('profile') ?? 'cybersecurity'

  const [data, setData] = useState<ChecklistEnvelope | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [flaggedOnly, setFlaggedOnly] = useState(false)

  useEffect(() => {
    if (!docId) return
    setLoading(true)
    setError(null)
    setData(null)
    api
      .checklist({ doc_key: docId, profile })
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load checklist')
      })
      .finally(() => setLoading(false))
  }, [docId, profile])

  const items: ChecklistItem[] = data?.items ?? []
  const displayItems = flaggedOnly ? items.filter(i => i.requires_human_review) : items
  const flaggedCount = items.filter(i => i.requires_human_review).length

  return (
    <AppShell>
      <main className="max-w-full px-6 py-8 space-y-4">
        <div>
          <Link to="/checklists" className="text-sm text-blue-600 hover:underline">
            ← Back to generate
          </Link>
        </div>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Checklist</h1>
            <p className="mt-1 text-xs text-gray-400 font-mono">
              {docId} · {profile}
            </p>
          </div>

          {data && docId && (
            <ExportButtonGroup docKey={docId} profile={profile} />
          )}
        </div>

        {loading && <LoadingSpinner />}

        {!loading && error && <ErrorBanner message={error} />}

        {!loading && !error && data && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-gray-500">
                {data.summary.total_items} item{data.summary.total_items !== 1 ? 's' : ''}
                {flaggedCount > 0 && (
                  <span className="ml-2 text-amber-700">
                    · {flaggedCount} flagged for review
                  </span>
                )}
              </p>

              {flaggedCount > 0 && (
                <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={flaggedOnly}
                    onChange={e => setFlaggedOnly(e.target.checked)}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Flagged only
                </label>
              )}
            </div>

            {items.length === 0 ? (
              <p className="text-sm text-gray-500 py-8 text-center">
                No requirements had sufficient provenance to generate checklist items.
              </p>
            ) : displayItems.length === 0 ? (
              <p className="text-sm text-gray-500 py-8 text-center">
                No flagged items in this checklist.
              </p>
            ) : (
              <ChecklistTable items={displayItems} />
            )}
          </>
        )}
      </main>
    </AppShell>
  )
}
