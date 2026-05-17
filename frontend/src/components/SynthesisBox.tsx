interface Props {
  text: string
}

export default function SynthesisBox({ text }: Props) {
  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 mb-4">
      <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wide mb-2">
        Generated Answer
      </p>
      <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{text}</p>
    </div>
  )
}
