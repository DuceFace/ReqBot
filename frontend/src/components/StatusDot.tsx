import { useState, useEffect } from 'react'
import { status } from '../api/client'

/**
 * Polls /api/status on mount and every 30 s.
 * Green dot = Ollama + Qdrant both reachable; red = either down.
 * Renders nothing until the first check completes.
 */
export default function StatusDot() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [label, setLabel] = useState('')

  useEffect(() => {
    function check() {
      status()
        .then(s => {
          const ok = s.ollama.reachable && s.qdrant.reachable
          setHealthy(ok)
          if (ok) {
            setLabel('Ollama ✓  Qdrant ✓')
          } else {
            const parts = []
            if (!s.ollama.reachable) parts.push('Ollama ✗')
            if (!s.qdrant.reachable) parts.push('Qdrant ✗')
            setLabel(parts.join('  '))
          }
        })
        .catch(() => {
          setHealthy(false)
          setLabel('Backend unreachable')
        })
    }
    check()
    const id = setInterval(check, 30_000)
    return () => clearInterval(id)
  }, [])

  if (healthy === null) return null

  return (
    <div
      className="flex items-center gap-2 text-sm text-gray-500"
      title={label}
    >
      <span
        className={`w-2.5 h-2.5 rounded-full ${healthy ? 'bg-green-500' : 'bg-red-500'}`}
      />
      <span className="hidden sm:inline">{label}</span>
    </div>
  )
}
