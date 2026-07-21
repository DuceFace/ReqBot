import { useState, useEffect, useRef } from 'react'
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
  { label: 'Excel (XLSX)', value: 'xlsx' },
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
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  async function handleExport(format: Format) {
    setOpen(false)
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
      <div className="relative" ref={containerRef}>
        <button
          onClick={() => setOpen(o => !o)}
          disabled={exporting !== null}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {exporting ? 'Exporting…' : 'Export'}
          <span aria-hidden="true" className="text-gray-400">▾</span>
        </button>

        {open && (
          <div className="absolute right-0 mt-1 w-36 rounded border border-gray-200 bg-white shadow-md z-10">
            {FORMATS.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => handleExport(value)}
                className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 first:rounded-t last:rounded-b"
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
    </div>
  )
}
