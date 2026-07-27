/**
 * Zod schemas for runtime response validation at the api/client.ts boundary
 * (WP-30.3). Hand-written and manually kept in sync with api/types.ts's
 * interfaces and the Python response shapes they mirror — see types.ts's own
 * header comment for the full list of backend files to track. No
 * schema-driven codegen in either direction (Phase 30 Non-Goals).
 *
 * Scope is intentionally partial: only the newest/most complex contracts
 * (ConfigResponse, EvidenceResponse) are covered for now, not the full API
 * surface — see the Phase 30 doc's WP-30.3 Non-Goals. Expand incrementally.
 */
import { z } from 'zod'

// ─── Evidence ────────────────────────────────────────────────────────────────

// .nullish() (not .optional()) on every field below -- pipeline/embed_and_index.py's
// build_payload() stores several of these with no default (page_start,
// page_end in particular), so a legacy or otherwise-unmapped requirement
// payload genuinely returns an explicit JSON `null`, not just an absent key.
// evidence_service.build() passes the raw Qdrant payload straight through
// with no reconstruction, so this reaches the API response as-is. .optional()
// only accepts a missing key (undefined); it rejects an explicit null, which
// would have made this WP's fail-closed validation break the evidence view
// for exactly the legacy-data case it needs to tolerate (Codex + Gemini
// review, PR #139).
const evidenceRequirementSchema = z.object({
  requirement_id: z.string(),
  description: z.string().nullish(),
  source_quote: z.string().nullish(),
  source_ref: z.string().nullish(),
  source_pdf: z.string().nullish(),
  document_id: z.string().nullish(),
  domain_tags: z.array(z.string()).nullish(),
  requirement_type: z.string().nullish(),
  confidence: z.number().nullish(),
  page_start: z.number().nullish(),
  page_end: z.number().nullish(),
  // list[str] hierarchy breadcrumb -- see the matching comment on
  // EvidenceRequirement in types.ts for how this was caught.
  section_title_path: z.array(z.string()).nullish(),
})

const evidenceGroupSchema = z.object({
  source_ref: z.string(),
  representative: evidenceRequirementSchema,
  sources: z.array(evidenceRequirementSchema),
  context_text: z.string().nullable(),
})

export const evidenceResponseSchema = z.object({
  query: z.string(),
  timestamp: z.string(),
  groups: z.record(z.string(), evidenceGroupSchema),
  group_order: z.array(z.string()),
  total_sources: z.number(),
  synthesis_text: z.string(),
  warnings: z.array(z.string()),
})

// ─── Config ──────────────────────────────────────────────────────────────────

const effectiveConfigSchema = z.object({
  ollama_url: z.string(),
  qdrant_url: z.string(),
  default_model: z.string(),
  extraction_model: z.string(),
  enrichment_model: z.string(),
  rewrite_model: z.string(),
  synthesis_model: z.string(),
  embedding_model: z.string(),
  top_k: z.number(),
  min_score: z.number(),
  processed_dir: z.string(),
  authority_registry: z.string().nullable(),
  synthesis_backend: z.string(),
  remote_provider: z.string(),
  remote_model: z.string(),
  api_key_env: z.string(),
  authority: z.record(z.string(), z.unknown()),
})

export const configResponseSchema = z.object({
  config: effectiveConfigSchema,
  env_overridden: z.array(z.string()),
})
