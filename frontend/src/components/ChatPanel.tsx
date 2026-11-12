import { useEffect, useRef, useState } from 'react'
import { chat, chatStream } from '../api/client'
import type { ChatCitation } from '../api/types'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: ChatCitation[]
  model?: string
  error?: boolean
}

type Props = {
  selectedIds: string[]
}

const SUGGESTIONS = [
  'Summarize the key points',
  'What are the main risks?',
  'List action items mentioned',
]

export function ChatPanel({ selectedIds }: Props) {
  const [streaming, setStreaming] = useState(true)
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [openSources, setOpenSources] = useState<Record<string, boolean>>({})
  const messagesRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = messagesRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages, busy])

  const send = async (preset?: string) => {
    const text = (preset ?? input).trim()
    if (!text || busy) return
    if (!selectedIds.length) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'Select at least one ingested document on the left.',
          error: true,
        },
      ])
      return
    }

    setBusy(true)
    setInput('')
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
    }
    setMessages((prev) => [...prev, userMsg])

    try {
      if (streaming) {
        const assistantId = crypto.randomUUID()
        setMessages((prev) => [
          ...prev,
          { id: assistantId, role: 'assistant', content: '', citations: [] },
        ])
        await chatStream({
          message: text,
          conversationId,
          documentIds: selectedIds,
          onMeta: (meta) => {
            setConversationId(meta.conversation_id)
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, citations: meta.citations }
                  : m,
              ),
            )
          },
          onToken: (token) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + token }
                  : m,
              ),
            )
          },
        })
      } else {
        const res = await chat({
          message: text,
          conversationId,
          documentIds: selectedIds,
        })
        setConversationId(res.conversation_id)
        setMessages((prev) => [
          ...prev,
          {
            id: res.message_id,
            role: 'assistant',
            content: res.answer,
            citations: res.citations,
            model: res.model,
          },
        ])
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: err instanceof Error ? err.message : 'Chat failed',
          error: true,
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel chat-panel">
      <div className="panel-head">
        <h2>Chat</h2>
        {selectedIds.length ? (
          <span className="selection-badge">
            {selectedIds.length} document{selectedIds.length === 1 ? '' : 's'} in scope
          </span>
        ) : (
          <p>Select documents on the left to ground answers</p>
        )}
      </div>

      <div className="messages" aria-live="polite" ref={messagesRef}>
        <div className="message-column">
          {messages.map((m) => (
            <article
              key={m.id}
              className={`bubble ${m.role}${m.error ? ' error' : ''}`}
            >
              <p className="bubble-role">{m.role}</p>
              {m.content ? (
                <p className="bubble-body">{m.content}</p>
              ) : busy ? (
                <div className="typing-indicator" aria-label="Generating">
                  <span />
                  <span />
                  <span />
                </div>
              ) : null}
              {!!m.citations?.length && (
                <div className="citations">
                  <button
                    type="button"
                    className="sources-toggle"
                    aria-expanded={!!openSources[m.id]}
                    onClick={() =>
                      setOpenSources((prev) => ({
                        ...prev,
                        [m.id]: !prev[m.id],
                      }))
                    }
                  >
                    {openSources[m.id]
                      ? 'Hide sources'
                      : `More · ${m.citations.length} source${m.citations.length === 1 ? '' : 's'}`}
                  </button>
                  {openSources[m.id] && (
                    <div className="citations-list">
                      {m.citations.map((c) => (
                        <details key={`${m.id}-${c.rank}`}>
                          <summary>
                            <span className="cite-rank">{c.rank}</span>
                            <span>
                              {c.source_filename || 'source'}
                              {c.page_number != null ? ` · p.${c.page_number}` : ''}
                            </span>
                          </summary>
                          <p>{c.snippet}</p>
                        </details>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </article>
          ))}
          {!messages.length && (
            <div className="empty-state">
              <svg
                className="empty-state-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M7 8h10M7 12h6m-7 7 3.5-3.5H18a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h.5"
                />
              </svg>
              <h3>Ask your documents</h3>
              <p>
                Ingest at least one file, keep it selected, then start a grounded
                conversation.
              </p>
              <div className="suggestion-row">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="suggestion"
                    onClick={() => void send(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="composer-wrap">
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault()
            void send()
          }}
        >
          <div className="composer-main">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send()
                }
              }}
              placeholder="Ask about the selected documents…"
              rows={3}
              disabled={busy}
            />
            <button
              type="submit"
              className="btn primary send"
              disabled={busy || !input.trim()}
              aria-label={busy ? 'Thinking' : 'Send message'}
            >
              {busy ? (
                <span className="send-busy" aria-hidden="true" />
              ) : (
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M5 12h14M13 6l6 6-6 6"
                  />
                </svg>
              )}
            </button>
          </div>
          <div className="composer-toolbar">
            <div className="composer-meta">
              <span className="composer-hint">Enter · Shift+Enter</span>
              {selectedIds.length > 0 && (
                <span className="scope-chip">{selectedIds.length} in scope</span>
              )}
            </div>
            <label className="toggle">
              <input
                type="checkbox"
                checked={streaming}
                onChange={(e) => setStreaming(e.target.checked)}
              />
              Stream tokens
            </label>
          </div>
        </form>
      </div>
    </section>
  )
}
