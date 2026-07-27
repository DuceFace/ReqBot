import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseCitations, scrollToCitation } from './SynthesisBox'

describe('parseCitations', () => {
  it('returns a single text segment when there are no citations', () => {
    expect(parseCitations('No citations here.')).toEqual([
      { type: 'text', value: 'No citations here.' },
    ])
  })

  it('extracts a single citation', () => {
    expect(parseCitations('See [1] for details.')).toEqual([
      { type: 'text', value: 'See ' },
      { type: 'citation', index: 1, raw: '[1]' },
      { type: 'text', value: ' for details.' },
    ])
  })

  it('extracts multiple citations, including adjacent ones', () => {
    expect(parseCitations('Per [2][3], and also [10].')).toEqual([
      { type: 'text', value: 'Per ' },
      { type: 'citation', index: 2, raw: '[2]' },
      { type: 'citation', index: 3, raw: '[3]' },
      { type: 'text', value: ', and also ' },
      { type: 'citation', index: 10, raw: '[10]' },
      { type: 'text', value: '.' },
    ])
  })
})

describe('scrollToCitation', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('does nothing when no matching card exists (e.g. a hallucinated citation)', () => {
    expect(() => scrollToCitation(99)).not.toThrow()
  })

  it('scrolls to and briefly highlights the matching card', () => {
    vi.useFakeTimers()
    const el = document.createElement('div')
    el.id = 'citation-3'
    el.scrollIntoView = vi.fn()
    document.body.appendChild(el)

    scrollToCitation(3)

    expect(el.scrollIntoView).toHaveBeenCalled()
    expect(el.classList.contains('ring-2')).toBe(true)

    vi.advanceTimersByTime(1500)
    expect(el.classList.contains('ring-2')).toBe(false)

    vi.useRealTimers()
  })
})
