import { useState, useEffect, useCallback } from 'react'
import type { FormEvent } from 'react'
import * as api from '../api/client'
import type { ConfigResponse, ConfigUpdateRequest } from '../api/types'
import AppShell from '../components/AppShell'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'

// Fields where an emptied input means "clear back to inheriting default_model"
// (R-2.1) rather than "save an empty string" — mirrors cmd_init()'s own
// blank-means-inherit convention for these same three fields.
const NULLABLE_FIELDS = ['extraction_model', 'enrichment_model', 'rewrite_model'] as const
type NullableField = (typeof NULLABLE_FIELDS)[number]

interface FormState {
  ollama_url: string
  qdrant_url: string
  default_model: string
  extraction_model: string
  enrichment_model: string
  rewrite_model: string
  synthesis_model: string
  embedding_model: string
  top_k: string
  min_score: string
  synthesis_backend: string
  remote_provider: string
  remote_model: string
  api_key_env: string
}

function toForm(cfg: ConfigResponse['config']): FormState {
  return {
    ollama_url: cfg.ollama_url,
    qdrant_url: cfg.qdrant_url,
    default_model: cfg.default_model,
    extraction_model: cfg.extraction_model,
    enrichment_model: cfg.enrichment_model,
    rewrite_model: cfg.rewrite_model,
    synthesis_model: cfg.synthesis_model,
    embedding_model: cfg.embedding_model,
    top_k: String(cfg.top_k),
    min_score: String(cfg.min_score),
    synthesis_backend: cfg.synthesis_backend,
    remote_provider: cfg.remote_provider,
    remote_model: cfg.remote_model,
    api_key_env: cfg.api_key_env,
  }
}

/** REQBOT_* env var name for a field, per core.config._ENV_MAP's fixed naming
 * convention (not sent by the API — derived here; see api/types.ts). */
function envVarName(field: string): string {
  return `REQBOT_${field.toUpperCase()}`
}

interface DiffResult {
  partial: ConfigUpdateRequest
  errors: string[]
}

/** Diff form against baseline into a partial update — only actually-changed
 * fields are included, so unmodified role-model fields never get resent and
 * accidentally frozen as an explicit override (see api/types.ts). */
function buildDiff(form: FormState, baseline: FormState): DiffResult {
  const partial: ConfigUpdateRequest = {}
  const errors: string[] = []

  const requiredField = (
    key: keyof FormState,
    label: string,
  ): void => {
    const val = form[key].trim()
    if (!val) {
      errors.push(`${label} cannot be empty.`)
      return
    }
    if (val !== baseline[key]) {
      // All required string fields happen to share this shape; cast is safe
      // per-call since callers only pass string-typed ConfigUpdateRequest keys.
      ;(partial as Record<string, string>)[key] = val
    }
  }

  requiredField('ollama_url', 'Ollama URL')
  requiredField('qdrant_url', 'Qdrant URL')
  requiredField('default_model', 'Default model')
  requiredField('embedding_model', 'Embedding model')

  for (const key of NULLABLE_FIELDS as readonly NullableField[]) {
    const val = form[key].trim()
    if (val === baseline[key]) continue
    partial[key] = val === '' ? null : val
  }

  const topK = Number(form.top_k)
  if (!Number.isInteger(topK) || topK < 1 || topK > 100) {
    errors.push('Default top-k must be a whole number between 1 and 100.')
  } else if (form.top_k !== baseline.top_k) {
    partial.top_k = topK
  }

  const minScore = Number(form.min_score)
  if (!Number.isFinite(minScore) || minScore < 0 || minScore > 1) {
    errors.push('Minimum relevance score must be a number between 0 and 1.')
  } else if (form.min_score !== baseline.min_score) {
    partial.min_score = minScore
  }

  if (form.synthesis_backend !== baseline.synthesis_backend) {
    partial.synthesis_backend = form.synthesis_backend as ConfigUpdateRequest['synthesis_backend']
  }

  if (form.synthesis_backend === 'remote') {
    requiredField('remote_model', 'Remote model')
    requiredField('api_key_env', 'API key environment variable')
    if (form.remote_provider !== baseline.remote_provider) {
      partial.remote_provider = form.remote_provider as ConfigUpdateRequest['remote_provider']
    }
  }

  if (form.synthesis_backend !== 'remote') {
    requiredField('synthesis_model', 'Synthesis model')
  }

  return { partial, errors }
}

interface FieldProps {
  label: string
  id: string
  value: string
  onChange: (v: string) => void
  type?: string
  min?: number
  max?: number
  step?: number
  placeholder?: string
  overridden?: boolean
  hint?: string
}

function Field({
  label, id, value, onChange, type = 'text', min, max, step, placeholder, overridden, hint,
}: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-gray-500 mb-1">{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={e => { onChange(e.target.value) }}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
      {overridden && (
        <p className="mt-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          Currently overridden by <code className="font-mono">{envVarName(id)}</code> — this
          change will take effect once that variable is unset.
        </p>
      )}
    </div>
  )
}

export default function SettingsView() {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [baseline, setBaseline] = useState<FormState | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [envOverridden, setEnvOverridden] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [validationErrors, setValidationErrors] = useState<string[]>([])

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    api.getConfig()
      .then(res => {
        const next = toForm(res.config)
        setBaseline(next)
        setForm(next)
        setEnvOverridden(res.env_overridden)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : 'Failed to load settings')
      })
      .finally(() => { setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm(f => (f ? { ...f, [key]: value } : f))
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!form || !baseline) return

    const { partial, errors } = buildDiff(form, baseline)
    setValidationErrors(errors)
    setSaveError(null)
    setSaveMessage(null)
    if (errors.length > 0) return
    if (Object.keys(partial).length === 0) {
      setSaveMessage('No changes to save.')
      return
    }

    const embeddingChanged = 'embedding_model' in partial

    setSaving(true)
    api.updateConfig(partial)
      .then(res => {
        const next = toForm(res.config)
        setBaseline(next)
        setForm(next)
        setEnvOverridden(res.env_overridden)
        setSaveMessage(
          embeddingChanged
            ? 'Saved. This does not retroactively re-embed your existing corpus — run '
              + '"reqbot reindex" afterward, or search results may show mismatch warnings until you do.'
            : 'Saved — takes effect on the next request, no restart needed.',
        )
      })
      .catch((err: unknown) => {
        setSaveError(err instanceof Error ? err.message : 'Failed to save settings')
      })
      .finally(() => { setSaving(false) })
  }

  if (loading) {
    return (
      <AppShell>
        <main className="max-w-2xl mx-auto px-6 py-8"><LoadingSpinner /></main>
      </AppShell>
    )
  }

  if (loadError || !form) {
    return (
      <AppShell>
        <main className="max-w-2xl mx-auto px-6 py-8">
          <ErrorBanner message={loadError ?? 'Failed to load settings'} onRetry={load} />
        </main>
      </AppShell>
    )
  }

  const isRemote = form.synthesis_backend === 'remote'

  return (
    <AppShell>
      <main className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <h1 className="text-xl font-bold text-gray-900">Settings</h1>

        <form onSubmit={handleSubmit} className="space-y-8">

          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-700">Connections</h2>
            <Field
              label="Ollama URL" id="ollama_url" value={form.ollama_url}
              onChange={v => { set('ollama_url', v) }}
              overridden={envOverridden.includes('ollama_url')}
            />
            <Field
              label="Qdrant URL" id="qdrant_url" value={form.qdrant_url}
              onChange={v => { set('qdrant_url', v) }}
              overridden={envOverridden.includes('qdrant_url')}
            />
          </section>

          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-700">Models</h2>
            <Field
              label="Default model" id="default_model" value={form.default_model}
              onChange={v => { set('default_model', v) }}
              overridden={envOverridden.includes('default_model')}
            />
            <Field
              label="Step C extraction model" id="extraction_model" value={form.extraction_model}
              onChange={v => { set('extraction_model', v) }}
              placeholder="Inherits from Default model"
              hint="Leave blank and save to always follow Default model."
              overridden={envOverridden.includes('extraction_model')}
            />
            <Field
              label="Step D.5 enrichment model" id="enrichment_model" value={form.enrichment_model}
              onChange={v => { set('enrichment_model', v) }}
              placeholder="Inherits from Default model"
              hint="Leave blank and save to always follow Default model."
              overridden={envOverridden.includes('enrichment_model')}
            />
            <Field
              label="Query-rewrite / HyDE model" id="rewrite_model" value={form.rewrite_model}
              onChange={v => { set('rewrite_model', v) }}
              placeholder="Inherits from Default model"
              hint="Leave blank and save to always follow Default model."
              overridden={envOverridden.includes('rewrite_model')}
            />
            <Field
              label="Embedding model" id="embedding_model" value={form.embedding_model}
              onChange={v => { set('embedding_model', v) }}
              hint="Defines the vector shape already stored in Qdrant — changing this does not
                    retroactively re-embed the existing corpus. Run reqbot reindex afterward."
              overridden={envOverridden.includes('embedding_model')}
            />
          </section>

          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-700">Retrieval</h2>
            <Field
              label="Default top-k" id="top_k" value={form.top_k} type="number"
              min={1} max={100}
              onChange={v => { set('top_k', v) }}
              overridden={envOverridden.includes('top_k')}
            />
            <Field
              label="Minimum relevance score" id="min_score" value={form.min_score} type="number"
              min={0} max={1} step={0.01}
              onChange={v => { set('min_score', v) }}
              overridden={envOverridden.includes('min_score')}
            />
          </section>

          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-700">Synthesis</h2>
            <div>
              <label htmlFor="synthesis_backend" className="block text-xs text-gray-500 mb-1">
                Synthesis backend
              </label>
              <select
                id="synthesis_backend"
                value={form.synthesis_backend}
                onChange={e => { set('synthesis_backend', e.target.value) }}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="local">Local Ollama</option>
                <option value="remote">Remote (Claude / GPT-4o)</option>
                <option value="none">None — retrieval only</option>
              </select>
              {envOverridden.includes('synthesis_backend') && (
                <p className="mt-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                  Currently overridden by <code className="font-mono">REQBOT_SYNTHESIS_BACKEND</code> —
                  this change will take effect once that variable is unset.
                </p>
              )}
            </div>

            {!isRemote && (
              <Field
                label="Local synthesis model" id="synthesis_model" value={form.synthesis_model}
                onChange={v => { set('synthesis_model', v) }}
                overridden={envOverridden.includes('synthesis_model')}
              />
            )}

            {isRemote && (
              <>
                <div>
                  <label htmlFor="remote_provider" className="block text-xs text-gray-500 mb-1">
                    Remote provider
                  </label>
                  <select
                    id="remote_provider"
                    value={form.remote_provider}
                    onChange={e => { set('remote_provider', e.target.value) }}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="anthropic">Anthropic</option>
                    <option value="openai">OpenAI</option>
                  </select>
                </div>
                <Field
                  label="Remote model" id="remote_model" value={form.remote_model}
                  onChange={v => { set('remote_model', v) }}
                  overridden={envOverridden.includes('remote_model')}
                />
                <Field
                  label="API key environment variable" id="api_key_env" value={form.api_key_env}
                  onChange={v => { set('api_key_env', v) }}
                  hint="The name of the environment variable holding the API key on the server —
                        not the key itself. ReqBot never accepts or displays an actual key value here."
                  overridden={envOverridden.includes('api_key_env')}
                />
              </>
            )}
          </section>

          {validationErrors.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700 space-y-1">
              {validationErrors.map((msg, i) => <p key={i}>{msg}</p>)}
            </div>
          )}

          {saveError && <ErrorBanner message={saveError} />}

          {saveMessage && (
            <p className="bg-green-50 border border-green-200 rounded p-4 text-sm text-green-700">
              {saveMessage}
            </p>
          )}

          <div>
            <button
              type="submit"
              disabled={saving}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-5 py-2 rounded text-sm font-medium transition-colors"
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>

        </form>
      </main>
    </AppShell>
  )
}
