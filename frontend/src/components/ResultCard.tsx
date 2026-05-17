import { Link, useLocation } from 'react-router-dom'
import type { AskResult } from '../api/types'
import { pageRange } from '../utils/ui'

interface Props {
  result: AskResult
}

export default function ResultCard({ result }: Props) {
  const location = useLocation()
  const snippet =
    result.description.length > 220
      ? result.description.slice(0, 220) + '…'
      : result.description

  const pages = pageRange(result.page_start, result.page_end)

  return (
    <Link
      to={`/trace/${encodeURIComponent(result.requirement_id)}`}
      // Pass the current search URL so TraceView can render "← Back to search"
      // with the query intact (e.g. /search?q=encryption&doc=AFI-17-101).
      state={{ from: location.search }}
      className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition-all no-underline"
    >
      <div className="flex items-center justify-between mb-1.5 gap-4">
        <span className="font-mono text-xs font-semibold text-blue-700 truncate">
          {result.requirement_id}
        </span>
        <div className="flex items-center gap-3 text-xs text-gray-400 shrink-0">
          <span>{result.document_id}</span>
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
