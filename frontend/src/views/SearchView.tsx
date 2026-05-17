import { useState, useEffect, useRef } from 'react'
import type { FormEvent, ChangeEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import * as api from '../api/client'
import type { AskResult, DocsEntry } from '../api/types'
import ResultCard from '../components/ResultCard'
import LoadingSpinner from '../components/LoadingSpinner'
import NavBar from '../components/NavBar'

export default function SearchView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''
  const doc = searchParams.get('doc') ?? ''

  // input tracks the text field; q tracks the committed (URL) query.
  // They diverge while the user is typing a new query.
  const [input, setInput] = useState(q)

  const [docOptions, setDocOptions] = useState<DocsEntry[]>([])
  const [results, setResults] = useState<AskResult[] | null>(null)
  const [retrievalMs, setRetrievalMs] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Incrementing this triggers a retry without changing q or doc.
  const [retries, setRetries] = useState(0)

  const [synthLoading, setSynthLoading] = useState(false)
  const [synthError, setSynthError] = useState<string | null>(null)
  const [synthText, setSynthText] = useState<string | null>(null)
  const [synthElapsed, setSynthElapsed] = useState(0)
  const synthCancelledRef = useRef(false)

  // Sync input field when q changes via browser back/forward.
  useEffect(() => {
    setInput(q)
  }, [q])

  // Reset synthesis when the committed query or doc filter changes.
  useEffect(() => {
    synthCancelledRef.current = true
    setSynthLoading(false)
    setSynthError(null)
    setSynthText(null)
    setSynthElapsed(0)
  }, [q, doc])

  // Elapsed timer while synthesis is running.
  useEffect(() => {
    if (!synthLoading) return
    setSynthElapsed(0)
    const iv = setInterval(() => setSynthElapsed(s => s + 1), 1000)
    return () => clearInterval(iv)
  }, [synthLoading])

  // Load document list once on mount for the filter dropdown.
  useEffect(() => {
    api.docs().then(d => setDocOptions(d.docs)).catch(() => { /* silent */ })
  }, [])

  // Run search whenever the committed query, doc filter, or retry count changes.
  // A `cancelled` flag prevents stale responses from superseded requests
  // overwriting the UI when the query changes before the previous fetch completes.
  useEffect(() => {
    if (!q) {
      // Reset all search UI — previously only results/retrievalMs were cleared,
      // leaving stale error banners and loading indicators after navigating back.
      setResults(null)
      setRetrievalMs(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .ask({
        question: q,
        top_k: 20,
        document_ids: doc ? [doc] : undefined,
      })
      .then(res => {
        if (cancelled) return
        setResults(res.results)
        setRetrievalMs(res.metadata.retrieval_ms)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Search failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
    // retries intentionally included so the retry button can re-run
    // the same query without changing the URL params.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, doc, retries])

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed) return
    const params: Record<string, string> = { q: trimmed }
    if (doc) params.doc = doc
    setSearchParams(params)
  }

  function handleGenerateAnswer() {
    if (!q || synthLoading) return
    synthCancelledRef.current = false
    setSynthLoading(true)
    setSynthError(null)
    setSynthText(null)
    api
      .ask({
        question: q,
        top_k: 20,
        document_ids: doc ? [doc] : undefined,
        synthesize: true,
      })
      .then(res => {
        if (synthCancelledRef.current) return
        setSynthText(res.metadata.synthesis || null)
      })
      .catch((err: unknown) => {
        if (synthCancelledRef.current) return
        setSynthError(err instanceof Error ? err.message : 'Synthesis failed')
      })
      .finally(() => {
        if (!synthCancelledRef.current) setSynthLoading(false)
      })
  }

  function handleDocChange(e: ChangeEvent<HTMLSelectElement>) {
    const newDoc = e.target.value
    const params: Record<string, string> = {}
    if (q) params.q = q
    if (newDoc) params.doc = newDoc
    setSearchParams(params)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      {/* Main */}
      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Search form */}
        <form onSubmit={handleSubmit} className="flex gap-2 mb-4">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Search compliance requirements…"
            className="flex-1 border border-gray-300 rounded px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded text-sm font-medium"
          >
            Search
          </button>
        </form>

        {/* Document filter */}
        <div className="mb-6">
          <label className="text-sm text-gray-600 mr-2" htmlFor="doc-filter">
            Filter by document:
          </label>
          <select
            id="doc-filter"
            value={doc}
            onChange={handleDocChange}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All documents</option>
            {docOptions.map(d => (
              <option key={d.doc_key} value={d.source_pdf}>
                {d.source_pdf}
              </option>
            ))}
          </select>
        </div>

        {/* Loading */}
        {loading && <LoadingSpinner />}

        {/* Error */}
        {!loading && error && (
          <div className="flex items-center justify-between bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
            <span>{error}</span>
            <button
              onClick={() => setRetries(r => r + 1)}
              className="ml-4 underline hover:no-underline shrink-0"
            >
              Retry
            </button>
          </div>
        )}

        {/* Results */}
        {!loading && !error && results !== null && (
          <>
            <div className="flex items-center justify-between mb-4 text-sm text-gray-500">
              <span>Results ({results.length})</span>
              <div className="flex items-center gap-3">
                {retrievalMs !== null && (
                  <span className="tabular-nums">{retrievalMs.toFixed(0)} ms</span>
                )}
                {results.length > 0 && (
                  synthLoading ? (
                    <button
                      disabled
                      className="bg-gray-100 text-gray-500 cursor-not-allowed px-3 py-1 rounded text-xs font-medium border border-gray-200"
                    >
                      Generating…{synthElapsed > 0 ? ` ${synthElapsed}s` : ''}
                    </button>
                  ) : (
                    <button
                      onClick={handleGenerateAnswer}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1 rounded text-xs font-medium transition-colors"
                    >
                      Generate Answer
                    </button>
                  )
                )}
              </div>
            </div>

            {/* Synthesis error */}
            {synthError && (
              <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700 mb-4">
                Synthesis failed: {synthError}
              </div>
            )}

            {/* Synthesis output */}
            {synthText && (
              <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 mb-4">
                <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wide mb-2">
                  Generated Answer
                </p>
                <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{synthText}</p>
              </div>
            )}

            {results.length === 0 ? (
              <p className="text-sm text-gray-500">
                No results found for &ldquo;{q}&rdquo;
              </p>
            ) : (
              <div className="space-y-3">
                {results.map(r => (
                  <ResultCard key={r.requirement_id} result={r} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
