/** Returns a formatted page reference string, or null if no page data. */
export function pageRange(start?: number, end?: number): string | null {
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
