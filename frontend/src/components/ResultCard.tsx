import { Link, useLocation } from 'react-router-dom'
import type { AskResult } from '../api/types'
import { pageRange } from '../utils/ui'

interface Props {
  result: AskResult
  // 1-indexed position in SearchView's results array -- matches the [N] citation
  // numbering core/ask.py::format_evidence() already uses for synthesis input
  // (WP-31.2). Also doubles as this card's `citation-{index}` DOM id.
  index: number
}

export default function ResultCard({ result, index }: Props) {
  const location = useLocation()
  const text = result.source_quote || result.description
  const snippet = text.length > 220 ? text.slice(0, 220) + '…' : text

  const pages = pageRange(result.page_start, result.page_end)

  return (
    <Link
      id={`citation-${index}`}
      to={`/trace/${encodeURIComponent(result.requirement_id)}`}
      // Pass the current search URL so TraceView can render "← Back to search"
      // with the query intact (e.g. /search?q=encryption&doc=AFI-17-101).
      state={{ from: location.pathname + location.search }}
      className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition-all no-underline"
    >
      <div className="flex items-center justify-between mb-1.5 gap-4">
        <div className="flex items-center gap-2 min-w-0">
          <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-gray-100 text-gray-500 text-[11px] font-semibold tabular-nums">
            {index}
          </span>
          <span className="font-mono text-xs font-semibold text-blue-700 truncate">
            {result.requirement_id}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400 shrink-0">
          <span>{result.source_pdf}</span>
          {pages && <span>{pages}</span>}
          <span className="font-medium text-gray-600 tabular-nums">
            {result.score.toFixed(3)}
          </span>
        </div>
      </div>
      <p className="text-sm text-gray-700 leading-snug">{snippet}</p>
      {result.source_ref && (
        <p className="mt-1.5 text-xs text-gray-400 truncate">{result.source_ref}</p>
      )}
    </Link>
  )
}
