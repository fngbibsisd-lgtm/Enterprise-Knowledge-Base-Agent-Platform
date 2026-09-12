<template>
  <el-aside width="300px" class="sidebar">
    <div class="brand">知识库管理</div>
    <div class="user">当前用户：<b>{{ auth.username }}</b>（{{ auth.role }}）</div>
    <el-button text type="primary" size="small" @click="onLogout">退出登录</el-button>

    <el-divider />

    <div class="session-header">
      <span>对话记录</span>
      <el-button text size="small" type="primary" @click="onNewSession">新对话</el-button>
    </div>
    <div class="session-list">
      <div
        v-for="s in chatStore.sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === chatStore.currentSessionId }"
        @click="onSelect(s.id)"
      >
        <span class="session-title">{{ s.title }}</span>
        <el-button text size="small" class="session-del" @click.stop="onDelete(s.id)">删除</el-button>
      </div>
      <div v-if="!chatStore.sessions.length" class="session-empty">暂无对话</div>
    </div>

    <el-divider />

    <template v-if="auth.isAdmin">
      <el-upload :auto-upload="false" :show-file-list="false" accept=".pdf,.txt" :on-change="onFileChange">
        <el-button style="width: 100%">选择文档</el-button>
      </el-upload>
      <div v-if="file" class="filename">{{ file.name }}</div>
      <el-button type="primary" :disabled="!file" :loading="uploading" style="width: 100%; margin-top: 8px" @click="doUpload">
        上传
      </el-button>
      <el-divider />
    </template>

    <div class="status">已索引 <b>{{ status.total_chunks }}</b> 个 chunk</div>

    <template v-if="auth.isAdmin">
      <el-divider />
      <el-select v-model="since" style="width: 100%">
        <el-option v-for="o in sinceOptions" :key="o" :label="o" :value="o" />
      </el-select>
      <el-button :loading="resetting" style="width: 100%; margin-top: 8px" @click="doReset">重置知识库</el-button>
    </template>
  </el-aside>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getStatus, reset, upload } from '../api'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'

const router = useRouter()
const auth = useAuthStore()
const chatStore = useChatStore()

const file = ref<File | null>(null)
const uploading = ref(false)
const resetting = ref(false)
const since = ref('all')
const sinceOptions = ['all', '2h', '12h', '24h']
const status = ref({ indexed: false, total_chunks: 0 })

function onFileChange(uploadFile: any) {
  file.value = uploadFile.raw as File
}

async function loadStatus() {
  try {
    status.value = await getStatus()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function doUpload() {
  if (!file.value) return
  uploading.value = true
  try {
    const resp = await upload(file.value)
    ElMessage.success(resp.message)
    file.value = null
    await loadStatus()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    uploading.value = false
  }
}

async function doReset() {
  resetting.value = true
  try {
    const resp = await reset(since.value)
    ElMessage.success(`已删除 ${resp.deleted_chunks} 个 chunk`)
    await loadStatus()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    resetting.value = false
  }
}

function onLogout() {
  auth.logout()
  router.push('/login')
}

function onNewSession() {
  chatStore.newSession()
}

function onSelect(id: number) {
  void chatStore.selectSession(id)
}

async function onDelete(id: number) {
  try {
    await chatStore.removeSession(id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.sidebar {
  background: #fff;
  border-right: 1px solid #e5e7eb;
  padding: 16px;
}
.brand {
  font-size: 16px;
  font-weight: 600;
  color: #4d6bfe;
  margin-bottom: 8px;
}
.user {
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}
.filename {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
  word-break: break-all;
}
.status {
  font-size: 13px;
  color: #606266;
}
.session-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #606266;
  margin-bottom: 6px;
}
.session-list {
  max-height: 40vh;
  overflow-y: auto;
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 13px;
  color: #303133;
  cursor: pointer;
}
.session-item:hover {
  background: #f5f7fa;
}
.session-item.active {
  background: #eef2ff;
  color: #4d6bfe;
}
.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-del {
  visibility: hidden;
}
.session-item:hover .session-del {
  visibility: visible;
}
.session-empty {
  font-size: 12px;
  color: #b0b3b8;
  padding: 4px 8px;
}
</style>
