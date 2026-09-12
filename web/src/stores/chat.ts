import { defineStore } from 'pinia'
import { deleteSession, getSessionMessages, listSessions } from '../api'
import type { ChatMessage, Session } from '../types'

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessions: [] as Session[],
    currentSessionId: null as number | null,
    messages: [] as ChatMessage[],
    loadingMessages: false,
  }),

  actions: {
    async loadSessions() {
      try {
        this.sessions = await listSessions()
      } catch {
        this.sessions = []
      }
    },

    // 新建对话:清空当前会话与消息
    newSession() {
      this.currentSessionId = null
      this.messages = []
    },

    // 切换会话:加载该会话历史消息
    async selectSession(id: number) {
      this.currentSessionId = id
      this.loadingMessages = true
      try {
        const msgs = await getSessionMessages(id)
        this.messages = msgs.map((m) => ({
          role: m.role,
          content: m.content,
          sources: m.sources,
          toolCalls: m.tool_calls,
        }))
      } catch (e: any) {
        this.messages = [{ role: 'assistant', content: `加载失败：${e?.message || e}` }]
      } finally {
        this.loadingMessages = false
      }
    },

    async removeSession(id: number) {
      await deleteSession(id)
      await this.loadSessions()
      if (this.currentSessionId === id) {
        this.currentSessionId = null
        this.messages = []
      }
    },
  },
})
