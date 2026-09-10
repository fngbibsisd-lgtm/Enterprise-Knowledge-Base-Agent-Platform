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
          <MessageItem v-for="(msg, i) in messages" :key="i" :msg="msg" />
          <div v-if="messages.length === 0" class="empty">开始提问吧，支持 RAG 文档检索和 Agent 智能问答</div>
        </div>

        <div class="input-bar">
          <el-radio-group v-model="mode">
            <el-radio-button value="RAG 问答">RAG 问答</el-radio-button>
            <el-radio-button value="Agent 问答">Agent 问答</el-radio-button>
          </el-radio-group>
          <el-input
            v-model="prompt"
            placeholder="请输入你的问题..."
            class="input"
            :disabled="sending"
            @keyup.enter="send"
          />
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import SideBar from '../components/SideBar.vue'
import MessageItem from '../components/MessageItem.vue'
import { agentChat, chat } from '../api'
import { useAuthStore } from '../stores/auth'
import type { ChatMessage } from '../types'

const auth = useAuthStore()
const mode = ref('RAG 问答')
const prompt = ref('')
const sending = ref(false)
const messages = ref<ChatMessage[]>([])

async function send() {
  const query = prompt.value.trim()
  if (!query || sending.value) return
  prompt.value = ''
  sending.value = true

  messages.value.push({ role: 'user', content: query })

  try {
    if (mode.value === 'RAG 问答') {
      const resp = await chat(query)
      messages.value.push({ role: 'assistant', content: resp.answer, sources: resp.sources })
    } else {
      const resp = await agentChat(query)
      messages.value.push({ role: 'assistant', content: resp.answer, toolCalls: resp.tool_calls })
    }
  } catch (e: any) {
    messages.value.push({ role: 'assistant', content: `请求失败：${e.message}` })
    ElMessage.error(e.message)
  } finally {
    sending.value = false
  }
}
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
