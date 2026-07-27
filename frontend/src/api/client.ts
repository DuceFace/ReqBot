/**
 * Typed fetch wrappers for all four ReqBot API endpoints.
 * All calls use the /api/ prefix — in dev the Vite proxy forwards to :8000;
 * in production reqbot serve handles the request directly.
 */
import type {
  AskRequest,
  AskResponse,
  TraceResponse,
  DocsResponse,
  StatusResponse,
  CompareRequest,
  CompareResponse,
  EvidenceRequest,
  EvidenceResponse,
  ChecklistRequest,
  ChecklistExportRequest,
  ChecklistEnvelope,
  ProfilesResponse,
  ConfigResponse,
  ConfigUpdateRequest,
} from './types'
import type { ZodType } from 'zod'
import { configResponseSchema, evidenceResponseSchema } from './schemas'

const BASE = '/api'

/**
 * Fail-closed schema validation (WP-30.3): a mismatch throws, surfacing
 * through the same try/catch/setError/ErrorBanner path a network failure
 * already takes, rather than letting `undefined` silently reach the UI.
 * Fail-open (log and pass the raw response through anyway) was explicitly
 * ruled out in the Phase 30 doc — a warning nobody looks at isn't a fix for
 * contract drift. The full ZodError still goes to the console as a
 * diagnostic aid; it just isn't the only signal something went wrong.
 */
function parseOrThrow<T>(schema: ZodType<T>, data: unknown, label: string): T {
  const result = schema.safeParse(data)
  if (!result.success) {
    console.warn(`${label} response failed schema validation`, result.error)
    throw new Error(`${label} response did not match the expected shape — see console for details`)
  }
  return result.data
}

export async function ask(req: AskRequest): Promise<AskResponse> {
  const res = await fetch(`${BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`ask failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<AskResponse>
}

/**
 * Fetch full provenance for a requirement by ID.
 * encodeURIComponent is used per spec — corpus IDs are path-safe today
 * but encoding is correct practice and costs nothing.
 */
export async function trace(
  reqId: string,
  context = false,
): Promise<TraceResponse> {
  const params = context ? '?context=true' : ''
  const res = await fetch(
    `${BASE}/trace/${encodeURIComponent(reqId)}${params}`,
  )
  if (res.status === 404)
    throw new NotFoundError(`Requirement not found: ${reqId}`)
  if (!res.ok) throw new Error(`trace failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<TraceResponse>
}

export async function docs(): Promise<DocsResponse> {
  const res = await fetch(`${BASE}/docs`)
  if (!res.ok) throw new Error(`docs failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<DocsResponse>
}

export async function status(): Promise<StatusResponse> {
  const res = await fetch(`${BASE}/status`)
  if (!res.ok)
    throw new Error(`status failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<StatusResponse>
}

export async function compare(req: CompareRequest): Promise<CompareResponse> {
  const res = await fetch(`${BASE}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: string }) => b.detail ?? '').catch(() => '')
    throw new Error(detail || `compare failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<CompareResponse>
}

export async function evidence(req: EvidenceRequest): Promise<EvidenceResponse> {
  const res = await fetch(`${BASE}/evidence`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: string }) => b.detail ?? '').catch(() => '')
    throw new Error(detail || `evidence failed: ${res.status} ${res.statusText}`)
  }
  return parseOrThrow(evidenceResponseSchema, await res.json(), 'evidence')
}

export async function profiles(): Promise<ProfilesResponse> {
  const res = await fetch(`${BASE}/profiles`)
  if (!res.ok) throw new Error(`profiles failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<ProfilesResponse>
}

export async function checklistExport(
  req: ChecklistExportRequest,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${BASE}/checklist/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: string }) => b.detail ?? '').catch(() => '')
    throw new Error(detail || `export failed: ${res.status} ${res.statusText}`)
  }
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/)
  const ext = req.format === 'markdown' ? 'md' : req.format
  const filename = match?.[1] ?? `checklist_${req.doc_key}.${ext}`
  const blob = await res.blob()
  return { blob, filename }
}

export async function checklist(req: ChecklistRequest): Promise<ChecklistEnvelope> {
  const res = await fetch(`${BASE}/checklist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: string }) => b.detail ?? '').catch(() => '')
    throw new Error(detail || `checklist failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<ChecklistEnvelope>
}

export async function getConfig(): Promise<ConfigResponse> {
  const res = await fetch(`${BASE}/config`)
  if (!res.ok) throw new Error(`getConfig failed: ${res.status} ${res.statusText}`)
  return parseOrThrow(configResponseSchema, await res.json(), 'getConfig')
}

/**
 * A FastAPI/Pydantic-generated 422 (as opposed to one of this route's own
 * hand-raised HTTPExceptions) returns `detail` as an array of error objects,
 * not a string — stringifying that array directly produces "[object
 * Object]" in the UI (Gemini review, PR #133).
 */
function extractErrorDetail(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(e => (e && typeof e === 'object' && typeof (e as { msg?: unknown }).msg === 'string')
        ? (e as { msg: string }).msg
        : JSON.stringify(e))
      .join('; ')
  }
  if (detail) return JSON.stringify(detail)
  return ''
}

export async function updateConfig(req: ConfigUpdateRequest): Promise<ConfigResponse> {
  const res = await fetch(`${BASE}/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = extractErrorDetail(body)
    throw new Error(detail || `updateConfig failed: ${res.status} ${res.statusText}`)
  }
  return parseOrThrow(configResponseSchema, await res.json(), 'updateConfig')
}

/** Thrown by trace() when the requirement ID is not found (HTTP 404). */
export class NotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NotFoundError'
  }
}
