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
} from './types'

const BASE = '/api'

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

/** Thrown by trace() when the requirement ID is not found (HTTP 404). */
export class NotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NotFoundError'
  }
}
