/**
 * TypeScript types mirroring the ReqBot API contract (Phase 16C).
 * Field names are snake_case to match the Python/FastAPI response exactly.
 * Any drift here becomes a runtime mismatch — keep in sync with:
 *   api/routes/ask.py   (AskRequest, AskResponse)
 *   api/routes/trace.py (TraceResponse)
 *   api/routes/docs.py  (DocsResponse)
 *   api/routes/status.py (StatusResponse)
 *   services/ask_service.py (canonical response shape)
 */

// ─── Requirement ─────────────────────────────────────────────────────────────

/**
 * Base payload fields present on every indexed requirement.
 * confidence comes from the extraction pipeline and is optional —
 * older records may not carry it.
 */
export interface Requirement {
  requirement_id: string
  description: string
  source_quote: string
  source_ref: string
  document_id: string
  source_pdf: string
  domain_tags: string[]
  requirement_type: string
  confidence?: number         // extraction-time confidence; not always present
  page_start?: number
  page_end?: number
  section_title_path?: string // schema v2.0 hierarchy fields
  section_ref_path?: string
  parent_context?: string
  chunk_id?: number
  domain_profile?: string     // Phase 20+; pre-Phase-20 records return "cybersecurity" via fallback
}

// ─── Ask ─────────────────────────────────────────────────────────────────────

/**
 * Request body for POST /api/ask.
 * All fields except question are optional (API provides defaults).
 * synthesize is always omitted/false for GUI calls in Phase 18.
 */
export interface AskRequest {
  question: string
  top_k?: number
  min_score?: number
  synthesize?: boolean
  model?: string
  rewrite_model?: string
  domain_tags?: string[]
  requirement_types?: string[]
  document_ids?: string[]
  no_rewrite?: boolean
  context?: boolean
  hyde?: boolean
}

/**
 * Ask results merge the Qdrant retrieval score with the full payload.
 * score is always present (added by ask_service before returning).
 */
export interface AskResult extends Requirement {
  score: number
  context_text?: string | null // included when ask is called with context=true
}

/**
 * filters mirrors ask_service.ask() return exactly:
 *   document_id:       document_ids or None → string[] | null
 *   domain_tag:        domain_tags or None  → string[] | null
 *   requirement_type:  requirement_types or None → string[] | null
 */
export interface AskResponse {
  query: string
  filters: {
    document_id: string[] | null
    domain_tag: string[] | null
    requirement_type: string[] | null
  }
  results: AskResult[]
  metadata: {
    top_k: number
    result_count: number
    retrieval_ms: number
    synthesis: string | null  // always null in Phase 18 (synthesis not exposed in GUI)
  }
}

// ─── Trace ───────────────────────────────────────────────────────────────────

export interface TraceResponse {
  requirement: Requirement
  cross_matches: Requirement[]
  context_text: string | null
}

// ─── Docs ────────────────────────────────────────────────────────────────────

export interface DocsEntry {
  doc_key: string
  source_pdf: string  // canonical Qdrant key, e.g. "afi17-101.pdf" (added WP-19.1)
  path: string
  count: number
  mode: string
  run_date: string
  profile?: string    // Phase 22.2+; "cybersecurity" fallback for pre-Phase-20 records
}

export interface DocsResponse {
  docs: DocsEntry[]
  total_reqs: number
  total_docs: number
}

// ─── Compare ─────────────────────────────────────────────────────────────────

export interface CompareRequest {
  doc_id_1: string
  doc_id_2: string
  topic: string
  top_k?: number
}

/**
 * A single requirement payload as returned by compare_service.
 * Mirrors the Qdrant stored payload; requirement_id is always present.
 */
export interface ComparePayload {
  requirement_id: string
  description: string
  source_quote?: string
  source_ref: string
  source_pdf: string
  document_id: string
  domain_tags?: string[]
  requirement_type?: string
  confidence?: number
  page_start?: number
  page_end?: number
  section_title_path?: string
}

/**
 * Semantic mode (free-text topic): results grouped by source_ref, then by source_pdf.
 * doc_pdf_1 / doc_pdf_2 are the exact keys used in ref_groups — use them to split
 * results into three sections (both, doc1-only, doc2-only).
 */
export interface CompareResponseSemantic {
  doc_id_1: string
  doc_id_2: string
  doc_pdf_1: string   // exact source_pdf key present in ref_groups
  doc_pdf_2: string
  query: string
  mode: 'semantic'
  ref_order: string[]
  ref_groups: Record<string, Record<string, ComparePayload>>
}

/**
 * Exact mode (control ID query): one representative per document.
 * doc_pdf_1 / doc_pdf_2 are the exact keys present in groups.
 */
export interface CompareResponseExact {
  doc_id_1: string
  doc_id_2: string
  doc_pdf_1: string
  doc_pdf_2: string
  query: string
  mode: 'exact'
  source_ref: string
  groups: Record<string, ComparePayload>
}

export type CompareResponse = CompareResponseSemantic | CompareResponseExact

// ─── Evidence ────────────────────────────────────────────────────────────────

export interface EvidenceRequest {
  topic: string
  domain_tags?: string[]
  requirement_types?: string[]
  synthesize?: boolean
  top_k?: number
}

/**
 * Raw Qdrant payload for a single requirement returned by evidence_service.
 * Uses optional fields because payload values are not guaranteed for every
 * record (esp. older ingested docs). requirement_id is always present.
 */
export interface EvidenceRequirement {
  requirement_id: string
  description?: string
  source_quote?: string
  source_ref?: string
  source_pdf?: string
  document_id?: string
  domain_tags?: string[]
  requirement_type?: string
  confidence?: number
  page_start?: number
  page_end?: number
  section_title_path?: string
}

/**
 * One evidence group keyed by source_ref.
 * representative is the highest-confidence requirement in the group.
 * sources is every requirement that matched in this group (includes representative).
 */
export interface EvidenceGroup {
  source_ref: string
  representative: EvidenceRequirement
  sources: EvidenceRequirement[]
  context_text: string | null
}

/**
 * Full response from POST /api/evidence.
 * groups is keyed by source_ref; group_order preserves the RRF rank order.
 * synthesis_text is empty string when synthesize=false.
 */
export interface EvidenceResponse {
  query: string
  timestamp: string
  groups: Record<string, EvidenceGroup>
  group_order: string[]
  total_sources: number
  synthesis_text: string
}

// ─── Checklist ───────────────────────────────────────────────────────────────

export interface ChecklistRequest {
  doc_key: string
  profile?: string
}

export interface ChecklistExportRequest {
  doc_key: string
  profile?: string
  format: 'csv' | 'json' | 'markdown' | 'xlsx'
}

export interface ChecklistItem {
  checklist_item_id: string
  requirement_ids: string[]
  source_quote: string
  source_ref: string
  section_title_path: string[]
  page_refs: number[]
  domain_tags: string[]
  confidence: number
  audit_question: string
  status: string
  assessor_notes: string
  requires_human_review: boolean
  review_reasons: string[]
}

export interface ChecklistEnvelope {
  format: string
  format_version: string
  generated_at: string
  generator: { tool: string; command: string }
  document: { document_id: string; source_pdf: string }
  profile: string
  summary: { total_items: number; items_requiring_review: number }
  items: ChecklistItem[]
}

export interface ProfilesResponse {
  profiles: string[]
}

// ─── Status ──────────────────────────────────────────────────────────────────

/**
 * Mirrors status_service.check() return shape.
 * points is number | string because Qdrant returns "?" when the count
 * is unavailable (collection detail request fails).
 */
export interface StatusResponse {
  ollama_url: string
  qdrant_url: string
  ollama: {
    reachable: boolean
    models: Array<{ name: string; size_gb: number }>
  }
  qdrant: {
    reachable: boolean
    collections: Array<{ name: string; points: number | string }>
  }
  processed_documents: Array<{ path: string; count: number }>
  /** Which model ReqBot is actually configured to use per role — distinct from
   *  ollama.models above, which is just what's installed on the server. */
  configured_models: {
    extraction: string
    enrichment: string
    rewrite: string
    synthesis: string
  }
}
