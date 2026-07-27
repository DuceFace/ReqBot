import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import * as api from '../api/client'
import type { EvidenceRequirement, EvidenceResponse } from '../api/types'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import SynthesisBox from '../components/SynthesisBox'
import AppShell from '../components/AppShell'
import { useSynthesis } from '../hooks/useSynthesis'
import {
  pageRange, clampTopK, parseTopKParam, MIN_TOP_K, MAX_TOP_K, DEFAULT_TOP_K,
} from '../utils/ui'

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

  // topK tracks the number input; urlTopK tracks the committed (URL) value.
  // They diverge while the user is editing the field, mirroring how topic/urlQ work.
  const urlTopK = parseTopKParam(searchParams.get('top_k'))
  const [topK, setTopK] = useState<number | ''>(urlTopK)

  const [data, setData] = useState<EvidenceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // "Show all sources" is pure local UI state -- group.sources is already fully populated
  // regardless of show_context, no fetch needed.
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set())

  // Context is fetched once, lazily, on the first "Show source context" click for any group
  // (evidence_service.build() batches context for every group representative in one call --
  // there's no per-group endpoint -- so the first click fetches all of them, and each group's
  // reveal button independently controls only whether its own panel is visible).
  const [contextByRef, setContextByRef] = useState<Record<string, string | null> | null>(null)
  const [contextLoading, setContextLoading] = useState(false)
  const [contextError, setContextError] = useState(false)
  const [expandedContext, setExpandedContext] = useState<Set<string>>(new Set())

  const synth = useSynthesis()
  const { reset: synthReset } = synth

  // Kept in sync with the current search on every render. Used to discard a context-fetch
  // response that arrives after the user has already moved on to a different topic/depth
  // (Codex + Gemini review, PR #131) -- mirrors TraceView.tsx's reqIdRef pattern.
  const searchKeyRef = useRef('')
  searchKeyRef.current = `${urlQ} ${urlTopK}`

  // Sync input with URL on browser back/forward
  useEffect(() => { setTopic(urlQ) }, [urlQ])
  useEffect(() => { setTopK(urlTopK) }, [urlTopK])

  // Reset synthesis and per-group expand/context state when topic or result depth changes --
  // otherwise a stale answer or stale context from a previous search stays displayed against a
  // since-changed evidence set (Codex review, PR #130, applied here too for the same reason).
  useEffect(() => {
    synthReset()
    setExpandedSources(new Set())
    setContextByRef(null)
    setContextLoading(false)
    setContextError(false)
    setExpandedContext(new Set())
  }, [urlQ, urlTopK, synthReset])

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
      .evidence({ topic: urlQ, top_k: urlTopK })
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
  }, [urlQ, urlTopK])

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = topic.trim()
    if (!trimmed) return
    const submittedTopK = topK === '' ? DEFAULT_TOP_K : clampTopK(topK)
    setSearchParams({ q: trimmed, top_k: String(submittedTopK) })
  }

  function handleGenerateAnswer() {
    if (!urlQ || synth.loading) return
    // Retrieval here can differ from what's currently displayed (e.g. HyDE's
    // nondeterministic hypothesis leg), and the synthesis text's [N] citations are
    // numbered against THIS fetch's group_order -- so the displayed groups must be
    // replaced with it, or clicking a citation can silently land on an unrelated
    // requirement (Codex review, PR #142). Guarded by the existing searchKeyRef so a
    // stale response (topic/depth changed while this was in flight) can't clobber a
    // newer, correct result set.
    const requestKey = searchKeyRef.current
    synth.run(() =>
      api.evidence({ topic: urlQ, top_k: urlTopK, synthesize: true })
        .then(res => {
          if (searchKeyRef.current === requestKey) setData(res)
          return res.synthesis_text || null
        })
    )
  }

  function toggleSources(ref: string) {
    setExpandedSources(prev => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }

  function handleShowContext(ref: string) {
    if (contextByRef !== null) {
      // Already fetched for this search -- just reveal this group's panel.
      setExpandedContext(prev => new Set(prev).add(ref))
      return
    }
    if (contextLoading) return
    const requestKey = searchKeyRef.current
    setContextLoading(true)
    setContextError(false)
    api
      .evidence({ topic: urlQ, top_k: urlTopK, show_context: true })
      .then(res => {
        if (searchKeyRef.current !== requestKey) return // superseded by a newer search
        const byRef: Record<string, string | null> = {}
        for (const r of res.group_order) {
          byRef[r] = res.groups[r]?.context_text ?? null
        }
        setContextByRef(byRef)
        setExpandedContext(prev => new Set(prev).add(ref))
      })
      .catch(() => {
        if (searchKeyRef.current !== requestKey) return
        setContextError(true)
      })
      .finally(() => {
        if (searchKeyRef.current === requestKey) setContextLoading(false)
      })
  }

  function hideContext(ref: string) {
    setExpandedContext(prev => {
      const next = new Set(prev)
      next.delete(ref)
      return next
    })
  }

  const fromPath = location.pathname + location.search

  return (
    <AppShell>
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
          <label htmlFor="evidence-top-k" className="sr-only">
            Result depth
          </label>
          <input
            id="evidence-top-k"
            type="number"
            min={MIN_TOP_K}
            max={MAX_TOP_K}
            value={topK}
            onChange={e => setTopK(e.target.value === '' ? '' : Number(e.target.value))}
            title="Result depth (number of sources to retrieve, 1–100)"
            aria-label="Result depth"
            className="w-20 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                <SynthesisBox text={synth.text} citationCount={data.group_order.length} />
              </div>
            )}

            {/* Empty state */}
            {data.group_order.length === 0 ? (
              <p className="text-sm text-gray-500">
                No evidence groups found for &ldquo;{urlQ}&rdquo;.
              </p>
            ) : (
              <div className="space-y-6">
                {data.group_order.map((ref, i) => {
                  const group = data.groups[ref]
                  if (!group) return null
                  const sourcesShown = expandedSources.has(ref)
                  const contextShown = expandedContext.has(ref) && contextByRef !== null
                  return (
                    // id/number match the [N] citation core/ask.py's evidence_service.py
                    // already uses for synthesis input, via group_order's position (WP-31.2).
                    // One number per group, not per individual source row.
                    <section key={ref} id={`citation-${i + 1}`} className="rounded-lg transition-shadow">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-gray-100 text-gray-500 text-[11px] font-semibold tabular-nums">
                          {i + 1}
                        </span>
                        <h2 className="text-sm font-semibold text-gray-700 truncate">
                          {ref}
                        </h2>
                        <span className="text-xs text-gray-400 shrink-0">
                          ({group.sources.length} source{group.sources.length !== 1 ? 's' : ''})
                        </span>
                      </div>

                      {sourcesShown ? (
                        <div className="space-y-2">
                          {group.sources.map((src, i) => (
                            <EvidenceCard key={src.requirement_id || i} req={src} from={fromPath} />
                          ))}
                        </div>
                      ) : (
                        <EvidenceCard req={group.representative} from={fromPath} />
                      )}

                      {group.sources.length > 1 && (
                        <button
                          onClick={() => toggleSources(ref)}
                          className="mt-1.5 text-xs text-blue-600 underline hover:no-underline"
                        >
                          {sourcesShown ? 'Show fewer sources' : `Show all ${group.sources.length} sources`}
                        </button>
                      )}

                      <div className="mt-2">
                        {contextShown ? (
                          <>
                            <pre className="text-xs text-gray-600 bg-gray-100 rounded p-3 whitespace-pre-wrap leading-relaxed overflow-x-auto">
                              {contextByRef?.[ref] || '(no context available)'}
                            </pre>
                            <button
                              onClick={() => hideContext(ref)}
                              className="mt-1.5 text-xs text-blue-600 underline hover:no-underline"
                            >
                              Hide source context
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => handleShowContext(ref)}
                              disabled={contextLoading}
                              className="text-sm text-blue-600 underline hover:no-underline disabled:opacity-50"
                            >
                              {contextLoading ? 'Loading…' : 'Show source context'}
                            </button>
                            {contextError && (
                              <p className="mt-1 text-xs text-red-600">
                                Failed to load context. Try again.
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    </section>
                  )
                })}
              </div>
            )}
          </>
        )}
      </main>
    </AppShell>
  )
}
