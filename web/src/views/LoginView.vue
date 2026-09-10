<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h1 class="title">企业智能知识库 Agent</h1>
      <p class="subtitle">基于 RAG + Agent 的企业知识库智能问答平台</p>

      <el-tabs v-model="activeTab" stretch>
        <el-tab-pane label="登录" name="login">
          <el-input v-model="loginForm.username" placeholder="用户名" size="large" style="margin-bottom: 12px" />
          <el-input v-model="loginForm.password" type="password" placeholder="密码" size="large" show-password style="margin-bottom: 16px" @keyup.enter="onLogin" />
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onLogin">登录</el-button>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-input v-model="registerForm.username" placeholder="用户名（至少3位）" size="large" style="margin-bottom: 12px" />
          <el-input v-model="registerForm.password" type="password" placeholder="密码（至少6位）" size="large" show-password style="margin-bottom: 16px" @keyup.enter="onRegister" />
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onRegister">注册</el-button>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, register } from '../api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const activeTab = ref('login')
const loading = ref(false)
const loginForm = ref({ username: '', password: '' })
const registerForm = ref({ username: '', password: '' })

async function onLogin() {
  loading.value = true
  try {
    const data = await login(loginForm.value.username, loginForm.value.password)
    auth.setAuth(data.token, data.username, data.role)
    router.push('/')
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  loading.value = true
  try {
    const data = await register(registerForm.value.username, registerForm.value.password)
    auth.setAuth(data.token, data.username, data.role)
    router.push('/')
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  width: 400px;
  padding: 12px 8px;
}
.title {
  text-align: center;
  color: #4d6bfe;
  margin: 0 0 4px;
  font-size: 22px;
}
.subtitle {
  text-align: center;
  color: #909399;
  margin: 0 0 20px;
  font-size: 13px;
}
</style>
