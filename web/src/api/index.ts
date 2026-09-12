import http from './http'
import type {
  AgentChatResponse,
  AgentMessage,
  AgentStreamEvent,
  ChatResponse,
  LoginResponse,
  ResetResponse,
  Session,
  StatusResponse,
  UploadResponse,
} from '../types'

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/login', { username, password })
  return data
}

export async function register(username: string, password: string): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/register', { username, password })
  return data
}

export async function getStatus(): Promise<StatusResponse> {
  const { data } = await http.get<StatusResponse>('/status')
  return data
}

export async function upload(file: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<UploadResponse>('/upload', form)
  return data
}

export async function chat(query: string): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', { query })
  return data
}

export async function agentChat(query: string, sessionId?: number | null): Promise<AgentChatResponse> {
  const { data } = await http.post<AgentChatResponse>('/chat/agent', {
    query,
    session_id: sessionId ?? null,
  })
  return data
}

export interface AgentStreamOptions {
  query: string
  sessionId?: number | null
  onEvent: (ev: AgentStreamEvent) => void
  signal?: AbortSignal
  multi?: boolean
}

// 用原生 fetch 消费 SSE（EventSource 只支持 GET,axios 不支持流式）
export async function agentChatStream(opts: AgentStreamOptions): Promise<void> {
  const token = localStorage.getItem('token') || ''
  const path = opts.multi ? '/api/chat/agent/multi/stream' : '/api/chat/agent/stream'
  const resp = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: token ? `Bearer ${token}` : '',
    },
    body: JSON.stringify({ query: opts.query, session_id: opts.sessionId ?? null }),
    signal: opts.signal,
  })

  if (!resp.ok || !resp.body) {
    let message = `请求失败(${resp.status})`
    try {
      const data = await resp.json()
      const detail = data?.detail
      if (typeof detail === 'string') message = detail
      else if (detail) message = JSON.stringify(detail)
    } catch {
      /* 非 JSON 响应体,保留默认信息 */
    }
    throw new Error(message)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      const json = line.slice(5).trim()
      if (!json) continue
      try {
        opts.onEvent(JSON.parse(json) as AgentStreamEvent)
      } catch {
        /* 忽略单帧解析失败 */
      }
    }
  }
}

export async function reset(since: string): Promise<ResetResponse> {
  const { data } = await http.post<ResetResponse>('/admin/reset', { since })
  return data
}

export async function listSessions(): Promise<Session[]> {
  const { data } = await http.get<Session[]>('/chat/agent/sessions')
  return data
}

export async function getSessionMessages(id: number): Promise<AgentMessage[]> {
  const { data } = await http.get<AgentMessage[]>(`/chat/agent/sessions/${id}/messages`)
  return data
}

export async function deleteSession(id: number): Promise<void> {
  await http.delete(`/chat/agent/sessions/${id}`)
}
