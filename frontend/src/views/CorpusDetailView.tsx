import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import * as api from '../api/client'
import type { DocsEntry, DocsResponse } from '../api/types'
import AppShell from '../components/AppShell'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import { docValue } from '../utils/ui'

export default function CorpusDetailView() {
  const { docId } = useParams<{ docId: string }>()
  const [data, setData] = useState<DocsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .docs()
      .then(res => { setData(res) })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load documents')
      })
      .finally(() => { setLoading(false) })
  }, [])

  const doc: DocsEntry | undefined = data?.docs.find(d => d.doc_key === docId)

  return (
    <AppShell>
      <main className="max-w-4xl mx-auto px-6 py-8 space-y-6">

        <div>
          <Link to="/corpus" className="text-sm text-blue-600 hover:underline">
            ← Back to corpus
          </Link>
        </div>

        {loading && <LoadingSpinner />}
        {!loading && error && <ErrorBanner message={error} />}

        {!loading && !error && !doc && (
          <div className="bg-yellow-50 border border-yellow-200 rounded p-6">
            <p className="text-gray-700 font-medium">Document not found</p>
            <p className="mt-1 text-sm text-gray-500 font-mono">{docId}</p>
          </div>
        )}

        {!loading && !error && doc && (
          <>
            <div>
              <h1 className="text-xl font-bold text-gray-900 break-all">
                {doc.source_pdf || doc.doc_key}
              </h1>
              {doc.source_pdf && (
                <p className="mt-1 text-xs text-gray-400 font-mono">{doc.doc_key}</p>
              )}
            </div>

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-gray-400 whitespace-nowrap">Requirements</dt>
              <dd className="text-gray-700">{doc.count.toLocaleString()}</dd>

              <dt className="text-gray-400 whitespace-nowrap">Profile</dt>
              <dd className="text-gray-700">{doc.profile || 'cybersecurity'}</dd>

              <dt className="text-gray-400 whitespace-nowrap">Extraction mode</dt>
              <dd className="text-gray-700">{doc.mode}</dd>

              <dt className="text-gray-400 whitespace-nowrap">Run date</dt>
              <dd className="text-gray-700">{doc.run_date}</dd>
            </dl>

            <div className="flex flex-wrap gap-3 pt-1">
              <Link
                to={`/search?doc=${encodeURIComponent(docValue(doc))}`}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                Search this doc ↗
              </Link>
              <Link
                to={`/compare?doc1=${encodeURIComponent(docValue(doc))}`}
                className="px-4 py-2 text-sm bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Compare from here
              </Link>
              <Link
                to={`/checklists?doc=${encodeURIComponent(doc.doc_key)}`}
                className="px-4 py-2 text-sm bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Generate checklist
              </Link>
            </div>
          </>
        )}

      </main>
    </AppShell>
  )
}
