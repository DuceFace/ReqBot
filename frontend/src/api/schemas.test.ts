import { describe, expect, it } from 'vitest'
import { configResponseSchema, evidenceResponseSchema } from './schemas'

describe('configResponseSchema', () => {
  it('parses a known-good GET /api/config response', () => {
    const fixture = {
      config: {
        ollama_url: 'http://192.168.90.100:11434',
        qdrant_url: 'http://192.168.30.153:6333',
        default_model: 'llama3.1:8b-instruct-q4_K_M',
        extraction_model: 'llama3.1:8b-instruct-q4_K_M',
        enrichment_model: 'llama3.1:8b-instruct-q4_K_M',
        rewrite_model: 'llama3.1:8b-instruct-q4_K_M',
        synthesis_model: 'qwen2.5:14b',
        embedding_model: 'nomic-embed-text',
        top_k: 20,
        min_score: 0.02,
        processed_dir: '~/documents/processed',
        authority_registry: null,
        synthesis_backend: 'local',
        remote_provider: 'anthropic',
        remote_model: 'claude-sonnet-4-6',
        api_key_env: 'ANTHROPIC_API_KEY',
        authority: {},
      },
      env_overridden: ['top_k'],
    }
    const result = configResponseSchema.safeParse(fixture)
    expect(result.success).toBe(true)
  })

  it('rejects a response missing a required field', () => {
    const fixture = {
      config: {
        // ollama_url missing entirely
        qdrant_url: 'http://192.168.30.153:6333',
        default_model: 'llama3.1:8b-instruct-q4_K_M',
        extraction_model: 'llama3.1:8b-instruct-q4_K_M',
        enrichment_model: 'llama3.1:8b-instruct-q4_K_M',
        rewrite_model: 'llama3.1:8b-instruct-q4_K_M',
        synthesis_model: 'qwen2.5:14b',
        embedding_model: 'nomic-embed-text',
        top_k: 20,
        min_score: 0.02,
        processed_dir: '~/documents/processed',
        authority_registry: null,
        synthesis_backend: 'local',
        remote_provider: 'anthropic',
        remote_model: 'claude-sonnet-4-6',
        api_key_env: 'ANTHROPIC_API_KEY',
        authority: {},
      },
      env_overridden: [],
    }
    const result = configResponseSchema.safeParse(fixture)
    expect(result.success).toBe(false)
  })

  it('rejects a response with a wrong-typed field (contract-drift simulation)', () => {
    const fixture = {
      config: {
        ollama_url: 'http://192.168.90.100:11434',
        qdrant_url: 'http://192.168.30.153:6333',
        default_model: 'llama3.1:8b-instruct-q4_K_M',
        extraction_model: 'llama3.1:8b-instruct-q4_K_M',
        enrichment_model: 'llama3.1:8b-instruct-q4_K_M',
        rewrite_model: 'llama3.1:8b-instruct-q4_K_M',
        synthesis_model: 'qwen2.5:14b',
        embedding_model: 'nomic-embed-text',
        // top_k as a string instead of number -- the kind of drift a backend
        // refactor could introduce without either side's static types catching it.
        top_k: '20',
        min_score: 0.02,
        processed_dir: '~/documents/processed',
        authority_registry: null,
        synthesis_backend: 'local',
        remote_provider: 'anthropic',
        remote_model: 'claude-sonnet-4-6',
        api_key_env: 'ANTHROPIC_API_KEY',
        authority: {},
      },
      env_overridden: [],
    }
    const result = configResponseSchema.safeParse(fixture)
    expect(result.success).toBe(false)
  })
})

describe('evidenceResponseSchema', () => {
  it('parses a known-good POST /api/evidence response', () => {
    const fixture = {
      query: 'access control',
      timestamp: '2026-07-25T00:00:00Z',
      group_order: ['3.1.1'],
      groups: {
        '3.1.1': {
          source_ref: '3.1.1',
          representative: {
            requirement_id: 'REQ-abc123',
            description: 'Systems must enforce role-based access control.',
            source_quote: 'Systems must enforce role-based access control.',
            source_ref: '3.1.1',
            source_pdf: 'afi17-101.pdf',
            document_id: 'abc123def456ab01',
            domain_tags: ['access-control'],
            requirement_type: 'mandatory',
            confidence: 0.9,
            page_start: 3,
            page_end: 3,
            section_title_path: ['Access Control'],
          },
          sources: [
            { requirement_id: 'REQ-abc123' },
          ],
          context_text: null,
        },
      },
      total_sources: 1,
      synthesis_text: '',
      warnings: [],
    }
    const result = evidenceResponseSchema.safeParse(fixture)
    expect(result.success).toBe(true)
  })

  it('parses the empty-result shape (no groups, no matches)', () => {
    const fixture = {
      query: 'access control',
      timestamp: '2026-07-25T00:00:00Z',
      group_order: [],
      groups: {},
      total_sources: 0,
      synthesis_text: '',
      warnings: [],
    }
    const result = evidenceResponseSchema.safeParse(fixture)
    expect(result.success).toBe(true)
  })

  it('rejects a response missing a required field', () => {
    const fixture = {
      query: 'access control',
      // timestamp missing entirely
      group_order: [],
      groups: {},
      total_sources: 0,
      synthesis_text: '',
      warnings: [],
    }
    const result = evidenceResponseSchema.safeParse(fixture)
    expect(result.success).toBe(false)
  })

  it('rejects a group missing requirement_id on its representative', () => {
    const fixture = {
      query: 'access control',
      timestamp: '2026-07-25T00:00:00Z',
      group_order: ['3.1.1'],
      groups: {
        '3.1.1': {
          source_ref: '3.1.1',
          representative: { description: 'no requirement_id here' },
          sources: [],
          context_text: null,
        },
      },
      total_sources: 1,
      synthesis_text: '',
      warnings: [],
    }
    const result = evidenceResponseSchema.safeParse(fixture)
    expect(result.success).toBe(false)
  })
})
