import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import SynthesisBox, { parseCitations, scrollToCitation } from './SynthesisBox'

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
    vi.useRealTimers()
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
  })
})

// Citations outside [1, citationCount] (e.g. an LLM-hallucinated out-of-range number)
// must render as plain text, not a styled button that no-ops on click (Codex review,
// PR #142) -- this is React's conditional-element-type output, not pure arithmetic,
// so it's verified by rendering rather than by inspecting parseCitations alone.
describe('SynthesisBox citation rendering', () => {
  it('renders an in-range citation as a clickable button', () => {
    render(<SynthesisBox text="See [1] for details." citationCount={3} />)
    expect(screen.getByRole('button', { name: '[1]' })).toBeInTheDocument()
  })

  it('renders an out-of-range citation as plain text, not a button', () => {
    render(<SynthesisBox text="See [5] for details." citationCount={3} />)
    expect(screen.queryByRole('button', { name: '[5]' })).not.toBeInTheDocument()
    expect(screen.getByText('[5]', { exact: false })).toBeInTheDocument()
  })
})
