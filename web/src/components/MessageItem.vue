<template>
  <div class="msg" :class="msg.role">
    <div class="bubble">
      <template v-if="msg.role === 'assistant'">
        <div
          v-if="(msg.toolCalls && msg.toolCalls.length) || (msg.streaming && !msg.content)"
          class="thinking-box"
        >
          <div class="thinking-head">
            <span v-if="msg.streaming" class="spin"></span>
            <span class="thinking-title">{{ msg.streaming ? msg.thinking || '正在思考…' : '思考过程' }}</span>
          </div>
          <div v-for="(t, i) in msg.toolCalls || []" :key="i" class="tool">
            <div class="tool-line">
              <span class="tool-name">{{ toolLine(t) }}</span>
            </div>
            <div v-if="t.summary" class="tool-result">{{ t.summary }}</div>
            <div v-else-if="msg.streaming" class="tool-result pending">执行中…</div>
          </div>
        </div>
        <div v-if="msg.plan && msg.plan.length" class="plan-box">
          <div class="plan-title">任务规划</div>
          <ol class="plan-list">
            <li v-for="(s, i) in msg.plan" :key="i">{{ s }}</li>
          </ol>
          <div v-for="(r, i) in (msg.subResults || [])" :key="i" class="sub-result">
            <div class="sub-result-task">{{ i + 1 }}. {{ r.task }}</div>
            <div class="sub-result-answer markdown" v-html="renderMarkdown(r.answer)"></div>
          </div>
        </div>
        <div class="content markdown" v-html="renderMarkdown(msg.content)" @click="onCopyClick"></div>
      </template>
      <div v-else class="content">{{ msg.content }}</div>

      <el-collapse v-if="msg.sources && msg.sources.length" class="extra">
        <el-collapse-item title="引用来源" name="sources">
          <div v-for="(s, i) in msg.sources" :key="i" class="source">
            <div class="source-name">【{{ i + 1 }}】{{ s.source }}（相关度 {{ s.score.toFixed(2) }}）</div>
            <div v-if="s.preview" class="source-preview">{{ s.preview }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import type { ChatMessage, ToolCall } from '../types'

import 'highlight.js/styles/atom-one-dark.css'
import 'katex/dist/katex.min.css'

const md = new MarkdownIt({
  breaks: true,
  linkify: true,
})

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

md.use(texmath, {
  engine: katex,
  delimiters: 'dollars',
  katexOptions: { throwOnError: false },
})

// 代码块：深色主题语法高亮 + 语言标签 + 复制按钮
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const lang = token.info.trim().split(/\s+/)[0]
  const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
  const highlighted = hljs.highlight(token.content, { language }).value
  const label = escapeHtml(lang) || 'text'
  return (
    '<div class="code-block">' +
    '<div class="code-header"><span class="code-lang">' + label + '</span>' +
    '<button class="code-copy" type="button">复制</button></div>' +
    '<pre><code class="hljs language-' + language + '">' + highlighted + '</code></pre>' +
    '</div>'
  )
}

function renderMarkdown(text: string): string {
  return md.render(text)
}

const TOOL_LABELS: Record<string, string> = {
  knowledge_search: '检索知识库',
  get_document: '读取文档',
  list_tables: '查看表结构',
  sql_query: '查询数据库',
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name
}

// 只挑对人类有意义的参数,不暴露内部细节(SQL/JSON 都不显示)
function argSummary(name: string, args: Record<string, unknown>): string {
  switch (name) {
    case 'knowledge_search':
      return typeof args.query === 'string' ? args.query : ''
    case 'get_document':
      return typeof args.source === 'string' ? args.source : ''
    default:
      return ''
  }
}

function toolLine(t: ToolCall): string {
  const label = toolLabel(t.tool_name)
  const arg = argSummary(t.tool_name, t.arguments)
  return arg ? `${label}：${arg}` : label
}

// 事件委托：点「复制」按钮时拷贝对应代码块内容
async function onCopyClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  const btn = target?.closest?.('.code-copy') as HTMLButtonElement | null
  if (!btn) return
  const code = btn.closest('.code-block')?.querySelector('code')?.textContent ?? ''
  try {
    await navigator.clipboard.writeText(code)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = code
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  btn.textContent = '已复制'
  window.setTimeout(() => {
    btn.textContent = '复制'
  }, 1500)
}

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

/* ===== Markdown 正文（DeepSeek 风格）===== */
.markdown {
  white-space: normal;
  font-size: 15px;
  line-height: 1.6;
}
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3),
.markdown :deep(h4),
.markdown :deep(h5),
.markdown :deep(h6) {
  margin: 12px 0 6px;
  font-weight: 600;
  line-height: 1.4;
}
.markdown :deep(h1) { font-size: 19px; }
.markdown :deep(h2) { font-size: 18px; }
.markdown :deep(h3) { font-size: 16px; }
.markdown :deep(h4) { font-size: 15px; }
.markdown :deep(h5) { font-size: 14px; }
.markdown :deep(h6) { font-size: 13px; }
.markdown :deep(p) {
  margin: 6px 0;
}
.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 6px 0;
  padding-left: 22px;
}
.markdown :deep(li) {
  margin: 3px 0;
}
.markdown :deep(li)::marker {
  color: #4d6bfe;
}
.markdown :deep(strong) {
  font-weight: 600;
}
.markdown :deep(code) {
  background: #f0f1f3;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace;
  font-size: 13px;
  color: #d63384;
}
.markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 2px 12px;
  border-left: 3px solid #4d6bfe;
  color: #606266;
}
.markdown :deep(a) {
  color: #4d6bfe;
  text-decoration: none;
}
.markdown :deep(a:hover) {
  text-decoration: underline;
}
.markdown :deep(hr) {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 12px 0;
}

/* 表格 */
.markdown :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
  font-size: 14px;
}
.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 7px 10px;
  text-align: left;
}
.markdown :deep(th) {
  background: #f7f8fa;
  font-weight: 600;
}
.markdown :deep(tr:nth-child(even) td) {
  background: #fafbfc;
}

/* 代码块 */
.markdown :deep(.code-block) {
  margin: 10px 0;
  border-radius: 8px;
  overflow: hidden;
  background: #282c34;
  border: 1px solid #3a3f4b;
}
.markdown :deep(.code-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  background: #21252b;
  font-size: 12px;
  color: #9da5b4;
}
.markdown :deep(.code-lang) {
  font-family: ui-monospace, Consolas, monospace;
  text-transform: lowercase;
}
.markdown :deep(.code-copy) {
  background: transparent;
  border: none;
  color: #9da5b4;
  cursor: pointer;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
}
.markdown :deep(.code-copy:hover) {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}
.markdown :deep(.code-block pre) {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
  background: #282c34;
}
.markdown :deep(.code-block code.hljs) {
  background: transparent;
  padding: 0;
  color: #abb2bf;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
}

/* 数学公式 */
.markdown :deep(.katex) {
  font-size: 1.05em;
}
.markdown :deep(.katex-display) {
  margin: 8px 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 4px 0;
}

/* 引用来源 / 工具调用折叠面板 */
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
.typing {
  color: #909399;
  font-size: 13px;
  padding: 2px 0;
}
.thinking-box {
  margin-bottom: 8px;
  padding: 8px 10px;
  background: #f7f8fa;
  border-left: 3px solid #c0c4cc;
  border-radius: 6px;
}
.plan-box {
  margin-bottom: 10px;
  padding: 10px 12px;
  background: #f7f8fa;
  border-left: 3px solid #4d6bfe;
  border-radius: 6px;
}
.plan-title {
  font-size: 13px;
  font-weight: 600;
  color: #4d6bfe;
  margin-bottom: 6px;
}
.plan-list {
  margin: 0 0 6px;
  padding-left: 20px;
  font-size: 13px;
  color: #606266;
}
.sub-result {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e0e3e8;
}
.sub-result-task {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.sub-result-answer {
  font-size: 13px;
  color: #606266;
  margin-top: 4px;
}
.thinking-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.thinking-title {
  font-size: 13px;
  color: #909399;
}
.spin {
  width: 12px;
  height: 12px;
  border: 2px solid #c0c4cc;
  border-top-color: #4d6bfe;
  border-radius: 50%;
  animation: spin-rotate 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin-rotate {
  to {
    transform: rotate(360deg);
  }
}
.tool {
  padding: 6px 0;
  border-bottom: 1px dashed #eee;
}
.tool:last-child {
  border-bottom: none;
}
.tool-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tool-name {
  font-weight: 600;
  font-size: 13px;
  color: #4d6bfe;
}
.tool-result {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f5f7fa;
  padding: 6px 8px;
  border-radius: 4px;
}
.tool-result.pending {
  color: #4d6bfe;
  background: #eef2ff;
}
</style>
