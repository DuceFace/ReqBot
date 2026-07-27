import { describe, expect, it } from 'vitest'
import { docValue, pageRange } from './ui'

describe('pageRange', () => {
  it('returns null when start is missing', () => {
    expect(pageRange(undefined, undefined)).toBeNull()
    expect(pageRange(undefined, 5)).toBeNull()
  })

  it('formats a single page when end is missing or equal to start', () => {
    expect(pageRange(3, undefined)).toBe('p. 3')
    expect(pageRange(3, 3)).toBe('p. 3')
  })

  it('formats a range when end differs from start', () => {
    expect(pageRange(3, 7)).toBe('pp. 3–7')
  })

  it('treats start 0 as present, not missing', () => {
    // `start == null` only catches null/undefined -- 0 is a valid page number
    // and must not be misread as "no page data" via falsy coercion.
    expect(pageRange(0, undefined)).toBe('p. 0')
  })
})

describe('docValue', () => {
  it('prefers source_pdf when present and non-blank', () => {
    expect(docValue({ source_pdf: 'afi17-101.pdf', doc_key: 'afi17-101' })).toBe('afi17-101.pdf')
  })

  it('falls back to doc_key when source_pdf is absent', () => {
    expect(docValue({ doc_key: 'afi17-101' })).toBe('afi17-101')
  })

  it('falls back to doc_key when source_pdf is blank/whitespace-only', () => {
    expect(docValue({ source_pdf: '', doc_key: 'afi17-101' })).toBe('afi17-101')
    expect(docValue({ source_pdf: '   ', doc_key: 'afi17-101' })).toBe('afi17-101')
  })
})
