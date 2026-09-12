<template>
  <el-container class="layout">
    <SideBar />

    <el-container>
      <el-header class="header">
        <span class="header-title">企业智能知识库 Agent 平台</span>
        <span class="header-user">{{ auth.username }}（{{ auth.role }}）</span>
      </el-header>

      <el-main class="main">
        <div class="messages">
          <MessageItem v-for="(msg, i) in chatStore.messages" :key="i" :msg="msg" />
          <div v-if="chatStore.messages.length === 0" class="empty">开始提问吧，支持 RAG 文档检索和 Agent 智能问答</div>
        </div>

        <div class="input-bar">
          <el-radio-group v-model="mode">
            <el-radio-button value="RAG 问答">RAG 问答</el-radio-button>
            <el-radio-button value="Agent 问答">Agent 问答</el-radio-button>
            <el-radio-button value="多智能体">多智能体</el-radio-button>
          </el-radio-group>
          <el-input
            v-model="prompt"
            placeholder="请输入你的问题..."
            class="input"
            :disabled="sending"
            @keyup.enter="send"
          />
          <el-button v-if="sending && mode !== 'RAG 问答'" @click="stop">停止</el-button>
          <el-button v-else type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import SideBar from '../components/SideBar.vue'
import MessageItem from '../components/MessageItem.vue'
import { agentChatStream, chat } from '../api'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import type { ChatMessage } from '../types'

const auth = useAuthStore()
const chatStore = useChatStore()
const mode = ref('RAG 问答')
const prompt = ref('')
const sending = ref(false)
let abortController: AbortController | null = null

// 选中会话时自动切到 Agent 模式（会话都是 Agent 对话）
watch(
  () => chatStore.currentSessionId,
  (id) => {
    if (id != null) mode.value = 'Agent 问答'
  },
)

function send() {
  const query = prompt.value.trim()
  if (!query || sending.value) return
  prompt.value = ''
  if (mode.value === 'RAG 问答') void sendRag(query)
  else void sendAgent(query, mode.value === '多智能体')
}

async function sendRag(query: string) {
  sending.value = true
  chatStore.messages.push({ role: 'user', content: query })
  try {
    const resp = await chat(query)
    chatStore.messages.push({ role: 'assistant', content: resp.answer, sources: resp.sources })
  } catch (e: any) {
    chatStore.messages.push({ role: 'assistant', content: `请求失败：${e.message}` })
    ElMessage.error(e.message)
  } finally {
    sending.value = false
  }
}

async function sendAgent(query: string, multi = false) {
  sending.value = true
  chatStore.messages.push({ role: 'user', content: query })
  // 注意:必须 reactive,否则 push 进响应式数组后,改这个对象不会触发视图更新
  const assistant = reactive<ChatMessage>({ role: 'assistant', content: '', toolCalls: [], streaming: true })
  chatStore.messages.push(assistant)

  abortController = new AbortController()
  let pendingDelta = ''
  let raf = 0
  const flush = () => {
    if (pendingDelta) {
      assistant.content += pendingDelta
      pendingDelta = ''
      raf = 0
    }
  }

  try {
    await agentChatStream({
      query,
      sessionId: chatStore.currentSessionId,
      signal: abortController.signal,
      multi,
      onEvent(ev) {
        switch (ev.type) {
          case 'status':
            assistant.thinking = ev.message
            break
          case 'plan':
            assistant.plan = ev.steps
            assistant.subResults = []
            break
          case 'sub_result':
            assistant.subResults = assistant.subResults || []
            assistant.subResults.push({ task: ev.task, answer: ev.answer })
            break
          case 'tool_call':
            assistant.toolCalls!.push({ tool_name: ev.name, arguments: ev.arguments, summary: undefined })
            break
          case 'tool_result': {
            const tc = assistant.toolCalls!.find((t) => t.summary === undefined)
            if (tc) tc.summary = ev.summary
            break
          }
          case 'answer':
            pendingDelta += ev.delta
            if (!raf) raf = requestAnimationFrame(flush)
            break
          case 'sources':
            assistant.sources = ev.sources.map((s) => ({ source: s.source, score: s.score }))
            break
          case 'done':
            flush()
            assistant.streaming = false
            if (ev.session_id && !chatStore.currentSessionId) {
              chatStore.currentSessionId = ev.session_id
            }
            void chatStore.loadSessions()
            break
          case 'error':
            flush()
            assistant.content = assistant.content || ev.message
            assistant.streaming = false
            break
        }
      },
    })
  } catch (e: any) {
    flush()
    if (e?.name === 'AbortError') {
      assistant.content += '\n\n*已停止生成*'
    } else {
      assistant.content = assistant.content || `请求失败：${e.message}`
      ElMessage.error(e.message)
    }
    assistant.streaming = false
  } finally {
    sending.value = false
    abortController = null
  }
}

function stop() {
  abortController?.abort()
}

onMounted(() => {
  void chatStore.loadSessions()
})
</script>

<style scoped>
.layout {
  height: 100%;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}
.header-title {
  color: #4d6bfe;
  font-weight: 600;
  font-size: 16px;
}
.header-user {
  color: #606266;
  font-size: 14px;
}
.main {
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.empty {
  text-align: center;
  color: #909399;
  margin-top: 60px;
}
.input-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #e5e7eb;
}
.input {
  flex: 1;
}
</style>
