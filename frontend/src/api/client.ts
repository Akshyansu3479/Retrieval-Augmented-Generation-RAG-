import type {
  ApiError,
  ChatCitation,
  ChatResponse,
  Document,
  DocumentListResponse,
  IngestionJob,
  ReadyResponse,
} from './types'

async function parseError(res: Response): Promise<never> {
  let payload: ApiError = { message: res.statusText || 'Request failed' }
  try {
    payload = (await res.json()) as ApiError
  } catch {
    // keep statusText
  }
  throw new Error(payload.message || `HTTP ${res.status}`)
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) await parseError(res)
  return res.json() as Promise<T>
}

export function getReady(): Promise<ReadyResponse> {
  return getJson<ReadyResponse>('/ready')
}

export function listDocuments(): Promise<DocumentListResponse> {
  return getJson<DocumentListResponse>('/api/v1/documents?limit=50')
}

export async function uploadDocument(file: File): Promise<Document> {
  const body = new FormData()
  body.append('file', file)
  const res = await fetch('/api/v1/documents/upload', {
    method: 'POST',
    body,
  })
  if (!res.ok) await parseError(res)
  return res.json() as Promise<Document>
}

export async function enqueueIngestion(
  documentId: string,
  force = true,
): Promise<{ job_id: string; status: string }> {
  const res = await fetch(
    `/api/v1/ingestion/${documentId}?force=${force ? 'true' : 'false'}`,
    { method: 'POST' },
  )
  if (!res.ok) await parseError(res)
  return res.json()
}

export function getIngestionStatus(documentId: string): Promise<IngestionJob> {
  return getJson<IngestionJob>(`/api/v1/ingestion/${documentId}/status`)
}

export async function chat(params: {
  message: string
  conversationId?: string | null
  documentIds: string[]
}): Promise<ChatResponse> {
  const res = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: params.message,
      conversation_id: params.conversationId || null,
      document_ids: params.documentIds.length ? params.documentIds : null,
      stream: false,
    }),
  })
  if (!res.ok) await parseError(res)
  return res.json() as Promise<ChatResponse>
}

export async function chatStream(params: {
  message: string
  conversationId?: string | null
  documentIds: string[]
  onMeta: (meta: {
    conversation_id: string
    message_id: string
    citations: ChatCitation[]
  }) => void
  onToken: (token: string) => void
}): Promise<void> {
  const res = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: params.message,
      conversation_id: params.conversationId || null,
      document_ids: params.documentIds.length ? params.documentIds : null,
      stream: true,
    }),
  })
  if (!res.ok) await parseError(res)
  if (!res.body) throw new Error('No stream body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const line = chunk
        .split('\n')
        .map((l) => l.trim())
        .find((l) => l.startsWith('data:'))
      if (!line) continue
      const data = JSON.parse(line.slice(5).trim()) as {
        event: string
        token?: string
        conversation_id?: string
        message_id?: string
        citations?: ChatCitation[]
      }
      if (data.event === 'meta') {
        params.onMeta({
          conversation_id: data.conversation_id!,
          message_id: data.message_id!,
          citations: data.citations || [],
        })
      } else if (data.event === 'token' && data.token) {
        params.onToken(data.token)
      }
    }
  }
}
