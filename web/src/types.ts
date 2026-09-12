// 与后端 backend/schemas 对齐的请求/响应类型

export interface LoginResponse {
  token: string
  username: string
  role: string
}

export interface Source {
  source: string
  score: number
  text?: string
  preview?: string
}

export interface ChatResponse {
  answer: string
  sources: Source[]
}

// 工具调用记录：只保留人类可读摘要,不暴露内部细节
export interface ToolCall {
  tool_name: string
  arguments: Record<string, unknown>
  summary?: string
}

export interface AgentChatResponse {
  answer: string
  tool_calls: ToolCall[]
  iterations: number
  sources: Source[]
}

export interface UploadResponse {
  filename: string
  message: string
}

export interface StatusResponse {
  indexed: boolean
  total_chunks: number
}

export interface ResetResponse {
  deleted_files: number
  remaining_files: number
  deleted_chunks: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  toolCalls?: ToolCall[]
  streaming?: boolean
  thinking?: string
  plan?: string[]
  subResults?: { task: string; answer: string }[]
}

export interface Session {
  id: number
  title: string
  updated_at: string
}

export interface AgentMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ToolCall[]
  sources?: Source[]
  created_at: string
}

export interface SourceRef {
  source: string
  score: number
}

// SSE 事件流（/chat/agent/stream 与 /chat/agent/multi/stream）
export type AgentStreamEvent =
  | { type: 'status'; message: string }
  | { type: 'plan'; steps: string[] }
  | { type: 'sub_result'; index: number; task: string; answer: string }
  | { type: 'tool_call'; name: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; name: string; summary: string; found?: boolean; row_count?: number }
  | { type: 'answer'; delta: string }
  | { type: 'sources'; sources: SourceRef[] }
  | { type: 'done'; answer: string; iterations: number; sources: SourceRef[]; session_id?: number }
  | { type: 'error'; message: string }
