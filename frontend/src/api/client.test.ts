import { afterEach, describe, expect, it, vi } from 'vitest'
import { evidence, getConfig } from './client'

const VALID_CONFIG_RESPONSE = {
  config: {
    ollama_url: 'http://ollama:11434',
    qdrant_url: 'http://qdrant:6333',
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

const VALID_EVIDENCE_RESPONSE = {
  query: 'access control',
  timestamp: '2026-07-25T00:00:00Z',
  group_order: [],
  groups: {},
  total_sources: 0,
  synthesis_text: '',
  warnings: [],
}

function mockFetchOnce(body: unknown, ok = true) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    statusText: ok ? 'OK' : 'Internal Server Error',
    json: () => Promise.resolve(body),
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getConfig fail-closed validation', () => {
  it('resolves normally for a schema-valid response', async () => {
    mockFetchOnce(VALID_CONFIG_RESPONSE)
    await expect(getConfig()).resolves.toEqual(VALID_CONFIG_RESPONSE)
  })

  it('throws (does not resolve with the malformed data) when the response fails schema validation', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    // top_k as a string -- same contract-drift shape covered in schemas.test.ts,
    // exercised here through the actual client wrapper.
    mockFetchOnce({
      ...VALID_CONFIG_RESPONSE,
      config: { ...VALID_CONFIG_RESPONSE.config, top_k: '20' },
    })
    await expect(getConfig()).rejects.toThrow(/did not match the expected shape/)
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })
})

describe('evidence fail-closed validation', () => {
  it('resolves normally for a schema-valid response', async () => {
    mockFetchOnce(VALID_EVIDENCE_RESPONSE)
    await expect(evidence({ topic: 'access control' })).resolves.toEqual(VALID_EVIDENCE_RESPONSE)
  })

  it('throws when a required field is missing from the response', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const { timestamp: _timestamp, ...withoutTimestamp } = VALID_EVIDENCE_RESPONSE
    mockFetchOnce(withoutTimestamp)
    await expect(evidence({ topic: 'access control' })).rejects.toThrow(/did not match the expected shape/)
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })
})
