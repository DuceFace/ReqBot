/**
 * Returns a formatted page reference string, or null if no page data.
 * Accepts null as well as undefined -- callers like EvidenceRequirement's
 * page_start/page_end can carry an explicit null from the backend, not just
 * an absent key (PR #139). The `== null` checks below already treat both the
 * same way; only the signature needed widening to match.
 */
export function pageRange(start?: number | null, end?: number | null): string | null {
  if (start == null) return null
  if (end != null && end !== start) return `pp. ${start}–${end}`
  return `p. ${start}`
}

/**
 * Returns the canonical stable identifier for a document entry.
 * Prefers source_pdf (human-readable filename); falls back to doc_key
 * (JSONL stem) for partially-indexed or legacy entries where source_pdf is absent.
 */
export function docValue(doc: { source_pdf?: string; doc_key: string }): string {
  return doc.source_pdf && doc.source_pdf.trim() !== '' ? doc.source_pdf : doc.doc_key
}

/**
 * Joins a section hierarchy breadcrumb (e.g. ["3", "3.2", "3.2.1 Access Control"])
 * into a readable path, or '—' if empty. Shared by ChecklistTable and TraceView
 * (WP-31.1) -- both render the same list[str] hierarchy field from the backend.
 */
export function formatPath(parts: string[]): string {
  return parts.length > 0 ? parts.join(' › ') : '—'
}

// Shared by EvidenceView and SearchView (WP-30.2) -- both need identical
// top_k clamping/URL-parsing, so it lives here once rather than duplicated
// across the two views.
export const MIN_TOP_K = 1
export const MAX_TOP_K = 100
export const DEFAULT_TOP_K = 20

export function clampTopK(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_TOP_K
  return Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, Math.round(value)))
}

export function parseTopKParam(raw: string | null): number {
  if (raw === null || raw.trim() === '') return DEFAULT_TOP_K
  return clampTopK(Number(raw))
}
