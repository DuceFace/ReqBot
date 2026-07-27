import { useState, useEffect } from 'react'
import type { FormEvent, ChangeEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import * as api from '../api/client'
import type { AskResult, DocsEntry } from '../api/types'
import ResultCard from '../components/ResultCard'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import SynthesisBox from '../components/SynthesisBox'
import AppShell from '../components/AppShell'
import { useSynthesis } from '../hooks/useSynthesis'
import { clampTopK, DEFAULT_TOP_K, docValue, MAX_TOP_K, MIN_TOP_K, parseTopKParam } from '../utils/ui'

export default function SearchView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''
  const doc = searchParams.get('doc') ?? ''

  // input tracks the text field; q tracks the committed (URL) query.
  // They diverge while the user is typing a new query.
  const [input, setInput] = useState(q)

  // topK tracks the number input; urlTopK tracks the committed (URL) value.
  // They diverge while the user is editing the field, mirroring EvidenceView's
  // topic/urlQ split (WP-30.2, same pattern WP-29.1 established).
  const urlTopK = parseTopKParam(searchParams.get('top_k'))
  const [topK, setTopK] = useState<number | ''>(urlTopK)

  const [docOptions, setDocOptions] = useState<DocsEntry[]>([])
  const [docLoadError, setDocLoadError] = useState(false)
  const [results, setResults] = useState<AskResult[] | null>(null)
  const [retrievalMs, setRetrievalMs] = useState<number | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Incrementing this triggers a retry without changing q or doc.
  const [retries, setRetries] = useState(0)
  // Fast mode skips the HyDE hypothesis leg (2-leg dense+BM25 RRF instead of 3-leg).
  const [fastMode, setFastMode] = useState(false)

  const synth = useSynthesis()
  const { reset: synthReset } = synth

  // Sync input fields when q/top_k change via browser back/forward.
  useEffect(() => {
    setInput(q)
  }, [q])
  useEffect(() => {
    setTopK(urlTopK)
  }, [urlTopK])

  // Reset synthesis when the committed query, doc filter, result depth, or fast mode changes —
  // toggling fast mode changes the underlying evidence set, so a previously
  // generated answer may no longer match what's on screen.
  useEffect(() => {
    synthReset()
  }, [q, doc, urlTopK, fastMode, synthReset])

  // Load document list once on mount for the filter dropdown.
  useEffect(() => {
    api.docs()
      .then(d => setDocOptions(d.docs))
      .catch(() => { setDocLoadError(true) })
  }, [])

  // Run search whenever the committed query, doc filter, result depth, or retry count changes.
  // A `cancelled` flag prevents stale responses from superseded requests
  // overwriting the UI when the query changes before the previous fetch completes.
  useEffect(() => {
    if (!q) {
      // Reset all search UI — previously only results/retrievalMs were cleared,
      // leaving stale error banners and loading indicators after navigating back.
      setResults(null)
      setRetrievalMs(null)
      setWarnings([])
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
        top_k: urlTopK,
        document_ids: doc ? [doc] : undefined,
        hyde: !fastMode,
      })
      .then(res => {
        if (cancelled) return
        setResults(res.results)
        setRetrievalMs(res.metadata.retrieval_ms)
        setWarnings(res.warnings)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Search failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
    // retries is intentionally included (not referenced in the body) so the
    // retry button can re-run the same query without changing the URL params.
    // Every other dependency this effect actually closes over — q, doc,
    // urlTopK, fastMode — is listed above, so this disable covers only that
    // one deliberate exception, not a genuinely missing dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, doc, urlTopK, fastMode, retries])

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed) return
    const submittedTopK = topK === '' ? DEFAULT_TOP_K : clampTopK(topK)
    const params: Record<string, string> = { q: trimmed, top_k: String(submittedTopK) }
    if (doc) params.doc = doc
    setSearchParams(params)
  }

  function handleGenerateAnswer() {
    if (!q || synth.loading) return
    synth.run(() =>
      api.ask({
        question: q,
        top_k: urlTopK,
        document_ids: doc ? [doc] : undefined,
        synthesize: true,
        hyde: !fastMode,
      }).then(res => res.metadata.synthesis || null)
    )
  }

  function handleDocChange(e: ChangeEvent<HTMLSelectElement>) {
    const newDoc = e.target.value
    // Carry top_k forward -- this previously rebuilt params from scratch with
    // only q/doc, so changing the document filter silently reset result depth
    // back to the default the moment this control existed (Codex review,
    // PR #136).
    const params: Record<string, string> = { top_k: String(urlTopK) }
    if (q) params.q = q
    if (newDoc) params.doc = newDoc
    setSearchParams(params)
  }

  return (
    <AppShell>
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
          <label htmlFor="search-top-k" className="sr-only">
            Result depth
          </label>
          <input
            id="search-top-k"
            type="number"
            min={MIN_TOP_K}
            max={MAX_TOP_K}
            value={topK}
            onChange={e => setTopK(e.target.value === '' ? '' : Number(e.target.value))}
            title="Result depth (number of results to retrieve, 1–100)"
            aria-label="Result depth"
            className="w-20 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
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
              <option key={d.doc_key} value={docValue(d)}>
                {docValue(d)}
              </option>
            ))}
          </select>
          {docLoadError && (
            <p className="mt-1 text-xs text-red-600">Could not load document list.</p>
          )}
          <label className="flex items-center gap-2 mt-2 text-sm text-gray-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={fastMode}
              onChange={e => setFastMode(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Fast mode (skip HyDE)
          </label>
        </div>

        {/* Loading */}
        {loading && <LoadingSpinner />}

        {/* Error */}
        {!loading && error && (
          <ErrorBanner message={error} onRetry={() => setRetries(r => r + 1)} />
        )}

        {/* Results */}
        {!loading && !error && results !== null && (
          <>
            {warnings.length > 0 && (
              <div className="mb-4 rounded border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-800">
                {warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            )}

            <div className="flex items-center justify-between mb-4 text-sm text-gray-500">
              <span>Results ({results.length})</span>
              <div className="flex items-center gap-3">
                {retrievalMs !== null && (
                  <span className="tabular-nums">{retrievalMs.toFixed(0)} ms</span>
                )}
                {results.length > 0 && (
                  synth.loading ? (
                    <button
                      disabled
                      className="bg-gray-100 text-gray-500 cursor-not-allowed px-3 py-1 rounded text-xs font-medium border border-gray-200"
                    >
                      Generating…{synth.elapsed > 0 ? ` ${synth.elapsed}s` : ''}
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
            {synth.error && (
              <div className="mb-4">
                <ErrorBanner message={`Synthesis failed: ${synth.error}`} />
              </div>
            )}

            {/* Synthesis output */}
            {synth.text && <SynthesisBox text={synth.text} />}

            {results.length === 0 ? (
              <p className="text-sm text-gray-500">
                No results found for &ldquo;{q}&rdquo;
              </p>
            ) : (
              <div className="space-y-3">
                {results.map((r, i) => (
                  <ResultCard key={r.requirement_id} result={r} index={i + 1} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </AppShell>
  )
}
