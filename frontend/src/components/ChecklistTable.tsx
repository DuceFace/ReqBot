import type { ChecklistItem } from '../api/types'
import ReviewFlagBadge from './ReviewFlagBadge'
import { formatPath } from '../utils/ui'

interface Props {
  items: ChecklistItem[]
}

// ── Cell formatters ───────────────────────────────────────────────────────────

function formatPageRefs(refs: number[]): string {
  if (refs.length === 0) return '—'
  if (refs.length === 1) return `p. ${refs[0]}`
  return `pp. ${refs[0]}–${refs[refs.length - 1]}`
}

function formatList(items: string[]): string {
  return items.length > 0 ? items.join(', ') : '—'
}

// ── Column group headers ──────────────────────────────────────────────────────

const GROUP_HEADER_CLASS =
  'py-2 px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider text-center border-b border-gray-200'

const COL_HEADER_CLASS =
  'py-2 px-3 text-xs font-medium text-gray-500 text-left bg-gray-50 border-b border-gray-200 whitespace-nowrap'

// ── Table ─────────────────────────────────────────────────────────────────────

export default function ChecklistTable({ items }: Props) {
  return (
    <div className="overflow-x-auto rounded border border-gray-200 [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-track]:bg-gray-100 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 hover:[&::-webkit-scrollbar-thumb]:bg-gray-400">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          {/* Group header row */}
          <tr className="bg-gray-100 border-b border-gray-200">
            <th scope="colgroup" colSpan={3} className={`${GROUP_HEADER_CLASS} border-r border-gray-300`}>
              Locate
            </th>
            <th scope="colgroup" colSpan={2} className={`${GROUP_HEADER_CLASS} border-r border-gray-300`}>
              Ask
            </th>
            <th scope="colgroup" colSpan={2} className={`${GROUP_HEADER_CLASS} border-r border-gray-300`}>
              Record
            </th>
            <th scope="colgroup" colSpan={3} className={`${GROUP_HEADER_CLASS} border-r border-gray-300`}>
              Verify
            </th>
            <th scope="colgroup" colSpan={3} className={GROUP_HEADER_CLASS}>
              Trace
            </th>
          </tr>
          {/* Column header row */}
          <tr>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[100px]`}>Ref</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[160px]`}>Section</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[72px] border-r border-gray-200`}>Pages</th>

            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[220px]`}>Source quote</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[140px] border-r border-gray-200`}>Audit question</th>

            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[100px]`}>Status</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[140px] border-r border-gray-200`}>Notes</th>

            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[110px]`}>Flag</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[120px]`}>Reasons</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[72px] border-r border-gray-200`}>Conf.</th>

            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[170px]`}>Item ID</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[130px]`}>Req IDs</th>
            <th scope="col" className={`${COL_HEADER_CLASS} min-w-[120px]`}>Tags</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const flagged = item.requires_human_review
            const rowBg = flagged ? 'bg-amber-50' : idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
            const cell = `py-3 px-3 text-gray-700 align-top ${rowBg}`
            const borderR = `${cell} border-r border-gray-200`

            return (
              <tr key={item.checklist_item_id} className="border-b border-gray-100 last:border-b-0">
                {/* Locate */}
                <td className={cell}>{item.source_ref || '—'}</td>
                <td className={cell}>{formatPath(item.section_title_path)}</td>
                <td className={`${borderR} whitespace-nowrap`}>{formatPageRefs(item.page_refs)}</td>

                {/* Ask */}
                <td className={cell}>
                  {item.source_quote
                    ? <span className="break-words">{item.source_quote}</span>
                    : <span className="break-words text-amber-700 font-medium">[MISSING SOURCE QUOTE]</span>}
                </td>
                <td className={`${borderR}`}>
                  {item.audit_question || <span className="text-gray-400">—</span>}
                </td>

                {/* Record */}
                <td className={cell}>{item.status || '—'}</td>
                <td className={`${borderR}`}>
                  {item.assessor_notes || <span className="text-gray-400">—</span>}
                </td>

                {/* Verify */}
                <td className={cell}>
                  {flagged ? (
                    <ReviewFlagBadge reasons={item.review_reasons} />
                  ) : (
                    <span className="text-gray-300">—</span>
                  )}
                </td>
                <td className={cell}>
                  {item.review_reasons.length > 0
                    ? formatList(item.review_reasons)
                    : <span className="text-gray-400">—</span>}
                </td>
                <td className={`${borderR} whitespace-nowrap tabular-nums`}>
                  {(item.confidence * 100).toFixed(0)}%
                </td>

                {/* Trace */}
                <td className={`${cell} font-mono text-xs`}>{item.checklist_item_id}</td>
                <td className={cell}>{formatList(item.requirement_ids)}</td>
                <td className={cell}>{formatList(item.domain_tags)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
