import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/client'
import type { DocsEntry, DocsResponse } from '../api/types'
import LoadingSpinner from '../components/LoadingSpinner'
import NavBar from '../components/NavBar'

// ── Types ─────────────────────────────────────────────────────────────────────

type SortKey = 'name' | 'count' | 'date'

// ── Sub-components ────────────────────────────────────────────────────────────

function DocRow({ entry }: { entry: DocsEntry }) {
  const displayName = entry.source_pdf || entry.doc_key

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{displayName}</p>
          <p className="text-xs text-gray-400 mt-1">
            {entry.count.toLocaleString()} requirement{entry.count !== 1 ? 's' : ''}
            {' · '}
            {entry.mode}
            {' · '}
            {entry.run_date}
          </p>
        </div>
        <Link
          to={`/search?doc=${encodeURIComponent(entry.doc_key)}`}
          className="shrink-0 text-sm text-blue-600 hover:underline whitespace-nowrap"
        >
          Search this doc ↗
        </Link>
      </div>
    </div>
  )
}

// ── Sort button ───────────────────────────────────────────────────────────────

function SortBtn({
  label,
  sortKey,
  active,
  asc,
  onClick,
}: {
  label: string
  sortKey: SortKey
  active: boolean
  asc: boolean
  onClick: (k: SortKey) => void
}) {
  return (
    <button
      onClick={() => onClick(sortKey)}
      className={`px-2 py-1 rounded text-xs ${
        active
          ? 'bg-blue-100 text-blue-700 font-medium'
          : 'text-gray-500 hover:bg-gray-100'
      }`}
    >
      {label}
      {active && (asc ? ' ↑' : ' ↓')}
    </button>
  )
}

// ── Main view ─────────────────────────────────────────────────────────────────

export default function DocsView() {
  const [data, setData] = useState<DocsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [filter, setFilter] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortAsc, setSortAsc] = useState(true)

  useEffect(() => {
    api
      .docs()
      .then(res => { setData(res) })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load documents')
      })
      .finally(() => { setLoading(false) })
  }, [])

  const filtered = useMemo<DocsEntry[]>(() => {
    if (!data) return []
    const q = filter.trim().toLowerCase()
    if (!q) return data.docs
    return data.docs.filter(d => {
      const haystack = `${d.source_pdf} ${d.doc_key}`.toLowerCase()
      return haystack.includes(q)
    })
  }, [data, filter])

  const sorted = useMemo<DocsEntry[]>(() => {
    const mult = sortAsc ? 1 : -1
    return [...filtered].sort((a, b) => {
      if (sortKey === 'count') return mult * (a.count - b.count)
      if (sortKey === 'date') return mult * a.run_date.localeCompare(b.run_date)
      return mult * (a.source_pdf || a.doc_key).localeCompare(b.source_pdf || b.doc_key)
    })
  }, [filtered, sortKey, sortAsc])

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc(prev => !prev)
    } else {
      setSortKey(key)
      setSortAsc(true)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Loading */}
        {loading && <LoadingSpinner />}

        {/* Error */}
        {!loading && error && (
          <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Results */}
        {!loading && !error && data && (
          <>
            {/* Corpus summary */}
            <p className="text-sm text-gray-500 mb-6">
              Corpus
              {' · '}
              {data.total_docs} document{data.total_docs !== 1 ? 's' : ''}
              {' · '}
              {data.total_reqs.toLocaleString()} requirements
            </p>

            {/* Filter + sort */}
            <div className="flex items-center gap-3 mb-3">
              <input
                type="text"
                value={filter}
                onChange={e => setFilter(e.target.value)}
                placeholder="Filter by name…"
                className="flex-1 border border-gray-300 rounded px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="flex items-center gap-1 shrink-0">
                <span className="text-xs text-gray-400 mr-1">Sort:</span>
                <SortBtn label="Name" sortKey="name" active={sortKey === 'name'} asc={sortAsc} onClick={handleSort} />
                <SortBtn label="Count" sortKey="count" active={sortKey === 'count'} asc={sortAsc} onClick={handleSort} />
                <SortBtn label="Date" sortKey="date" active={sortKey === 'date'} asc={sortAsc} onClick={handleSort} />
              </div>
            </div>

            {/* Row count */}
            <p className="text-xs text-gray-400 mb-3">
              {sorted.length} of {data.total_docs} document{data.total_docs !== 1 ? 's' : ''}
              {filter.trim() ? ` matching “${filter.trim()}”` : ''}
            </p>

            {/* Document list */}
            {sorted.length === 0 ? (
              <p className="text-sm text-gray-500">
                No documents match &ldquo;{filter}&rdquo;.
              </p>
            ) : (
              <div className="space-y-2">
                {sorted.map(entry => (
                  <DocRow key={entry.doc_key} entry={entry} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
