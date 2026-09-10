import http from './http'
import type {
  AgentChatResponse,
  ChatResponse,
  LoginResponse,
  ResetResponse,
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

export async function agentChat(query: string): Promise<AgentChatResponse> {
  const { data } = await http.post<AgentChatResponse>('/chat/agent', { query })
  return data
}

export async function reset(since: string): Promise<ResetResponse> {
  const { data } = await http.post<ResetResponse>('/admin/reset', { since })
  return data
}
