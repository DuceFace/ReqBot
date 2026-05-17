import { useState, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useParams, Link, useLocation } from 'react-router-dom'
import * as api from '../api/client'
import { NotFoundError } from '../api/client'
import type { TraceResponse, Requirement } from '../api/types'
import LoadingSpinner from '../components/LoadingSpinner'
import { pageRange } from '../utils/ui'

// ── Sub-components ────────────────────────────────────────────────────────────

function Header({ backTo }: { backTo: string }) {
  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
      <Link to={backTo} className="text-sm text-blue-600 hover:underline shrink-0">
        ← Back to search
      </Link>
      <span className="text-xl font-bold text-gray-900">ReqBot</span>
    </header>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
        {label}
      </h2>
      {children}
    </section>
  )
}

/**
 * `from` is the original search query string (e.g. "?q=encryption&doc=AFI").
 * Threaded through so multi-hop cross-match navigation still has a working
 * "← Back to search" link that restores the original query.
 */
function CrossMatchCard({ match, from }: { match: Requirement; from: string }) {
  const snippet =
    match.description.length > 200
      ? match.description.slice(0, 200) + '…'
      : match.description
  const pages = pageRange(match.page_start, match.page_end)

  return (
    <Link
      to={`/trace/${encodeURIComponent(match.requirement_id)}`}
      state={{ from }}
      className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition-all no-underline"
    >
      <div className="flex items-center justify-between mb-1.5 gap-4">
        <span className="font-mono text-xs font-semibold text-blue-700 truncate">
          {match.requirement_id}
        </span>
        <div className="flex items-center gap-3 text-xs text-gray-400 shrink-0">
          <span>{match.document_id}</span>
          {pages && <span>{pages}</span>}
        </div>
      </div>
      <p className="text-sm text-gray-700 leading-snug">{snippet}</p>
      {match.source_ref && (
        <p className="mt-1.5 text-xs text-gray-400 truncate">{match.source_ref}</p>
      )}
    </Link>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TraceView() {
  const { reqId } = useParams<{ reqId: string }>()
  const location = useLocation()

  // Restore the previous search URL if ResultCard (or CrossMatchCard) passed it
  // via router state. Falls back to bare /search for direct navigation.
  const fromSearch = (location.state as { from?: string } | null)?.from ?? ''
  const backTo = fromSearch ? `/search${fromSearch}` : '/search'

  const [data, setData] = useState<TraceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [retries, setRetries] = useState(0)

  // Context is hidden by default and fetched on demand.
  const [contextText, setContextText] = useState<string | null>(null)
  const [contextLoading, setContextLoading] = useState(false)

  // Ref kept in sync with the current reqId on every render.
  // Used to discard context-fetch responses that arrive after navigation.
  const reqIdRef = useRef(reqId)
  reqIdRef.current = reqId

  // Main fetch — guarded with `cancelled` flag (same pattern as SearchView)
  // to prevent superseded responses from overwriting state after navigation.
  useEffect(() => {
    if (!reqId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setNotFound(false)
    setData(null)
    setContextText(null)
    setContextLoading(false)
    api
      .trace(reqId)
      .then(res => {
        if (cancelled) return
        setData(res)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof NotFoundError) {
          setNotFound(true)
        } else {
          setError(err instanceof Error ? err.message : 'Request failed')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reqId, retries])

  function handleExpandContext() {
    if (!reqId || contextLoading) return
    // Capture reqId at the time of the request so we can discard the response
    // if the user navigates to a different requirement before it returns.
    const capturedReqId = reqId
    setContextLoading(true)
    api
      .trace(reqId, true)
      .then(res => {
        if (reqIdRef.current !== capturedReqId) return
        setContextText(res.context_text ?? '(no context available)')
      })
      .catch(() => {
        if (reqIdRef.current !== capturedReqId) return
        setContextText('(failed to load context)')
      })
      .finally(() => {
        if (reqIdRef.current === capturedReqId) setContextLoading(false)
      })
  }

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header backTo={backTo} />
        <main className="max-w-4xl mx-auto px-6 py-8">
          <LoadingSpinner />
        </main>
      </div>
    )
  }

  // ── Not found ────────────────────────────────────────────────────────────────
  if (notFound) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header backTo={backTo} />
        <main className="max-w-4xl mx-auto px-6 py-8">
          <div className="bg-yellow-50 border border-yellow-200 rounded p-6 text-center">
            <p className="text-gray-700 font-medium mb-1">Requirement not found</p>
            <p className="text-sm text-gray-500 mb-4">
              <span className="font-mono">{reqId}</span> does not exist in the index.
            </p>
            <Link to={backTo} className="text-sm text-blue-600 underline">
              ← Back to search
            </Link>
          </div>
        </main>
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header backTo={backTo} />
        <main className="max-w-4xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
            <span>{error}</span>
            <button
              onClick={() => setRetries(r => r + 1)}
              className="ml-4 underline hover:no-underline shrink-0"
            >
              Retry
            </button>
          </div>
        </main>
      </div>
    )
  }

  if (!data) return null

  const req = data.requirement
  const pages = pageRange(req.page_start, req.page_end)

  // ── Full detail ──────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      <Header backTo={backTo} />
      <main className="max-w-4xl mx-auto px-6 py-8 space-y-6">

        {/* ID + breadcrumb */}
        <div>
          <h1 className="font-mono text-lg font-bold text-blue-700 break-all">
            {req.requirement_id}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {req.document_id}
            {req.section_title_path && <> · {req.section_title_path}</>}
            {pages && <> · {pages}</>}
          </p>
        </div>

        {/* Description */}
        <Section label="Description">
          {req.description ? (
            <p className="text-sm text-gray-700 leading-relaxed">{req.description}</p>
          ) : (
            <p className="text-sm text-gray-400">No description available.</p>
          )}
        </Section>

        {/* Source quote */}
        <Section label="Source Quote">
          {req.source_quote ? (
            <>
              <blockquote className="border-l-4 border-blue-200 pl-4 text-sm text-gray-700 italic leading-relaxed">
                {req.source_quote}
              </blockquote>
              {req.source_ref && (
                <p className="mt-2 text-xs text-gray-400">{req.source_ref}</p>
              )}
            </>
          ) : (
            <p className="text-sm text-gray-400">No source quote available.</p>
          )}
        </Section>

        {/* Source context — hidden by default, fetched on demand */}
        <Section label="Source Context">
          {contextText === null ? (
            <button
              onClick={handleExpandContext}
              disabled={contextLoading}
              className="text-sm text-blue-600 underline hover:no-underline disabled:opacity-50"
            >
              {contextLoading ? 'Loading…' : 'Show source context'}
            </button>
          ) : (
            <pre className="text-xs text-gray-600 bg-gray-100 rounded p-3 whitespace-pre-wrap leading-relaxed overflow-x-auto">
              {contextText}
            </pre>
          )}
        </Section>

        {/* Provenance */}
        <Section label="Provenance">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-gray-400 whitespace-nowrap">Document ID</dt>
            <dd className="text-gray-700 font-mono text-xs">{req.document_id}</dd>

            <dt className="text-gray-400 whitespace-nowrap">Source PDF</dt>
            <dd className="text-gray-700 text-xs break-all">{req.source_pdf}</dd>

            <dt className="text-gray-400 whitespace-nowrap">Type</dt>
            <dd className="text-gray-700">{req.requirement_type}</dd>

            {req.domain_tags.length > 0 && (
              <>
                <dt className="text-gray-400 whitespace-nowrap">Domain tags</dt>
                <dd className="text-gray-700">
                  <div className="flex flex-wrap gap-1.5">
                    {req.domain_tags.map(tag => (
                      <span
                        key={tag}
                        className="bg-blue-50 text-blue-700 text-xs rounded px-2 py-0.5"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </dd>
              </>
            )}

            {req.confidence != null && (
              <>
                <dt className="text-gray-400 whitespace-nowrap">Confidence</dt>
                <dd className="text-gray-700 tabular-nums">
                  {req.confidence.toFixed(2)}
                </dd>
              </>
            )}

            {req.section_ref_path && (
              <>
                <dt className="text-gray-400 whitespace-nowrap">Section ref</dt>
                <dd className="text-gray-700 text-xs">{req.section_ref_path}</dd>
              </>
            )}
          </dl>
        </Section>

        {/* Cross-framework matches */}
        <Section label={`Cross-Framework Matches (${data.cross_matches.length})`}>
          {data.cross_matches.length === 0 ? (
            <p className="text-sm text-gray-400">No cross-framework matches found.</p>
          ) : (
            <div className="space-y-3">
              {data.cross_matches.map(m => (
                <CrossMatchCard key={m.requirement_id} match={m} from={fromSearch} />
              ))}
            </div>
          )}
        </Section>

      </main>
    </div>
  )
}
