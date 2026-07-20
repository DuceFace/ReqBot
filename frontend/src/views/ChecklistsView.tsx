import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { docValue } from '../utils/ui'
import * as api from '../api/client'
import type { DocsEntry } from '../api/types'
import AppShell from '../components/AppShell'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'

export default function ChecklistsView() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [docOptions, setDocOptions] = useState<DocsEntry[]>([])
  const [docKey, setDocKey] = useState(searchParams.get('doc') ?? '')
  const [docsError, setDocsError] = useState(false)

  const [profileOptions, setProfileOptions] = useState<string[]>(['cybersecurity'])
  const [profile, setProfile] = useState('cybersecurity')
  const [profilesError, setProfilesError] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.docs()
      .then(d => setDocOptions(d.docs))
      .catch(() => setDocsError(true))
  }, [])

  useEffect(() => {
    api.profiles()
      .then(p => {
        setProfileOptions(p.profiles)
        // keep 'cybersecurity' if present; otherwise fall back to first item
        if (p.profiles.length > 0 && !p.profiles.includes('cybersecurity')) {
          setProfile(p.profiles[0])
        }
      })
      .catch(() => setProfilesError(true))
  }, [])

  async function handleGenerate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!docKey || !profile || loading) return
    setLoading(true)
    setError(null)
    try {
      await api.checklist({ doc_key: docKey, profile })
      navigate(
        `/checklists/${encodeURIComponent(docKey)}?profile=${encodeURIComponent(profile)}`,
      )
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Checklist generation failed')
      setLoading(false)
    }
  }

  const canSubmit = docKey !== '' && profile !== '' && !loading

  return (
    <AppShell>
      <main className="max-w-2xl mx-auto px-6 py-8">
        <h1 className="text-xl font-bold text-gray-900 mb-6">Generate Checklist</h1>

        {docsError && (
          <div className="mb-4">
            <ErrorBanner message="Could not load document list. Check that the API is reachable." />
          </div>
        )}
        {profilesError && (
          <div className="mb-4">
            <ErrorBanner message="Could not load profiles. Using default." />
          </div>
        )}

        <form onSubmit={handleGenerate} className="space-y-4">
          <div>
            <label
              className="block text-xs text-gray-500 mb-1"
              htmlFor="doc-select"
            >
              Document
            </label>
            <select
              id="doc-select"
              value={docKey}
              onChange={e => setDocKey(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Select document…</option>
              {docOptions.map(d => (
                <option key={d.doc_key} value={d.doc_key}>
                  {docValue(d)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              className="block text-xs text-gray-500 mb-1"
              htmlFor="profile-select"
            >
              Profile
            </label>
            <select
              id="profile-select"
              value={profile}
              onChange={e => setProfile(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {profileOptions.map(p => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={!canSubmit}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-5 py-2 rounded text-sm font-medium transition-colors"
          >
            {loading ? 'Generating checklist…' : 'Generate'}
          </button>
        </form>

        {loading && (
          <div className="mt-6">
            <LoadingSpinner />
          </div>
        )}

        {!loading && error && (
          <div className="mt-4">
            <ErrorBanner message={error} />
          </div>
        )}
      </main>
    </AppShell>
  )
}
