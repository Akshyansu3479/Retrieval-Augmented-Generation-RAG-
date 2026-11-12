export type DependencyStatus = {
  name: string
  status: 'ok' | 'degraded' | 'unavailable'
  detail: string | null
  latency_ms: number | null
}

export type ReadyResponse = {
  status: string
  service: string
  dependencies: DependencyStatus[]
}

export type DocumentVersion = {
  id: string
  version_number: number
  filename: string
  size_bytes: number
}

export type Document = {
  id: string
  filename: string
  content_type: string | null
  status: string
  current_version: number
  created_at: string
  versions: DocumentVersion[]
}

export type DocumentListResponse = {
  items: Document[]
  total: number
  limit: number
  offset: number
}

export type IngestionJob = {
  id: string
  document_id: string
  status: string
  progress_pct: number
  error_message: string | null
  meta: Record<string, unknown>
}

export type ChatCitation = {
  rank: number
  chunk_id: string | null
  document_id: string | null
  score: number | null
  page_number: number | null
  section_name: string | null
  source_filename: string | null
  snippet: string | null
}

export type ChatResponse = {
  conversation_id: string
  message_id: string
  answer: string
  model: string
  retrieval_mode: string
  citations: ChatCitation[]
  latency_ms: number | null
}

export type ApiError = {
  code?: string
  message: string
  details?: Record<string, unknown>
}
