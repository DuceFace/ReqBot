import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import * as api from '../api/client'
import type { EvidenceRequirement, EvidenceResponse } from '../api/types'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import SynthesisBox from '../components/SynthesisBox'
import NavBar from '../components/NavBar'
import { useSynthesis } from '../hooks/useSynthesis'
import { pageRange } from '../utils/ui'

// ── Sub-components ────────────────────────────────────────────────────────────

function EvidenceCard({ req, from }: { req: EvidenceRequirement; from: string }) {
  if (!req.requirement_id) return null
  const text = req.source_quote || req.description || ''
  const snippet = text.length > 220 ? text.slice(0, 220) + '…' : text
  const pages = pageRange(req.page_start, req.page_end)

  return (
    <Link
      to={`/trace/${encodeURIComponent(req.requirement_id)}`}
      state={{ from }}
      className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition-all no-underline"
    >
      <div className="flex items-center justify-between mb-1.5 gap-4">
        <span className="font-mono text-xs font-semibold text-blue-700 truncate">
          {req.requirement_id}
        </span>
        <div className="flex items-center gap-3 text-xs text-gray-400 shrink-0">
          {req.source_pdf && <span>{req.source_pdf}</span>}
          {pages && <span>{pages}</span>}
        </div>
      </div>
      {snippet && (
        <p className="text-sm text-gray-700 leading-snug">{snippet}</p>
      )}
      {req.source_ref && (
        <p className="mt-1.5 text-xs text-gray-400 truncate">{req.source_ref}</p>
      )}
    </Link>
  )
}

// ── Main view ─────────────────────────────────────────────────────────────────

export default function EvidenceView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  const urlQ = searchParams.get('q') ?? ''
  const [topic, setTopic] = useState(urlQ)

  const [data, setData] = useState<EvidenceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const synth = useSynthesis()
  const { reset: synthReset } = synth

  // Sync input with URL on browser back/forward
  useEffect(() => { setTopic(urlQ) }, [urlQ])

  // Reset synthesis when topic changes
  useEffect(() => { synthReset() }, [urlQ, synthReset])

  // Run evidence map whenever URL param changes
  useEffect(() => {
    if (!urlQ) {
      setData(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .evidence({ topic: urlQ, top_k: 20 })
      .then(res => {
        if (cancelled) return
        setData(res)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Evidence map failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [urlQ])

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = topic.trim()
    if (!trimmed) return
    setSearchParams({ q: trimmed })
  }

  function handleGenerateAnswer() {
    if (!urlQ || synth.loading) return
    synth.run(() =>
      api.evidence({ topic: urlQ, top_k: 20, synthesize: true })
        .then(res => res.synthesis_text || null)
    )
  }

  const fromPath = location.pathname + location.search

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Map form */}
        <form onSubmit={handleSubmit} className="flex gap-2 mb-8">
          <input
            type="text"
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="Topic or control area (e.g. encryption at rest, multi-factor authentication)"
            className="flex-1 border border-gray-300 rounded px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={!topic.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-5 py-2 rounded text-sm font-medium transition-colors"
          >
            Map
          </button>
        </form>

        {/* Loading */}
        {loading && <LoadingSpinner />}

        {/* Error */}
        {!loading && error && <ErrorBanner message={error} />}

        {/* Results */}
        {!loading && !error && data && (
          <>
            {/* Summary + Generate Answer */}
            <div className="flex items-center justify-between mb-6">
              <p className="text-sm text-gray-500">
                {data.total_sources} requirement{data.total_sources !== 1 ? 's' : ''} across{' '}
                {data.group_order.length} group{data.group_order.length !== 1 ? 's' : ''} for &ldquo;{urlQ}&rdquo;
              </p>
              {synth.loading ? (
                <button
                  disabled
                  className="bg-gray-100 text-gray-500 cursor-not-allowed px-4 py-1.5 rounded text-sm font-medium border border-gray-200"
                >
                  Generating…{synth.elapsed > 0 ? ` ${synth.elapsed}s` : ''}
                </button>
              ) : (
                <button
                  onClick={handleGenerateAnswer}
                  disabled={data.group_order.length === 0}
                  className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-4 py-1.5 rounded text-sm font-medium transition-colors"
                >
                  Generate Answer
                </button>
              )}
            </div>

            {/* Synthesis error */}
            {synth.error && (
              <div className="mb-6">
                <ErrorBanner message={`Synthesis failed: ${synth.error}`} />
              </div>
            )}

            {/* Synthesis output */}
            {synth.text && (
              <div className="mb-6">
                <SynthesisBox text={synth.text} />
              </div>
            )}

            {/* Empty state */}
            {data.group_order.length === 0 ? (
              <p className="text-sm text-gray-500">
                No evidence groups found for &ldquo;{urlQ}&rdquo;.
              </p>
            ) : (
              <div className="space-y-6">
                {data.group_order.map(ref => {
                  const group = data.groups[ref]
                  if (!group) return null
                  return (
                    <section key={ref}>
                      <div className="flex items-center gap-2 mb-2">
                        <h2 className="text-sm font-semibold text-gray-700 truncate">
                          {ref}
                        </h2>
                        <span className="text-xs text-gray-400 shrink-0">
                          ({group.sources.length} source{group.sources.length !== 1 ? 's' : ''})
                        </span>
                      </div>
                      <EvidenceCard req={group.representative} from={fromPath} />
                    </section>
                  )
                })}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
