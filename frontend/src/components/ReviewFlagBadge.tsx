interface Props {
  reasons: string[]
}

export default function ReviewFlagBadge({ reasons }: Props) {
  return (
    <div className="space-y-1">
      <span className="inline-block bg-amber-100 text-amber-800 text-xs font-medium px-2 py-0.5 rounded whitespace-nowrap">
        Review needed
      </span>
      {reasons.length > 0 && (
        <ul className="text-xs text-amber-700 space-y-0.5 pl-0.5">
          {reasons.map(r => (
            <li key={r}>· {r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
