import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import * as api from '../api/client'
import type { ComparePayload, CompareResponse, DocsEntry } from '../api/types'
import LoadingSpinner from '../components/LoadingSpinner'
import NavBar from '../components/NavBar'

// ── Result-splitting logic ────────────────────────────────────────────────────

interface BothItem {
  ref: string
  p1: ComparePayload
  p2: ComparePayload
}

interface SingleItem {
  ref: string
  payload: ComparePayload
}

interface SplitResult {
  both: BothItem[]
  doc1Only: SingleItem[]
  doc2Only: SingleItem[]
}

function splitResult(res: CompareResponse): SplitResult {
  const { doc_pdf_1, doc_pdf_2 } = res

  if (res.mode === 'exact') {
    const p1 = res.groups[doc_pdf_1]
    const p2 = res.groups[doc_pdf_2]
    if (p1 && p2) return { both: [{ ref: res.source_ref, p1, p2 }], doc1Only: [], doc2Only: [] }
    if (p1) return { both: [], doc1Only: [{ ref: res.source_ref, payload: p1 }], doc2Only: [] }
    if (p2) return { both: [], doc1Only: [], doc2Only: [{ ref: res.source_ref, payload: p2 }] }
    return { both: [], doc1Only: [], doc2Only: [] }
  }

  const both: BothItem[] = []
  const doc1Only: SingleItem[] = []
  const doc2Only: SingleItem[] = []

  for (const ref of res.ref_order) {
    const group = res.ref_groups[ref]
    const p1 = group[doc_pdf_1]
    const p2 = group[doc_pdf_2]
    if (p1 && p2) {
      both.push({ ref, p1, p2 })
    } else if (p1) {
      doc1Only.push({ ref, payload: p1 })
    } else if (p2) {
      doc2Only.push({ ref, payload: p2 })
    }
  }

  return { both, doc1Only, doc2Only }
}

// ── Card components ───────────────────────────────────────────────────────────

function snippet(text: string, max = 220): string {
  return text.length > max ? text.slice(0, max) + '…' : text
}

function BothCard({ item, from }: { item: BothItem; from: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-mono text-xs text-gray-500">{item.ref}</span>
        <span className="text-xs text-green-700 bg-green-50 rounded px-1.5 py-0.5 font-medium">
          in both
        </span>
      </div>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Link
          to={`/trace/${encodeURIComponent(item.p1.requirement_id)}`}
          state={{ from }}
          className="font-mono text-xs font-semibold text-blue-700 hover:underline truncate max-w-xs"
        >
          {item.p1.requirement_id}
        </Link>
        <span className="text-xs text-gray-400 shrink-0">↔</span>
        <Link
          to={`/trace/${encodeURIComponent(item.p2.requirement_id)}`}
          state={{ from }}
          className="font-mono text-xs font-semibold text-blue-700 hover:underline truncate max-w-xs"
        >
          {item.p2.requirement_id}
        </Link>
      </div>
      <p className="text-sm text-gray-700 leading-snug">
        {snippet(item.p1.description)}
      </p>
    </div>
  )
}

function SingleCard({ item, from }: { item: SingleItem; from: string }) {
  return (
    <Link
      to={`/trace/${encodeURIComponent(item.payload.requirement_id)}`}
      state={{ from }}
      className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition-all no-underline"
    >
      <div className="flex items-center justify-between mb-1.5 gap-4">
        <span className="font-mono text-xs font-semibold text-blue-700 truncate">
          {item.payload.requirement_id}
        </span>
        {item.payload.confidence != null && (
          <span className="text-xs text-gray-400 shrink-0 tabular-nums">
            {item.payload.confidence.toFixed(3)}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-700 leading-snug">
        {snippet(item.payload.description)}
      </p>
      {item.ref && (
        <p className="mt-1.5 text-xs text-gray-400 truncate">{item.ref}</p>
      )}
    </Link>
  )
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <h2 className="text-sm font-semibold text-gray-700 mb-3">
      {label}{' '}
      <span className="text-gray-400 font-normal">({count})</span>
    </h2>
  )
}

// ── Main view ─────────────────────────────────────────────────────────────────

export default function CompareView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  // URL-driven committed values
  const urlDoc1 = searchParams.get('doc1') ?? ''
  const urlDoc2 = searchParams.get('doc2') ?? ''
  const urlQ = searchParams.get('q') ?? ''

  // Local input state (what the form controls show)
  const [doc1, setDoc1] = useState(urlDoc1)
  const [doc2, setDoc2] = useState(urlDoc2)
  const [topic, setTopic] = useState(urlQ)

  const [docOptions, setDocOptions] = useState<DocsEntry[]>([])
  const [result, setResult] = useState<CompareResponse | null>(null)
  const [split, setSplit] = useState<SplitResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Keep inputs in sync with URL (browser back/forward)
  useEffect(() => { setDoc1(urlDoc1) }, [urlDoc1])
  useEffect(() => { setDoc2(urlDoc2) }, [urlDoc2])
  useEffect(() => { setTopic(urlQ) }, [urlQ])

  // Load document list once on mount
  useEffect(() => {
    api.docs().then(d => setDocOptions(d.docs)).catch(() => { /* silent */ })
  }, [])

  // Run compare whenever URL params change and all three are present
  useEffect(() => {
    if (!urlDoc1 || !urlDoc2 || !urlQ) {
      setResult(null)
      setSplit(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .compare({ doc_id_1: urlDoc1, doc_id_2: urlDoc2, topic: urlQ, top_k: 20 })
      .then(res => {
        if (cancelled) return
        setResult(res)
        setSplit(splitResult(res))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Compare failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [urlDoc1, urlDoc2, urlQ])

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmedQ = topic.trim()
    if (!doc1 || !doc2 || !trimmedQ || doc1 === doc2) return
    setSearchParams({ doc1, doc2, q: trimmedQ })
  }

  const sameDoc = doc1 !== '' && doc1 === doc2
  const canSubmit = doc1 !== '' && doc2 !== '' && topic.trim() !== '' && !sameDoc
  // Full path string passed to trace cards so back-nav returns here
  const fromPath = location.pathname + location.search
  const totalCount = split ? split.both.length + split.doc1Only.length + split.doc2Only.length : 0

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Compare form */}
        <form onSubmit={handleSubmit} className="space-y-3 mb-8">
          <div className="flex gap-3 flex-wrap">
            <div className="flex-1 min-w-[180px]">
              <label className="block text-xs text-gray-500 mb-1" htmlFor="doc1-select">
                Document 1
              </label>
              <select
                id="doc1-select"
                value={doc1}
                onChange={e => setDoc1(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select document…</option>
                {docOptions.map(d => (
                  <option key={d.doc_key} value={d.doc_key}>
                    {d.doc_key}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1 min-w-[180px]">
              <label className="block text-xs text-gray-500 mb-1" htmlFor="doc2-select">
                Document 2
              </label>
              <select
                id="doc2-select"
                value={doc2}
                onChange={e => setDoc2(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select document…</option>
                {docOptions.map(d => (
                  <option key={d.doc_key} value={d.doc_key}>
                    {d.doc_key}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {sameDoc && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
              Document 1 and Document 2 must be different.
            </p>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="Topic or control ID (e.g. multi-factor authentication, IA-5)"
              className="flex-1 border border-gray-300 rounded px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={!canSubmit}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-5 py-2 rounded text-sm font-medium transition-colors"
            >
              Compare
            </button>
          </div>
        </form>

        {/* Loading */}
        {loading && <LoadingSpinner />}

        {/* Error */}
        {!loading && error && (
          <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Results */}
        {!loading && !error && split !== null && (
          <>
            <div className="mb-6 text-sm text-gray-500">
              {totalCount === 0
                ? `No results for "${urlQ}"`
                : `${totalCount} result${totalCount !== 1 ? 's' : ''} for "${urlQ}"`}
              {result && (
                <span className="ml-2 text-gray-400">
                  · {result.mode === 'exact' ? 'exact match' : 'semantic'}
                </span>
              )}
            </div>

            {/* Both docs */}
            {split.both.length > 0 && (
              <section className="mb-8">
                <SectionHeader
                  label={`In both documents`}
                  count={split.both.length}
                />
                <div className="space-y-3">
                  {split.both.map((item, i) => (
                    <BothCard key={`both-${i}`} item={item} from={fromPath} />
                  ))}
                </div>
              </section>
            )}

            {/* Doc 1 only */}
            {split.doc1Only.length > 0 && (
              <section className="mb-8">
                <SectionHeader
                  label={`From ${urlDoc1} only`}
                  count={split.doc1Only.length}
                />
                <div className="space-y-3">
                  {split.doc1Only.map((item, i) => (
                    <SingleCard key={`d1-${i}`} item={item} from={fromPath} />
                  ))}
                </div>
              </section>
            )}

            {/* Doc 2 only */}
            {split.doc2Only.length > 0 && (
              <section className="mb-8">
                <SectionHeader
                  label={`From ${urlDoc2} only`}
                  count={split.doc2Only.length}
                />
                <div className="space-y-3">
                  {split.doc2Only.map((item, i) => (
                    <SingleCard key={`d2-${i}`} item={item} from={fromPath} />
                  ))}
                </div>
              </section>
            )}

            {/* Empty state */}
            {totalCount === 0 && (
              <p className="text-sm text-gray-500">
                No requirements matched &ldquo;{urlQ}&rdquo; in either document.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  )
}
