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
  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 mb-4">
      <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wide mb-2">
        Generated Answer
      </p>
      <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
        {parseCitations(text).map((seg, i) => {
          if (seg.type === 'text') return <span key={i}>{seg.value}</span>
          const hasTarget = seg.index >= 1 && seg.index <= citationCount
          if (!hasTarget) return <span key={i}>{seg.raw}</span>
          return (
            <button
              key={i}
              type="button"
              onClick={() => scrollToCitation(seg.index)}
              className="font-semibold text-emerald-800 hover:underline bg-transparent border-0 p-0 cursor-pointer"
            >
              {seg.raw}
            </button>
          )
        })}
      </p>
    </div>
  )
}
