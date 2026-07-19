import { useState, useEffect, useCallback } from 'react'
import * as api from '../api/client'
import type { StatusResponse } from '../api/types'
import AppShell from '../components/AppShell'
import SystemHealthPanel from '../components/SystemHealthPanel'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'

export default function SystemView() {
  const [data, setData] = useState<StatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .status()
      .then(res => { setData(res) })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load system status')
      })
      .finally(() => { setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <AppShell>
      <main className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">System</h1>
          <button
            onClick={load}
            disabled={loading}
            className="px-3 py-1.5 text-sm bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {loading ? 'Checking…' : 'Refresh'}
          </button>
        </div>

        {loading && <LoadingSpinner />}
        {!loading && error && <ErrorBanner message={error} onRetry={load} />}
        {!loading && !error && data && <SystemHealthPanel data={data} />}

      </main>
    </AppShell>
  )
}
