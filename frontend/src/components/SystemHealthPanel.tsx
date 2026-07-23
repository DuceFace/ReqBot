import type { StatusResponse } from '../api/types'

interface Props {
  data: StatusResponse
}

function StatusRow({ name, ok, detail }: { name: string; ok: boolean; detail?: string }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-gray-100 last:border-0">
      <span
        className={`mt-0.5 w-2.5 h-2.5 rounded-full shrink-0 ${ok ? 'bg-green-500' : 'bg-red-500'}`}
      />
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-900">{name}</p>
        {detail && <p className="text-xs text-gray-400 mt-0.5">{detail}</p>}
      </div>
      <span className={`ml-auto text-xs font-medium shrink-0 ${ok ? 'text-green-600' : 'text-red-600'}`}>
        {ok ? 'OK' : 'DOWN'}
      </span>
    </div>
  )
}

export default function SystemHealthPanel({ data }: Props) {
  const modelList = data.ollama.models.length > 0
    ? data.ollama.models.map(m => `${m.name} (${m.size_gb.toFixed(1)} GB)`).join(', ')
    : 'no models loaded'

  const collectionList = data.qdrant.collections.length > 0
    ? data.qdrant.collections.map(c => `${c.name}: ${c.points} pts`).join(', ')
    : 'no collections'

  const docCount = data.processed_documents.length

  return (
    <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
      <div className="px-5 py-3 bg-gray-50 rounded-t-lg">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Services</p>
      </div>
      <div className="px-5">
        <StatusRow
          name="Ollama"
          ok={data.ollama.reachable}
          detail={data.ollama.reachable ? modelList : `Unreachable — ${data.ollama_url}`}
        />
        <StatusRow
          name="Qdrant"
          ok={data.qdrant.reachable}
          detail={data.qdrant.reachable ? collectionList : `Unreachable — ${data.qdrant_url}`}
        />
      </div>
      <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">
          Configured Models
        </p>
        <p className="text-xs text-gray-500">
          Extraction: {data.configured_models.extraction} &middot; Enrichment: {data.configured_models.enrichment}
          {' '}&middot; Rewrite: {data.configured_models.rewrite} &middot; Synthesis: {data.configured_models.synthesis}
        </p>
      </div>
      <div className="px-5 py-3 bg-gray-50 rounded-b-lg">
        <p className="text-xs text-gray-500">
          {docCount} processed document{docCount !== 1 ? 's' : ''} on disk
        </p>
      </div>
    </div>
  )
}
