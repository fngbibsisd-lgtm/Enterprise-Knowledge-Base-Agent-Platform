// 与后端 backend/schemas 对齐的请求/响应类型

export interface LoginResponse {
  token: string
  username: string
  role: string
}

export interface Source {
  source: string
  text: string
  preview: string
  score: number
}

export interface ChatResponse {
  answer: string
  sources: Source[]
}

export interface ToolCall {
  tool_name: string
  arguments: Record<string, unknown>
  result: string
}

export interface AgentChatResponse {
  answer: string
  tool_calls: ToolCall[]
  iterations: number
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
}
