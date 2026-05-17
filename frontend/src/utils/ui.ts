/** Returns a formatted page reference string, or null if no page data. */
export function pageRange(start?: number, end?: number): string | null {
  if (start == null) return null
  if (end != null && end !== start) return `pp. ${start}–${end}`
  return `p. ${start}`
}
