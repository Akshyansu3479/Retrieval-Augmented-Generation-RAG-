import { useEffect, useState } from 'react'
import { getReady } from '../api/client'
import type { ReadyResponse } from '../api/types'

export function StatusBar() {
  const [ready, setReady] = useState<ReadyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await getReady()
        if (!cancelled) {
          setReady(data)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Ready check failed')
        }
      }
    }
    void load()
    const id = window.setInterval(load, 10000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  return (
    <header className="status-bar">
      <div className="brand-block">
        <div className="brand-row">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="9" fill="url(#brandGrad)" />
              <path
                d="M9 21V11h5.2c2.3 0 3.7 1.2 3.7 3.05 0 1.2-.6 2.15-1.7 2.6L19.4 21h-2.55l-2.85-4.05H11.4V21H9Zm2.4-6.15h2.55c1.1 0 1.75-.55 1.75-1.4s-.65-1.35-1.75-1.35H11.4v2.75Z"
                fill="#f0fdfa"
              />
              <defs>
                <linearGradient id="brandGrad" x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#0f766e" />
                  <stop offset="1" stopColor="#14b8a6" />
                </linearGradient>
              </defs>
            </svg>
          </span>
          <div>
            <p className="brand">RAG Playground</p>
            <p className="brand-sub">Upload → ingest → ask with citations</p>
          </div>
        </div>
      </div>
      <div className="dep-row" aria-live="polite">
        {error && <span className="dep chip unavailable">{error}</span>}
        {ready && (
          <>
            <span className={`dep chip ${ready.status}`}>{ready.status}</span>
            {ready.dependencies.map((dep) => (
              <span
                key={dep.name}
                className={`dep chip ${dep.status}`}
                title={dep.detail || undefined}
              >
                {dep.name}
              </span>
            ))}
          </>
        )}
      </div>
    </header>
  )
}
