import { Children, cloneElement, isValidElement, useMemo, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'

export type SynthesisSegment =
  | { type: 'text'; value: string }
  | { type: 'citation'; index: number; raw: string }

const CITATION_PATTERN = /(\[\d+\])/g

/** Splits synthesis text into plain-text and citation segments (WP-31.2). */
export function parseCitations(text: string): SynthesisSegment[] {
  return text
    .split(CITATION_PATTERN)
    .filter(part => part !== '')
    .map(part => {
      const match = /^\[(\d+)\]$/.exec(part)
      return match
        ? { type: 'citation' as const, index: Number(match[1]), raw: part }
        : { type: 'text' as const, value: part }
    })
}

/**
 * Scrolls to and briefly highlights the result/evidence card matching a citation
 * number. Ids are assigned as citation-{n} by ResultCard and EvidenceView's group
 * sections, matching the [N] order core/ask.py and evidence_service.py already use
 * for synthesis input (WP-31.2). No-ops if the LLM cited a number with no matching
 * card (e.g. a hallucinated out-of-range citation) rather than throwing -- the
 * backend's own numbering always matches the returned results/group_order array,
 * so this can only happen from the LLM's output, not a backend ordering bug.
 */
export function scrollToCitation(n: number): void {
  const el = document.getElementById(`citation-${n}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('ring-2', 'ring-amber-400')
  window.setTimeout(() => el.classList.remove('ring-2', 'ring-amber-400'), 1500)
}

function renderSegment(seg: SynthesisSegment, key: string, citationCount: number): ReactNode {
  if (seg.type === 'text') return <span key={key}>{seg.value}</span>
  const hasTarget = seg.index >= 1 && seg.index <= citationCount
  if (!hasTarget) return <span key={key}>{seg.raw}</span>
  return (
    <button
      key={key}
      type="button"
      onClick={() => scrollToCitation(seg.index)}
      className="font-semibold text-emerald-800 hover:underline bg-transparent border-0 p-0 cursor-pointer"
    >
      {seg.raw}
    </button>
  )
}

/**
 * Walks react-markdown's rendered children, splitting every plain-text leaf into
 * citation-aware segments (WP-31.2's [N] linking) while leaving markdown elements
 * (e.g. <strong>) structurally intact -- a citation can land inside or outside
 * bold text (SYNTHESIS_PROMPT's own rule 2 puts one right after a bolded label in
 * practice), so this recurses into element children rather than only handling the
 * top-level string case.
 */
// ul/ol are plain string-tag elements react-markdown builds directly (no override
// below), so recursing into them just reaches their <li> children -- harmless, but
// skipped anyway since diving in accomplishes nothing.
//
// p/li are NOT plain string-tag elements at the point linkifyCitations first sees
// them as an unresolved child: react-markdown passes them down as
// `{ type: components.p, ... }` / `{ type: components.li, ... }` -- the *function*
// reference, not yet invoked -- and only React's own render pass later calls that
// function to produce a real <p>/<li> DOM element. So `typeof node.type === 'string'`
// never matches a not-yet-rendered p/li, and a naive string-tag-only skip list lets
// linkifyCitations recurse straight through into a nested p/li's raw (unprocessed)
// children -- which get citation-linked once here, then AGAIN when React actually
// invokes that p/li's own override moments later, wrapping an already-built
// <button> in a second <button> (invalid DOM, double click handler). Skipping any
// function-typed element covers this for every current and future component
// override, not just p/li by name (Gemini, PR #151).
//
// button is the element renderSegment() itself produces -- recursing into one
// (e.g. because it survived some other skip-list gap) would re-run parseCitations
// on its own already-final "[N]" text and wrap it in a second button.
function isAlreadyProcessed(type: unknown): boolean {
  if (typeof type === 'function') return true
  return typeof type === 'string' && (type === 'button' || type === 'ul' || type === 'ol')
}

function linkifyCitations(node: ReactNode, citationCount: number, keyPrefix = 'n'): ReactNode {
  if (typeof node === 'string') {
    return parseCitations(node).map((seg, i) => renderSegment(seg, `${keyPrefix}-${i}`, citationCount))
  }
  if (Array.isArray(node)) {
    return node.map((child, i) => linkifyCitations(child, citationCount, `${keyPrefix}-${i}`))
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    if (isAlreadyProcessed(node.type)) {
      return node
    }
    return cloneElement(
      node,
      undefined,
      linkifyCitations(node.props.children, citationCount, keyPrefix)
    )
  }
  return node
}

/**
 * Markdown element overrides, scoped to exactly the syntax SYNTHESIS_PROMPT and
 * _EVIDENCE_AUDITOR_PROMPT actually produce (bold, bullet/numbered lists) --
 * WP-32.6's non-goal is markdown rendering anywhere else, so this isn't trying to
 * be a general-purpose renderer. Only block-level containers (p, li) need the
 * citation-linking override; linkifyCitations recurses into their children, which
 * already reaches nested <strong>/<em> text without a separate override for those.
 *
 * react-markdown does not render raw HTML from the source text by default (no
 * rehype-raw plugin is registered here) -- LLM-generated text staying inert as
 * markdown-only, never live HTML, is the sanitization this WP calls for. Don't
 * add rehype-raw/dangerouslySetInnerHTML without re-deciding that.
 */
function markdownComponents(citationCount: number): Components {
  return {
    p: ({ children }) => <p>{linkifyCitations(Children.toArray(children), citationCount)}</p>,
    li: ({ children }) => <li>{linkifyCitations(Children.toArray(children), citationCount)}</li>,
  }
}

interface Props {
  text: string
  // Number of valid citation targets currently rendered (results.length for Search,
  // group_order.length for Evidence) -- a citation is only clickable if its number
  // falls in [1, citationCount]. Anything outside that range (e.g. an LLM-hallucinated
  // out-of-range citation) renders as plain text instead of a dead-looking, styled
  // button that does nothing on click (Codex review, PR #142).
  citationCount: number
}

export default function SynthesisBox({ text, citationCount }: Props) {
  // react-markdown identifies component overrides by referential identity -- a
  // fresh object/functions every render would make it remount the entire rendered
  // tree (losing any DOM state) on every unrelated re-render of this component,
  // not just when citationCount actually changes (Gemini, PR #151).
  const components = useMemo(() => markdownComponents(citationCount), [citationCount])

  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 mb-4">
      <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wide mb-2">
        Generated Answer
      </p>
      <div
        className="text-sm text-gray-800 leading-relaxed space-y-2
          [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5
          [&_strong]:font-semibold"
      >
        <ReactMarkdown components={components}>{text}</ReactMarkdown>
      </div>
    </div>
  )
}
