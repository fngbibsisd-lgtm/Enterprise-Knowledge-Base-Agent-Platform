<template>
  <div class="msg" :class="msg.role">
    <div class="bubble">
      <div class="content">{{ msg.content }}</div>

      <el-collapse v-if="msg.sources && msg.sources.length" class="extra">
        <el-collapse-item title="引用来源" name="sources">
          <div v-for="(s, i) in msg.sources" :key="i" class="source">
            <div class="source-name">【{{ i + 1 }}】{{ s.source }}（相关度 {{ s.score.toFixed(2) }}）</div>
            <div class="source-preview">{{ s.preview }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <el-collapse v-if="msg.toolCalls && msg.toolCalls.length" class="extra">
        <el-collapse-item title="工具调用记录" name="tools">
          <pre class="tools">{{ JSON.stringify(msg.toolCalls, null, 2) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage } from '../types'

defineProps<{ msg: ChatMessage }>()
</script>

<style scoped>
.msg {
  display: flex;
  margin-bottom: 16px;
}
.msg.user {
  justify-content: flex-end;
}
.msg.assistant {
  justify-content: flex-start;
}
.bubble {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.msg.user .bubble {
  background: #4d6bfe;
  color: #fff;
}
.msg.assistant .bubble {
  background: #fff;
  color: #262730;
}
.content {
  white-space: pre-wrap;
  word-break: break-word;
}
.extra {
  margin-top: 8px;
  border: none;
}
.source {
  padding: 4px 0;
  border-bottom: 1px dashed #eee;
}
.source-name {
  font-weight: 600;
  font-size: 13px;
  color: #4d6bfe;
}
.source-preview {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.tools {
  font-size: 12px;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  overflow-x: auto;
}
</style>
