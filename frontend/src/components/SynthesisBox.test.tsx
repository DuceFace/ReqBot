import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import SynthesisBox, { parseCitations, scrollToCitation } from './SynthesisBox'

// vite.config.ts doesn't set test.globals, so @testing-library/react's automatic
// afterEach-based cleanup never registers -- without this, DOM from one render()
// call leaks into the next test in the same file, which only stayed invisible
// pre-WP-32.6 because the two pre-existing tests happened to query for
// differently-numbered citations. New markdown tests below reuse [1]/[2] across
// multiple it() blocks, so unmounting between tests is no longer optional.
afterEach(cleanup)

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

// WP-32.6: SYNTHESIS_PROMPT and _EVIDENCE_AUDITOR_PROMPT produce **bold** and
// '- ' bullet-list markdown; SynthesisBox now renders it instead of showing the
// raw syntax, without breaking WP-31.2's citation-token linking.
describe('SynthesisBox markdown rendering', () => {
  it('renders **bold** text as a <strong> element, not raw asterisks', () => {
    const { container } = render(<SynthesisBox text="**Important:** do the thing." citationCount={0} />)
    const strong = container.querySelector('strong')
    expect(strong).toBeInTheDocument()
    expect(strong).toHaveTextContent('Important:')
    expect(container.textContent).not.toContain('**')
  })

  it('renders a "- " bullet list as real <ul>/<li> elements, not raw dashes', () => {
    const { container } = render(
      <SynthesisBox text={'- First item\n- Second item'} citationCount={0} />
    )
    const items = container.querySelectorAll('ul > li')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('First item')
    expect(items[1]).toHaveTextContent('Second item')
  })

  it('renders a numbered list as real <ol>/<li> elements', () => {
    const { container } = render(
      <SynthesisBox text={'1. First step\n2. Second step'} citationCount={0} />
    )
    expect(container.querySelectorAll('ol > li')).toHaveLength(2)
  })

  it('keeps citation links clickable inside bullet-list items', () => {
    render(<SynthesisBox text={'- Claim one [1]\n- Claim two [2]'} citationCount={2} />)
    expect(screen.getByRole('button', { name: '[1]' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '[2]' })).toBeInTheDocument()
  })

  // A "loose" list (blank line between items, valid CommonMark and plausible LLM
  // output) makes react-markdown wrap each item's content in a nested <p>, a
  // different path than the tight list above. Regression test for a real bug
  // (Gemini, PR #151): the citation-linking recursion didn't recognize a not-yet-
  // rendered <p>/<li> component override (its `type` is a function reference at
  // that point, not the string 'p'/'li'), so it recursed straight through and
  // double-processed the citation, nesting a <button> inside another <button>.
  it('keeps citation links clickable inside a loose list, without nesting buttons', () => {
    const { container } = render(
      <SynthesisBox text={'- Claim one [1]\n\n- Claim two [2]'} citationCount={2} />
    )
    expect(screen.getByRole('button', { name: '[1]' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '[2]' })).toBeInTheDocument()
    expect(container.querySelectorAll('button button')).toHaveLength(0)
  })

  it('keeps citation links clickable inside bold text', () => {
    render(<SynthesisBox text="**Finding [1]:** something happened." citationCount={1} />)
    const button = screen.getByRole('button', { name: '[1]' })
    expect(button).toBeInTheDocument()
    // The citation must actually be nested inside the bold element, not just
    // present somewhere on the page -- confirms linkifyCitations recursed into
    // <strong>'s children rather than only handling the <p> level.
    expect(button.closest('strong')).not.toBeNull()
  })

  it('does not render raw HTML from the synthesis text as live elements', () => {
    // LLM-generated text is untrusted; react-markdown is safe by default here
    // only because no HTML-passthrough plugin (e.g. rehype-raw) is registered.
    // This guards against that safety property being silently broken later.
    const { container } = render(
      <SynthesisBox text={'<img src=x onerror="window.__pwned = true">'} citationCount={0} />
    )
    expect(container.querySelector('img')).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })
})
