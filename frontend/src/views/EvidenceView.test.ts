import { describe, expect, it } from 'vitest'
import { clampTopK, parseTopKParam } from './EvidenceView'

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
