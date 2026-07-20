import { useState } from 'react'
import * as api from '../api/client'
import type { ChecklistExportRequest } from '../api/types'
import ErrorBanner from './ErrorBanner'

interface Props {
  docKey: string
  profile: string
}

type Format = ChecklistExportRequest['format']

const FORMATS: { label: string; value: Format }[] = [
  { label: 'CSV', value: 'csv' },
  { label: 'JSON', value: 'json' },
  { label: 'Markdown', value: 'markdown' },
]

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function ExportButtonGroup({ docKey, profile }: Props) {
  const [exporting, setExporting] = useState<Format | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleExport(format: Format) {
    setExporting(format)
    setError(null)
    try {
      const { blob, filename } = await api.checklistExport({ doc_key: docKey, profile, format })
      triggerDownload(blob, filename)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExporting(null)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2 flex-wrap">
        {FORMATS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => handleExport(value)}
            disabled={exporting !== null}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {exporting === value ? `Exporting ${label}…` : `Export ${label}`}
          </button>
        ))}
      </div>
      {error && <ErrorBanner message={error} />}
    </div>
  )
}
