/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module 'markdown-it-texmath' {
  import type MarkdownIt from 'markdown-it'
  const texmath: (md: MarkdownIt, options?: Record<string, unknown>) => void
  export default texmath
}
