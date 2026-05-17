import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Manages synthesis request state shared by SearchView and EvidenceView.
 *
 * run(fetcher) starts a new synthesis call. The fetcher receives no arguments
 * and returns Promise<string | null> — callers build the API call themselves
 * so each view can pass the right request body without the hook knowing about it.
 *
 * reset() invalidates any in-flight request (via generation counter) and clears
 * all state. Call it from a useEffect when the query/topic changes.
 *
 * Generation counter: each run() increments genRef before launching the fetch.
 * Callbacks guard on genRef.current === gen so only the most-recently-started
 * request can write state. reset() also increments the counter, discarding any
 * request that was in-flight at the time the topic changed.
 */
export function useSynthesis() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const genRef = useRef(0)

  useEffect(() => {
    if (!loading) return
    setElapsed(0)
    const iv = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(iv)
  }, [loading])

  const run = useCallback((fetcher: () => Promise<string | null>) => {
    const gen = ++genRef.current
    setLoading(true)
    setError(null)
    setText(null)
    fetcher()
      .then(result => {
        if (genRef.current !== gen) return
        setText(result)
      })
      .catch((err: unknown) => {
        if (genRef.current !== gen) return
        setError(err instanceof Error ? err.message : 'Synthesis failed')
      })
      .finally(() => {
        if (genRef.current === gen) setLoading(false)
      })
  }, [])

  const reset = useCallback(() => {
    genRef.current += 1
    setLoading(false)
    setError(null)
    setText(null)
    setElapsed(0)
  }, [])

  return { loading, error, text, elapsed, run, reset }
}
