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
  ChecklistEnvelope,
  ProfilesResponse,
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
  return res.json() as Promise<EvidenceResponse>
}

export async function profiles(): Promise<ProfilesResponse> {
  const res = await fetch(`${BASE}/profiles`)
  if (!res.ok) throw new Error(`profiles failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<ProfilesResponse>
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

/** Thrown by trace() when the requirement ID is not found (HTTP 404). */
export class NotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NotFoundError'
  }
}
