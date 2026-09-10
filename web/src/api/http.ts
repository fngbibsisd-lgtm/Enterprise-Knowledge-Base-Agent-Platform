import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 300000, // 300s：大文件 embedding + Agent 多轮较慢
})

// 请求拦截：自动带 token
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：统一错误处理，把后端 detail 转成 Error.message
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const detail = error.response?.data?.detail
    const message = typeof detail === 'string' ? detail : error.message || '请求失败'
    return Promise.reject(new Error(message))
  },
)

export default http
