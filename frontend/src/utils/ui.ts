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
