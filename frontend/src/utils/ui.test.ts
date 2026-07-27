import { describe, expect, it } from 'vitest'
import { clampTopK, docValue, pageRange, parseTopKParam } from './ui'

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

// clampTopK/parseTopKParam originated in EvidenceView.tsx (WP-29.1, tested in WP-30.1) and were
// relocated here as shared code once SearchView needed the same logic (WP-30.2) -- these tests
// moved along with the functions.
describe('clampTopK', () => {
  it('passes through values already in range', () => {
    expect(clampTopK(1)).toBe(1)
    expect(clampTopK(20)).toBe(20)
    expect(clampTopK(100)).toBe(100)
  })

  it('clamps below the minimum up to 1', () => {
    expect(clampTopK(0)).toBe(1)
    expect(clampTopK(-5)).toBe(1)
  })

  it('clamps above the maximum down to 100', () => {
    expect(clampTopK(101)).toBe(100)
    expect(clampTopK(9999)).toBe(100)
  })

  it('rounds non-integer values', () => {
    expect(clampTopK(20.4)).toBe(20)
    expect(clampTopK(20.5)).toBe(21)
  })

  it('falls back to the default for non-finite input', () => {
    expect(clampTopK(NaN)).toBe(20)
    expect(clampTopK(Infinity)).toBe(20)
    expect(clampTopK(-Infinity)).toBe(20)
  })
})

describe('parseTopKParam', () => {
  it('returns the default for null or blank input', () => {
    expect(parseTopKParam(null)).toBe(20)
    expect(parseTopKParam('')).toBe(20)
    expect(parseTopKParam('   ')).toBe(20)
  })

  it('parses and clamps a valid numeric string', () => {
    expect(parseTopKParam('50')).toBe(50)
    expect(parseTopKParam('0')).toBe(1)
    expect(parseTopKParam('500')).toBe(100)
  })

  it('falls back to the default for a non-numeric string', () => {
    // Number('abc') is NaN, which clampTopK's Number.isFinite guard catches.
    expect(parseTopKParam('abc')).toBe(20)
  })
})
