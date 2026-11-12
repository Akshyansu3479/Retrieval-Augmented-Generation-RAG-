import { useCallback, useEffect, useState } from 'react'
import {
  enqueueIngestion,
  getIngestionStatus,
  listDocuments,
  uploadDocument,
} from '../api/client'
import type { Document, IngestionJob } from '../api/types'

type Props = {
  selectedIds: string[]
  onSelectionChange: (ids: string[]) => void
}

export function DocumentPanel({ selectedIds, onSelectionChange }: Props) {
  const [docs, setDocs] = useState<Document[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Record<string, IngestionJob>>({})
  const [dragOver, setDragOver] = useState(false)

  const refresh = useCallback(async () => {
    const data = await listDocuments()
    setDocs(data.items)
  }, [])

  useEffect(() => {
    void refresh().catch((err: unknown) => {
      setMessage(err instanceof Error ? err.message : 'Failed to load documents')
    })
  }, [refresh])

  useEffect(() => {
    const running = Object.values(jobs).some(
      (j) => j.status === 'pending' || j.status === 'running',
    )
    if (!running) return
    const id = window.setInterval(() => {
      void (async () => {
        const next: Record<string, IngestionJob> = { ...jobs }
        for (const [docId, job] of Object.entries(jobs)) {
          if (job.status === 'succeeded' || job.status === 'failed') continue
          try {
            next[docId] = await getIngestionStatus(docId)
          } catch {
            // keep previous
          }
        }
        setJobs(next)
        await refresh()
      })()
    }, 1500)
    return () => window.clearInterval(id)
  }, [jobs, refresh])

  const onUpload = async (fileList: FileList | null) => {
    if (!fileList?.length) return
    setBusy(true)
    setMessage(null)
    try {
      const uploaded: Document[] = []
      for (const file of Array.from(fileList)) {
        uploaded.push(await uploadDocument(file))
      }
      await refresh()
      const ids = uploaded.map((d) => d.id)
      onSelectionChange([...new Set([...selectedIds, ...ids])])
      setMessage(`Uploaded ${uploaded.length} file(s). Click Ingest to index.`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const ingestOne = async (documentId: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await enqueueIngestion(documentId, true)
      const status = await getIngestionStatus(documentId)
      setJobs((prev) => ({ ...prev, [documentId]: status }))
      setMessage('Ingestion queued')
      await refresh()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Ingest failed')
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id: string) => {
    if (selectedIds.includes(id)) {
      onSelectionChange(selectedIds.filter((x) => x !== id))
    } else {
      onSelectionChange([...new Set([...selectedIds, id])])
    }
  }

  return (
    <section className="panel document-panel">
      <div className="panel-head">
        <h2>Documents</h2>
        <p>Upload files, ingest them, then select for chat.</p>
      </div>

      <label
        className={`upload-zone${dragOver ? ' dragover' : ''}`}
        onDragEnter={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={(e) => {
          e.preventDefault()
          setDragOver(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          void onUpload(e.dataTransfer.files)
        }}
      >
        <input
          type="file"
          multiple
          disabled={busy}
          onChange={(e) => void onUpload(e.target.files)}
        />
        <svg
          className="upload-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 16V7m0 0 3.5 3.5M12 7 8.5 10.5M5 16.5V18a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-1.5"
          />
        </svg>
        <span>{busy ? 'Working…' : dragOver ? 'Release to upload' : 'Drop or choose files'}</span>
        <span className="upload-hint">PDF, text, and more</span>
      </label>

      {message && <p className="panel-msg">{message}</p>}

      <ul className="doc-list">
        {docs.map((doc) => {
          const job = jobs[doc.id]
          const selected = selectedIds.includes(doc.id)
          return (
            <li key={doc.id} className={`doc-item${selected ? ' selected' : ''}`}>
              <label className="doc-select">
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggle(doc.id)}
                />
                <span className="doc-name">
                  <span className="doc-ext" aria-hidden="true">
                    {(doc.filename.split('.').pop() || 'file').slice(0, 4).toUpperCase()}
                  </span>
                  {doc.filename}
                </span>
              </label>
              <div className="doc-meta">
                <span className={`status-pill ${doc.status}`}>{doc.status}</span>
                {job && (
                  <span className="job-pill">
                    {job.status} {Math.round(job.progress_pct)}%
                  </span>
                )}
              </div>
              <button
                type="button"
                className="btn ghost"
                disabled={busy}
                onClick={() => void ingestOne(doc.id)}
              >
                Ingest
              </button>
            </li>
          )
        })}
        {!docs.length && <li className="empty">No documents yet.</li>}
      </ul>
    </section>
  )
}
